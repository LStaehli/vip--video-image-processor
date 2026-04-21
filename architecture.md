# VIP — Video Image Processor: Architecture

## Overview

VIP is a Python web application that ingests a live video stream (webcam or Raspberry Pi camera via RTSP/MJPEG), applies real-time computer vision features, and streams the annotated result to a browser via WebSocket.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Web framework | FastAPI | Async-native, built-in WebSocket, Pydantic validation |
| CV & streaming | OpenCV (`cv2`) | Unified `VideoCapture` for RTSP/MJPEG/webcam + drawing primitives |
| Object detection | YOLOv8 (`ultralytics`) | Works directly on numpy arrays; nano variant fits real-time budget |
| Package manager | uv | Fast, modern Python package manager |
| Frontend | Vanilla HTML / JS / CSS | Canvas rendering; no framework overhead needed |

---

## High-Level Architecture

```
Raspberry Pi              Server (Python / FastAPI)                      Browser
┌─────────────┐          ┌─────────────────────────────────────────┐   ┌──────────────────────┐
│ Camera      │          │                                         │   │                      │
│ picamera2 / │─RTSP/──► │ StreamReader (background thread)        │   │ <canvas> video       │
│ libcamera   │  MJPEG   │   └─ asyncio.Queue (maxsize=2)          │   │ Zone editor canvas   │
└─────────────┘          │                                         │   │ Sidebar controls     │
                         │ FramePipeline (async coroutine)         │   │ Notifications list   │
                         │   ├─ MotionProcessor                    │   └──────────────────────┘
                         │   ├─ ZoneProcessor ──► RecordingService │          ▲
                         │   └─ DetectionProcessor (YOLO thread)   │          │ WebSocket (binary JPEG)
                         │                                         │──────────┤
                         │ WebSocketManager                        │          │ WebSocket (JSON events)
                         │   ├─ /ws/video  (binary JPEG frames)    │──────────┘
                         │   └─ /ws/events (JSON events)           │
                         │                                         │
                         │ REST API                                │
                         │   ├─ GET|PUT  /api/config               │
                         │   ├─ GET|POST|DELETE /api/zones         │
                         │   ├─ GET      /api/status               │
                         │   ├─ GET      /api/recording/status     │
                         │   └─ POST     /api/recording/start|stop │
                         │              /api/recording/screenshot  │
                         └─────────────────────────────────────────┘
```

---

## Data Flow (per frame)

1. **StreamReader** runs in a background thread, calling `cap.read()` (blocking). On success it schedules `queue.put_nowait(frame)` on the event loop via `loop.call_soon_threadsafe`. If the queue is full the frame is silently dropped — the pipeline never falls behind.
2. **FramePipeline** (async coroutine) pulls frames from the queue, throttles to `target_fps`, and passes each frame through the enabled processor chain. Each processor receives the numpy frame + a shared `FrameState` and returns the (possibly annotated) frame.
3. The annotated frame is JPEG-encoded (`cv2.imencode`) and broadcast by `WebSocketManager` over `/ws/video` to all connected browser clients, and written to disk if `RecordingService` is active.
4. Side-effects (zone alerts, recording state changes, model loading progress) are sent as JSON over `/ws/events` to all connected event clients.

---

## Processor Chain

All processors share the same interface:

```python
class BaseProcessor(ABC):
    enabled: bool

    @abstractmethod
    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        ...
```

`FrameState` accumulates results as it passes through the chain:

```python
@dataclass
class FrameState:
    timestamp: float
    centroids: list[tuple[int, int]]   # set by MotionProcessor
    detections: list[Detection]        # set by DetectionProcessor
    zone_hits: list[str]               # set by ZoneProcessor
```

All three processors are always registered at startup. The `enabled` flag on each is checked per-frame, so any processor can be toggled at runtime via the API without restarting.

### MotionProcessor

Uses OpenCV MOG2 background subtraction to detect moving regions. Applies morphological dilation to merge nearby blobs, then extracts contours and centroids. Draws trail dots, direction arrow, contour outline, and center dot — all individually configurable via the visual settings modal.

### ZoneProcessor

Stores zones as in-memory dicts with polygon points in normalised 0–1 coordinates. On each frame, tests all motion centroids against all zones using `cv2.pointPolygonTest`. When a centroid enters a zone, delegates to `RecordingService` to start recording. Recording stops after a 10-second inactivity grace period. Stop condition is configurable: inactivity inside the zone only, or inactivity in the entire stream.

### DetectionProcessor

Runs YOLOv8 inference. The model is loaded lazily in a `ThreadPoolExecutor` thread on first use (or when the model name changes), so the event loop and video stream stay live during download/initialisation. `model_loading` and `model_ready` WebSocket events are broadcast to the browser to show/hide a loading indicator. Inference runs every N frames (skip-frame strategy); the last result set is reused on skipped frames.

---

## Recording Service

`RecordingService` wraps an OpenCV `VideoWriter`. It is shared between manual control (header record button → `/api/recording/start|stop`) and automatic zone-triggered recording (`ZoneProcessor`). A guard prevents double-starts. Screenshots save a single JPEG from the pipeline's last annotated frame.

Output filenames are built from a user-configurable pattern supporting `{project_name}`, `{current_date}`, and `{current_timestamp}` tokens.

---

## WebSocket Channels

| Channel | Format | Purpose |
|---|---|---|
| `ws://.../ws/video` | Binary (JPEG bytes) | Annotated video frames at target FPS |
| `ws://.../ws/events` | JSON | Zone alerts, recording state, model loading progress |

Two separate connections avoid multiplexing complexity on both server and browser.

Event types sent over `/ws/events`:

| Type | Payload fields | Trigger |
|---|---|---|
| `zone_alert` | `zone_id`, `zone_name` | Motion centroid enters a zone |
| `recording_started` | `path` | Recording begins (manual or zone-triggered) |
| `recording_stopped` | `saved_to` | Recording ends and file is written |
| `model_loading` | `model` | YOLO model load begins in background thread |
| `model_ready` | `model` | YOLO model is loaded and ready |
| `model_error` | `model`, `error` | YOLO model failed to load |

---

## Zone Coordinate System

Zone polygon points are stored in **normalised coordinates** (0.0–1.0 relative to frame width/height). This means zones survive camera resolution changes without any data migration. Pixel conversion happens at runtime inside `ZoneProcessor` before hit-testing and drawing.

---

## Project Structure

```
vip--video-image-processor/
├── pyproject.toml               # uv / PEP 621 project definition
├── .env                         # local environment variables (git-ignored)
├── LICENSE                      # PolyForm Noncommercial 1.0.0
├── README.md                    # user-facing documentation
├── architecture.md              # this file
│
├── app/
│   ├── main.py                  # FastAPI app, lifespan, processor wiring, router mounts
│   ├── config.py                # Pydantic Settings — all runtime config, mutable via API
│   │
│   ├── stream/
│   │   ├── reader.py            # StreamReader: background thread + asyncio.Queue
│   │   ├── pipeline.py          # FramePipeline: FPS throttle, processor chain, JPEG encode
│   │   └── websocket_manager.py # Broadcast frames + JSON events to all WS clients
│   │
│   ├── processors/
│   │   ├── base.py              # BaseProcessor ABC + FrameState + Detection dataclasses
│   │   ├── motion.py            # MOG2, dilation, contours, trail, arrow, center dot
│   │   ├── zones.py             # Zone hit-test, overlay drawing, recording trigger
│   │   └── detection.py        # YOLOv8 async load + inference + bounding box draw
│   │
│   ├── api/
│   │   ├── stream.py            # /ws/video, /ws/events, /stream.mjpeg, /api/status
│   │   ├── config.py            # GET|PUT /api/config
│   │   ├── recording.py         # POST /api/recording/start|stop|screenshot, GET /api/recording/status
│   │   └── zones.py             # GET|POST|DELETE /api/zones
│   │
│   ├── services/
│   │   └── recording.py         # RecordingService: VideoWriter lifecycle + screenshot
│   │
│   └── static/
│       ├── index.html           # Single-page app shell + all modals
│       ├── css/
│       │   └── app.css          # Dark theme, layout, component styles
│       └── js/
│           ├── stream.js        # WS video client, canvas rendering, status polling
│           ├── controls.js      # Sidebar panels, sliders, modals, record/screenshot buttons
│           ├── zone_editor.js   # Polygon zone drawing on canvas overlay
│           └── notifications.js # Zone alert display in sidebar notification list
│
├── models/                      # YOLOv8 weights — downloaded on first use, git-ignored
└── recordings/                  # Default output for recordings and screenshots, git-ignored
```

---

## Key Design Decisions

### Processing on server, not on Pi
The Pi streams raw video only. All CV runs on the server. This keeps the Pi thermally safe and simple, and lets models be upgraded without touching the Pi.

### MOG2 over frame differencing
MOG2 background subtraction adapts to lighting changes and multi-modal backgrounds (swaying trees, clouds). Simple frame differencing produces excessive false positives outdoors.

### YOLO loaded in a thread pool
`YOLO("yolov8n.pt")` blocks for several seconds on first load. Running it in a `ThreadPoolExecutor` keeps the asyncio event loop — and therefore the video stream — live during download and initialisation. The browser shows a spinner while loading via `model_loading`/`model_ready` WebSocket events.

### YOLO skip-N strategy
YOLOv8 runs every Nth frame (default N=3), reusing the last result set on skipped frames. At 15 fps pipeline, effective inference rate is 5 fps — sufficient for person detection without saturating a single CPU core.

### Normalised zone coordinates
Zones are stored as 0.0–1.0 normalised points so they survive resolution changes. Pixel conversion happens at runtime inside the processor.

### In-memory zone store
Zones are stored in a module-level dict in `processors/zones.py`. This keeps the implementation simple — no database dependency. Zones are lost on server restart, which is acceptable for the current use case.

### All processors always registered
All processors are added to the pipeline at startup regardless of their enabled state. This allows runtime toggling via `processor.enabled = True/False` without restarting the server or reconstructing the pipeline.

### Frame drop over backpressure
`StreamReader` uses `asyncio.Queue(maxsize=2)`. When the pipeline is busy (e.g. during YOLO inference), excess frames are dropped rather than buffered. This prevents memory growth and keeps latency constant.

---

## Performance Budget (single CPU core, laptop)

| Component | Approximate cost |
|---|---|
| Frame read + JPEG encode | ~2 ms |
| MOG2 + dilation + contour detection | ~5 ms |
| Zone hit-test (polygon point test) | ~1 ms |
| YOLOv8n inference — every 3rd frame, amortized | ~10 ms/frame |
| WebSocket broadcast | ~1 ms |
| **Total** | **~19 ms → fits comfortably within 67 ms at 15 fps** |

---

## Raspberry Pi Setup (Stream Source)

The Pi is responsible for streaming only — no CV runs on it.

**Option A — RTSP via mediamtx:**
```bash
mediamtx &
libcamera-vid -t 0 --inline --listen -o - \
  | ffmpeg -i - -c copy -f rtsp rtsp://localhost:8554/cam
```

**Option B — MJPEG via picamera2:**
```python
# Simple HTTP MJPEG server using picamera2
```

Then set on the server:
```
STREAM_URL=rtsp://<raspberry-pi-ip>:8554/cam
```

For local development: `STREAM_URL=0` uses the laptop webcam.
