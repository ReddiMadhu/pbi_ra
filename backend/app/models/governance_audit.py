"""Governance audit trail models.

Tracks every human override action on KPI mappings for SOX-grade
auditability. Each row records what changed, from what, to what,
who did it, and why.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.session import Base


class MappingAuditLog(Base):
    __tablename__ = "mapping_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mapping_id = Column(String, nullable=False, index=True)
    field_changed = Column(String, nullable=False)  # e.g. "canonical_kpi_id", "mapping_status"
    original_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    approval_user = Column(String, nullable=False, default="analyst")
    timestamp = Column(DateTime, default=datetime.utcnow)
