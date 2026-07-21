import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ontology import OntologyKPI, ReportKPIMapping
from app.models.governance_audit import MappingAuditLog
from app.models.postgres import Dashboard, Workbook, CalculatedField
from app.services.ontology.embedding_service import embed_ontology_kpis
from app.services.ontology.ontology_service import (
    enrich_with_ontology_inventory,
    process_dashboard_kpis,
    update_representative_lineage,
)
from app.services.ontology.taxonomy import (
    get_taxonomy_for_api,
    is_sector_active,
    normalize_scope,
    validate_sector,
    validate_subdomain,
)

router = APIRouter()


import logging

logger = logging.getLogger(__name__)


def trigger_bg_embed():
    import threading

    def _bg_task():
        try:
            from app.db.session import SessionLocal
            from app.services.ontology.embedding_service import embed_ontology_kpis

            db_sess = SessionLocal()
            try:
                embed_ontology_kpis(db_sess)
            finally:
                db_sess.close()
        except Exception as err:
            logger.error("Background embedding failed: %s", err)

    t = threading.Thread(target=_bg_task, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Pydantic request models for input validation
# ---------------------------------------------------------------------------

class CreateKPIRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500, description="KPI name")
    definition: str = Field(..., min_length=1, max_length=5000, description="KPI definition")
    sector: Optional[str] = Field(None, max_length=200)
    subdomain: Optional[str] = Field(None, max_length=200)
    line_of_business: Optional[str] = Field(None, max_length=200)
    domain: Optional[str] = Field(None, max_length=500)
    aliases: List[str] = Field(default_factory=list)
    aggregation_type: str = Field(default="UNKNOWN", max_length=50)
    valid_dimensions: List[str] = Field(default_factory=list)
    created_by: str = Field(default="analyst", max_length=200)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()


class UpdateMappingRequest(BaseModel):
    action: str = Field(..., pattern="^(accept|reject|reassign)$", description="Must be accept, reject, or reassign")
    canonical_kpi_id: Optional[str] = Field(None, max_length=200)
    analyst_id: str = Field(default="analyst", max_length=200)


class PromoteKPIRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500, description="Canonical KPI name")
    definition: str = Field(..., min_length=1, max_length=5000, description="KPI definition")
    sector: Optional[str] = Field(None, max_length=200)
    subdomain: Optional[str] = Field(None, max_length=200)
    line_of_business: Optional[str] = Field(None, max_length=200)
    domain: Optional[str] = Field(None, max_length=500)
    aliases: List[str] = Field(default_factory=list)
    analyst_id: str = Field(default="analyst", max_length=200)


class ApproveScopeRequest(BaseModel):
    sector: str = Field(..., max_length=200)
    subdomain: str = Field(..., max_length=200)
    line_of_business: Optional[str] = Field(None, max_length=200)


class UpdateScopeRequest(BaseModel):
    sector: Optional[str] = Field(None, max_length=200)
    subdomain: Optional[str] = Field(None, max_length=200)


def _kpi_to_dict(kpi: OntologyKPI) -> dict:
    aliases = []
    try:
        aliases = json.loads(kpi.aliases) if kpi.aliases else []
    except Exception:
        pass
    return {
        "kpi_id": kpi.kpi_id,
        "name": kpi.name,
        "definition": kpi.definition,
        "domain": kpi.domain,
        "sector": kpi.sector,
        "subdomain": kpi.subdomain,
        "line_of_business": getattr(kpi, "line_of_business", None),
        "aliases": aliases,
        "aggregation_type": kpi.aggregation_type,
        "valid_dimensions": json.loads(kpi.valid_dimensions) if kpi.valid_dimensions else [],
        "created_by": kpi.created_by,
        "created_at": kpi.created_at.isoformat() if kpi.created_at else None,
        "status": kpi.status,
        "is_active_sector": is_sector_active(kpi.sector),
        "embedding_model": getattr(kpi, "embedding_model", None),
    }


def _mapping_to_dict(row: ReportKPIMapping) -> dict:
    lineage = []
    try:
        lineage = json.loads(row.report_kpi_lineage) if row.report_kpi_lineage else []
    except Exception:
        pass

    alternative_candidates = []
    try:
        if row.alternative_candidates:
            alternative_candidates = json.loads(row.alternative_candidates)
    except Exception:
        pass

    return {
        "mapping_id": row.mapping_id,
        "report_id": row.report_id,
        "worksheet_id": row.worksheet_id,
        "worksheet_name": row.worksheet_name,
        "report_kpi_name": row.report_kpi_name,
        "report_kpi_lineage": lineage,
        "report_kpi_aggregation": row.report_kpi_aggregation,
        "report_kpi_definition": row.report_kpi_definition,
        "canonical_kpi_id": row.canonical_kpi_id,
        "similarity_score": row.similarity_score,
        "confidence_score": row.confidence_score,
        "similarity_rationale": row.similarity_rationale,
        "confidence_rationale": row.confidence_rationale,
        "mapping_status": row.mapping_status,
        "resolved_by": row.resolved_by,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "model_used": row.model_used,
        "mapping_type": row.mapping_type,
        "alternative_candidates": alternative_candidates,
        "formula_similarity": getattr(row, "formula_similarity", None),
        "warnings": _parse_json_safe(getattr(row, "warnings", None)),
        "approval_decision": getattr(row, "approval_decision", None),
    }


def _parse_json_safe(raw) -> list:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def _apply_kpi_scope(body: dict, existing: OntologyKPI | None = None) -> tuple[str, str]:
    sector = validate_sector(body.get("sector") or (existing.sector if existing else None))
    subdomain = validate_subdomain(sector, body.get("subdomain") or (existing.subdomain if existing else None))
    if not sector or not subdomain:
        sec, sub = normalize_scope(
            body.get("sector"),
            body.get("subdomain"),
            legacy_domain=body.get("domain"),
        )
        return sec, sub
    return sector, subdomain


@router.get("/workbook/{workbook_name}/kpis")
def get_workbook_ontology_kpis(workbook_name: str, db: Session = Depends(get_db)):
    """Aggregated ontology matching results for all dashboards in a workbook."""
    workbook = db.query(Workbook).filter(Workbook.name == workbook_name).first()
    if not workbook:
        workbook = db.query(Workbook).filter(
            Workbook.name.like(f"%{workbook_name}%")
        ).first()
    if not workbook:
        return {"dashboards": [], "summary": {"total": 0, "mapped": 0, "review": 0, "not_found": 0, "ontology_score": 0}}

    all_dashboards = []
    total = 0
    mapped = 0
    review = 0
    not_found = 0

    for dash in workbook.dashboards:
        mappings = (
            db.query(ReportKPIMapping)
            .filter(ReportKPIMapping.report_id == str(dash.id))
            .all()
        )

        items = []
        for m in mappings:
            canonical = None
            if m.canonical_kpi_id:
                kpi = db.query(OntologyKPI).filter(OntologyKPI.kpi_id == m.canonical_kpi_id).first()
                if kpi:
                    canonical = {
                        "kpi_id": kpi.kpi_id,
                        "name": kpi.name,
                        "definition": kpi.definition,
                        "domain": kpi.domain,
                        "sector": kpi.sector,
                        "subdomain": kpi.subdomain,
                        "aggregation_type": kpi.aggregation_type,
                    }

            lineage = []
            try:
                lineage = json.loads(m.report_kpi_lineage) if m.report_kpi_lineage else []
            except Exception:
                pass

            items.append({
                "mapping_id": m.mapping_id,
                "report_kpi_name": m.report_kpi_name,
                "report_kpi_definition": m.report_kpi_definition,
                "report_kpi_lineage": lineage,
                "report_kpi_aggregation": m.report_kpi_aggregation,
                "worksheet_name": m.worksheet_name,
                "canonical_kpi": canonical,
                "similarity_score": m.similarity_score,
                "confidence_score": m.confidence_score,
                "similarity_rationale": m.similarity_rationale,
                "confidence_rationale": m.confidence_rationale,
                "mapping_status": m.mapping_status,
                "resolved_by": m.resolved_by,
            })

            total += 1
            status = m.mapping_status or ""
            if status in ("auto_accepted", "human_accepted", "promoted"):
                mapped += 1
            elif status == "pending_review":
                review += 1
            elif status == "not_found":
                not_found += 1

        all_dashboards.append({
            "dashboard_name": dash.name,
            "dashboard_id": dash.id,
            "ontology_sector": dash.ontology_sector,
            "ontology_subdomain": dash.ontology_subdomain,
            "items": items,
        })

    ontology_score = round(mapped / total, 2) if total > 0 else 0

    return {
        "dashboards": all_dashboards,
        "summary": {
            "total": total,
            "mapped": mapped,
            "review": review,
            "not_found": not_found,
            "ontology_score": ontology_score,
        },
    }


@router.get("/taxonomy")
def get_taxonomy():
    return get_taxonomy_for_api()


@router.get("/kpis")
def list_kpis(
    domain: str | None = None,
    sector: str | None = None,
    subdomain: str | None = None,
    status: str = "active",
    skip: int = 0,
    limit: int = 2000,
    db: Session = Depends(get_db),
):
    from app.services.ontology.taxonomy import (
        SUBDOMAIN_DISPLAY_LABELS,
        canonicalize_subdomain,
        validate_sector,
    )

    q = db.query(OntologyKPI).filter(OntologyKPI.status == status)
    if domain:
        q = q.filter(OntologyKPI.domain == domain)

    sec = validate_sector(sector) if sector else None
    if sector and not sec:
        sec = sector.strip().lower()
    if sec:
        # Case-insensitive sector match via Python post-filter (SQLite)
        pass

    rows = q.offset(skip).limit(max(limit, 5000)).all()

    if sec:
        rows = [r for r in rows if (r.sector or "").strip().lower() == sec]

    sub = canonicalize_subdomain(subdomain) if subdomain else None
    if subdomain and not sub:
        sub = subdomain.strip().lower().replace(" ", "_")
    if sub:
        label = SUBDOMAIN_DISPLAY_LABELS.get(sub, "").lower()
        want = {sub, (subdomain or "").strip().lower(), label}
        want.discard("")

        def _sub_match(raw: str | None) -> bool:
            s = (raw or "").strip()
            if not s:
                return False
            if s.lower() in want:
                return True
            canon = canonicalize_subdomain(s)
            return bool(canon and canon in want)

        rows = [r for r in rows if _sub_match(r.subdomain)]

    return [_kpi_to_dict(r) for r in rows]


@router.post("/kpis")
def create_kpi(body: CreateKPIRequest, db: Session = Depends(get_db)):
    body_dict = body.model_dump()
    sector, subdomain = _apply_kpi_scope(body_dict)
    name = body.name
    existing = (
        db.query(OntologyKPI)
        .filter(
            OntologyKPI.name == name,
            OntologyKPI.sector == sector,
            OntologyKPI.subdomain == subdomain,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            409,
            f"KPI '{name}' already exists for {sector}/{subdomain}",
        )
    kpi = OntologyKPI(
        kpi_id=str(uuid.uuid4()),
        name=name,
        definition=body.definition,
        domain=body.domain or f"{sector}/{subdomain}",
        sector=sector,
        subdomain=subdomain,
        line_of_business=body.line_of_business,
        aliases=json.dumps(body.aliases),
        aggregation_type=body.aggregation_type,
        valid_dimensions=json.dumps(body.valid_dimensions),
        created_by=body.created_by,
    )
    db.add(kpi)
    db.commit()
    db.refresh(kpi)
    trigger_bg_embed()
    return _kpi_to_dict(kpi)


@router.put("/kpis/{kpi_id}")
def update_kpi(kpi_id: str, body: dict, db: Session = Depends(get_db)):
    kpi = db.query(OntologyKPI).filter(OntologyKPI.kpi_id == kpi_id).first()
    if not kpi:
        raise HTTPException(404, "KPI not found")
    if "name" in body:
        kpi.name = body["name"]
    if "definition" in body:
        kpi.definition = body["definition"]
    if "domain" in body:
        kpi.domain = body["domain"]
    if "line_of_business" in body:
        kpi.line_of_business = body["line_of_business"]
    if "sector" in body or "subdomain" in body:
        sector, subdomain = _apply_kpi_scope(body, existing=kpi)
        kpi.sector = sector
        kpi.subdomain = subdomain
    if "aliases" in body:
        kpi.aliases = json.dumps(body["aliases"])
    if "aggregation_type" in body:
        kpi.aggregation_type = body["aggregation_type"]
    if "valid_dimensions" in body:
        kpi.valid_dimensions = json.dumps(body["valid_dimensions"])
    if "status" in body:
        kpi.status = body["status"]
    db.commit()
    db.refresh(kpi)
    trigger_bg_embed()
    return _kpi_to_dict(kpi)


@router.get("/reports/{report_id}/kpis")
def get_report_kpi_inventory(report_id: str, db: Session = Depends(get_db)):
    rows = db.query(ReportKPIMapping).filter(ReportKPIMapping.report_id == report_id).all()
    inv = enrich_with_ontology_inventory(report_id, db)
    if inv is None:
        inv = {"report_id": report_id, "total": 0, "mapped": 0, "ambiguous": 0, "not_found": 0, "ontology_score": 0}
    dash = db.query(Dashboard).filter(Dashboard.id == int(report_id)).first()
    if dash:
        inv["ontology_sector"] = dash.ontology_sector
        inv["ontology_subdomain"] = dash.ontology_subdomain
    inv["items"] = [_mapping_to_dict(r) for r in rows]
    return inv


@router.put("/reports/{report_id}/scope")
def update_dashboard_scope(report_id: str, body: UpdateScopeRequest, db: Session = Depends(get_db)):
    dashboard = db.query(Dashboard).filter(Dashboard.id == int(report_id)).first()
    if not dashboard:
        raise HTTPException(404, "Dashboard not found")
    sector, subdomain = _apply_kpi_scope(body.model_dump())
    dashboard.ontology_sector = sector
    dashboard.ontology_subdomain = subdomain
    db.commit()
    return {
        "report_id": report_id,
        "ontology_sector": sector,
        "ontology_subdomain": subdomain,
    }


def _run_extraction_background(dashboard_id: int):
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        from app.models.metadata import (
            WorkbookMetadata, WorksheetMetadata, DatasourceMetadata,
            CalculatedFieldMetadata, DashboardMetadata
        )
        from app.services.ontology.ontology_service import process_dashboard_kpis
        
        dashboard = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
        if not dashboard:
            return
        workbook = dashboard.workbook
        if not workbook:
            return
            
        calc_fields = []
        seen_cf = set()
        for d in workbook.dashboards:
            for cf in db.query(CalculatedField).filter(CalculatedField.dashboard_id == d.id).all():
                key = (cf.name, cf.formula)
                if key in seen_cf:
                    continue
                seen_cf.add(key)
                calc_fields.append(CalculatedFieldMetadata(name=cf.name, caption=cf.name, formula=cf.formula, datatype=cf.datatype))

        worksheets = [
            WorksheetMetadata(
                name=ws.name,
                used_calculated_fields=ws.used_calculated_fields or [],
                rows=ws.rows or [],
                columns=ws.columns or [],
                filters_and_marks=ws.filters_and_marks or [],
                mark_type=ws.mark_type,
                measure_bindings=ws.measure_bindings or [],
            )
            for ws in workbook.worksheets
        ]

        dashboards_meta = [
            DashboardMetadata(name=d.name, worksheets=[w.name for w in d.worksheets])
            for d in workbook.dashboards
        ]

        wb_meta = WorkbookMetadata(
            source_file=workbook.source_file,
            datasources=[DatasourceMetadata(name="default", caption=None, calculated_fields=calc_fields)],
            worksheets=worksheets,
            dashboards=dashboards_meta,
        )
        process_dashboard_kpis(db, dashboard.id, wb_meta, {})
    except Exception as e:
        logger.error("Background scope approval extraction failed: %s", e, exc_info=True)
    finally:
        db.close()


@router.get("/dashboards/pending-scope")
def list_pending_scope_dashboards(db: Session = Depends(get_db)):
    dashboards = db.query(Dashboard).filter(Dashboard.scope_status == "pending_approval").all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "workbook_name": d.workbook.name if d.workbook else None,
            "ontology_sector": d.ontology_sector,
            "ontology_subdomain": d.ontology_subdomain,
            "line_of_business": d.line_of_business,
            "scope_status": d.scope_status,
        }
        for d in dashboards
    ]


@router.post("/dashboards/{dashboard_id}/approve-scope")
def approve_dashboard_scope(
    dashboard_id: int,
    body: ApproveScopeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    dashboard = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
    if not dashboard:
        raise HTTPException(404, "Dashboard not found")
        
    dashboard.ontology_sector = body.sector
    dashboard.ontology_subdomain = body.subdomain
    dashboard.line_of_business = body.line_of_business
    dashboard.scope_status = "approved"
    db.commit()
    
    background_tasks.add_task(_run_extraction_background, dashboard_id)
    return {"status": "scope_approved", "dashboard_id": dashboard_id}


@router.post("/reports/{report_id}/extract")
def trigger_extraction(report_id: str, db: Session = Depends(get_db)):
    from app.models.metadata import (
        WorkbookMetadata,
        WorksheetMetadata,
        DatasourceMetadata,
        CalculatedFieldMetadata,
        DashboardMetadata,
    )

    dashboard = db.query(Dashboard).filter(Dashboard.id == int(report_id)).first()
    if not dashboard:
        raise HTTPException(404, "Dashboard not found")

    workbook = dashboard.workbook
    if not workbook:
        raise HTTPException(404, "Workbook not found")

    calc_fields: list[CalculatedFieldMetadata] = []
    seen_cf: set[str] = set()
    for dash in workbook.dashboards:
        for cf in db.query(CalculatedField).filter(CalculatedField.dashboard_id == dash.id).all():
            key = (cf.name, cf.formula)
            if key in seen_cf:
                continue
            seen_cf.add(key)
            calc_fields.append(CalculatedFieldMetadata(name=cf.name, caption=cf.name, formula=cf.formula, datatype=cf.datatype))

    worksheets = [
        WorksheetMetadata(
            name=ws.name,
            used_calculated_fields=ws.used_calculated_fields or [],
            rows=ws.rows or [],
            columns=ws.columns or [],
            filters_and_marks=ws.filters_and_marks or [],
            mark_type=ws.mark_type,
            measure_bindings=ws.measure_bindings or [],
        )
        for ws in workbook.worksheets
    ]

    dashboards_meta = [
        DashboardMetadata(name=d.name, worksheets=[w.name for w in d.worksheets])
        for d in workbook.dashboards
    ]

    wb_meta = WorkbookMetadata(
        source_file=workbook.source_file,
        datasources=[DatasourceMetadata(name="default", caption=None, calculated_fields=calc_fields)],
        worksheets=worksheets,
        dashboards=dashboards_meta,
    )
    count = process_dashboard_kpis(db, dashboard.id, wb_meta, {})
    return {"status": "extraction_triggered", "report_id": report_id, "mappings_created": count}


@router.get("/mappings/pending")
def list_pending_mappings(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    rows = (
        db.query(ReportKPIMapping)
        .filter(ReportKPIMapping.mapping_status.in_(["pending_review", "not_found"]))
        .order_by(ReportKPIMapping.confidence_score.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_mapping_to_dict(r) for r in rows]


@router.put("/mappings/{mapping_id}")
def update_mapping(mapping_id: str, body: UpdateMappingRequest, db: Session = Depends(get_db)):
    row = db.query(ReportKPIMapping).filter(ReportKPIMapping.mapping_id == mapping_id).first()
    if not row:
        raise HTTPException(404, "Mapping not found")

    # Record audit trail BEFORE mutating
    old_status = row.mapping_status
    old_canonical = row.canonical_kpi_id

    if body.action == "accept":
        row.mapping_status = "human_accepted"
    elif body.action == "reject":
        row.mapping_status = "human_rejected"
    elif body.action == "reassign":
        if not body.canonical_kpi_id:
            raise HTTPException(400, "canonical_kpi_id is required for reassign action")
        row.canonical_kpi_id = body.canonical_kpi_id
        row.mapping_status = "human_accepted"
    row.resolved_by = body.analyst_id
    row.resolved_at = datetime.utcnow()

    # Write audit log entries
    db.add(MappingAuditLog(
        mapping_id=mapping_id,
        field_changed="mapping_status",
        original_value=old_status,
        new_value=row.mapping_status,
        reason=body.action,
        approval_user=body.analyst_id,
    ))
    if body.action == "reassign" and old_canonical != row.canonical_kpi_id:
        db.add(MappingAuditLog(
            mapping_id=mapping_id,
            field_changed="canonical_kpi_id",
            original_value=old_canonical,
            new_value=row.canonical_kpi_id,
            reason=f"Reassigned by {body.analyst_id}",
            approval_user=body.analyst_id,
        ))

    db.commit()
    if body.action in ("accept", "reassign") and row.canonical_kpi_id:
        lineage = json.loads(row.report_kpi_lineage) if row.report_kpi_lineage else []
        update_representative_lineage(db, row.canonical_kpi_id, lineage)
    return _mapping_to_dict(row)


@router.post("/mappings/{mapping_id}/promote")
def promote_nf_kpi(mapping_id: str, body: PromoteKPIRequest, db: Session = Depends(get_db)):
    row = db.query(ReportKPIMapping).filter(
        ReportKPIMapping.mapping_id == mapping_id,
        ReportKPIMapping.mapping_status == "not_found",
    ).first()
    if not row:
        raise HTTPException(404, "Not-Found mapping not found")
    dash = db.query(Dashboard).filter(Dashboard.id == int(row.report_id)).first()
    sector, subdomain = normalize_scope(
        body.sector or (dash.ontology_sector if dash else None),
        body.subdomain or (dash.ontology_subdomain if dash else None),
        legacy_domain=dash.domain_classification if dash else None,
    )
    new_kpi = OntologyKPI(
        kpi_id=str(uuid.uuid4()),
        name=body.name,
        definition=body.definition,
        domain=body.domain or f"{sector}/{subdomain}",
        sector=sector,
        subdomain=subdomain,
        line_of_business=body.line_of_business or getattr(dash, "line_of_business", None),
        aliases=json.dumps(body.aliases or [row.report_kpi_name]),
        aggregation_type=row.report_kpi_aggregation or "UNKNOWN",
        representative_lineage=row.report_kpi_lineage,
        created_by=body.analyst_id,
    )
    db.add(new_kpi)

    # Audit trail for promotion
    db.add(MappingAuditLog(
        mapping_id=mapping_id,
        field_changed="mapping_status",
        original_value="not_found",
        new_value="promoted",
        reason=f"Promoted to new KPI '{body.name}' by {body.analyst_id}",
        approval_user=body.analyst_id,
    ))

    row.canonical_kpi_id = new_kpi.kpi_id
    row.mapping_status = "promoted"
    row.resolved_by = body.analyst_id
    row.resolved_at = datetime.utcnow()
    db.commit()
    trigger_bg_embed()
    return {"new_kpi": _kpi_to_dict(new_kpi), "updated_mapping": _mapping_to_dict(row)}

