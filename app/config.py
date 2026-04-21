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
    enable_zones: bool = False
    enable_detection: bool = False

    # Motion processor tuning
    motion_min_area: int = 3500       # px² — minimum contour area to track
    motion_trail_length: int = 30     # number of historical positions in trail
    motion_mog2_threshold: int = 120  # MOG2 variance threshold (sensitivity)

    # Motion visual style (colors as hex strings, converted to BGR in the processor)
    motion_trail_enabled: bool = True
    motion_trail_color: str = "#32dc64"      # fading dot trail
    motion_trail_max_radius: int = 5         # radius of newest trail dot (px)
    motion_contour_enabled: bool = True
    motion_contour_color: str = "#32dc64"    # moving object outline
    motion_contour_thickness: int = 2        # outline thickness (px)
    motion_arrow_color: str = "#00c8ff"      # direction arrow
    motion_arrow_thickness: int = 2          # arrow thickness (px)
    motion_arrow_enabled: bool = True
    motion_center_color: str = "#ffffff"     # centroid dot
    motion_center_radius: int = 5            # centroid dot radius (px)
    motion_center_enabled: bool = True

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
