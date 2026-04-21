from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Stream source
    stream_url: str = "0"  # "0" = local webcam; RTSP/MJPEG URL for Pi

    # Pipeline performance
    target_fps: int = 15
    jpeg_quality: int = 70

    # Feature toggles
    enable_motion: bool = True
    enable_zones: bool = True
    enable_detection: bool = False

    # Database
    db_path: str = "vip.db"

    # YOLOv8
    yolo_model: str = "yolov8n.pt"
    yolo_confidence: float = 0.4
    yolo_skip_frames: int = 3
    detect_classes: str = ""  # comma-separated, empty = all

    # SMTP notifications (all optional)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    notify_email: str = ""

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
