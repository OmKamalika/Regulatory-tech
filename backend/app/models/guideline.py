"""
Guideline reference data synced from DPDPA rule definitions.
"""

import uuid
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, JSON, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class GuidelineSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Guideline(Base):
    __tablename__ = "guidelines"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(128), nullable=False, unique=True, index=True)
    regulation_type = Column(String(64), nullable=False, index=True)
    version = Column(String(64), nullable=True)
    description = Column(Text, nullable=True)
    requirement_text = Column(Text, nullable=False)
    severity = Column(SQLEnum(GuidelineSeverity), nullable=False, default=GuidelineSeverity.WARNING)
    check_type = Column(String(128), nullable=True)
    weaviate_id = Column(String(128), nullable=True)
    clause_number = Column(String(128), nullable=True)
    penalty_ref = Column(String(256), nullable=True)
    check_types_json = Column(JSON, nullable=False, default=list)
    category = Column(String(128), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
