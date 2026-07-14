import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.ontology import OntologyKPI, ReportKPIMapping
from app.services.ontology.embedding_service import (
    blob_to_embedding,
    cosine_similarity,
    compute_embedding,
    embed_ontology_kpis,
)
from app.services.ontology.kpi_extractor import ExtractedKPI, extract_kpis_per_worksheet
from app.services.ontology.ontology_cache import OntologyCache

MAX_PHASE3_CALLS_PER_EXTRACTION = 200
ONTOLOGY_VERSION = "v1"
TOP_K_CANDIDATES = 5

_phase3_call_counter = 0
_last_phase3_candidates: list[dict] = []


def reset_phase3_counter() -> None:
    global _phase3_call_counter
    _phase3_call_counter = 0


def get_last_phase3_candidates() -> list[dict]:
    return list(_last_phase3_candidates)


def _parse_aliases(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _parse_lineage(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return sorted(parsed) if isinstance(parsed, list) else []
    except Exception:
        return []


def _status_from_confidence(confidence: float) -> str:
    if confidence >= 0.90:
        return "auto_accepted"
    if confidence >= 0.50:
        return "pending_review"
    return "not_found"


def _agg_key(aggregation: str) -> str:
    agg = (aggregation or "UNKNOWN").upper()
    if agg == "AVERAGE":
        return "AVG"
    if agg in ("CNT", "COUNTD"):
        return "COUNT"
    return agg


def _lineage_agg_match(kpi: ExtractedKPI, ok: dict) -> bool:
    rep = ok.get("representative_lineage") or []
    if not rep or not kpi.resolved_lineage:
        return False
    return sorted(rep) == sorted(kpi.resolved_lineage) and _agg_key(kpi.aggregation_type) == _agg_key(
        ok.get("aggregation_type") or "UNKNOWN"
    )


def build_ontology_match_indexes(ontology_kpis: list[dict]) -> dict:
    """O(1) lookup indexes for Phase 1 name/alias/lineage matching."""
    name_index: dict[str, dict] = {}
    alias_index: dict[str, dict] = {}
    lineage_index: dict[tuple[tuple[str, ...], str], dict] = {}
    for ok in ontology_kpis:
        name_key = ok.get("name", "").strip().lower()
        if name_key:
            name_index[name_key] = ok
        for alias in ok.get("aliases") or []:
            alias_key = str(alias).strip().lower()
            if alias_key:
                alias_index[alias_key] = ok
        rep = ok.get("representative_lineage") or []
        if rep:
            lineage_index[(tuple(sorted(rep)), _agg_key(ok.get("aggregation_type") or "UNKNOWN"))] = ok
    return {"name": name_index, "alias": alias_index, "lineage": lineage_index}


def _phase1_match(
    kpi: ExtractedKPI,
    ontology_kpis: list[dict],
    indexes: dict | None,
) -> dict | None:
    name_lower = kpi.name.strip().lower()
    if indexes:
        ok = indexes["name"].get(name_lower)
        if ok:
            return {
                "matched_kpi_id": ok["kpi_id"],
                "similarity_score": 1.0,
                "confidence_score": 1.0,
                "similarity_rationale": "Exact name match",
                "confidence_rationale": "Phase 1 exact match",
                "model_used": kpi.extraction_method,
                "mapping_status": "auto_accepted",
            }
        ok = indexes["alias"].get(name_lower)
        if ok:
            return {
                "matched_kpi_id": ok["kpi_id"],
                "similarity_score": 0.98,
                "confidence_score": 0.95,
                "similarity_rationale": f"Alias match: {name_lower}",
                "confidence_rationale": "Phase 1 alias match",
                "model_used": kpi.extraction_method,
                "mapping_status": "auto_accepted",
            }
        if kpi.resolved_lineage:
            lineage_key = (tuple(sorted(kpi.resolved_lineage)), _agg_key(kpi.aggregation_type))
            ok = indexes["lineage"].get(lineage_key)
            if ok:
                return {
                    "matched_kpi_id": ok["kpi_id"],
                    "similarity_score": 1.0,
                    "confidence_score": 1.0,
                    "similarity_rationale": "Phase 1 lineage+agg match",
                    "confidence_rationale": "Phase 1 lineage+agg match",
                    "model_used": kpi.extraction_method,
                    "mapping_status": "auto_accepted",
                }
        return None

    for ok in ontology_kpis:
        if ok.get("name", "").strip().lower() == name_lower:
            return {
                "matched_kpi_id": ok["kpi_id"],
                "similarity_score": 1.0,
                "confidence_score": 1.0,
                "similarity_rationale": "Exact name match",
                "confidence_rationale": "Phase 1 exact match",
                "model_used": kpi.extraction_method,
                "mapping_status": "auto_accepted",
            }
        for alias in ok.get("aliases") or []:
            if str(alias).strip().lower() == name_lower:
                return {
                    "matched_kpi_id": ok["kpi_id"],
                    "similarity_score": 0.98,
                    "confidence_score": 0.95,
                    "similarity_rationale": f"Alias match: {alias}",
                    "confidence_rationale": "Phase 1 alias match",
                    "model_used": kpi.extraction_method,
                    "mapping_status": "auto_accepted",
                }
    for ok in ontology_kpis:
        if _lineage_agg_match(kpi, ok):
            return {
                "matched_kpi_id": ok["kpi_id"],
                "similarity_score": 1.0,
                "confidence_score": 1.0,
                "similarity_rationale": "Phase 1 lineage+agg match",
                "confidence_rationale": "Phase 1 lineage+agg match",
                "model_used": kpi.extraction_method,
                "mapping_status": "auto_accepted",
            }
    return None


def match_kpi_to_ontology(
    kpi: ExtractedKPI,
    ontology_kpis: list[dict],
    cache: OntologyCache,
    llm: Any = None,
    embedding_fn: Any = None,
    indexes: dict | None = None,
) -> dict:
    global _phase3_call_counter, _last_phase3_candidates
    embedding_fn = embedding_fn or compute_embedding

    cached = cache.get(kpi.resolved_lineage, kpi.aggregation_type)
    if cached:
        cached["mapping_status"] = _status_from_confidence(cached.get("confidence_score") or 0.0)
        return cached

    phase1 = _phase1_match(kpi, ontology_kpis, indexes)
    if phase1:
        cache.set(kpi.resolved_lineage, kpi.aggregation_type, phase1, commit=False)
        return phase1

    # Phase 2: embedding pre-filter with Top-5
    kpi_text = f"{kpi.name} {kpi.definition} {' '.join(kpi.resolved_lineage)}"
    kpi_emb = embedding_fn(kpi_text)
    ranked: list[tuple[float, dict]] = []
    for ok in ontology_kpis:
        ok_text = f"{ok.get('name', '')} {ok.get('definition', '')} {' '.join(_parse_aliases(ok.get('aliases_raw')))}"
        ok_emb = ok.get("embedding")
        if ok_emb is None:
            ok_emb = embedding_fn(ok_text)
        sim = cosine_similarity(kpi_emb, ok_emb)
        ranked.append((sim, ok))
    ranked.sort(key=lambda x: x[0], reverse=True)

    best_sim = ranked[0][0] if ranked else 0.0
    best_id = ranked[0][1]["kpi_id"] if ranked else None
    best_name = ranked[0][1].get("name", "") if ranked else ""
    top5 = [{"kpi_id": ok["kpi_id"], "name": ok["name"], "score": sim} for sim, ok in ranked[:TOP_K_CANDIDATES]]

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
        cache.set(kpi.resolved_lineage, kpi.aggregation_type, result, commit=False)
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
        cache.set(kpi.resolved_lineage, kpi.aggregation_type, result, commit=False)
        return result

    # Phase 3: LLM judge on Top-5
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
        cache.set(kpi.resolved_lineage, kpi.aggregation_type, result, commit=False)
        return result

    _phase3_call_counter += 1
    _last_phase3_candidates = top5
    candidates = [{"kpi_id": c["kpi_id"], "name": c["name"]} for c in top5]
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

    cache.set(kpi.resolved_lineage, kpi.aggregation_type, result, commit=False)
    return result


def load_ontology_kpis(db: Session) -> list[dict]:
    rows = db.query(OntologyKPI).filter(OntologyKPI.status == "active").all()
    out = []
    for r in rows:
        emb = blob_to_embedding(r.embedding) if r.embedding else None
        out.append(
            {
                "kpi_id": r.kpi_id,
                "name": r.name,
                "definition": r.definition,
                "domain": r.domain,
                "aliases": _parse_aliases(r.aliases),
                "aliases_raw": r.aliases,
                "aggregation_type": r.aggregation_type,
                "representative_lineage": _parse_lineage(r.representative_lineage),
                "embedding": emb,
            }
        )
    return out


def update_representative_lineage(db: Session, canonical_kpi_id: str, lineage: list[str]) -> None:
    if not canonical_kpi_id or not lineage:
        return
    kpi = db.query(OntologyKPI).filter(OntologyKPI.kpi_id == canonical_kpi_id).first()
    if kpi and not kpi.representative_lineage:
        kpi.representative_lineage = json.dumps(sorted(lineage))
        db.commit()


def persist_mapping(
    db: Session,
    report_id: str,
    kpi: ExtractedKPI,
    match: dict,
    *,
    commit: bool = True,
) -> ReportKPIMapping:
    ws_id = kpi.worksheet_id
    existing = (
        db.query(ReportKPIMapping)
        .filter(
            ReportKPIMapping.report_id == report_id,
            ReportKPIMapping.worksheet_id == ws_id,
            ReportKPIMapping.report_kpi_name == kpi.name,
        )
        .first()
    )
    if existing:
        row = existing
    else:
        row = ReportKPIMapping(
            mapping_id=str(uuid.uuid4()),
            report_id=report_id,
            worksheet_id=ws_id,
            worksheet_name=kpi.worksheet_name,
            report_kpi_name=kpi.name,
        )
        db.add(row)

    row.worksheet_id = ws_id
    row.worksheet_name = kpi.worksheet_name
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
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def process_dashboard_kpis(
    db: Session,
    dashboard_id: int,
    workbook_metadata: Any,
    col_to_table_map: dict | None = None,
    *,
    ontology_kpis: list[dict] | None = None,
    llm: Any = None,
    cache: OntologyCache | None = None,
    per_ws: dict[str, list[ExtractedKPI]] | None = None,
    match_indexes: dict | None = None,
) -> int:
    from app.core.llm import get_llm
    from app.models.postgres import Dashboard

    dashboard = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
    if not dashboard:
        return 0

    loaded_fresh = ontology_kpis is None
    ontology_kpis = ontology_kpis or load_ontology_kpis(db)
    if not ontology_kpis:
        return 0

    if loaded_fresh:
        reset_phase3_counter()

    llm = llm if llm is not None else get_llm(temperature=0.0)
    cache = cache or OntologyCache(db)
    match_indexes = match_indexes or build_ontology_match_indexes(ontology_kpis)

    worksheet_rows = list(dashboard.worksheets)
    dash_ws_names = {ws.name for ws in worksheet_rows}
    if per_ws is None:
        per_ws = extract_kpis_per_worksheet(
            workbook_metadata,
            col_to_table_map or {},
            worksheet_db_rows=worksheet_rows,
            llm=llm,
        )

    report_id = str(dashboard_id)
    count = 0
    for ws_name, kpis in per_ws.items():
        if ws_name not in dash_ws_names:
            continue
        for kpi in kpis:
            match = match_kpi_to_ontology(kpi, ontology_kpis, cache, llm, indexes=match_indexes)
            persist_mapping(db, report_id, kpi, match, commit=False)
            count += 1

    if count:
        cache.flush()
        db.commit()
    return count


def process_workbook_ontology(metadata, db, col_to_table_map: dict | None = None) -> int:
    """Run Stage -1 extraction for all dashboards in a synced workbook."""
    from app.core.llm import get_llm
    from app.models.postgres import Workbook

    wb = db.query(Workbook).filter(Workbook.source_file == metadata.source_file).first()
    if not wb:
        return 0

    ontology_kpis = load_ontology_kpis(db)
    if not ontology_kpis:
        return 0

    reset_phase3_counter()
    llm = get_llm(temperature=0.0)
    cache = OntologyCache(db)
    match_indexes = build_ontology_match_indexes(ontology_kpis)

    ws_by_id: dict[int, Any] = {}
    for dash in wb.dashboards:
        for ws in dash.worksheets:
            ws_by_id[ws.id] = ws
    per_ws = extract_kpis_per_worksheet(
        metadata,
        col_to_table_map or {},
        worksheet_db_rows=list(ws_by_id.values()),
        llm=llm,
    )

    total = 0
    for dash in wb.dashboards:
        total += process_dashboard_kpis(
            db,
            dash.id,
            metadata,
            col_to_table_map or {},
            ontology_kpis=ontology_kpis,
            llm=llm,
            cache=cache,
            per_ws=per_ws,
            match_indexes=match_indexes,
        )
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
