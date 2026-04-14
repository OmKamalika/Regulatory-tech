"""
Audit trail records for compliance pipeline execution.
"""

import uuid
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class AuditStep(str, Enum):
    FRAME_FETCH = "frame_fetch"
    VISUAL_CHECK = "visual_check"
    OCR_CHECK = "ocr_check"
    AUDIO_CHECK = "audio_check"
    RULE_MATCH = "rule_match"
    FINDING_CREATED = "finding_created"
    REPORT_GENERATED = "report_generated"
    DATA_PURGED = "data_purged"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    report_id = Column(String(36), ForeignKey("compliance_reports.id", ondelete="SET NULL"), nullable=True, index=True)

    step = Column(SQLEnum(AuditStep), nullable=False, index=True)
    action = Column(Text, nullable=False)
    rule_id = Column(String(128), nullable=True, index=True)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    duration_ms = Column(Integer, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)
