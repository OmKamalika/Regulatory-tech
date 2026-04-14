"""
Per-frame analysis records generated during video processing.
"""

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class FrameAnalysis(Base):
    __tablename__ = "frame_analyses"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)

    frame_number = Column(Integer, nullable=False)
    timestamp = Column(Float, nullable=False, default=0.0)
    minio_path = Column(String(1024), nullable=False, default="")

    objects_detected = Column(JSON, nullable=False, default=list)
    faces_detected = Column(Integer, nullable=False, default=0)
    persons_detected = Column(Integer, nullable=False, default=0)
    ocr_text = Column(Text, nullable=True)
    weaviate_id = Column(String(128), nullable=True)

    visual_analysis_completed = Column(Boolean, nullable=False, default=False)
    ocr_completed = Column(Boolean, nullable=False, default=False)
    vectorized = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
