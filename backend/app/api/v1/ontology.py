import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ontology import OntologyKPI, ReportKPIMapping
from app.models.postgres import Dashboard, Workbook, CalculatedField
from app.services.ontology.ontology_service import (
    enrich_with_ontology_inventory,
    process_dashboard_kpis,
    update_representative_lineage,
)

router = APIRouter()


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
        "aliases": aliases,
        "aggregation_type": kpi.aggregation_type,
        "valid_dimensions": json.loads(kpi.valid_dimensions) if kpi.valid_dimensions else [],
        "created_by": kpi.created_by,
        "created_at": kpi.created_at.isoformat() if kpi.created_at else None,
        "status": kpi.status,
    }


def _mapping_to_dict(row: ReportKPIMapping) -> dict:
    lineage = []
    try:
        lineage = json.loads(row.report_kpi_lineage) if row.report_kpi_lineage else []
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
        "canonical_kpi_id": row.canonical_kpi_id,
        "similarity_score": row.similarity_score,
        "confidence_score": row.confidence_score,
        "similarity_rationale": row.similarity_rationale,
        "confidence_rationale": row.confidence_rationale,
        "mapping_status": row.mapping_status,
        "resolved_by": row.resolved_by,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "model_used": row.model_used,
    }


@router.get("/kpis")
def list_kpis(
    domain: str | None = None,
    status: str = "active",
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(OntologyKPI).filter(OntologyKPI.status == status)
    if domain:
        q = q.filter(OntologyKPI.domain == domain)
    rows = q.offset(skip).limit(limit).all()
    return [_kpi_to_dict(r) for r in rows]


@router.post("/kpis")
def create_kpi(body: dict, db: Session = Depends(get_db)):
    kpi = OntologyKPI(
        kpi_id=str(uuid.uuid4()),
        name=body["name"],
        definition=body["definition"],
        domain=body.get("domain", "General"),
        aliases=json.dumps(body.get("aliases", [])),
        aggregation_type=body.get("aggregation_type", "UNKNOWN"),
        valid_dimensions=json.dumps(body.get("valid_dimensions", [])),
        created_by=body.get("created_by", "analyst"),
    )
    db.add(kpi)
    db.commit()
    db.refresh(kpi)
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
    return _kpi_to_dict(kpi)


@router.get("/reports/{report_id}/kpis")
def get_report_kpi_inventory(report_id: str, db: Session = Depends(get_db)):
    rows = db.query(ReportKPIMapping).filter(ReportKPIMapping.report_id == report_id).all()
    inv = enrich_with_ontology_inventory(report_id, db)
    if inv is None:
        inv = {"report_id": report_id, "total": 0, "mapped": 0, "ambiguous": 0, "not_found": 0, "ontology_score": 0}
    inv["items"] = [_mapping_to_dict(r) for r in rows]
    return inv


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
def update_mapping(mapping_id: str, body: dict, db: Session = Depends(get_db)):
    row = db.query(ReportKPIMapping).filter(ReportKPIMapping.mapping_id == mapping_id).first()
    if not row:
        raise HTTPException(404, "Mapping not found")
    action = body.get("action")
    if action == "accept":
        row.mapping_status = "human_accepted"
    elif action == "reject":
        row.mapping_status = "human_rejected"
    elif action == "reassign":
        row.canonical_kpi_id = body["canonical_kpi_id"]
        row.mapping_status = "human_accepted"
    else:
        raise HTTPException(400, "action must be accept, reject, or reassign")
    row.resolved_by = body.get("analyst_id", "analyst")
    row.resolved_at = datetime.utcnow()
    db.commit()
    if action in ("accept", "reassign") and row.canonical_kpi_id:
        lineage = json.loads(row.report_kpi_lineage) if row.report_kpi_lineage else []
        update_representative_lineage(db, row.canonical_kpi_id, lineage)
    return _mapping_to_dict(row)


@router.post("/mappings/{mapping_id}/promote")
def promote_nf_kpi(mapping_id: str, body: dict, db: Session = Depends(get_db)):
    row = db.query(ReportKPIMapping).filter(
        ReportKPIMapping.mapping_id == mapping_id,
        ReportKPIMapping.mapping_status == "not_found",
    ).first()
    if not row:
        raise HTTPException(404, "Not-Found mapping not found")
    new_kpi = OntologyKPI(
        kpi_id=str(uuid.uuid4()),
        name=body["name"],
        definition=body["definition"],
        domain=body.get("domain", "General"),
        aliases=json.dumps(body.get("aliases", [row.report_kpi_name])),
        aggregation_type=row.report_kpi_aggregation or "UNKNOWN",
        representative_lineage=row.report_kpi_lineage,
        created_by=body.get("analyst_id", "analyst"),
    )
    db.add(new_kpi)
    row.canonical_kpi_id = new_kpi.kpi_id
    row.mapping_status = "promoted"
    row.resolved_by = body.get("analyst_id", "analyst")
    row.resolved_at = datetime.utcnow()
    db.commit()
    return {"new_kpi": _kpi_to_dict(new_kpi), "updated_mapping": _mapping_to_dict(row)}
