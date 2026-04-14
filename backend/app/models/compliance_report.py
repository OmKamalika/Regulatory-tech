"""
Compliance report and finding entities.
"""

import uuid
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class ComplianceStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PARTIAL = "partial"
    INCOMPLETE = "incomplete"


class ComplianceReport(Base):
    __tablename__ = "compliance_reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)

    status = Column(SQLEnum(ComplianceStatus), nullable=False, default=ComplianceStatus.PENDING_REVIEW, index=True)
    compliance_score = Column(Float, nullable=True)
    total_checks = Column(Integer, nullable=False, default=0)
    passed_checks = Column(Integer, nullable=False, default=0)
    failed_checks = Column(Integer, nullable=False, default=0)
    critical_violations = Column(Integer, nullable=False, default=0)
    warnings = Column(Integer, nullable=False, default=0)

    executive_summary = Column(Text, nullable=True)
    recommendations = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class ComplianceFinding(Base):
    __tablename__ = "compliance_findings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id = Column(String(36), ForeignKey("compliance_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    guideline_id = Column(String(36), ForeignKey("guidelines.id", ondelete="SET NULL"), nullable=True, index=True)

    is_violation = Column(Boolean, nullable=False, default=True)
    severity = Column(String(32), nullable=False, default="info")
    description = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    timestamp_start = Column(Float, nullable=True)
    timestamp_end = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    visual_evidence = Column(JSON, nullable=False, default=dict)
    ocr_text_excerpt = Column(Text, nullable=True)
    transcript_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
