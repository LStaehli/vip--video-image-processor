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
| ✅ Done | Object detection — YOLOv8 bounding boxes with class labels and confidence scores, configurable model and class filter |
| ✅ Done | Face recognition — Facenet512/ArcFace embeddings, manual enrollment, auto-enrollment, landmark overlay, rename |
| ✅ Done | SQLite database — persisted zones, recording metadata, zone events, face recognition history |
| 🔜 Phase 5 | Polish: Docker packaging, reconnection hardening, unit tests |

---

## Tech stack

- **Backend:** Python 3.11+, [FastAPI](https://fastapi.tiangolo.com/), [OpenCV](https://opencv.org/), [uvicorn](https://www.uvicorn.org/)
- **Computer vision:** OpenCV (motion tracking + zone detection), [YOLOv8 / ultralytics](https://docs.ultralytics.com/) (object detection), [DeepFace](https://github.com/serengil/deepface) (face recognition)
- **Database:** SQLite via [aiosqlite](https://github.com/omnilib/aiosqlite) — zones, recordings, events, face embeddings
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
│   │   ├── detection.py         # YOLOv8 object detection
│   │   └── faces.py             # Face recognition (DeepFace)
│   ├── api/
│   │   ├── stream.py            # /ws/video, /ws/events, /stream.mjpeg, /api/status
│   │   ├── config.py            # GET/PUT /api/config
│   │   ├── recording.py         # POST /api/recording/start|stop|screenshot
│   │   ├── zones.py             # GET/POST/DELETE /api/zones
│   │   └── faces.py             # GET/POST/PATCH/DELETE /api/faces
│   ├── services/
│   │   ├── database.py          # SQLite service — schema, all DB operations
│   │   ├── recording.py         # RecordingService — VideoWriter lifecycle + DB logging
│   │   └── face_store.py        # Face embedding store — in-memory + SQLite backend
│   └── static/                  # Browser frontend (HTML/JS/CSS)
│       ├── index.html
│       ├── css/app.css
│       └── js/
│           ├── stream.js        # WebSocket video + event client, status polling
│           ├── controls.js      # Sidebar panels, sliders, modals, record button
│           ├── zone_editor.js   # Zone polygon drawing + management
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

Copy `.env.example` to `.env` and edit as needed:

| Variable | Default | Description |
|---|---|---|
| `STREAM_URL` | `0` | `0` = laptop webcam; or an RTSP/MJPEG URL |
| `TARGET_FPS` | `15` | Pipeline frame rate |
| `JPEG_QUALITY` | `70` | JPEG quality sent to browser (1–100) |
| `ENABLE_MOTION` | `false` | Motion tracking overlay |
| `ENABLE_ZONES` | `false` | Detection zone recording trigger |
| `ENABLE_DETECTION` | `false` | YOLOv8 object detection |
| `ENABLE_FACES` | `false` | Face recognition |
| `YOLO_MODEL` | `yolov8n.pt` | Model weights file (downloaded on first use) |
| `YOLO_CONFIDENCE` | `0.4` | Minimum detection confidence (0.05–0.95) |
| `YOLO_SKIP_FRAMES` | `3` | Run inference every N frames |
| `DETECT_CLASSES` | `` | Comma-separated class filter, empty = all COCO classes |
| `FACE_MODEL` | `Facenet512` | Recognition model (`Facenet512` or `ArcFace`) |
| `FACE_SIMILARITY_THRESHOLD` | `0.4` | Cosine similarity required to identify a face |
| `FACE_SKIP_FRAMES` | `3` | Run recognition every N frames |
| `RECORDING_OUTPUT_DIR` | `recordings` | Directory where recordings and screenshots are saved |
| `RECORDING_PROJECT_NAME` | `vip` | Project name used in filename patterns |
| `RECORDING_FILENAME_PATTERN` | `{project_name}_{current_timestamp}` | Filename template |
| `DB_PATH` | `vip.db` | SQLite database file path |
| `ZONE_STOP_MODE` | `zone` | When to stop zone-triggered recording: `zone` or `stream` |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG` for diagnostics) |

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

Zones are persisted in the SQLite database and reloaded automatically on server restart — no need to redraw them.

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

---

## Recording

### Manual recording

Click the **record button** (red dot) in the top-right header area to start recording. The button pulses red and an elapsed timer is shown while recording is active. Click again to stop and save the file.

### Screenshot

Click the **camera icon** button next to the record button to save a single annotated frame as a JPEG. A brief green flash confirms the capture.

### Output path

Recordings and screenshots are saved to the directory configured in **General Settings** (hamburger menu, top left). The filename is built from a pattern supporting these variables:

| Variable | Example output |
|---|---|
| `{project_name}` | `vip` |
| `{current_date}` | `2026-04-22` |
| `{current_timestamp}` | `2026-04-22_14-31-42` |

Example pattern: `{project_name}_{current_timestamp}` → `vip_2026-04-22_14-31-42.mp4`

| File type | Suffix |
|---|---|
| Video recording | `.mp4` |
| Manual screenshot | `_screenshot.jpg` |
| Auto-enroll capture | `_autoenroll.jpg` |

---

## Object Detection

Enable the **Object Detection** toggle in the sidebar to activate YOLOv8 inference on each frame. Detected objects are drawn as bounding boxes with a class label and confidence score. Each class is assigned a consistent color across frames.

> The model weights are downloaded automatically on first use and cached in the `models/` directory. The first inference after enabling may take a few seconds while the model loads — a spinner is shown in the sidebar during this time.

### Sidebar controls

| Control | Description |
|---|---|
| Toggle switch | Enable / disable detection without restarting |
| Model | YOLOv8 variant to use — `yolov8n` is fastest, `yolov8x` is most accurate |
| Confidence | Minimum confidence threshold for a detection to be shown (5–95 %) |
| Skip frames | Run inference only every N frames — reduces CPU/GPU load at the cost of responsiveness |
| Class filter | Comma-separated list of class names to show (e.g. `person, car`). Leave empty to show all classes. |

### Customising what gets detected

#### Option 1 — Filter the built-in COCO classes

By default YOLOv8 is trained on the [COCO dataset](https://cocodataset.org/) which includes 80 everyday object categories. Use the **Class filter** field in the sidebar (or the `detect_classes` API field) to restrict which classes are displayed.

Full list of COCO class names:

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

#### Option 2 — Swap the pre-trained model

| Model | Size | Speed | Use case |
|---|---|---|---|
| `yolov8n.pt` | 6 MB | Fastest | Raspberry Pi / low-power devices |
| `yolov8s.pt` | 22 MB | Fast | General use |
| `yolov8m.pt` | 50 MB | Balanced | Better accuracy on small objects |
| `yolov8l.pt` | 87 MB | Slower | High accuracy |
| `yolov8x.pt` | 136 MB | Slowest | Maximum accuracy |

#### Option 3 — Train on your own classes

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

Set the resulting weights in `.env` or the sidebar:
```
YOLO_MODEL=models/my-custom-model/weights/best.pt
```

---

## Face Recognition

Enable the **Face Recognition** toggle in the sidebar to activate face detection and identification on each frame. Known faces are drawn with a green bounding box and their name + similarity score. Unknown faces are shown with a grey bounding box.

> The model weights are downloaded automatically on first use (~100 MB, stored in `~/.deepface/weights`). A spinner is shown in the sidebar while loading.

### Sidebar controls

| Control | Description |
|---|---|
| Toggle switch | Enable / disable face recognition without restarting |
| Match threshold | Minimum cosine similarity to accept a match — higher = stricter |
| Run every | Frames between recognition calls — higher = faster stream |
| Show landmarks | Overlay 5-point facial landmark mesh (eyes, nose, mouth corners) with connecting lines |
| Auto-enroll unknown faces | Automatically enroll unknown faces that meet the quality threshold |
| Min quality | Minimum detection confidence to trigger auto-enrollment (50–100 %) |

### Enrolling faces manually

1. Make sure Face Recognition is enabled and the model has finished loading.
2. Position your face clearly in front of the camera.
3. Click **Enroll face…** and enter a name.
4. The embedding is saved immediately to the database and the face is active on the next frame.

### Auto-enrollment

When **Auto-enroll unknown faces** is enabled, any unknown face detected with a confidence score above the **Min quality** threshold is enrolled automatically. A timestamped name is generated (`face_20260422_143142`) and a screenshot of the frame is saved to the recordings directory with a `_autoenroll.jpg` suffix.

A green notification appears in the sidebar and the enrolled faces list refreshes automatically.

### Managing enrolled faces

Each entry in the sidebar face list shows the name and enrollment timestamp.

| Action | How |
|---|---|
| Rename | Click the ✎ icon, enter a new name in the prompt |
| Delete | Click the × button |

Renaming and deletion update both the in-memory store and the database immediately. Enrolled faces survive server restarts.

### Landmark overlay

When **Show landmarks** is enabled, five facial key points are drawn on each detected face: left eye, right eye, nose tip, left mouth corner, and right mouth corner, connected by lines. The overlay uses the same color as the bounding box (green for known, grey for unknown).

Eye positions are taken from the detector when available; otherwise they are estimated from standard facial geometry ratios applied to the bounding box.

### Models

| Model | Accuracy (LFW) | Notes |
|---|---|---|
| `Facenet512` | ~99.6 % | Default — fast and accurate |
| `ArcFace` | ~99.8 % | Best accuracy, slightly slower |

Change the model via `.env` (`FACE_MODEL=ArcFace`). The model reloads automatically when the setting changes.

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
| `WS /ws/events` | JSON event stream |
| `GET /stream.mjpeg` | MJPEG fallback stream |
| `GET /api/status` | Stream health, actual FPS, client count |

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

### Configuration

```bash
# Get current config
curl http://localhost:8000/api/config

# Enable face recognition with strict threshold
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"enable_faces": true, "face_similarity_threshold": 0.6}'

# Enable auto-enrollment
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"face_auto_enroll": true, "face_auto_enroll_min_score": 0.9}'
```

Full list of configurable fields (in addition to motion/zone/detection fields):

| Field | Type | Description |
|---|---|---|
| `enable_faces` | bool | Face recognition on/off |
| `face_model` | string | `Facenet512` or `ArcFace` |
| `face_similarity_threshold` | float | Cosine similarity threshold (0.1–0.9) |
| `face_skip_frames` | int | Run recognition every N frames (1–10) |
| `face_show_landmarks` | bool | Landmark overlay on/off |
| `face_auto_enroll` | bool | Auto-enrollment mode on/off |
| `face_auto_enroll_min_score` | float | Minimum det_score to trigger auto-enroll (0.5–1.0) |

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
# Start / stop recording
curl -X POST http://localhost:8000/api/recording/start
curl -X POST http://localhost:8000/api/recording/stop

# Take a screenshot
curl -X POST http://localhost:8000/api/recording/screenshot

# Check status
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

# Notification system

## Telegram

### Setup for a Telegram channel                                                                                       
                                                                                                                                                                                                                                                    
#### Step 1 — Create a bot and get the token                                                                                                                                                                                                           
                                                                                                                                                                                                                                                    
1. Open Telegram and search for @BotFather                                                                                                                                                                                                        
2. Send /newbot                                                                                                                                                                                                                                   
3. Choose a name (e.g. VIP Monitor) and a username (must end in bot, e.g. vip_monitor_bot)                                                                                                                                                      
4. BotFather replies with your token — looks like: 7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx                                                                                                                                                 
                                                                                                                                                                                                                                                    
→ This is your TELEGRAM_BOT_TOKEN                                                                                                                                                                                                                 
                                                                                                                                                                                                                                                
---                                                                                                                                                                                                                                               
#### Step 2 — Add the bot to your channel                                                                                                                                                                                                            
                                      
1. Open your channel → Edit → Administrators
2. Add your bot as an administrator (it needs permission to Post Messages)                                                                                                                                                                        
                                                                                                                                                                                                                                                    
---                                                                                                                                                                                                                                               
#### Step 3 — Get the channel chat ID                                                                                                                                                                                                                  
                                                                                                                                                                                                                                              
Channel IDs are not visible in the UI. Easiest way:
                                                                                                                                                                                                                                                    
1. Send any message to your channel                                                                                                                                                                                                               
2. Open this URL in your browser (replace YOUR_TOKEN):                                                                                                                                                                                            
https://api.telegram.org/botYOUR_TOKEN/getUpdates                                                                                                                                                                                                 
3. Look for "chat" → "id" in the JSON response. For a public channel it looks like @your_channel_name. For a private channel it's a negative number like -1001234567890.                                                                          
                                                                                                                                                                                                                                                    
→ This is your TELEGRAM_CHAT_ID                                                                                                                                                                                                                   
                                                                                                                                                                                                                                                
▎ If getUpdates returns an empty array: the bot hasn't received any messages yet. Forward a message from the channel to the bot directly, then try the URL again. Alternatively, use @userinfobot — forward a message from your channel to it and 
it will reply with the channel's ID.
                                                                                                                                                                                                                                                
---                                                                                                                                                                                                                                             
Step 4 — Add to your .env
                                                                                                                                                                                                                                                
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=-1001234567890                                                                                                                                                                                                                   
                                                                  

---

## Architecture

See [`architecture.md`](architecture.md) for the full system design, data flow, and processor chain details.

---

## Roadmap

- **Phase 5** — Polish: Docker packaging, reconnection hardening, unit tests
