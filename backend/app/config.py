"""
Application configuration management using Pydantic Settings.
"""
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    APP_NAME: str = "Regtech Video Compliance"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

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

    # Model Settings
    WHISPER_MODEL: str = "medium"  # tiny, small, medium, large
    YOLO_MODEL: str = "yolov8n.pt"  # yolov8n, yolov8s, yolov8m, yolov8l, yolov8x
    EMBEDDING_MODEL: str = "all-mpnet-base-v2"
    OCR_LANGUAGES: str = "en"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # File Upload
    MAX_UPLOAD_SIZE: int = 5368709120  # 5GB
    ALLOWED_VIDEO_FORMATS: str = "mp4,avi,mov,mkv,webm"

    # Processing
    FRAME_EXTRACTION_FPS: int = 1
    ENABLE_SCENE_DETECTION: bool = True
    MAX_CONCURRENT_JOBS: int = 3

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


# Global settings instance
settings = Settings()
