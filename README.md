# VIP — Video Image Processor

A Python web application that ingests one or more live video streams (webcam or Raspberry Pi camera via RTSP/MJPEG), applies real-time computer vision features per channel, and streams the annotated result to a browser via WebSocket.

---

## Features

| Status | Feature |
|--------|---------|
| ✅ Done | Multi-stream support — up to 4 independent channels managed from the UI |
| ✅ Done | Per-channel config — motion, detection, zones, faces and visual settings are independent per channel |
| ✅ Done | Live video streaming (webcam / RTSP / MJPEG) to browser via WebSocket |
| ✅ Done | MJPEG fallback endpoint for clients without WebSocket support |
| ✅ Done | URL-based channel persistence — `?channel=N` in the address bar survives page reload |
| ✅ Done | Processor chain architecture (pluggable CV feature modules) |
| ✅ Done | Motion tracking — MOG2 background subtraction, contour outline, direction arrow, fading trail, center dot |
| ✅ Done | Motion visual settings — colors, sizes and visibility of each overlay element, editable live via UI modal |
| ✅ Done | Detection zones — draw polygon zones in the browser, automatically start/stop recording when movement is detected inside |
| ✅ Done | Per-zone notification messages — custom Telegram and email templates per zone, with variable substitution |
| ✅ Done | Video recording — start/stop via header button or zone trigger; configurable output directory, project name, and filename pattern |
| ✅ Done | Screenshot capture — save a single annotated frame to disk at any time |
| ✅ Done | Object detection — YOLOv8 bounding boxes with class labels and confidence scores, configurable model and class filter |
| ✅ Done | Face recognition — Facenet512/ArcFace embeddings, manual enrollment, auto-enrollment, landmark overlay, rename |
| ✅ Done | SQLite database — persisted streams, zones, zone settings, per-stream config, recording metadata, face recognition history |
| ✅ Done | Notification system — Telegram and email alerts on zone trigger, with per-zone custom messages |
| 🔜 Phase 5 | Polish: Docker packaging, reconnection hardening, unit tests |

---

## Tech stack

- **Backend:** Python 3.11+, [FastAPI](https://fastapi.tiangolo.com/), [OpenCV](https://opencv.org/), [uvicorn](https://www.uvicorn.org/)
- **Computer vision:** OpenCV (motion tracking + zone detection), [YOLOv8 / ultralytics](https://docs.ultralytics.com/) (object detection), [DeepFace](https://github.com/serengil/deepface) (face recognition)
- **Database:** SQLite via [aiosqlite](https://github.com/omnilib/aiosqlite) — streams, zones, recordings, events, face embeddings, per-channel config
- **Real-time transport:** WebSocket (binary JPEG frames + JSON events) + MJPEG fallback
- **Frontend:** Vanilla HTML / JS / CSS — no framework
- **Package manager:** [uv](https://docs.astral.sh/uv/)

---

## Project structure

```
vip--video-image-processor/
├── app/
│   ├── main.py                  # FastAPI app entry point + lifespan
│   ├── config.py                # Pydantic Settings (global .env config) + StreamConfig dataclass
│   ├── stream/
│   │   ├── reader.py            # Threaded VideoCapture with reconnection
│   │   ├── pipeline.py          # Processor chain, FPS throttle, JPEG encode
│   │   ├── registry.py          # StreamRegistry — lifecycle of N independent pipeline stacks
│   │   └── websocket_manager.py # Broadcast frames + events to all clients
│   ├── processors/
│   │   ├── base.py              # BaseProcessor ABC + FrameState dataclass
│   │   ├── motion.py            # Motion tracking
│   │   ├── zones.py             # Detection zones + recording trigger + zone notifications
│   │   ├── detection.py         # YOLOv8 object detection
│   │   └── faces.py             # Face recognition (DeepFace)
│   ├── api/
│   │   ├── stream.py            # /ws/video, /ws/events, /stream.mjpeg (legacy single-stream)
│   │   ├── streams.py           # /api/streams — multi-stream registry + per-stream sub-resources
│   │   ├── config.py            # GET/PUT /api/config (global recording/notification settings)
│   │   ├── recording.py         # POST /api/recording/start|stop|screenshot (legacy)
│   │   ├── zones.py             # /api/zones (legacy single-stream zones)
│   │   └── faces.py             # GET/POST/PATCH/DELETE /api/faces
│   ├── services/
│   │   ├── database.py          # SQLite service — schema, all DB operations
│   │   ├── recording.py         # RecordingService — VideoWriter lifecycle + DB logging
│   │   ├── notifications.py     # Telegram and email notification dispatch
│   │   └── face_store.py        # Face embedding store — in-memory + SQLite backend
│   └── static/                  # Browser frontend (HTML/JS/CSS)
│       ├── index.html
│       ├── css/app.css
│       └── js/
│           ├── stream.js        # WebSocket video + event client, stream tab switching
│           ├── controls.js      # Sidebar panels, sliders, modals, record button
│           ├── zone_editor.js   # Zone polygon drawing + management + notification settings
│           └── notifications.js # Alert notification display
├── models/                      # Model weights (git-ignored, downloaded on first use)
├── recordings/                  # Default output directory for recordings (git-ignored)
├── vip.db                       # SQLite database (git-ignored)
├── architecture.md              # Full system architecture
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

Copy `.env.example` to `.env` and edit as needed.

**Global settings** (apply to the whole application):

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `vip.db` | SQLite database file path |
| `RECORDING_OUTPUT_DIR` | `recordings` | Directory where recordings and screenshots are saved |
| `RECORDING_PROJECT_NAME` | `vip` | Project name used in filename patterns |
| `RECORDING_FILENAME_PATTERN` | `{project_name}_{channel_number}_{current_timestamp}` | Filename template (see variables below) |
| `NOTIFY_ON_ZONE_TRIGGER` | `false` | Default: send notifications on zone trigger |
| `NOTIFY_COOLDOWN` | `60` | Seconds between repeated alerts for the same zone |
| `TELEGRAM_BOT_TOKEN` | `` | Telegram bot token (optional) |
| `TELEGRAM_CHAT_ID` | `` | Telegram chat/channel ID (optional) |
| `SMTP_HOST` | `` | SMTP server hostname (optional) |
| `SMTP_PORT` | `587` | SMTP port (587 = STARTTLS, 465 = implicit TLS) |
| `SMTP_USER` / `SMTP_PASSWORD` | `` | SMTP credentials |
| `SMTP_FROM` | `` | Sender address (defaults to `SMTP_USER`) |
| `NOTIFY_EMAIL` | `` | Recipient email address |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG` for diagnostics) |

**Per-channel defaults** — these values are seeded into each new channel's config the first time it starts. After that, the channel stores its own values in the database and the `.env` values are no longer read for that channel.

| Variable | Default | Description |
|---|---|---|
| `TARGET_FPS` | `15` | Pipeline frame rate |
| `JPEG_QUALITY` | `70` | JPEG quality sent to browser (1–100) |
| `ENABLE_MOTION` | `false` | Motion tracking overlay |
| `ENABLE_ZONES` | `false` | Detection zone recording trigger |
| `ENABLE_DETECTION` | `false` | YOLOv8 object detection |
| `ENABLE_FACES` | `false` | Face recognition |
| `ZONE_STOP_MODE` | `zone` | When to stop zone-triggered recording: `zone` or `stream` |
| `YOLO_MODEL` | `yolov8n.pt` | Model weights file (downloaded on first use) |
| `YOLO_CONFIDENCE` | `0.4` | Minimum detection confidence (0.05–0.95) |
| `YOLO_SKIP_FRAMES` | `3` | Run inference every N frames |
| `DETECT_CLASSES` | `` | Comma-separated class filter, empty = all COCO classes |
| `FACE_MODEL` | `Facenet512` | Recognition model (`Facenet512` or `ArcFace`) |
| `FACE_SIMILARITY_THRESHOLD` | `0.4` | Cosine similarity required to identify a face |
| `FACE_SKIP_FRAMES` | `3` | Run recognition every N frames |
| `MOTION_MIN_AREA` | `3500` | Minimum blob area to track (px²) |
| `MOTION_TRAIL_LENGTH` | `30` | Number of historical positions in the trail |
| `MOTION_MOG2_THRESHOLD` | `80` | MOG2 variance threshold (sensitivity) |
| `MOTION_DILATE_KERNEL` | `50` | Dilation kernel size — larger values merge nearby blobs |

### Run

```bash
python -m uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** in your browser.

> **macOS note:** the first run may require granting camera access to your terminal application in System Settings → Privacy & Security → Camera.

---

## UI overview

### Header

The header contains the application title, the **stream tab bar** (visible when more than one channel is active), and quick-access icon buttons on the right:

| Button | Description |
|---|---|
| Record (red dot) | Start/stop manual recording for the active channel |
| Screenshot (camera) | Save a single annotated frame |
| Sidebar toggle | Show/hide the right-hand controls sidebar (persisted across reloads) |
| Stream settings (gear) | Open the stream settings modal for the active channel |

A hamburger menu on the far left opens **General Settings** (recording output directory, project name, filename pattern).

### Stream context bar

Sits below the header and shows live stats for the active channel: connection indicator, source URL, FPS, and connected client count.

### Sidebar

The right-hand collapsible sidebar contains feature panels (Motion, Zones, Object Detection, Face Recognition) for the **active channel**. All settings are per-channel and apply independently to each stream. Click a panel header to expand or collapse it.

### Tab bar

When more than one channel is registered, tabs appear in the header. Clicking a tab switches the video feed and sidebar to that channel. The active channel is reflected in the URL (`?channel=N`) so the page reloads on the correct channel.

---

## Multi-stream channels

VIP supports up to **4 independent channels** (RTSP, MJPEG, or local webcam). Each channel runs its own pipeline stack with independent processors, zones, config, and recording service.

Channels are managed in the **Stream Settings** modal (gear icon):

1. Click **+ Add channel**, enter a channel number (1–4), name, and source URL.
2. Click **Apply** — the tab appears immediately and the pipeline starts automatically.
3. To edit or delete a channel, use the edit (✎) and delete (×) buttons in the channel list.

Channel numbers must be unique. Attempting to create or edit a channel with a duplicate number shows an error.

---

## Detection Zones

Detection zones let you draw one or more polygon areas on the video frame. When a tracked object enters a zone, recording starts automatically. Zones are **per-channel** and persisted in the database.

> **Prerequisite:** Motion Tracking must be enabled — zones use the centroids produced by the motion processor to detect presence.

### How to draw a zone

1. Enable **Detection Zones** in the sidebar toggle.
2. Click **Draw zone**.
3. Click on the video frame to place polygon vertices. A dashed orange line connects your points as you draw.
4. Close the polygon by clicking the first vertex (an orange highlight indicates snapping range) or by double-clicking anywhere.
5. A dialog appears — enter a name for the zone.
6. The zone is saved and immediately active on the server. It will appear baked into the video frames as a semi-transparent orange polygon.

To delete a zone, click the **×** button next to its name in the sidebar list. Press **Escape** at any time to cancel an in-progress drawing.

### Notification settings per zone

Each zone has a **notification settings** panel (gear icon next to the zone name). You can configure custom Telegram and email message templates that are sent when that specific zone is triggered.

Templates support the following variables:

| Variable | Example output |
|---|---|
| `{zone_name}` | `Entrance` |
| `{channel_number}` | `1` |
| `{channel_slug}` | `front-door` |
| `{current_timestamp}` | `2026-04-23 14:31:42` |

Leave a message blank to use the default notification message for that channel.

### Recording behaviour

| Stop mode | Behaviour |
|---|---|
| **No movement in zone** | Recording stops 10 s after the tracked object leaves the zone, even if movement continues elsewhere in the frame |
| **No movement in stream** | Recording stops 10 s after all movement in the entire frame disappears |

Select the mode using the radio buttons in the Detection Zones panel.

---

## Recording

### Manual recording

Click the **record button** (red dot) in the header to start recording the active channel. The button pulses red and an elapsed timer appears while recording is active. Click again to stop and save the file.

### Screenshot

Click the **camera icon** button in the header to save a single annotated frame as a JPEG. A brief green flash confirms the capture.

### Output path

Recordings and screenshots are saved to the directory configured in **General Settings** (hamburger menu). The filename is built from a configurable pattern:

| Variable | Example output |
|---|---|
| `{project_name}` | `vip` |
| `{current_date}` | `2026-04-23` |
| `{current_timestamp}` | `2026-04-23_14-31-42` |
| `{channel_number}` | `1` |
| `{channel_slug}` | `front-door` |

Example pattern: `{project_name}_{channel_number}_{current_timestamp}` → `vip_1_2026-04-23_14-31-42.mp4`

| File type | Suffix |
|---|---|
| Video recording | `.mp4` |
| Manual screenshot | `_screenshot.jpg` |
| Auto-enroll capture | `_autoenroll.jpg` |

---

## Motion Tracking

Enable the **Motion Tracking** toggle in the sidebar to activate the MOG2 background subtraction pipeline. Moving objects are identified as blobs, tracked frame-to-frame, and annotated in real time.

Settings are per-channel and take effect immediately — no restart needed.

### Sidebar controls

| Control | Description |
|---|---|
| Toggle switch | Enable / disable motion tracking |
| Sensitivity | MOG2 variance threshold — lower = more sensitive to subtle movement |
| Min area (px²) | Minimum blob size to track — filters out noise and compression artefacts |
| Blob merge | Dilation kernel size — higher values fuse nearby motion regions into one polygon |

### Visual settings modal

Click **Visual settings…** to fine-tune the appearance of each overlay element:

| Group | Controls |
|---|---|
| **Trail** | Show/hide toggle · color picker · history length · max dot radius |
| **Object outline** | Show/hide toggle · color picker · stroke thickness |
| **Direction arrow** | Show/hide toggle · color picker · stroke thickness |
| **Center dot** | Show/hide toggle · color picker · dot radius |

---

## Object Detection

Enable the **Object Detection** toggle in the sidebar to activate YOLOv8 inference. Detected objects are drawn as bounding boxes with a class label and confidence score. Settings are per-channel.

> Model weights are downloaded automatically on first use and cached in `models/`. A spinner is shown in the sidebar during load.

### Sidebar controls

| Control | Description |
|---|---|
| Toggle switch | Enable / disable detection |
| Model | YOLOv8 variant to use — `yolov8n` is fastest, `yolov8x` is most accurate |
| Confidence | Minimum confidence threshold for a detection to be shown (5–95 %) |
| Skip frames | Run inference only every N frames — reduces CPU/GPU load |
| Class filter | Comma-separated list of class names to show (e.g. `person, car`). Leave empty to show all classes. |

### YOLOv8 model variants

| Model | Size | Speed | Use case |
|---|---|---|---|
| `yolov8n.pt` | 6 MB | Fastest | Raspberry Pi / low-power devices |
| `yolov8s.pt` | 22 MB | Fast | General use |
| `yolov8m.pt` | 50 MB | Balanced | Better accuracy on small objects |
| `yolov8l.pt` | 87 MB | Slower | High accuracy |
| `yolov8x.pt` | 136 MB | Slowest | Maximum accuracy |

### COCO classes (80 total)

```
person, bicycle, car, motorcycle, airplane, bus, train, truck, boat,
traffic light, fire hydrant, stop sign, parking meter, bench, bird,
cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe, backpack,
umbrella, handbag, tie, suitcase, frisbee, skis, snowboard, sports ball,
kite, baseball bat, baseball glove, skateboard, surfboard, tennis racket,
bottle, wine glass, cup, fork, knife, spoon, bowl, banana, apple,
sandwich, orange, broccoli, carrot, hot dog, pizza, donut, cake, chair,
couch, potted plant, bed, dining table, toilet, tv, laptop, mouse,
remote, keyboard, cell phone, microwave, oven, toaster, sink,
refrigerator, book, clock, vase, scissors, teddy bear, hair drier, toothbrush
```

### Training a custom model

```python
from ultralytics import YOLO

model = YOLO("yolov8n.pt")
model.train(
    data="path/to/dataset.yaml",
    epochs=50,
    imgsz=640,
    project="models",
    name="my-custom-model",
)
```

Set the resulting weights in `.env` or via the sidebar:
```
YOLO_MODEL=models/my-custom-model/weights/best.pt
```

---

## Face Recognition

Enable the **Face Recognition** toggle in the sidebar to activate face detection and identification. Known faces are drawn with a green bounding box and their name + similarity score. Unknown faces are shown with a grey bounding box. Settings are per-channel.

> Model weights are downloaded automatically on first use (~100 MB, stored in `~/.deepface/weights`). A spinner is shown while loading.

### Sidebar controls

| Control | Description |
|---|---|
| Toggle switch | Enable / disable face recognition |
| Match threshold | Minimum cosine similarity to accept a match — higher = stricter |
| Run every | Frames between recognition calls — higher = faster stream |
| Show landmarks | Overlay 5-point facial landmark mesh (eyes, nose, mouth corners) |
| Auto-enroll unknown faces | Automatically enroll unknown faces that meet the quality threshold |
| Min quality | Minimum detection confidence to trigger auto-enrollment (50–100 %) |

### Enrolling faces manually

1. Enable Face Recognition and wait for the model to finish loading.
2. Position the face clearly in front of the camera.
3. Click **Enroll face…** and enter a name.
4. The embedding is saved to the database and active on the next frame.

### Auto-enrollment

When **Auto-enroll unknown faces** is enabled, any unknown face detected above the **Min quality** threshold is enrolled automatically with a timestamped name (`face_20260422_143142`) and a screenshot is saved with a `_autoenroll.jpg` suffix.

### Managing enrolled faces

| Action | How |
|---|---|
| Rename | Click the ✎ icon, enter a new name |
| Delete | Click the × button |

### Models

| Model | Accuracy (LFW) | Notes |
|---|---|---|
| `Facenet512` | ~99.6 % | Default — fast and accurate |
| `ArcFace` | ~99.8 % | Best accuracy, slightly slower |

---

## Stream settings

Click the **gear icon** in the header to open the Stream Settings modal for the **active channel**:

| Tab | Controls |
|---|---|
| **Channel list** | Register, edit, or delete channels. Channel numbers 1–4; must be unique. |
| **Active channel** | Source URL, target FPS, JPEG quality |

Live stats (connection status, actual FPS, client count) are shown read-only in the context bar.

---

## API reference

### Streams

| Endpoint | Description |
|---|---|
| `GET /api/streams` | List all registered streams |
| `POST /api/streams` | Register a new stream (`channel_number`, `name`, `url`) |
| `PATCH /api/streams/{id}` | Update stream properties |
| `DELETE /api/streams/{id}` | Remove a stream and stop its pipeline |
| `GET /api/streams/{id}/status` | Live stats for one stream |

### Per-stream config

| Endpoint | Description |
|---|---|
| `GET /api/streams/{id}/config` | Get all per-channel settings |
| `PUT /api/streams/{id}/config` | Update one or more per-channel settings (partial update) |

Configurable fields (all optional in PUT):

| Field | Type | Description |
|---|---|---|
| `target_fps` | int | Pipeline frame rate (1–60) |
| `jpeg_quality` | int | JPEG encoding quality (10–100) |
| `enable_motion` | bool | Motion tracking on/off |
| `enable_zones` | bool | Detection zones on/off |
| `enable_detection` | bool | Object detection on/off |
| `enable_faces` | bool | Face recognition on/off |
| `zone_stop_mode` | string | `zone` or `stream` |
| `notify_on_zone_trigger` | bool | Zone trigger notifications on/off |
| `yolo_model` | string | YOLO weights file |
| `yolo_confidence` | float | Detection confidence threshold |
| `yolo_skip_frames` | int | Frames between YOLO inferences |
| `detect_classes` | string | Comma-separated class filter |
| `face_model` | string | `Facenet512` or `ArcFace` |
| `face_similarity_threshold` | float | Cosine similarity threshold |
| `face_skip_frames` | int | Frames between face recognition calls |
| `face_show_landmarks` | bool | Landmark overlay on/off |
| `face_auto_enroll` | bool | Auto-enrollment on/off |
| `face_auto_enroll_min_score` | float | Minimum det_score for auto-enroll |
| `motion_*` | various | All motion tuning and visual style fields |

### Per-stream recording

| Endpoint | Description |
|---|---|
| `POST /api/streams/{id}/recording/start` | Start recording on stream |
| `POST /api/streams/{id}/recording/stop` | Stop recording on stream |
| `POST /api/streams/{id}/recording/screenshot` | Take screenshot from stream |
| `GET /api/streams/{id}/recording/status` | Recording state for stream |

### Per-stream zones

| Endpoint | Description |
|---|---|
| `GET /api/streams/{id}/zones` | List zones for stream |
| `POST /api/streams/{id}/zones` | Create a zone (`name`, `polygon`) |
| `DELETE /api/streams/{id}/zones/{zone_id}` | Delete one zone |
| `DELETE /api/streams/{id}/zones` | Clear all zones on stream |
| `GET /api/streams/{id}/zones/{zone_id}/settings` | Get zone notification settings |
| `PUT /api/streams/{id}/zones/{zone_id}/settings` | Set zone notification message templates |

### WebSocket

| Channel | Format | Purpose |
|---|---|---|
| `WS /ws/video/{stream_id}` | Binary JPEG | Annotated video frames at target FPS |
| `WS /ws/events/{stream_id}` | JSON | Zone alerts, recording state, model events, face events |

### WebSocket events

| Type | Fields | Trigger |
|---|---|---|
| `recording_started` | `path` | Recording begins |
| `recording_stopped` | `saved_to` | Recording ends and file is written |
| `zone_alert` | `zone_id`, `zone_name` | Motion centroid enters a zone |
| `model_loading` | `model` | YOLO model load begins |
| `model_ready` | `model` | YOLO model is ready |
| `model_error` | `model`, `error` | YOLO model failed to load |
| `face_model_loading` | `model` | Face model load begins |
| `face_model_ready` | `model` | Face model is ready |
| `face_model_error` | `model`, `error` | Face model failed to load |
| `face_recognized` | `name`, `similarity` | Known face detected (10 s cooldown) |
| `face_enrolled` | `name`, `created_at` | Face auto-enrolled |

### Faces

```bash
# List enrolled faces
curl http://localhost:8000/api/faces

# Enroll a face from the current frame
curl -X POST http://localhost:8000/api/faces/enroll \
  -H "Content-Type: application/json" \
  -d '{"name": "John"}'

# Rename an enrolled face
curl -X PATCH http://localhost:8000/api/faces/John \
  -H "Content-Type: application/json" \
  -d '{"new_name": "John Smith"}'

# Delete a face
curl -X DELETE http://localhost:8000/api/faces/John

# Clear all faces
curl -X DELETE http://localhost:8000/api/faces
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

Then register the stream in the UI (Stream Settings → Add channel) with:
```
URL: rtsp://<raspberry-pi-ip>:8554/cam
```

---

# Notification system

## Telegram

### Step 1 — Create a bot and get the token

1. Open Telegram and search for @BotFather
2. Send `/newbot`
3. Choose a name (e.g. VIP Monitor) and a username (must end in `bot`, e.g. `vip_monitor_bot`)
4. BotFather replies with your token — looks like: `7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

→ This is your `TELEGRAM_BOT_TOKEN`

### Step 2 — Add the bot to your channel

1. Open your channel → Edit → Administrators
2. Add your bot as an administrator (it needs permission to Post Messages)

### Step 3 — Get the channel chat ID

1. Send any message to your channel
2. Open this URL in your browser (replace `YOUR_TOKEN`):
   `https://api.telegram.org/botYOUR_TOKEN/getUpdates`
3. Look for `"chat"` → `"id"` in the JSON response. For a private channel it is a negative number like `-1001234567890`.

→ This is your `TELEGRAM_CHAT_ID`

> If `getUpdates` returns an empty array: forward a message from the channel to the bot directly, then try again. Alternatively, use @userinfobot — forward a message from your channel to it and it will reply with the channel's ID.

### Step 4 — Add to `.env`

```
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=-1001234567890
```

### Per-zone custom messages

After setting up the bot, you can configure a **custom message template** per zone via the gear icon in the zone list. Use template variables (`{zone_name}`, `{channel_number}`, `{channel_slug}`, `{current_timestamp}`) to include dynamic context. Leave the field empty to use the default message.

---

## Architecture

See [`architecture.md`](architecture.md) for the full system design, data flow, and processor chain details.

---

## Roadmap

- **Phase 5** — Polish: Docker packaging, reconnection hardening, unit tests
