import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# Must be set before cv2 tries to use AVFoundation on macOS, otherwise the
# authorization request deadlocks when called from a background thread.
os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_RECONNECT_INITIAL_DELAY = 1.0
_RECONNECT_MAX_DELAY = 30.0

# Detect MJPEG HTTP/HTTPS streams (mjpg-streamer, picamera2, etc.)
_MJPEG_SCHEMES = ("http", "https")
_MJPEG_PATH_HINTS = ("action=stream", "stream.mjpg", "mjpeg", "video.mjpeg")


def _is_local_file(source) -> bool:
    """Return True when source is a path to a local file (not a URL, not a device index)."""
    if not isinstance(source, str):
        return False
    parsed = urlparse(source)
    # Treat as local file when there is no network scheme
    return parsed.scheme in ("", "file") and Path(source.replace("file://", "")).exists()


def _is_mjpeg_url(source) -> bool:
    """Return True if the source looks like an HTTP MJPEG stream."""
    if not isinstance(source, str):
        return False
    parsed = urlparse(source)
    if parsed.scheme not in _MJPEG_SCHEMES:
        return False
    url_lower = source.lower()
    return any(hint in url_lower for hint in _MJPEG_PATH_HINTS)


def _strip_credentials(url: str) -> tuple[str, str | None, str | None]:
    """Return (clean_url, username, password) with credentials removed from URL."""
    parsed = urlparse(url)
    username = parsed.username
    password = parsed.password
    if username or password:
        # Rebuild URL without credentials
        netloc = parsed.hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        clean = urlunparse((
            parsed.scheme, netloc, parsed.path,
            parsed.params, parsed.query, parsed.fragment,
        ))
        return clean, username, password
    return url, None, None


class StreamReader:
    """Reads frames from a video source in a background thread and places them
    into an asyncio.Queue for the async pipeline to consume.

    For HTTP MJPEG streams (mjpg-streamer, picamera2) the reader uses Python's
    urllib instead of OpenCV/FFmpeg. This bypasses FFmpeg's network stack, which
    fails on macOS for URLs with embedded credentials or on certain network
    configurations where curl/nc work fine but FFmpeg gets "No route to host".

    For all other sources (RTSP, local webcam, file) OpenCV VideoCapture is used.

    The queue has maxsize=2 so that the pipeline never falls behind — excess
    frames are silently dropped rather than accumulated.
    """

    def __init__(self, source: int | str, loop: asyncio.AbstractEventLoop) -> None:
        self._source = source
        self._loop = loop
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=2)
        self._running = False
        self._thread: threading.Thread | None = None
        self._cap: cv2.VideoCapture | None = None
        self.connected = False
        self._source_changed = False  # set by set_source() to skip reconnect delay

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="stream-reader")
        self._thread.start()
        logger.info("StreamReader started for source: %s", self._source)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._cap:
            self._cap.release()
        logger.info("StreamReader stopped")

    def set_source(self, source: int | str) -> None:
        """Switch to a new video source without restarting the server.

        Releases the current capture immediately; _run_opencv() detects the
        None cap on its next iteration and breaks out so _run() reopens the
        new source with no reconnect delay.
        """
        self._source = source
        self._source_changed = True
        self.connected = False
        if self._cap:
            self._cap.release()
            self._cap = None
        logger.info("StreamReader source changed to: %s", source)

    @property
    def queue(self) -> asyncio.Queue:
        return self._queue

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        delay = _RECONNECT_INITIAL_DELAY
        while self._running:
            source_changed = self._source_changed
            self._source_changed = False

            if _is_mjpeg_url(self._source):
                success = self._run_mjpeg(self._source)
            else:
                success = self._run_opencv()

            if source_changed:
                # Explicit source swap — reconnect immediately regardless of success
                delay = _RECONNECT_INITIAL_DELAY
            elif not success:
                self.connected = False
                logger.warning("Stream failed — retrying in %.1fs…", delay)
                time.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX_DELAY)
            else:
                delay = _RECONNECT_INITIAL_DELAY

    # ── OpenCV path (RTSP, local webcam, file) ────────────────────────────────

    def _open_capture(self) -> cv2.VideoCapture | None:
        backends = (
            [cv2.CAP_FFMPEG, cv2.CAP_ANY] if isinstance(self._source, str)
            else [cv2.CAP_ANY]
        )
        for backend in backends:
            cap = cv2.VideoCapture(self._source, backend)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if cap.isOpened():
                logger.debug("Stream opened with backend %d", backend)
                return cap
            cap.release()
        return None

    def _run_opencv(self) -> bool:
        """Read frames via OpenCV VideoCapture. Returns True if connected at least once.

        set_source() may be called from another thread at any time.  It releases
        self._cap and sets it to None.  We snapshot self._cap into a local ``cap``
        variable at the top of every iteration so we always hold a valid reference
        for the duration of that iteration, even if set_source() fires mid-loop.
        When we detect self._cap is None (source changed) we break immediately so
        _run() can re-open the new source with no reconnect delay.
        """
        self._cap = self._open_capture()
        if self._cap is None:
            logger.warning("OpenCV: failed to open source: %s", self._source)
            return False

        self.connected = True
        is_file = _is_local_file(self._source)
        if is_file:
            fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
            frame_delay = 1.0 / fps
            logger.info("Stream opened via OpenCV (local file, %.0f fps): %s", fps, self._source)
        else:
            frame_delay = 0.0
            logger.info("Stream opened via OpenCV: %s", self._source)

        while self._running:
            cap = self._cap          # atomic snapshot — safe across set_source() calls
            if cap is None:
                break                # source was swapped out; reconnect immediately

            ok, frame = cap.read()
            if not ok:
                if is_file and cap.isOpened():
                    # End of file — seek back to start and loop seamlessly
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    logger.debug("OpenCV: local file looped: %s", self._source)
                    continue
                # For live streams, or when the cap was released by set_source()
                logger.warning("OpenCV: stream read failed — reconnecting…")
                self.connected = False
                break
            self._push(frame)
            if frame_delay:
                time.sleep(frame_delay)

        # Guard: set_source() may have already released self._cap
        cap = self._cap
        if cap is not None:
            cap.release()
            self._cap = None
        return True

    # ── MJPEG-over-HTTP path ──────────────────────────────────────────────────

    def _run_mjpeg(self, url: str) -> bool:
        """Read MJPEG frames from an HTTP stream.

        Tries Python urllib first (works on most systems).
        Falls back to a curl subprocess if urllib hits a socket-level
        routing error (errno 65 / EHOSTUNREACH) — this happens on macOS when
        Python's BSD socket layer is blocked by a network extension or VPN
        while curl's Network.framework stack reaches the host fine.

        Returns True if at least one frame was received.
        """
        got = self._run_mjpeg_urllib(url)
        if got is None:
            # urllib hit a routing error — retry via curl
            logger.info("MJPEG: urllib unreachable, retrying via curl")
            got = self._run_mjpeg_curl(url)
        return bool(got)

    def _run_mjpeg_urllib(self, url: str):
        """Try urllib. Returns True (frames read), False (connected but no frames),
        or None (socket-level routing error — should fall back to curl)."""
        import urllib.request, errno as errno_mod

        clean_url, username, password = _strip_credentials(url)
        opener = urllib.request.build_opener()
        if username is not None:
            pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            pm.add_password(None, clean_url, username, password or "")
            opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(pm))

        logger.info("MJPEG: connecting via urllib: %s", clean_url)
        try:
            response = opener.open(clean_url, timeout=10)
        except OSError as exc:
            if getattr(exc, "errno", None) == errno_mod.EHOSTUNREACH or (
                hasattr(exc, "reason") and getattr(exc.reason, "errno", None) == errno_mod.EHOSTUNREACH
            ):
                logger.warning("MJPEG: urllib EHOSTUNREACH — will retry with curl")
                return None          # signal: try curl
            logger.warning("MJPEG urllib connect error: %s", exc)
            return False
        except Exception as exc:
            logger.warning("MJPEG urllib connect error: %s", exc)
            return False

        return self._drain_mjpeg_stream(response, url, source="urllib")

    def _run_mjpeg_curl(self, url: str):
        """Pipe MJPEG stream via a curl subprocess.

        curl on macOS uses Network.framework and works even when Python's
        BSD sockets are blocked by a VPN or network extension.
        Credentials are passed via -u user:pass (more reliable than URL embedding).
        """
        import shutil, subprocess, threading

        if not shutil.which("curl"):
            logger.error("MJPEG curl fallback: curl not found in PATH")
            return False

        clean_url, username, password = _strip_credentials(url)

        cmd = [
            "curl", "--silent", "--no-buffer",
            "--max-time", "0",        # no timeout — stream runs indefinitely
            "--connect-timeout", "10",
            "--anyauth",              # negotiate Basic or Digest automatically
        ]
        if username is not None:
            cmd += ["-u", f"{username}:{password or ''}"]
        cmd.append(clean_url)

        logger.info("MJPEG: starting curl subprocess: %s", " ".join(cmd))
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as exc:
            logger.warning("MJPEG curl subprocess failed to start: %s", exc)
            return False

        # Log curl's stderr in a daemon thread so it doesn't block
        def _log_stderr():
            for line in proc.stderr:
                text = line.decode(errors="replace").strip()
                if text:
                    logger.debug("curl stderr: %s", text)
        threading.Thread(target=_log_stderr, daemon=True).start()

        self.connected = True
        logger.info("MJPEG stream connected via curl: %s", clean_url)

        # Peek at the first 512 bytes so we can diagnose auth failures,
        # redirects, or unexpected content types before entering the drain loop.
        first = proc.stdout.read(512)
        if not first:
            logger.warning("curl: stdout empty immediately — auth failure or wrong URL")
            proc.terminate()
            self.connected = False
            return False
        logger.debug("curl first 512 bytes: %r", first)

        got_frame = self._drain_mjpeg_stream(proc.stdout, url, source="curl", prepend=first)

        proc.stdout.close()
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        self.connected = False
        return got_frame

    def _drain_mjpeg_stream(self, stream, url: str, source: str, prepend: bytes = b"") -> bool:
        """Read raw bytes from stream, extract JPEG frames, push to queue."""
        self.connected = True
        got_frame = False
        buf = prepend
        try:
            while self._running:
                if self._source != url:    # set_source() was called — stop
                    break
                chunk = stream.read(4096)
                if not chunk:
                    logger.warning("MJPEG (%s): connection closed", source)
                    break
                buf += chunk

                while True:
                    start = buf.find(b"\xff\xd8")   # JPEG SOI
                    end   = buf.find(b"\xff\xd9")   # JPEG EOI
                    if start == -1 or end == -1 or end < start:
                        break
                    frame = cv2.imdecode(
                        np.frombuffer(buf[start:end + 2], dtype=np.uint8),
                        cv2.IMREAD_COLOR,
                    )
                    buf = buf[end + 2:]
                    if frame is not None:
                        self._push(frame)
                        got_frame = True
        except Exception as exc:
            logger.warning("MJPEG (%s) read error: %s", source, exc)
        finally:
            self.connected = False
        return got_frame

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _push(self, frame: np.ndarray) -> None:
        """Schedule a frame onto the asyncio queue (drop if full)."""
        def _try_put(f=frame):
            try:
                self._queue.put_nowait(f)
            except asyncio.QueueFull:
                pass
        self._loop.call_soon_threadsafe(_try_put)
