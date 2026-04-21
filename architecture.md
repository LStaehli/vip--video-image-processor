# VIP - Video Image Processor: Architecture

## Overview

VIP is a Python web application that ingests a live video stream (e.g. from a Raspberry Pi camera via RTSP or MJPEG), applies real-time computer vision features, and streams the annotated result to a browser via WebSocket.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Web framework | FastAPI | Async-native, built-in WebSocket, Pydantic validation |
| CV & streaming | OpenCV (`cv2`) | Unified `VideoCapture` for RTSP/MJPEG/webcam + drawing primitives |
| Object detection | YOLOv8 (`ultralytics`) | Works directly on numpy arrays; nano variant fits real-time budget |
| Notifications | aiosmtplib + WebSocket events | Async email + browser Notification API via event channel |
| Persistence | SQLite (`aiosqlite`) | Zone definitions and config; no external DB needed |
| Package manager | uv | Fast, modern Python package manager |
| Frontend | Vanilla HTML / JS / CSS | Canvas rendering; no framework overhead needed |

---

## High-Level Architecture

```
Raspberry Pi              Server (Python / FastAPI)                   Browser
┌─────────────┐          ┌──────────────────────────────────┐        ┌────────────────────┐
│ Camera      │          │                                  │        │                    │
│ picamera2 / │─RTSP/──► │ StreamReader (ThreadPoolExecutor)│        │ <canvas> video     │
│ libcamera   │  MJPEG   │   └─ asyncio.Queue (maxsize=2)   │◄─ws────│ Zone editor canvas │
└─────────────┘          │                                  │◄─ws────│ Events / alarms UI │
                         │ FramePipeline (async coroutine)  │        └────────────────────┘
                         │   ├─ MotionProcessor             │
                         │   ├─ ZoneProcessor               │
                         │   └─ DetectionProcessor (YOLO)   │
                         │                                  │
                         │ WebSocketManager                 │
                         │   ├─ /ws/video  (binary JPEG)    │
                         │   └─ /ws/events (JSON)           │
                         │                                  │
                         │ REST API                         │
                         │   ├─ /api/zones   (CRUD)         │
                         │   └─ /api/config  (toggles)      │
                         └──────────────────────────────────┘
                                       ↕
                                  aiosqlite
                              (zones, config, notif history)
```

---

## Data Flow (per frame)

1. `StreamReader` runs in a `ThreadPoolExecutor` thread, calling `cap.read()` (blocking). On success it puts the raw frame into an `asyncio.Queue(maxsize=2)`. If the queue is full the frame is dropped — the pipeline never falls behind.
2. `FramePipeline` (async coroutine) pulls frames from the queue and passes them through each enabled processor in sequence. Each processor receives the numpy frame + a shared `FrameState` object and returns the annotated frame.
3. The annotated frame is JPEG-encoded (`cv2.imencode`) and broadcast by `WebSocketManager` over `ws/video` to all connected browser clients.
4. Side-effects (zone alarms, detection events) are placed into an event queue and sent as JSON over `ws/events`.
5. `NotificationService` consumes zone-trigger events and sends emails asynchronously via `aiosmtplib`.

---

## Processor Chain

Each feature is implemented as a class extending `BaseProcessor`:

```python
class BaseProcessor(ABC):
    @abstractmethod
    def process(self, frame: np.ndarray, state: FrameState) -> np.ndarray:
        ...
```

`FrameState` is a dataclass passed through the chain, accumulating results:

```python
@dataclass
class FrameState:
    timestamp: float
    centroids: list[tuple[int, int]]   # filled by MotionProcessor
    detections: list[Detection]        # filled by DetectionProcessor
    zone_hits: list[str]               # filled by ZoneProcessor
```

Processors are independently toggled via `app/config.py` flags (`ENABLE_MOTION`, `ENABLE_ZONES`, `ENABLE_DETECTION`).

---

## WebSocket Channels

| Channel | Format | Purpose |
|---|---|---|
| `ws://.../ws/video` | Binary (JPEG bytes) | Annotated video frames at target FPS |
| `ws://.../ws/events` | JSON | Zone alarms, stream status, detection summaries |

Two separate connections avoid multiplexing complexity on both the server and the browser.

---

## Zone Coordinate System

Zone polygon points are stored in **normalized coordinates** (0.0–1.0 relative to frame width/height). This means zones survive camera resolution changes without data migration. De-normalization to pixel coordinates happens at runtime inside `ZoneProcessor` before hit-testing.

---

## Project Structure

```
vip--video-image-processor/
├── pyproject.toml               # uv / PEP 621 project definition
├── .env.example                 # environment variable template
├── architecture.md              # this file
│
├── app/
│   ├── main.py                  # FastAPI app, lifespan, router mounts
│   ├── config.py                # Pydantic Settings (stream URL, SMTP, feature flags)
│   │
│   ├── stream/
│   │   ├── reader.py            # StreamReader: thread + asyncio.Queue
│   │   ├── pipeline.py          # FramePipeline: orchestrates processors
│   │   └── websocket_manager.py # WebSocketManager: broadcast to clients
│   │
│   ├── processors/
│   │   ├── base.py              # BaseProcessor ABC + FrameState dataclass
│   │   ├── motion.py            # MotionProcessor (MOG2, contours, trail, arrow)
│   │   ├── zones.py             # ZoneProcessor (hit-test, alarm overlay)
│   │   └── detection.py        # DetectionProcessor (YOLOv8 inference)
│   │
│   ├── api/
│   │   ├── stream.py            # WebSocket endpoints + stream status
│   │   ├── zones.py             # Zone CRUD REST endpoints
│   │   └── config.py            # Runtime config toggle endpoints
│   │
│   ├── services/
│   │   ├── notification.py      # Email (aiosmtplib) + event emission
│   │   └── zone_store.py        # SQLite access layer for zones
│   │
│   └── static/
│       ├── index.html
│       ├── js/
│       │   ├── stream.js        # WebSocket client + canvas rendering
│       │   ├── zone_editor.js   # Polygon zone drawing on canvas overlay
│       │   └── notifications.js # Browser Notification API integration
│       └── css/
│           └── app.css
│
├── models/                      # YOLOv8 weights (git-ignored)
│   └── .gitkeep
│
└── tests/
    ├── test_motion.py
    ├── test_zones.py
    └── test_pipeline.py
```

---

## Build Phases

| Phase | Scope | Goal |
|---|---|---|
| 0 | Scaffolding | Project structure, config, bare canvas + WebSocket skeleton |
| 1 | Core streaming | `StreamReader`, `WebSocketManager`, stable frame delivery |
| 2 | Motion tracking | MOG2, contours, direction arrow, fading trail |
| 3 | Detection zones | SQLite zones, polygon hit-test, alarms, notifications |
| 4 | Object detection | YOLOv8 bounding boxes, class labels, colored boxes |
| 5 | Polish | Settings UI, reconnection logic, Docker, tests |

---

## Key Design Decisions

### Processing on server, not on Pi
The Pi streams raw video only. All CV runs on the server. This keeps the Pi simple and thermally safe, and lets the model be upgraded without touching the Pi.

### MOG2 over frame differencing
MOG2 background subtraction adapts to lighting changes and multi-modal backgrounds (swaying trees, clouds). Frame differencing produces excessive false positives outdoors.

### YOLO skip-N strategy
YOLOv8 runs every Nth frame (default N=3), reusing the last result set on skipped frames. At 15fps pipeline, effective inference rate is 5fps — sufficient for person detection without saturating CPU.

### Normalized zone coordinates
Zones are stored as 0.0–1.0 normalized points so they survive resolution changes. Pixel conversion happens at runtime inside the processor.

---

## Raspberry Pi Setup (Stream Source)

The Pi is only responsible for streaming. Two recommended approaches:

**Option A — RTSP via mediamtx:**
```bash
# On the Pi
mediamtx &
libcamera-vid -t 0 --inline --listen -o - | ffmpeg -i - -c copy -f rtsp rtsp://localhost:8554/cam
```

**Option B — MJPEG via picamera2:**
```python
# Simple HTTP MJPEG server using picamera2
```

The server connects with:
```
STREAM_URL=rtsp://raspberry-pi-ip:8554/cam
```

For local development, set `STREAM_URL=0` to use the laptop webcam.

---

## Performance Budget (single CPU core, laptop)

| Component | Cost |
|---|---|
| Frame read + JPEG encode | ~2ms |
| MOG2 + contour detection | ~5ms |
| Zone hit-test (polygon) | ~1ms |
| YOLOv8n inference (every 3rd frame) | ~30ms amortized → ~10ms/frame |
| WebSocket broadcast | ~1ms |
| **Total** | **~19ms → ~52fps headroom at 15fps target** |
