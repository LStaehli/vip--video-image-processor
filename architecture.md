# VIP — Video Image Processor: Architecture

## Overview

VIP is a Python web application that ingests one or more live video streams (webcam or Raspberry Pi camera via RTSP/MJPEG), applies real-time computer vision features per channel, and streams the annotated result to a browser via WebSocket. Up to four independent channels run in parallel, each with its own pipeline, processor instances, WebSocket endpoints, and per-channel configuration stored in SQLite.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Web framework | FastAPI | Async-native, built-in WebSocket, Pydantic validation |
| CV & streaming | OpenCV (`cv2`) | Unified `VideoCapture` for RTSP/MJPEG/webcam + drawing primitives |
| Object detection | YOLOv8 (`ultralytics`) | Works directly on numpy arrays; nano variant fits real-time budget |
| Face recognition | DeepFace | Pure-Python, macOS ARM compatible; Facenet512/ArcFace embeddings |
| Database | SQLite + aiosqlite | Zero-dependency async persistence; single WAL-mode file |
| Package manager | uv | Fast, modern Python package manager |
| Frontend | Vanilla HTML / JS / CSS | Canvas rendering; no framework overhead needed |

---

## High-Level Architecture

```
Raspberry Pi              Server (Python / FastAPI)                        Browser
┌─────────────┐          ┌────────────────────────────────────────────────────┐   ┌────────────────────┐
│ Camera      │          │                                                    │   │                    │
│ picamera2 / │─RTSP/──► │ StreamReader × N  (background threads)             │   │ Stream tab bar     │
│ libcamera   │  MJPEG   │   └─ asyncio.Queue (maxsize=2) × N                 │   │ <canvas> video     │
└─────────────┘          │                                                    │   │ Zone editor canvas │
                         │ StreamRegistry                                     │   │ Sidebar controls   │
                         │  ├─ PipelineStack [ch1]                            │   │ Notifications list │
                         │  │   ├─ FramePipeline                              │   └────────────────────┘
                         │  │   │   ├─ MotionProcessor                        │          ▲
                         │  │   │   ├─ ZoneProcessor ──► Recorder             │          │ WS /ws/video/{id}
                         │  │   │   ├─ DetectionProcessor (thread)            │          │ (binary JPEG)
                         │  │   │   └─ FaceProcessor    (thread)              │──────────┤
                         │  │   ├─ WebSocketManager                           │          │ WS /ws/events/{id}
                         │  │   ├─ RecordingService                           │──────────┘ (JSON events)
                         │  │   └─ StreamConfig (per-channel)                 │
                         │  ├─ PipelineStack [ch2] …                          │
                         │  └─ PipelineStack [chN] …                          │
                         │                                                    │
                         │ Shared services                                    │
                         │  ├─ FaceStore (in-memory + SQLite)                 │
                         │  ├─ NotificationService (Telegram/email)           │
                         │  └─ DatabaseService (SQLite / aiosqlite)           │
                         │                                                    │
                         │ REST API                                           │
                         │  ├─ GET|POST|PATCH|DELETE /api/streams             │
                         │  ├─ GET|PUT  /api/streams/{id}/config              │
                         │  ├─ GET|POST|DELETE /api/streams/{id}/zones        │
                         │  ├─ GET|PUT  /api/streams/{id}/zones/{id}/settings │
                         │  ├─ POST     /api/streams/{id}/recording/start|stop│
                         │  ├─ GET      /api/streams/{id}/status              │
                         │  ├─ GET      /api/config                           │
                         │  ├─ GET|POST|PATCH|DELETE /api/faces               │
                         │  └─ GET|PUT  /api/faces/{name}/settings            │
                         └────────────────────────────────────────────────────┘
```

---

## Data Flow (per frame, per channel)

1. **StreamReader** runs in a background thread, calling `cap.read()` (blocking). On success it schedules `queue.put_nowait(frame)` on the event loop via `loop.call_soon_threadsafe`. If the queue is full the frame is silently dropped — the pipeline never falls behind.
2. **FramePipeline** (async coroutine) pulls frames from the queue, throttles to `target_fps`, and passes each frame through the enabled processor chain. Each processor receives the numpy frame + a shared `FrameState` and returns the (possibly annotated) frame.
3. The annotated frame is JPEG-encoded (`cv2.imencode`) and broadcast by `WebSocketManager` over `/ws/video/{stream_id}` to all connected browser clients, and written to disk if `RecordingService` is active.
4. Side-effects (zone alerts, recording state changes, model loading progress, face events) are sent as JSON over `/ws/events/{stream_id}` to all connected event clients.

Each `PipelineStack` is fully independent: separate reader thread, frame queue, processor instances, WebSocket manager, and recording service.

---

## StreamRegistry and PipelineStack

`StreamRegistry` is the central lifecycle manager for all active channel stacks, owned by `main.py`.

```python
@dataclass
class PipelineStack:
    stream_id: int
    channel_number: int
    name: str
    url: str
    reader: StreamReader
    pipeline: FramePipeline
    ws_manager: WebSocketManager
    recorder: RecordingService
    stream_cfg: StreamConfig          # per-channel settings object
    processors: dict[str, BaseProcessor]
    pipeline_task: asyncio.Task | None
```

On `StreamRegistry.start(stream)`:
1. Loads the channel's `StreamConfig` from the `stream_config` DB table, or seeds it from global `Settings` defaults if no row exists yet.
2. Constructs the four processors, injects `stream_cfg` into each via `processor._cfg`.
3. Starts the `StreamReader` thread and `FramePipeline` coroutine.

On `StreamRegistry.stop(stream_id)`, the pipeline task is cancelled and the reader thread is joined cleanly.

---

## Per-Channel Configuration

All feature settings (motion, zones, detection, faces, visual style, FPS, quality) are **per-channel** and stored in the `stream_config` SQLite table as key-value strings.

```python
@dataclass
class StreamConfig:
    target_fps: int = 15
    jpeg_quality: int = 70
    enable_motion: bool = False
    enable_zones: bool = False
    enable_detection: bool = False
    enable_faces: bool = False
    zone_stop_mode: str = "zone"
    notify_on_zone_trigger: bool = False
    notify_on_face_recognized: bool = False
    # … motion tuning, visual style, YOLO, face settings …

    @classmethod
    def from_settings(cls, s: Settings) -> "StreamConfig": ...
    def apply_dict(self, data: dict) -> None: ...   # type-converts from DB strings or API values
    def to_db_dict(self) -> dict[str, str]: ...     # str values for DB storage
    def to_api_dict(self) -> dict: ...              # full dict for API response
```

Processors reference their channel's config via `self._cfg` (injected by the registry). All `settings.X` reads in processors were replaced with `self._cfg.X` to ensure per-channel independence.

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

All four processors are always registered at startup. The `enabled` flag on each is checked per-frame, so any processor can be toggled at runtime via the API without restarting.

### MotionProcessor

Uses OpenCV MOG2 background subtraction to detect moving regions. Applies morphological dilation to merge nearby blobs, then extracts contours and centroids. Draws trail dots, direction arrow, contour outline, and center dot — all individually configurable via the visual settings modal. All tuning parameters are read from `self._cfg`.

### ZoneProcessor

Stores zones in an in-memory dict with polygon points in normalised 0–1 coordinates. Zone definitions are persisted in SQLite (`zones` table); `add_zone`/`remove_zone`/`clear_zones` fire async DB writes. On startup, saved zones are reloaded from the DB.

On each frame, tests all motion centroids against all zones using `cv2.pointPolygonTest`. Per-zone edge detection (`_active_zones` set) distinguishes newly-entered zones from zones already active — a `zone_events` DB row is written only on the first hit. When a centroid enters a zone, delegates to `RecordingService` to start recording and calls `_notify_zone()`.

**Zone notifications:** `_notify_zone()` is an async method that:
1. Fetches per-zone message templates from the `zone_settings` DB table.
2. Resolves template variables: `{zone_name}`, `{channel_number}`, `{channel_slug}`, `{current_timestamp}`.
3. Calls `notify_zone_trigger()` with the resolved custom messages (or empty strings to use defaults).

Stop condition is configurable via `self._cfg.zone_stop_mode`: inactivity inside the zone only, or inactivity in the entire stream.

### DetectionProcessor

Runs YOLOv8 inference. The model is loaded lazily in a `ThreadPoolExecutor` thread on first use (or when the model name changes), so the event loop and video stream stay live during download/initialisation. `model_loading` and `model_ready` WebSocket events are broadcast to show/hide a loading indicator. Inference runs every N frames (`self._cfg.yolo_skip_frames`); the last result set is reused on skipped frames. Class filter is applied via `self._cfg.detect_class_list`.

### FaceProcessor

Runs DeepFace face recognition with the same non-blocking load pattern as `DetectionProcessor`. Per frame:
1. Calls `DeepFace.represent()` to detect faces and extract embeddings in one pass.
2. Filters zero-confidence dummy entries.
3. Compares embeddings against enrolled references using cosine similarity.
4. **Auto-enrollment** (optional): unknown faces above `face_auto_enroll_min_score` are enrolled with a timestamped name, a screenshot is saved, and a `face_enrolled` event is broadcast. A 3-second global cooldown prevents duplicates.
5. Draws bounding boxes (green = known, grey = unknown), name + similarity labels, and optionally a 5-point landmark mesh.
6. Broadcasts `face_recognized` events with a 10-second per-name cooldown.
7. **Face notifications** (optional): when `self._cfg.notify_on_face_recognized` is true and a notifier is injected, a JPEG snapshot of the annotated frame is encoded once per detection cycle (not per face) and passed to `_notify_face()` for each recognised person. `_notify_face()` loads per-face custom message templates from the `face_notification_settings` table, resolves template variables, and calls `notify_face_recognized()` in the notification service. A 60-second per-face cooldown in the notification service prevents repeated alerts.

All settings are read from `self._cfg`. The notifier is injected by the registry (`face_proc._notifier = notifier`) alongside the recorder.

---

## Services

### Database

`database.py` owns a single persistent `aiosqlite` connection (WAL mode, foreign keys on) opened at startup and closed at shutdown.

**Schema:**

| Table | Purpose |
|---|---|
| `streams` | Registered stream channels — id, channel_number (UNIQUE), name, url, enabled |
| `stream_config` | Per-channel key-value config — (stream_id, key) PRIMARY KEY, value |
| `zones` | Persisted zone definitions — id, stream_id, name, polygon (JSON), created_at |
| `zone_settings` | Per-zone notification templates — zone_id (PK), telegram_message, email_message |
| `face_notification_settings` | Per-face notification templates — face_name (PK), telegram_message, email_message |
| `recordings` | Every recording session — path, start/end time, duration, trigger type and source |
| `zone_events` | Each time motion entered a zone — zone reference, timestamp, recording FK |
| `face_recognition_events` | Rate-limited recognition hits — face name, similarity, timestamp, recording FK |
| `faces` | Enrolled embeddings — name (PK), BLOB, created_at, updated_at |

Key operations:
- `insert_stream` / `load_streams` / `update_stream` / `delete_stream` / `stream_count`
- `load_stream_config(stream_id)` / `save_stream_config(stream_id, data)` — bulk upsert into `stream_config`
- `get_zone_settings(zone_id)` / `upsert_zone_settings(zone_id, ...)` / `delete_zone_settings(zone_id)`
- `get_face_notification_settings(face_name)` / `upsert_face_notification_settings(face_name, ...)` / `delete_face_notification_settings(face_name)`
- `UNIQUE INDEX` on `streams(channel_number)` — enforced at DB level; API returns HTTP 409 on conflict.

### RecordingService

`RecordingService` wraps an OpenCV `VideoWriter`. One instance per channel, owned by `PipelineStack`.

`start()` accepts `trigger`, `trigger_zone_id`, and `trigger_face_name` to tag the recording's origin. It generates a UUID `recording_id` synchronously and fires an async DB insert. `stop()` finalises the DB row.

`save_screenshot(frame, suffix)` saves a single JPEG derived from the recording filename pattern.

Output filenames are built from a user-configurable pattern supporting: `{project_name}`, `{current_date}`, `{current_timestamp}`, `{channel_number}`, `{channel_slug}`.

`{channel_slug}` is produced by `_slugify()`: lowercased, non-alphanumeric characters replaced with hyphens, leading/trailing hyphens stripped.

### NotificationService

`notifications.py` dispatches Telegram messages and SMTP emails when zones are triggered or known faces are detected.

**`notify_zone_trigger(zone_id, zone_name, recording_path, snapshot, telegram_message="", email_message="")`**
- Checks `settings.notify_on_zone_trigger`; returns immediately if false.
- Enforces a per-zone cooldown using `_last_notified[zone_id]` (monotonic timestamps).
- Sends an annotated JPEG snapshot via `sendPhoto` when available; falls back to text-only `sendMessage`.
- Both Telegram and email channels are optional; unconfigured channels are silently skipped.

**`notify_face_recognized(face_name, similarity, recording_path, snapshot, telegram_message="", email_message="")`**
- Enforces a per-face cooldown using `_last_notified_faces[face_name]` (same `NOTIFY_COOLDOWN` value, default 60 s).
- Same delivery logic as zone notifications: snapshot via `sendPhoto`, custom or default message, Telegram + email.
- Called by `FaceProcessor._notify_face()` which pre-resolves template variables (`{face_name}`, `{similarity}`, `{current_timestamp}`) from the `face_notification_settings` table before invoking the service.

Both functions check that at least one delivery channel is configured before attempting delivery. All network I/O is async (`httpx.AsyncClient`, `aiosmtplib`).

### FaceStore

`face_store.py` is a module-level singleton backed by the `faces` SQLite table. The in-memory dict (`name → {embedding, created_at}`) is the hot path for per-frame cosine similarity search. All mutations update the in-memory dict synchronously then fire an async DB write via `asyncio.ensure_future()`.

`init()` is awaited at startup to populate the in-memory store from the DB. Enrolled faces survive server restarts and are shared across all channels.

---

## WebSocket Channels

Each channel exposes two independent WebSocket endpoints:

| Channel | Format | Purpose |
|---|---|---|
| `ws://.../ws/video/{stream_id}` | Binary (JPEG bytes) | Annotated video frames at target FPS |
| `ws://.../ws/events/{stream_id}` | JSON | Zone alerts, recording state, model loading progress, face events |

Event types sent over `/ws/events/{stream_id}`:

| Type | Payload fields | Trigger |
|---|---|---|
| `zone_alert` | `zone_id`, `zone_name` | Motion centroid enters a zone |
| `recording_started` | `path` | Recording begins (manual or zone-triggered) |
| `recording_stopped` | `saved_to` | Recording ends and file is written |
| `model_loading` | `model` | YOLO model load begins in background thread |
| `model_ready` | `model` | YOLO model is loaded and ready |
| `model_error` | `model`, `error` | YOLO model failed to load |
| `face_model_loading` | `model` | DeepFace model load begins in background thread |
| `face_model_ready` | `model` | DeepFace model is loaded and ready |
| `face_model_error` | `model`, `error` | DeepFace model failed to load |
| `face_recognized` | `name`, `similarity` | Known face detected (10 s per-name WS cooldown; 60 s cooldown for Telegram/email) |
| `face_enrolled` | `name`, `created_at` | New face auto-enrolled from stream |

---

## Zone Coordinate System

Zone polygon points are stored in **normalised coordinates** (0.0–1.0 relative to frame width/height). This means zones survive camera resolution changes without any data migration. Pixel conversion happens at runtime inside `ZoneProcessor` before hit-testing and drawing.

---

## Project Structure

```
vip--video-image-processor/
├── pyproject.toml               # uv / PEP 621 project definition
├── .env                         # local environment variables (git-ignored)
├── LICENSE                      # All Rights Reserved — Ludovic Staehli
├── README.md                    # user-facing documentation
├── architecture.md              # this file
│
├── app/
│   ├── main.py                  # FastAPI app, lifespan, router mounts, registry init
│   ├── config.py                # StreamConfig dataclass + Settings (Pydantic BaseSettings)
│   │
│   ├── stream/
│   │   ├── reader.py            # StreamReader: background thread + asyncio.Queue
│   │   ├── pipeline.py          # FramePipeline: FPS throttle, processor chain, JPEG encode
│   │   ├── registry.py          # StreamRegistry + PipelineStack dataclass
│   │   └── websocket_manager.py # Broadcast frames + JSON events to all WS clients
│   │
│   ├── processors/
│   │   ├── base.py              # BaseProcessor ABC + FrameState + Detection dataclasses
│   │   ├── motion.py            # MOG2, dilation, contours, trail, arrow, center dot
│   │   ├── zones.py             # Zone hit-test, overlay drawing, recording trigger, notifications
│   │   ├── detection.py         # YOLOv8 async load + inference + bounding box draw
│   │   └── faces.py             # DeepFace async load + recognition + landmarks + auto-enroll
│   │
│   ├── api/
│   │   ├── stream.py            # /ws/video, /ws/events, /stream.mjpeg, /api/status (legacy)
│   │   ├── streams.py           # /api/streams — multi-stream registry + all per-stream endpoints
│   │   ├── config.py            # GET|PUT /api/config (global recording/notification settings)
│   │   ├── recording.py         # POST /api/recording/start|stop|screenshot (legacy)
│   │   ├── zones.py             # /api/zones (legacy single-stream)
│   │   └── faces.py             # GET|POST|PATCH|DELETE /api/faces + GET|PUT /api/faces/{name}/settings
│   │
│   ├── services/
│   │   ├── database.py          # SQLite service: schema, connection lifecycle, all DB ops
│   │   ├── recording.py         # RecordingService: VideoWriter lifecycle + DB logging
│   │   ├── notifications.py     # Telegram + email dispatch with custom message support
│   │   └── face_store.py        # FaceStore: in-memory embeddings + SQLite backend
│   │
│   └── static/
│       ├── index.html           # Single-page app shell + all modals
│       ├── css/
│       │   └── app.css          # Dark theme, layout, component styles
│       └── js/
│           ├── stream.js        # WS video/events client, stream tab switching, URL persistence
│           ├── controls.js      # Sidebar panels, sliders, modals, record/screenshot buttons
│           ├── zone_editor.js   # Polygon zone drawing, management, zone settings modal
│           └── notifications.js # Zone/face alert display in sidebar notification list
│
├── models/                      # YOLOv8 weights — downloaded on first use, git-ignored
├── recordings/                  # Default output for recordings and screenshots, git-ignored
└── vip.db                       # SQLite database (git-ignored)
```

---

## Key Design Decisions

### Multi-stream with independent pipeline stacks
Each channel runs its own `PipelineStack` with isolated reader thread, frame queue, processor instances, WebSocket manager, and recording service. Stacks share the global `FaceStore` and `NotificationService` but nothing else. This keeps the N-channel design simple — adding a channel is `registry.start(stream)`, removing it is `registry.stop(stream_id)`.

### Per-channel config via `StreamConfig`
All feature settings are encapsulated in a `StreamConfig` dataclass injected into each processor at stack construction. Processors read from `self._cfg` instead of the global `Settings` singleton, giving each channel full independence. `StreamConfig` is seeded from `Settings` on first start, then persisted in the `stream_config` DB table and loaded on subsequent restarts.

### Channel number uniqueness
Channel numbers (1–4) are enforced as unique at the DB level via `UNIQUE INDEX`. The API catches `aiosqlite.IntegrityError` and returns HTTP 409, which the frontend surfaces as an inline error message in the stream form.

### Processing on server, not on Pi
The Pi streams raw video only. All CV runs on the server. This keeps the Pi thermally safe and simple, and lets models be upgraded without touching the Pi.

### MOG2 over frame differencing
MOG2 background subtraction adapts to lighting changes and multi-modal backgrounds (swaying trees, clouds). Simple frame differencing produces excessive false positives outdoors.

### YOLO and DeepFace loaded in a thread pool
`YOLO("yolov8n.pt")` and `DeepFace.represent()` block for several seconds on first load. Running them in a `ThreadPoolExecutor` keeps the asyncio event loop — and therefore the video stream — live during download and initialisation. The browser shows a spinner via `model_loading`/`model_ready` WebSocket events.

### YOLO / DeepFace skip-N strategy
Both YOLO and DeepFace run every Nth frame (independently configurable per channel), reusing the last result set on skipped frames. This keeps CPU usage bounded while maintaining smooth visual feedback.

### SQLite over a server database
VIP is a single-process application deployed on one machine. SQLite in WAL mode handles the write patterns (infrequent zone events, recording metadata, face enrollments, config upserts) with zero operational overhead. aiosqlite wraps it in an async interface that integrates naturally with FastAPI's event loop.

### UUID primary keys for recordings
Recording UUIDs are generated synchronously by `RecordingService.start()` before any DB call. This lets processors immediately reference `recording_id` when logging correlated zone or face events — no need to await the insert or pass the id through callbacks.

### Non-blocking zone name modal
The zone drawing completion originally used `window.prompt()`, which blocks the JavaScript event loop and freezes the video canvas. Replaced with a Promise-based non-blocking modal (`#zone-name-overlay`) that resolves asynchronously, keeping the WebSocket video stream live.

### URL-based channel persistence
The active channel number is reflected in the URL as `?channel=N` via `history.replaceState()` (no page reload). On load, `URLSearchParams` reads the parameter to select the initial channel. This allows multiple browser tabs to show different channels simultaneously.

### Normalised zone coordinates
Zones are stored as 0.0–1.0 normalised points so they survive resolution changes. Pixel conversion happens at runtime inside the processor.

### Per-zone notification message templates
Zone trigger messages support template variables resolved at notification time: `{zone_name}`, `{channel_number}`, `{channel_slug}`, `{current_timestamp}`. Templates are stored in the `zone_settings` table. If a template is empty, the default notification message is used.

### Per-face notification message templates
Face recognition alerts follow the same pattern as zone alerts. `FaceProcessor._notify_face()` fetches the per-face message templates from the `face_notification_settings` table, resolves `{face_name}`, `{similarity}`, and `{current_timestamp}`, and passes the results to `notify_face_recognized()`. Notification settings are cleaned up when a face is deleted via the API. A 60-second per-face cooldown (shared `NOTIFY_COOLDOWN` setting) prevents repeated alerts. The snapshot (annotated JPEG) is encoded once per skip-frame cycle before iterating over recognised faces, avoiding redundant encode calls when multiple known faces appear in the same frame.

### DeepFace over InsightFace
InsightFace failed to build on macOS ARM due to missing C++ headers. DeepFace is pure Python, pip-installable on all platforms, and supports Facenet512 and ArcFace.

### Linear scan for face matching
Cosine similarity is computed against all enrolled faces on every recognition call. A linear scan is O(n) and fast enough for ≤1000 enrolled faces without a nearest-neighbour index.

### Frame drop over backpressure
`StreamReader` uses `asyncio.Queue(maxsize=2)`. When the pipeline is busy, excess frames are dropped rather than buffered. This prevents memory growth and keeps latency constant.

---

## Performance Budget (single CPU core, laptop)

| Component | Approximate cost |
|---|---|
| Frame read + JPEG encode | ~2 ms |
| MOG2 + dilation + contour detection | ~5 ms |
| Zone hit-test (polygon point test) | ~1 ms |
| YOLOv8n inference — every 3rd frame, amortised | ~10 ms/frame |
| DeepFace inference — every 3rd frame, amortised | ~50–150 ms/frame (model-dependent) |
| WebSocket broadcast | ~1 ms |

DeepFace inference is significantly heavier than YOLO. When both are enabled, run them on independent skip-frame counters and consider increasing `face_skip_frames` to reduce CPU pressure.

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

Then register the stream in the UI (Stream Settings → Add channel):
```
URL: rtsp://<raspberry-pi-ip>:8554/cam
```

For local development: use `0` as the URL to capture from the laptop webcam.
