"""Enterprise KPI Governance Agent.

Orchestrates the 9-task governance pipeline:
1. Business Classification
2. Ontology Mapping
3. Approval Rules
4. Rationale
5. Alternative Candidates
6. Human Override Support (audit trail)
7. New KPI Detection
8. Quality Checks
9. Final Decision
"""

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.ontology import OntologyKPI, ReportKPIMapping
from app.models.postgres import Dashboard

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable thresholds via environment variables
# ---------------------------------------------------------------------------
AUTO_APPROVE_THRESHOLD = float(os.getenv("GOVERNANCE_AUTO_APPROVE_THRESHOLD", "0.95"))
REVIEW_THRESHOLD = float(os.getenv("GOVERNANCE_REVIEW_THRESHOLD", "0.80"))


def _parse_json_col(raw: str | None) -> list:
    """Safely parse a JSON column, returning [] on failure."""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Task 8: Quality Checks
# ---------------------------------------------------------------------------

def _check_ambiguous(mapping: ReportKPIMapping, all_candidates: list[dict]) -> dict | None:
    """Flag if confidence is 0.50–0.80 and two candidates are within 0.05."""
    conf = mapping.confidence_score or 0.0
    if 0.50 <= conf <= 0.80 and len(all_candidates) >= 2:
        scores = sorted([c.get("score", 0) for c in all_candidates], reverse=True)
        if len(scores) >= 2 and abs(scores[0] - scores[1]) < 0.05:
            return {
                "type": "ambiguous_match",
                "severity": "Medium",
                "message": (
                    f"Confidence {conf:.0%} with top-2 candidates within 5% "
                    f"({scores[0]:.0%} vs {scores[1]:.0%}). Manual review recommended."
                ),
            }
    return None


def _check_weak_evidence(mapping: ReportKPIMapping) -> dict | None:
    """Flag if mapping has no lineage and no definition."""
    lineage = _parse_json_col(mapping.report_kpi_lineage)
    has_definition = bool(mapping.report_kpi_definition)
    if not lineage and not has_definition:
        return {
            "type": "weak_evidence",
            "severity": "Low",
            "message": "Mapping has no lineage and no formula/definition. Match is name-only.",
        }
    return None


def _check_low_confidence(mapping: ReportKPIMapping) -> dict | None:
    """Flag if confidence < 0.50."""
    conf = mapping.confidence_score or 0.0
    if conf < 0.50:
        return {
            "type": "low_confidence",
            "severity": "High",
            "message": f"Confidence {conf:.0%} is below 50%. This mapping is unreliable.",
        }
    return None


def _check_duplicates_in_dashboard(
    mappings: list[ReportKPIMapping],
) -> list[dict]:
    """Flag when the same canonical KPI is mapped from >1 worksheet."""
    canonical_ws: dict[str, list[str]] = defaultdict(list)
    for m in mappings:
        if m.canonical_kpi_id:
            ws = m.worksheet_name or m.worksheet_id or "unknown"
            canonical_ws[m.canonical_kpi_id].append(ws)

    warnings = []
    for kpi_id, worksheets in canonical_ws.items():
        if len(worksheets) > 1:
            warnings.append({
                "type": "duplicate_mapping",
                "severity": "Medium",
                "message": (
                    f"Canonical KPI '{kpi_id}' is mapped from {len(worksheets)} "
                    f"worksheets: {', '.join(set(worksheets))}."
                ),
                "canonical_kpi_id": kpi_id,
            })
    return warnings


def _check_conflicts_across_dashboards(
    report_kpi_name: str,
    current_canonical_id: str | None,
    db: Session,
) -> dict | None:
    """Flag if the same report KPI name maps to different canonical IDs elsewhere."""
    if not current_canonical_id:
        return None
    others = (
        db.query(ReportKPIMapping.canonical_kpi_id)
        .filter(
            ReportKPIMapping.report_kpi_name == report_kpi_name,
            ReportKPIMapping.canonical_kpi_id.isnot(None),
            ReportKPIMapping.canonical_kpi_id != current_canonical_id,
        )
        .distinct()
        .all()
    )
    if others:
        other_ids = [r[0] for r in others]
        return {
            "type": "conflicting_mapping",
            "severity": "High",
            "message": (
                f"'{report_kpi_name}' maps to '{current_canonical_id}' here, "
                f"but maps to {other_ids} in other dashboards."
            ),
        }
    return None


def _check_missing_metadata(dashboard: Dashboard | None) -> list[dict]:
    """Flag if dashboard is missing sector, LOB, or AI summary."""
    warnings = []
    if not dashboard:
        return warnings
    if not getattr(dashboard, "ontology_sector", None):
        warnings.append({
            "type": "missing_metadata",
            "severity": "Low",
            "message": "Dashboard has no sector classification.",
        })
    if not getattr(dashboard, "ontology_subdomain", None):
        warnings.append({
            "type": "missing_metadata",
            "severity": "Low",
            "message": "Dashboard has no subdomain / business function classification.",
        })
    return warnings


# ---------------------------------------------------------------------------
# Main evaluation orchestrator
# ---------------------------------------------------------------------------

def evaluate_dashboard(dashboard_id: int | str, db: Session) -> dict:
    """Run the full 9-task governance pipeline for a dashboard.

    Returns a structured JSON dict suitable for API response.
    """
    dashboard = db.query(Dashboard).filter(Dashboard.id == int(dashboard_id)).first()
    if not dashboard:
        return {"error": f"Dashboard {dashboard_id} not found"}

    # ── Task 1: Business Classification ──────────────────────────────
    classification = {
        "sector": getattr(dashboard, "ontology_sector", None),
        "subdomain": getattr(dashboard, "ontology_subdomain", None),
        "domain": getattr(dashboard, "domain_classification", None),
        "line_of_business": getattr(dashboard, "line_of_business", None),
    }

    # ── Load all mappings for this dashboard ─────────────────────────
    mappings = (
        db.query(ReportKPIMapping)
        .filter(ReportKPIMapping.report_id == str(dashboard_id))
        .all()
    )

    # ── Task 2–5, 7, 8, 9: Per-mapping evaluation ───────────────────
    kpi_evaluations = []
    dashboard_warnings = []

    # Task 8: Dashboard-level duplicate check
    dashboard_warnings.extend(_check_duplicates_in_dashboard(mappings))
    dashboard_warnings.extend(_check_missing_metadata(dashboard))

    # Canonical KPI lookup cache
    canonical_cache: dict[str, OntologyKPI] = {}

    for m in mappings:
        candidates = _parse_json_col(m.alternative_candidates)

        # Per-mapping quality checks
        mapping_warnings = []
        w = _check_ambiguous(m, candidates)
        if w:
            mapping_warnings.append(w)
        w = _check_weak_evidence(m)
        if w:
            mapping_warnings.append(w)
        w = _check_low_confidence(m)
        if w:
            mapping_warnings.append(w)
        w = _check_conflicts_across_dashboards(
            m.report_kpi_name, m.canonical_kpi_id, db
        )
        if w:
            mapping_warnings.append(w)

        # Task 3/9: Approval decision
        conf = m.confidence_score or 0.0
        mtype = m.mapping_type or "semantic_match"

        if mtype in ("exact", "alias") or conf >= AUTO_APPROVE_THRESHOLD:
            decision = "AUTO_APPROVE"
        elif conf >= REVIEW_THRESHOLD:
            decision = "REQUIRES_HUMAN_REVIEW"
        else:
            decision = "REQUIRES_HUMAN_REVIEW"

        # Override: if any warning is High severity, force review
        if any(w.get("severity") == "High" for w in mapping_warnings):
            decision = "REQUIRES_HUMAN_REVIEW"

        # Task 7: New KPI detection
        is_new_kpi_candidate = m.mapping_status == "not_found"
        new_kpi_suggestion = None
        if is_new_kpi_candidate:
            decision = "NEW_KPI_REQUIRED"
            new_kpi_suggestion = {
                "suggested_name": m.report_kpi_name,
                "suggested_definition": m.report_kpi_definition or m.report_kpi_name,
                "suggested_lineage": _parse_json_col(m.report_kpi_lineage),
                "suggested_aggregation": m.report_kpi_aggregation or "UNKNOWN",
            }

        # Look up canonical KPI name
        canonical_name = None
        if m.canonical_kpi_id:
            if m.canonical_kpi_id not in canonical_cache:
                canonical_cache[m.canonical_kpi_id] = (
                    db.query(OntologyKPI)
                    .filter(OntologyKPI.kpi_id == m.canonical_kpi_id)
                    .first()
                )
            ok = canonical_cache.get(m.canonical_kpi_id)
            if ok:
                canonical_name = ok.name

        # Persist warnings and decision back to DB
        if hasattr(m, "warnings"):
            m.warnings = json.dumps(mapping_warnings) if mapping_warnings else None
        if hasattr(m, "approval_decision"):
            m.approval_decision = decision

        kpi_evaluations.append({
            "mapping_id": m.mapping_id,
            "report_kpi_name": m.report_kpi_name,
            "worksheet_name": m.worksheet_name,
            "canonical_kpi_id": m.canonical_kpi_id,
            "canonical_kpi_name": canonical_name,
            "mapping_type": m.mapping_type,
            "similarity_score": m.similarity_score,
            "confidence_score": m.confidence_score,
            "formula_similarity": getattr(m, "formula_similarity", None),
            "similarity_rationale": m.similarity_rationale,
            "confidence_rationale": m.confidence_rationale,
            "model_used": m.model_used,
            "mapping_status": m.mapping_status,
            "approval_decision": decision,
            "warnings": mapping_warnings,
            "alternative_candidates": candidates,
            "new_kpi_suggestion": new_kpi_suggestion,
        })

    db.commit()

    # ── Aggregate stats ──────────────────────────────────────────────
    status_counts = Counter(m.mapping_status for m in mappings)
    decision_counts = Counter(e["approval_decision"] for e in kpi_evaluations)
    total_warnings = sum(len(e["warnings"]) for e in kpi_evaluations) + len(dashboard_warnings)

    overall = "AUTO_APPROVE"
    if decision_counts.get("REQUIRES_HUMAN_REVIEW", 0) > 0:
        overall = "REQUIRES_HUMAN_REVIEW"
    if decision_counts.get("NEW_KPI_REQUIRED", 0) > 0:
        overall = "REQUIRES_HUMAN_REVIEW"
    if total_warnings > 0:
        overall = "REQUIRES_HUMAN_REVIEW"

    return {
        "dashboard_id": str(dashboard_id),
        "dashboard_name": dashboard.name,
        "evaluated_at": datetime.utcnow().isoformat(),
        "thresholds": {
            "auto_approve": AUTO_APPROVE_THRESHOLD,
            "review": REVIEW_THRESHOLD,
        },
        "classification": classification,
        "summary": {
            "total_mappings": len(mappings),
            "auto_approved": decision_counts.get("AUTO_APPROVE", 0),
            "pending_review": decision_counts.get("REQUIRES_HUMAN_REVIEW", 0),
            "new_kpi_required": decision_counts.get("NEW_KPI_REQUIRED", 0),
            "total_warnings": total_warnings,
            "by_status": dict(status_counts),
        },
        "overall_decision": overall,
        "dashboard_warnings": dashboard_warnings,
        "kpi_evaluations": kpi_evaluations,
    }
