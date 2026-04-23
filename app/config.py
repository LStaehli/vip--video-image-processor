from dataclasses import dataclass, asdict
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Per-stream runtime configuration ─────────────────────────────────────────

@dataclass
class StreamConfig:
    """Independent configuration for one pipeline stack (one channel).

    Processors read from this instead of the global Settings singleton,
    allowing each channel to have fully independent feature settings.
    """
    # Pipeline
    target_fps: int = 15
    jpeg_quality: int = 70

    # Feature toggles
    enable_motion: bool = False
    enable_zones: bool = False
    enable_detection: bool = False
    enable_faces: bool = False

    # Zones
    zone_stop_mode: str = "zone"
    notify_on_zone_trigger: bool = False

    # Motion tuning
    motion_min_area: int = 3500
    motion_trail_length: int = 30
    motion_mog2_threshold: int = 80
    motion_dilate_kernel: int = 50

    # Motion visual style
    motion_trail_enabled: bool = True
    motion_trail_color: str = "#80f4dd"
    motion_trail_max_radius: int = 7
    motion_contour_enabled: bool = False
    motion_contour_color: str = "#fffdbd"
    motion_contour_thickness: int = 1
    motion_arrow_color: str = "#00c8ff"
    motion_arrow_thickness: int = 2
    motion_arrow_enabled: bool = True
    motion_center_color: str = "#ffc7c7"
    motion_center_radius: int = 5
    motion_center_enabled: bool = True

    # Object detection
    yolo_model: str = "yolov8n.pt"
    yolo_confidence: float = 0.4
    yolo_skip_frames: int = 3
    detect_classes: str = ""

    # Face recognition
    face_model: str = "Facenet512"
    face_similarity_threshold: float = 0.4
    face_skip_frames: int = 3
    face_show_landmarks: bool = True
    face_auto_enroll: bool = False
    face_auto_enroll_min_score: float = 0.85

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def detect_class_list(self) -> list[str]:
        if not self.detect_classes.strip():
            return []
        return [c.strip() for c in self.detect_classes.split(",") if c.strip()]

    @classmethod
    def from_settings(cls, s: "Settings") -> "StreamConfig":
        """Seed a new StreamConfig from the global Settings (env/defaults)."""
        return cls(
            target_fps=s.target_fps,
            jpeg_quality=s.jpeg_quality,
            enable_motion=s.enable_motion,
            enable_zones=s.enable_zones,
            enable_detection=s.enable_detection,
            enable_faces=s.enable_faces,
            zone_stop_mode=s.zone_stop_mode,
            notify_on_zone_trigger=s.notify_on_zone_trigger,
            motion_min_area=s.motion_min_area,
            motion_trail_length=s.motion_trail_length,
            motion_mog2_threshold=s.motion_mog2_threshold,
            motion_dilate_kernel=s.motion_dilate_kernel,
            motion_trail_enabled=s.motion_trail_enabled,
            motion_trail_color=s.motion_trail_color,
            motion_trail_max_radius=s.motion_trail_max_radius,
            motion_contour_enabled=s.motion_contour_enabled,
            motion_contour_color=s.motion_contour_color,
            motion_contour_thickness=s.motion_contour_thickness,
            motion_arrow_color=s.motion_arrow_color,
            motion_arrow_thickness=s.motion_arrow_thickness,
            motion_arrow_enabled=s.motion_arrow_enabled,
            motion_center_color=s.motion_center_color,
            motion_center_radius=s.motion_center_radius,
            motion_center_enabled=s.motion_center_enabled,
            yolo_model=s.yolo_model,
            yolo_confidence=s.yolo_confidence,
            yolo_skip_frames=s.yolo_skip_frames,
            detect_classes=s.detect_classes,
            face_model=s.face_model,
            face_similarity_threshold=s.face_similarity_threshold,
            face_skip_frames=s.face_skip_frames,
            face_show_landmarks=s.face_show_landmarks,
            face_auto_enroll=s.face_auto_enroll,
            face_auto_enroll_min_score=s.face_auto_enroll_min_score,
        )

    def to_api_dict(self) -> dict:
        return asdict(self)

    def apply_dict(self, data: dict) -> None:
        """Apply a partial update dict, converting types from DB strings or API values."""
        _BOOL = {
            "enable_motion", "enable_zones", "enable_detection", "enable_faces",
            "motion_trail_enabled", "motion_contour_enabled", "motion_arrow_enabled",
            "motion_center_enabled", "notify_on_zone_trigger", "face_show_landmarks",
            "face_auto_enroll",
        }
        _INT = {
            "target_fps", "jpeg_quality", "motion_min_area", "motion_trail_length",
            "motion_mog2_threshold", "motion_dilate_kernel", "motion_trail_max_radius",
            "motion_contour_thickness", "motion_arrow_thickness", "motion_center_radius",
            "yolo_skip_frames", "face_skip_frames",
        }
        _FLOAT = {"yolo_confidence", "face_similarity_threshold", "face_auto_enroll_min_score"}

        for key, value in data.items():
            if not hasattr(self, key):
                continue
            if key in _BOOL:
                if isinstance(value, str):
                    value = value.lower() in ("1", "true", "yes")
                else:
                    value = bool(value)
            elif key in _INT:
                value = int(value)
            elif key in _FLOAT:
                value = float(value)
            setattr(self, key, value)

    def to_db_dict(self) -> dict[str, str]:
        """Serialise all fields to strings for DB key-value storage."""
        return {k: str(v) for k, v in asdict(self).items()}


# ── Global application settings ───────────────────────────────────────────────

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Stream source
    stream_url: str = "0"  # "0" = local webcam; RTSP/MJPEG URL for Pi

    # Pipeline performance
    target_fps: int = 15
    jpeg_quality: int = 70

    # Feature toggles
    enable_motion: bool = False
    enable_zones: bool = False
    enable_detection: bool = False

    # Detection zone behaviour
    # "zone"   — stop recording when there is no more movement inside any zone
    # "stream" — stop recording only when there is no movement anywhere in the stream
    zone_stop_mode: str = "zone"

    # Motion processor tuning
    motion_min_area: int = 3500       # px² — minimum contour area to track
    motion_trail_length: int = 30     # number of historical positions in trail
    motion_mog2_threshold: int = 80   # MOG2 variance threshold (sensitivity)
    motion_dilate_kernel: int = 50    # dilation kernel size (px, odd); larger merges nearby blobs

    # Motion visual style (colors as hex strings, converted to BGR in the processor)
    motion_trail_enabled: bool = True
    motion_trail_color: str = "#80f4dd"      # fading dot trail
    motion_trail_max_radius: int = 7         # radius of newest trail dot (px)
    motion_contour_enabled: bool = False
    motion_contour_color: str = "#fffdbd"    # moving object outline
    motion_contour_thickness: int = 1        # outline thickness (px)
    motion_arrow_color: str = "#00c8ff"      # direction arrow
    motion_arrow_thickness: int = 2          # arrow thickness (px)
    motion_arrow_enabled: bool = True
    motion_center_color: str = "#ffc7c7"     # centroid dot
    motion_center_radius: int = 5            # centroid dot radius (px)
    motion_center_enabled: bool = True

    # Database
    db_path: str = "vip.db"

    # YOLOv8
    yolo_model: str = "yolov8n.pt"
    yolo_confidence: float = 0.4
    yolo_skip_frames: int = 3
    detect_classes: str = ""  # comma-separated, empty = all

    # Face recognition
    enable_faces: bool = False
    face_model: str = "Facenet512"          # Facenet512 (fast) or ArcFace (most accurate)
    face_similarity_threshold: float = 0.4  # cosine similarity — higher = stricter
    face_skip_frames: int = 3
    face_show_landmarks: bool = True        # overlay eye/nose/mouth points and lines
    face_auto_enroll: bool = False          # auto-enroll unknown faces above quality threshold
    face_auto_enroll_min_score: float = 0.85  # minimum det_score to trigger auto-enroll

    # Notifications — all fields optional; unconfigured channels are silently skipped
    notify_on_zone_trigger: bool = False
    notify_cooldown: int = 60   # seconds between repeated alerts for the same zone

    # Telegram (optional)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Email / SMTP (optional)
    smtp_host: str = ""
    smtp_port: int = 587        # 587 = STARTTLS, 465 = implicit TLS
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""         # defaults to smtp_user if empty
    notify_email: str = ""

    # Recording
    recording_output_dir: str = "recordings"
    recording_filename_pattern: str = "{project_name}_{current_timestamp}"
    recording_project_name: str = "vip"

    # Logging
    log_level: str = "INFO"

    @property
    def stream_source(self) -> int | str:
        """Return int 0 for local webcam, otherwise the URL string."""
        if self.stream_url.strip() == "0":
            return 0
        return self.stream_url

    @property
    def detect_class_list(self) -> list[str]:
        if not self.detect_classes.strip():
            return []
        return [c.strip() for c in self.detect_classes.split(",") if c.strip()]


settings = Settings()
