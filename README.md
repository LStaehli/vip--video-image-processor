# VIP — Video Image Processor

A Python web application that ingests a live video stream (webcam or Raspberry Pi camera via RTSP/MJPEG), applies real-time computer vision features, and streams the annotated result to a browser via WebSocket.

---

## Features

| Status | Feature |
|--------|---------|
| ✅ Done | Live video streaming (webcam / RTSP / MJPEG) to browser via WebSocket |
| ✅ Done | MJPEG fallback endpoint for clients without WebSocket support |
| ✅ Done | Runtime config API — toggle features and tune parameters without restart |
| ✅ Done | Processor chain architecture (pluggable CV feature modules) |
| ✅ Done | Motion tracking — MOG2 background subtraction, contour outline, direction arrow, fading trail, center dot |
| ✅ Done | Motion visual settings — colors, sizes and visibility of each overlay element, editable live via UI modal |
| ✅ Done | Detection zones — draw polygon zones in the browser, automatically start/stop recording when movement is detected inside |
| ✅ Done | Video recording — start/stop via header button or zone trigger; configurable output directory, project name, and filename pattern |
| ✅ Done | Screenshot capture — save a single annotated frame to disk at any time |
| 🔜 Phase 4 | Object/person detection — YOLOv8 bounding boxes with labels |

---

## Tech stack

- **Backend:** Python 3.11+, [FastAPI](https://fastapi.tiangolo.com/), [OpenCV](https://opencv.org/), [uvicorn](https://www.uvicorn.org/)
- **Computer vision:** OpenCV (motion tracking + zone detection), [YOLOv8 / ultralytics](https://docs.ultralytics.com/) (Phase 4)
- **Real-time transport:** WebSocket (binary JPEG frames + JSON events) + MJPEG fallback
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
│   │   └── websocket_manager.py # Broadcast frames + events to all clients
│   ├── processors/
│   │   ├── base.py              # BaseProcessor ABC + FrameState dataclass
│   │   ├── motion.py            # Motion tracking
│   │   ├── zones.py             # Detection zones + recording trigger
│   │   └── detection.py         # YOLOv8 object detection (Phase 4)
│   ├── api/
│   │   ├── stream.py            # /ws/video, /ws/events, /stream.mjpeg, /api/status
│   │   ├── config.py            # GET/PUT /api/config
│   │   ├── recording.py         # POST /api/recording/start|stop|screenshot, GET /api/recording/status
│   │   └── zones.py             # GET/POST/DELETE /api/zones
│   ├── services/
│   │   └── recording.py         # RecordingService — VideoWriter lifecycle
│   └── static/                  # Browser frontend (HTML/JS/CSS)
│       ├── index.html
│       ├── css/app.css
│       └── js/
│           ├── stream.js        # WebSocket video + event client, status polling
│           ├── controls.js      # Sidebar panels, sliders, modals, record button
│           ├── zone_editor.js   # Zone polygon drawing + management
│           └── notifications.js # Zone alert notification display
├── models/                      # YOLOv8 weights (git-ignored, downloaded on first use)
├── recordings/                  # Default output directory for recordings (git-ignored)
├── tests/
├── architecture.md              # Full system architecture and build plan
├── pyproject.toml
└── .env
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

Edit `.env` (or create one) with your settings:

| Variable | Default | Description |
|---|---|---|
| `STREAM_URL` | `0` | `0` = laptop webcam; or an RTSP/MJPEG URL |
| `TARGET_FPS` | `15` | Pipeline frame rate |
| `JPEG_QUALITY` | `70` | JPEG quality sent to browser (1–100) |
| `ENABLE_MOTION` | `false` | Motion tracking overlay |
| `ENABLE_ZONES` | `false` | Detection zone recording trigger |
| `ENABLE_DETECTION` | `false` | YOLOv8 object detection (Phase 4) |
| `RECORDING_OUTPUT_DIR` | `recordings` | Directory where recordings and screenshots are saved |
| `RECORDING_PROJECT_NAME` | `vip` | Project name used in filename patterns |
| `RECORDING_FILENAME_PATTERN` | `{project_name}_{current_timestamp}` | Filename template (see Recording section) |
| `ZONE_STOP_MODE` | `zone` | When to stop zone-triggered recording: `zone` or `stream` |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG` for zone/motion diagnostics) |

### Run

```bash
python -m uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** in your browser.

> **macOS note:** the first run may require granting camera access to your terminal application in System Settings → Privacy & Security → Camera.

---

## UI overview

The header contains quick-access buttons on the right: **record**, **screenshot**, and **stream settings**. A hamburger menu on the left opens **general settings** (recording configuration).

The right-hand sidebar contains collapsible panels for each feature. Click a panel header to expand or collapse it.

---

## Motion Tracking

Enable the **Motion Tracking** toggle in the sidebar to activate the MOG2 background subtraction pipeline. Moving objects are identified as blobs, tracked frame-to-frame, and annotated in real time.

### Sidebar controls

| Control | Description |
|---|---|
| Toggle switch | Enable / disable motion tracking without restarting |
| Sensitivity | MOG2 variance threshold — lower = more sensitive to subtle movement |
| Min area (px²) | Minimum blob size to track — filters out noise and compression artefacts |
| Blob merge | Dilation kernel size — higher values fuse nearby motion regions into one polygon |

### Visual settings modal

Click **Visual settings…** to open a modal for fine-tuning the appearance of each overlay element. All changes apply on the next frame — no restart needed.

| Group | Controls |
|---|---|
| **Trail** | Show/hide toggle · color picker · history length · max dot radius |
| **Object outline** | Show/hide toggle · color picker · stroke thickness |
| **Direction arrow** | Show/hide toggle · color picker · stroke thickness |
| **Center dot** | Show/hide toggle · color picker · dot radius |

**Reset defaults** restores the original values in the form without applying them.

---

## Detection Zones

Detection zones let you draw one or more polygon areas on the video frame. When a tracked object enters a zone, recording starts automatically. Recording stops after a configurable grace period once the zone (or stream) is inactive.

> **Prerequisite:** Motion Tracking must be enabled — zones use the centroids produced by the motion processor to detect presence.

### How to draw a zone

1. Enable **Detection Zones** in the sidebar toggle.
2. Click **Draw zone**.
3. Click on the video frame to place polygon vertices. A dashed orange line connects your points as you draw.
4. Close the polygon by clicking the first vertex (an orange highlight indicates snapping range) or by double-clicking anywhere.
5. Enter a name for the zone in the prompt that appears.
6. The zone is saved and immediately active on the server. It will appear baked into the video frames as a semi-transparent orange polygon.

To delete a zone, click the **×** button next to its name in the sidebar list. Press **Escape** at any time to cancel an in-progress drawing.

### Recording behaviour

| Stop mode | Behaviour |
|---|---|
| **No movement in zone** | Recording stops 10 s after the tracked object leaves the zone, even if movement continues elsewhere in the frame |
| **No movement in stream** | Recording stops 10 s after all movement in the entire frame disappears |

Select the mode using the radio buttons in the Detection Zones panel. The setting takes effect immediately without restart.

When a zone triggers recording, the record button in the header lights up automatically. The recording is saved to the configured output directory using the same filename pattern as manual recordings.

---

## Recording

### Manual recording

Click the **record button** (red dot) in the top-right header area to start recording. The button pulses red and an elapsed timer is shown while recording is active. Click again to stop and save the file.

### Screenshot

Click the **camera icon** button next to the record button to save a single annotated frame as a JPEG. A brief green flash confirms the capture. The file is saved to the same directory as recordings, with `_screenshot` appended to the filename.

### Output path

Recordings and screenshots are saved to the directory configured in **General Settings** (hamburger menu, top left). The filename is built from a pattern supporting these variables:

| Variable | Example output |
|---|---|
| `{project_name}` | `vip` |
| `{current_date}` | `2026-04-21` |
| `{current_timestamp}` | `2026-04-21_14-31-42` |

Example pattern: `{project_name}_{current_timestamp}` → `vip_2026-04-21_14-31-42.mp4`

Screenshots follow the same pattern with `_screenshot.jpg` appended.

---

## Stream settings

Click the **gear icon** in the top-right header to open the Stream Settings modal:

| Setting | Description |
|---|---|
| Source URL | Webcam index (`0`) or RTSP/MJPEG URL — changing this reconnects immediately |
| Target FPS | Pipeline frame rate (1–60) |
| JPEG quality | Encoding quality for frames sent to the browser (10–100) |

Live stats (connection status, actual FPS, client count) are shown read-only in the same modal.

---

## API reference

### Stream

| Endpoint | Description |
|---|---|
| `GET /` | Browser UI |
| `WS /ws/video` | Binary JPEG frame stream |
| `WS /ws/events` | JSON event stream (`recording_started`, `recording_stopped`) |
| `GET /stream.mjpeg` | MJPEG fallback stream |
| `GET /api/status` | Stream health, actual FPS, client count |

### Configuration

```bash
# Get current config
curl http://localhost:8000/api/config

# Change stream source
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"stream_url": "rtsp://192.168.1.10:8554/cam"}'

# Enable motion tracking and tune sensitivity
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"enable_motion": true, "motion_mog2_threshold": 80, "motion_min_area": 1000}'

# Enable zones and set stop mode
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"enable_zones": true, "zone_stop_mode": "stream"}'
```

Full list of configurable fields:

| Field | Type | Description |
|---|---|---|
| `stream_url` | string | Stream source — `"0"` for webcam or RTSP/MJPEG URL |
| `target_fps` | int | Pipeline frame rate (1–60) |
| `jpeg_quality` | int | JPEG encoding quality (1–100) |
| `enable_motion` | bool | Motion tracking on/off |
| `enable_zones` | bool | Detection zones on/off |
| `zone_stop_mode` | string | `"zone"` or `"stream"` |
| `motion_mog2_threshold` | int | MOG2 sensitivity (1–500) |
| `motion_min_area` | int | Minimum contour area in px² |
| `motion_dilate_kernel` | int | Dilation kernel size — controls blob merging (1–51) |
| `motion_trail_length` | int | Trail history length (1–60 frames) |
| `motion_trail_enabled` | bool | Show/hide fading trail |
| `motion_trail_color` | string | Trail color (`#rrggbb`) |
| `motion_trail_max_radius` | int | Trail dot max radius in px |
| `motion_contour_enabled` | bool | Show/hide object outline |
| `motion_contour_color` | string | Contour color (`#rrggbb`) |
| `motion_contour_thickness` | int | Contour stroke thickness in px |
| `motion_arrow_enabled` | bool | Show/hide direction arrow |
| `motion_arrow_color` | string | Arrow color (`#rrggbb`) |
| `motion_arrow_thickness` | int | Arrow stroke thickness in px |
| `motion_center_enabled` | bool | Show/hide center dot |
| `motion_center_color` | string | Center dot color (`#rrggbb`) |
| `motion_center_radius` | int | Center dot radius in px |
| `recording_output_dir` | string | Output directory for recordings |
| `recording_project_name` | string | Project name token in filename patterns |
| `recording_filename_pattern` | string | Filename pattern (see Recording section) |

### Zones

```bash
# List all zones
curl http://localhost:8000/api/zones

# Create a zone (polygon in normalised 0–1 coordinates)
curl -X POST http://localhost:8000/api/zones \
  -H "Content-Type: application/json" \
  -d '{"name": "Entrance", "polygon": [[0.1,0.1],[0.4,0.1],[0.4,0.5],[0.1,0.5]]}'

# Delete a zone
curl -X DELETE http://localhost:8000/api/zones/<zone-id>

# Clear all zones
curl -X DELETE http://localhost:8000/api/zones
```

### Recording

```bash
# Start recording manually
curl -X POST http://localhost:8000/api/recording/start

# Stop recording
curl -X POST http://localhost:8000/api/recording/stop

# Take a screenshot
curl -X POST http://localhost:8000/api/recording/screenshot

# Check recording status
curl http://localhost:8000/api/recording/status
```

---

## Raspberry Pi setup

The Pi streams raw video only — all processing runs on the server machine.

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

- **Phase 4** — Object/person detection: YOLOv8 bounding boxes with class labels and confidence scores
- **Phase 5** — Polish: Docker packaging, reconnection hardening, unit tests
