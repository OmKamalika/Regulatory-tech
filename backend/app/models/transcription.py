"""
Audio transcription segments extracted from videos.
"""

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class TranscriptionSegment(Base):
    __tablename__ = "transcription_segments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)

    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False, default="")
    confidence = Column(Float, nullable=True)
    weaviate_id = Column(String(128), nullable=True)
    vectorized = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
