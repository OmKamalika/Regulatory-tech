"""
Video model and processing lifecycle status.
"""

import uuid
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, Integer, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class VideoStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Video(Base):
    __tablename__ = "videos"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(512), nullable=False)
    original_filename = Column(String(512), nullable=False)
    file_size = Column(Integer, nullable=False, default=0)
    format = Column(String(32), nullable=False)
    minio_path = Column(String(1024), nullable=False)

    status = Column(SQLEnum(VideoStatus), nullable=False, default=VideoStatus.UPLOADED)
    processing_progress = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)

    frames_processed = Column(Integer, nullable=False, default=0)
    visual_analysis_completed = Column(Boolean, nullable=False, default=False)
    ocr_completed = Column(Boolean, nullable=False, default=False)
    transcription_completed = Column(Boolean, nullable=False, default=False)
    vectorization_completed = Column(Boolean, nullable=False, default=False)

    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
