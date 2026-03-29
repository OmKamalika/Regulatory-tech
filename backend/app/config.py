"""
Application configuration management using Pydantic Settings.
"""
import logging
import secrets
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

_config_logger = logging.getLogger(__name__)

# Placeholder strings that must be replaced before production
_PLACEHOLDER_SECRETS = {
    "your-secret-key-change-in-production",
    "your-jwt-secret-key-change-in-production",
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    APP_NAME: str = "Regtech Video Compliance"
    DEBUG: bool = False  # Must be explicitly set True in dev; never True in prod
    LOG_LEVEL: str = "INFO"
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # API Authentication
    # Set a long random string in .env — when empty, auth is skipped (local dev only).
    # Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    API_KEY: str = ""

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5433/regtech_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_VIDEOS: str = "videos"
    MINIO_BUCKET_FRAMES: str = "frames"
    MINIO_BUCKET_DOCUMENTS: str = "documents"
    MINIO_SECURE: bool = False

    # Weaviate
    WEAVIATE_URL: str = "http://localhost:8080"

    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    OLLAMA_OCR_MODEL: str = "qwen2-vl:7b"  # Vision model for OCR; set "" to disable

    # Model Settings
    WHISPER_MODEL: str = "medium"  # tiny, small, medium, large
    YOLO_MODEL: str = "yolov8n.pt"  # yolov8n, yolov8s, yolov8m, yolov8l, yolov8x
    EMBEDDING_MODEL: str = "all-mpnet-base-v2"
    OCR_LANGUAGES: str = "en"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    # Optional webhook called when a video pipeline task fails (POST with JSON body).
    # Leave empty to disable. Useful for Slack/Teams/PagerDuty alerts.
    FAILURE_WEBHOOK_URL: str = ""

    # File Upload
    MAX_UPLOAD_SIZE: int = 5368709120  # 5GB
    ALLOWED_VIDEO_FORMATS: str = "mp4,avi,mov,mkv,webm"

    # Processing
    FRAME_EXTRACTION_FPS: int = 1
    ENABLE_SCENE_DETECTION: bool = True
    MAX_CONCURRENT_JOBS: int = 3

    # Frame Preprocessing (improves OCR text detection on poor-quality frames)
    # Set ENABLE_FRAME_PREPROCESSING=False in .env to disable entirely.
    ENABLE_FRAME_PREPROCESSING: bool = True
    PREPROCESS_BLUR_THRESHOLD: float = 50.0   # Laplacian variance below this = skip frame
    PREPROCESS_MIN_BRIGHTNESS: int = 20       # Mean pixel value below this = too dark, skip
    PREPROCESS_MAX_BRIGHTNESS: int = 235      # Mean pixel value above this = overexposed, skip

    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_SECRET_KEY: str = "your-jwt-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

    @property
    def allowed_origins_list(self) -> List[str]:
        """Convert comma-separated origins to list"""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    @property
    def allowed_video_formats_list(self) -> List[str]:
        """Convert comma-separated formats to list"""
        return [fmt.strip() for fmt in self.ALLOWED_VIDEO_FORMATS.split(",")]

    @property
    def ocr_languages_list(self) -> List[str]:
        """Convert comma-separated languages to list"""
        return [lang.strip() for lang in self.OCR_LANGUAGES.split(",")]

    def validate_for_production(self) -> None:
        """
        Log warnings for insecure settings.
        Called at application startup — surfaces misconfiguration early.
        """
        if self.DEBUG:
            _config_logger.warning(
                "DEBUG=True — never run with debug enabled in production"
            )

        if not self.API_KEY:
            _config_logger.warning(
                "API_KEY is not set — all /api/v1 endpoints are unauthenticated. "
                "Set API_KEY in your .env file for production."
            )

        for field_name, value in [
            ("SECRET_KEY", self.SECRET_KEY),
            ("JWT_SECRET_KEY", self.JWT_SECRET_KEY),
        ]:
            if value in _PLACEHOLDER_SECRETS:
                _config_logger.warning(
                    "%s is still the placeholder value. "
                    "Generate a real secret: python -c \"import secrets; print(secrets.token_hex(32))\"",
                    field_name,
                )

        if self.MINIO_ACCESS_KEY == "minioadmin" or self.MINIO_SECRET_KEY == "minioadmin":
            _config_logger.warning(
                "MinIO credentials are still the default 'minioadmin'. "
                "Change MINIO_ACCESS_KEY and MINIO_SECRET_KEY in your .env file for production."
            )


# Global settings instance
settings = Settings()
