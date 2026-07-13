import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.ontology import OntologyKPI, ReportKPIMapping
from app.services.ontology.embedding_service import cosine_similarity, compute_embedding
from app.services.ontology.kpi_extractor import ExtractedKPI
from app.services.ontology.ontology_cache import OntologyCache

MAX_PHASE3_CALLS_PER_EXTRACTION = 200
ONTOLOGY_VERSION = "v1"

_phase3_call_counter = 0


def reset_phase3_counter() -> None:
    global _phase3_call_counter
    _phase3_call_counter = 0


def _parse_aliases(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _status_from_confidence(confidence: float) -> str:
    if confidence >= 0.90:
        return "auto_accepted"
    if confidence >= 0.50:
        return "pending_review"
    return "not_found"


def match_kpi_to_ontology(
    kpi: ExtractedKPI,
    ontology_kpis: list[dict],
    cache: OntologyCache,
    llm: Any = None,
    embedding_fn: Any = None,
) -> dict:
    global _phase3_call_counter
    embedding_fn = embedding_fn or compute_embedding

    cached = cache.get(kpi.resolved_lineage, kpi.aggregation_type)
    if cached:
        cached["mapping_status"] = _status_from_confidence(cached.get("confidence_score") or 0.0)
        return cached

    # Phase 1: exact name / alias
    name_lower = kpi.name.strip().lower()
    for ok in ontology_kpis:
        if ok.get("name", "").strip().lower() == name_lower:
            result = {
                "matched_kpi_id": ok["kpi_id"],
                "similarity_score": 1.0,
                "confidence_score": 1.0,
                "similarity_rationale": "Exact name match",
                "confidence_rationale": "Phase 1 exact match",
                "model_used": kpi.extraction_method,
                "mapping_status": "auto_accepted",
            }
            cache.set(kpi.resolved_lineage, kpi.aggregation_type, result)
            return result
        for alias in ok.get("aliases") or []:
            if str(alias).strip().lower() == name_lower:
                result = {
                    "matched_kpi_id": ok["kpi_id"],
                    "similarity_score": 0.98,
                    "confidence_score": 0.95,
                    "similarity_rationale": f"Alias match: {alias}",
                    "confidence_rationale": "Phase 1 alias match",
                    "model_used": kpi.extraction_method,
                    "mapping_status": "auto_accepted",
                }
                cache.set(kpi.resolved_lineage, kpi.aggregation_type, result)
                return result

    # Phase 2: embedding pre-filter
    kpi_text = f"{kpi.name} {kpi.definition} {' '.join(kpi.resolved_lineage)}"
    kpi_emb = embedding_fn(kpi_text)
    best_id = None
    best_sim = 0.0
    best_name = ""
    for ok in ontology_kpis:
        ok_text = f"{ok.get('name', '')} {ok.get('definition', '')} {' '.join(_parse_aliases(ok.get('aliases_raw')))}"
        ok_emb = ok.get("embedding")
        if ok_emb is None:
            ok_emb = embedding_fn(ok_text)
        sim = cosine_similarity(kpi_emb, ok_emb)
        if sim > best_sim:
            best_sim = sim
            best_id = ok["kpi_id"]
            best_name = ok.get("name", "")

    if best_sim >= 0.95:
        result = {
            "matched_kpi_id": best_id,
            "similarity_score": best_sim,
            "confidence_score": best_sim,
            "similarity_rationale": f"Embedding match to '{best_name}'",
            "confidence_rationale": "Phase 2b embedding auto-accept",
            "model_used": "embedding",
            "mapping_status": "auto_accepted",
        }
        cache.set(kpi.resolved_lineage, kpi.aggregation_type, result)
        return result

    if best_sim < 0.50:
        result = {
            "matched_kpi_id": None,
            "similarity_score": best_sim,
            "confidence_score": best_sim,
            "similarity_rationale": "No close ontology match",
            "confidence_rationale": "Phase 2b below threshold",
            "model_used": "embedding",
            "mapping_status": "not_found",
        }
        cache.set(kpi.resolved_lineage, kpi.aggregation_type, result)
        return result

    # Phase 3: LLM judge
    if _phase3_call_counter >= MAX_PHASE3_CALLS_PER_EXTRACTION or not llm:
        conf = best_sim
        result = {
            "matched_kpi_id": best_id if conf >= 0.70 else None,
            "similarity_score": best_sim,
            "confidence_score": conf,
            "similarity_rationale": "LLM cap reached; embedding-only decision",
            "confidence_rationale": "Phase 3 skipped",
            "model_used": "embedding_fallback",
            "mapping_status": _status_from_confidence(conf),
        }
        cache.set(kpi.resolved_lineage, kpi.aggregation_type, result)
        return result

    _phase3_call_counter += 1
    candidates = [{"kpi_id": ok["kpi_id"], "name": ok["name"]} for ok in ontology_kpis[:20]]
    prompt = f"""Judge if report KPI maps to a canonical ontology KPI.
Report KPI: {json.dumps({'name': kpi.name, 'lineage': kpi.resolved_lineage, 'agg': kpi.aggregation_type})}
Candidates: {json.dumps(candidates)}
Return JSON: matched_kpi_id (or null), similarity_score, confidence_score, rationale"""
    try:
        res = llm.invoke(prompt)
        content = (res.content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content).strip().rstrip("`")
        parsed = json.loads(content)
        conf = float(parsed.get("confidence_score", best_sim))
        result = {
            "matched_kpi_id": parsed.get("matched_kpi_id") or (best_id if conf >= 0.70 else None),
            "similarity_score": float(parsed.get("similarity_score", best_sim)),
            "confidence_score": conf,
            "similarity_rationale": parsed.get("rationale", "LLM judge"),
            "confidence_rationale": "Phase 3 LLM",
            "model_used": "llm_judge",
            "mapping_status": _status_from_confidence(conf),
        }
    except Exception:
        result = {
            "matched_kpi_id": best_id,
            "similarity_score": best_sim,
            "confidence_score": best_sim,
            "similarity_rationale": f"Embedding best match '{best_name}'",
            "confidence_rationale": "Phase 3 LLM failed; embedding fallback",
            "model_used": "embedding",
            "mapping_status": _status_from_confidence(best_sim),
        }

    cache.set(kpi.resolved_lineage, kpi.aggregation_type, result)
    return result


def load_ontology_kpis(db: Session) -> list[dict]:
    rows = db.query(OntologyKPI).filter(OntologyKPI.status == "active").all()
    out = []
    for r in rows:
        out.append(
            {
                "kpi_id": r.kpi_id,
                "name": r.name,
                "definition": r.definition,
                "domain": r.domain,
                "aliases": _parse_aliases(r.aliases),
                "aliases_raw": r.aliases,
                "aggregation_type": r.aggregation_type,
                "embedding": None,
            }
        )
    return out


def persist_mapping(
    db: Session,
    report_id: str,
    kpi: ExtractedKPI,
    match: dict,
) -> ReportKPIMapping:
    existing = (
        db.query(ReportKPIMapping)
        .filter(
            ReportKPIMapping.report_id == report_id,
            ReportKPIMapping.report_kpi_name == kpi.name,
        )
        .first()
    )
    if existing:
        row = existing
    else:
        row = ReportKPIMapping(mapping_id=str(uuid.uuid4()), report_id=report_id, report_kpi_name=kpi.name)
        db.add(row)

    row.report_kpi_lineage = json.dumps(kpi.resolved_lineage)
    row.report_kpi_aggregation = kpi.aggregation_type
    row.canonical_kpi_id = match.get("matched_kpi_id")
    row.similarity_score = match.get("similarity_score")
    row.confidence_score = match.get("confidence_score")
    row.similarity_rationale = match.get("similarity_rationale")
    row.confidence_rationale = match.get("confidence_rationale")
    row.mapping_status = match.get("mapping_status", "pending_review")
    row.model_used = match.get("model_used") or kpi.extraction_method
    row.ontology_version = ONTOLOGY_VERSION
    row.computed_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def process_dashboard_kpis(db: Session, dashboard_id: int, workbook_metadata: Any, col_to_table_map: dict | None = None) -> int:
    from app.services.ontology.kpi_extractor import extract_kpis_from_workbook
    from app.core.llm import get_llm

    ontology_kpis = load_ontology_kpis(db)
    if not ontology_kpis:
        return 0

    reset_phase3_counter()
    llm = get_llm(temperature=0.0)
    cache = OntologyCache(db)
    kpis = extract_kpis_from_workbook(workbook_metadata, col_to_table_map or {}, llm)
    report_id = str(dashboard_id)
    count = 0
    for kpi in kpis:
        match = match_kpi_to_ontology(kpi, ontology_kpis, cache, llm)
        persist_mapping(db, report_id, kpi, match)
        count += 1
    return count


def process_workbook_ontology(metadata, db, col_to_table_map: dict | None = None) -> int:
    """Run Stage -1 extraction for all dashboards in a synced workbook."""
    from app.models.postgres import Workbook

    wb = db.query(Workbook).filter(Workbook.source_file == metadata.source_file).first()
    if not wb:
        return 0
    total = 0
    for dash in wb.dashboards:
        total += process_dashboard_kpis(db, dash.id, metadata, col_to_table_map or {})
    return total


def enrich_with_ontology_inventory(report_id: str | int, db: Session) -> dict | None:
    rows = db.query(ReportKPIMapping).filter(ReportKPIMapping.report_id == str(report_id)).all()
    if not rows:
        return None
    mapped = sum(1 for r in rows if r.mapping_status in ("auto_accepted", "human_accepted", "promoted"))
    ambiguous = sum(1 for r in rows if r.mapping_status == "pending_review")
    not_found = sum(1 for r in rows if r.mapping_status == "not_found")
    return {
        "report_id": str(report_id),
        "total": len(rows),
        "mapped": mapped,
        "ambiguous": ambiguous,
        "not_found": not_found,
        "ontology_score": round(mapped / max(len(rows), 1), 3),
    }
