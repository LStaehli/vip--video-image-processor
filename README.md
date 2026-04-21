# VIP — Video Image Processor

A Python web application that ingests a live video stream (webcam or Raspberry Pi camera via RTSP/MJPEG), applies real-time computer vision features, and streams the annotated result to a browser via WebSocket.

---

## Features

| Status | Feature |
|---|---|
| ✅ Done | Live video streaming (webcam / RTSP / MJPEG) to browser via WebSocket |
| ✅ Done | MJPEG fallback endpoint for clients without WebSocket support |
| ✅ Done | Runtime config API — toggle features and tune FPS/quality without restart |
| ✅ Done | Processor chain architecture (pluggable CV feature modules) |
| 🔜 Phase 2 | Motion tracking — contours, direction arrow, fading trail |
| 🔜 Phase 3 | Detection zones — draw zones, trigger alarms and notifications |
| 🔜 Phase 4 | Object/person detection — YOLOv8 bounding boxes with labels |

---

## Tech stack

- **Backend:** Python 3.11+, [FastAPI](https://fastapi.tiangolo.com/), [OpenCV](https://opencv.org/), [uvicorn](https://www.uvicorn.org/)
- **Computer vision:** OpenCV (motion), [YOLOv8 / ultralytics](https://docs.ultralytics.com/) (detection, Phase 4)
- **Real-time transport:** WebSocket (binary JPEG frames) + MJPEG fallback
- **Persistence:** SQLite via aiosqlite (zone definitions, Phase 3)
- **Frontend:** Vanilla HTML / JS / CSS — no framework
- **Package manager:** [uv](https://docs.astral.sh/uv/)

---

## Project structure

```
vip--video-image-processor/
├── app/
│   ├── main.py                  # FastAPI app entry point + lifespan
│   ├── config.py                # Pydantic Settings (all config via .env)
│   ├── stream/
│   │   ├── reader.py            # Threaded VideoCapture with reconnection
│   │   ├── pipeline.py          # Processor chain, FPS throttle, JPEG encode
│   │   └── websocket_manager.py # Broadcast frames to all connected clients
│   ├── processors/
│   │   ├── base.py              # BaseProcessor ABC + FrameState dataclass
│   │   ├── motion.py            # Motion tracking (Phase 2)
│   │   ├── zones.py             # Detection zones (Phase 3)
│   │   └── detection.py        # YOLOv8 object detection (Phase 4)
│   ├── api/
│   │   ├── stream.py            # /ws/video, /ws/events, /stream.mjpeg, /api/status
│   │   └── config.py            # GET/PUT /api/config
│   ├── services/                # Notification service (Phase 3)
│   └── static/                  # Browser frontend (HTML/JS/CSS)
├── models/                      # YOLOv8 weights (git-ignored, downloaded on first use)
├── tests/
├── architecture.md              # Full system architecture and build plan
├── pyproject.toml
└── .env.example
```

---

## Getting started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — install with `pip install uv`
- A webcam **or** an RTSP/MJPEG stream (e.g. Raspberry Pi with `picamera2`)

### Install

```bash
git clone git@github.com:LStaehli/vip--video-image-processor.git
cd vip--video-image-processor
python -m uv sync
```

### Configure

```bash
cp .env.example .env
```

Key settings in `.env`:

| Variable | Default | Description |
|---|---|---|
| `STREAM_URL` | `0` | `0` = laptop webcam; or an RTSP/MJPEG URL |
| `TARGET_FPS` | `15` | Pipeline frame rate |
| `JPEG_QUALITY` | `75` | JPEG quality sent to browser (1–100) |
| `ENABLE_MOTION` | `false` | Motion tracking overlay |
| `ENABLE_ZONES` | `false` | Detection zone alerts |
| `ENABLE_DETECTION` | `false` | YOLOv8 object detection |

### Run

```bash
python -m uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** in your browser.

> **macOS note:** the first run may require granting camera access to your terminal application in System Settings → Privacy & Security → Camera.

---

## API reference

### Stream

| Endpoint | Description |
|---|---|
| `GET /` | Browser UI |
| `WS /ws/video` | Binary JPEG frame stream |
| `WS /ws/events` | JSON event stream (zone alarms, status) |
| `GET /stream.mjpeg` | MJPEG fallback stream |
| `GET /api/status` | Stream health, FPS, client count |

### Configuration

```bash
# Get current config
curl http://localhost:8000/api/config

# Update at runtime (no restart needed)
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"target_fps": 10, "jpeg_quality": 60, "enable_motion": true}'
```

---

## Raspberry Pi setup

The Pi streams raw video only — all processing runs on the server.

```bash
# On the Pi: install mediamtx, then stream via RTSP
mediamtx &
libcamera-vid -t 0 --inline --listen -o - \
  | ffmpeg -i - -c copy -f rtsp rtsp://localhost:8554/cam
```

Then set in your server's `.env`:

```
STREAM_URL=rtsp://<raspberry-pi-ip>:8554/cam
```

---

## Architecture

See [`architecture.md`](architecture.md) for the full system design, data flow, processor chain interface, and build phase breakdown.

---

## Roadmap

- **Phase 2** — Motion tracking: MOG2 background subtraction, contour drawing, direction arrow, fading position trail
- **Phase 3** — Detection zones: draw polygon zones in the browser, trigger email/browser notifications on entry
- **Phase 4** — Object/person detection: YOLOv8 bounding boxes with class labels and confidence scores
- **Phase 5** — Polish: settings UI, Docker, reconnection hardening, unit tests
