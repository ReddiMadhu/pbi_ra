"""Governance API endpoints.

Provides the unified governance evaluation pipeline and audit trail
access for Enterprise KPI Governance.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session
from typing import Optional

from app.db.session import get_db
from app.models.governance_audit import MappingAuditLog
from app.services.governance.governance_agent import evaluate_dashboard

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class OverrideRequest(BaseModel):
    field_changed: str = Field(..., description="Field being changed, e.g. canonical_kpi_id")
    original_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: str = Field(..., min_length=1, max_length=2000, description="Reason for the override")
    approval_user: str = Field(default="analyst", max_length=200)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/dashboard/{dashboard_id}/evaluate")
def governance_evaluate(dashboard_id: str, db: Session = Depends(get_db)):
    """Run the full 9-task governance pipeline for a dashboard."""
    result = evaluate_dashboard(dashboard_id, db)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/mappings/{mapping_id}/audit-log")
def get_audit_log(mapping_id: str, db: Session = Depends(get_db)):
    """Return all audit trail entries for a mapping, newest first."""
    entries = (
        db.query(MappingAuditLog)
        .filter(MappingAuditLog.mapping_id == mapping_id)
        .order_by(desc(MappingAuditLog.timestamp))
        .all()
    )
    return [
        {
            "id": e.id,
            "mapping_id": e.mapping_id,
            "field_changed": e.field_changed,
            "original_value": e.original_value,
            "new_value": e.new_value,
            "reason": e.reason,
            "approval_user": e.approval_user,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in entries
    ]


@router.post("/mappings/{mapping_id}/audit-log")
def create_audit_entry(
    mapping_id: str,
    body: OverrideRequest,
    db: Session = Depends(get_db),
):
    """Manually create an audit trail entry (used by override flows)."""
    entry = MappingAuditLog(
        mapping_id=mapping_id,
        field_changed=body.field_changed,
        original_value=body.original_value,
        new_value=body.new_value,
        reason=body.reason,
        approval_user=body.approval_user,
        timestamp=datetime.utcnow(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {
        "id": entry.id,
        "mapping_id": entry.mapping_id,
        "field_changed": entry.field_changed,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
    }


@router.get("/thresholds")
def get_thresholds():
    """Return current configurable governance thresholds."""
    from app.services.governance.governance_agent import (
        AUTO_APPROVE_THRESHOLD,
        REVIEW_THRESHOLD,
    )
    return {
        "auto_approve_threshold": AUTO_APPROVE_THRESHOLD,
        "review_threshold": REVIEW_THRESHOLD,
    }
