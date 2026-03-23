# Copilot Instructions — Security Camera Project

## Project Overview
This is a **home security camera system** built in Python. It combines real-time motion detection, facial recognition, and instant Telegram alerts. The target user is someone who wants to monitor their home without reviewing hours of footage — the system only records and alerts when something happens.

## Architecture
The system follows a pipeline pattern where each camera frame flows through sequential stages:

1. **Capture** → OpenCV reads frames from webcam, Pi Camera, or IP camera (MJPEG/RTSP)
2. **Motion Detection** → Gaussian blur + absolute frame difference + contour analysis. If changed pixel area exceeds `MOTION_THRESHOLD`, motion is confirmed.
3. **Face Recognition** → Only runs when motion is detected (saves CPU). Uses `face_recognition` library (dlib HOG/CNN). Compares detected faces against known faces in `rostros_conocidos/` folder.
4. **Alert & Record** → Sends photo + caption to Telegram via Bot API. Records MP4 clip of the event. Logs event for daily summary.

## Tech Stack
- **Language**: Python 3.8+
- **Computer Vision**: OpenCV (`cv2`) for capture, frame processing, motion detection, video recording
- **Face Recognition**: `face_recognition` library (wraps dlib). Encodings compared with euclidean distance, tolerance 0.6
- **Notifications**: Telegram Bot API via `urllib` (no external telegram library needed for basic usage)
- **Video Codec**: MP4 with `mp4v` codec via OpenCV VideoWriter

## Key Design Decisions
- Motion detection uses **frame differencing** (not background subtraction) for simplicity and low CPU usage
- Face recognition runs on **25% scaled frames** and only every N frames to reduce CPU load on Raspberry Pi
- Telegram alerts are sent in **background threads** so the camera pipeline never blocks
- **Cooldown system** prevents alert spam (configurable, default 30 seconds between alerts)
- Video recording is **event-driven**: only records when motion is active + N seconds after last motion

## Module Structure
```
security_camera.py          # Main entry point and SecurityCamera orchestrator class
├── TelegramNotifier        # Sends messages and photos to Telegram (async via threads)
├── FaceRecognizer          # Loads known faces, identifies faces in frames
├── MotionDetector          # Frame differencing, threshold, contour detection
└── VideoRecorder           # Event-driven MP4 recording with OpenCV VideoWriter
```

## Configuration Constants (top of security_camera.py)
| Constant | Type | Purpose |
|----------|------|---------|
| `TELEGRAM_BOT_TOKEN` | str | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | str | User chat ID from @userinfobot |
| `CAMERA_SOURCE` | int/str | 0=webcam, 1=second cam, or URL for IP cam |
| `CAMERA_RESOLUTION` | tuple | (width, height) in pixels |
| `MOTION_THRESHOLD` | int | Minimum pixel area change to trigger motion (default 5000) |
| `COOLDOWN_SECONDS` | int | Minimum seconds between consecutive alerts |
| `FACE_RECOGNITION_TOLERANCE` | float | 0.0-1.0, lower = stricter match (default 0.6) |
| `FACE_CHECK_INTERVAL` | int | Run face recognition every N frames |
| `RECORD_SECONDS_AFTER` | int | Keep recording N seconds after last motion |
| `ENABLE_FACE_RECOGNITION` | bool | Toggle face recognition on/off |
| `ENABLE_DAILY_SUMMARY` | bool | Toggle daily event summary |

## File & Folder Conventions
- `rostros_conocidos/` — Known face photos. Filename = person name (e.g., `juan.jpg`, `maria_garcia.png`). Underscores become spaces, names are title-cased.
- `grabaciones/` — Recorded video clips. Named `motion_YYYYMMDD_HHMMSS.mp4`
- `security_camera.log` — Runtime log with timestamps
- `snapshot_temp.jpg` — Temporary file for Telegram photo upload (overwritten each time)

## Coding Conventions
- Language: Python 3.8+ with type hints where helpful
- Classes: PascalCase, one responsibility per class
- Constants: UPPER_SNAKE_CASE at module top
- Logging: use `logging` module, not print()
- Threads: daemon threads for non-blocking I/O (Telegram sends)
- Error handling: try/except around all I/O operations (camera, network, filesystem)
- OpenCV frames: always BGR format (numpy ndarray, shape HxWx3)
- Face locations: tuple (top, right, bottom, left) in pixel coordinates

## Hardware Targets
- **Primary**: Raspberry Pi 4 (4GB) + Pi Camera Module v2
- **Dev/Testing**: Any laptop with webcam (CAMERA_SOURCE=0)
- **Budget**: ESP32-CAM (limited, no face recognition)
- **IP cameras**: Any MJPEG or RTSP stream URL

## Common Patterns to Follow
```python
# Motion detection pattern
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
gray = cv2.GaussianBlur(gray, (21, 21), 0)
delta = cv2.absdiff(previous_frame, gray)
thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# Face recognition pattern
small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
locations = face_recognition.face_locations(rgb)
encodings = face_recognition.face_encodings(rgb, locations)
matches = face_recognition.compare_faces(known_encodings, encoding, tolerance=0.6)

# Async Telegram send pattern
thread = threading.Thread(target=send_function, args=(data,), daemon=True)
thread.start()
```

## Dependencies
See `requirements.txt`. Core: opencv-python, face_recognition, numpy, Pillow.
Optional: python-telegram-bot (for advanced bot features beyond basic HTTP).

## Future Improvements (not yet implemented)
- Multiple camera support (thread per camera)
- Web dashboard with Flask/FastAPI + live MJPEG stream
- YOLO object detection (person vs pet vs vehicle)
- Cloud storage upload (Google Drive / S3)
- Audio detection (glass breaking, loud sounds)
- Exclusion zones (ignore motion in specific frame regions)
- WhatsApp integration via Cloud API
