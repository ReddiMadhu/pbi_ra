import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.ontology import OntologyKPI, ReportKPIMapping
from app.models.postgres import Dashboard
from app.services.ontology.embedding_service import (
    blob_to_embedding,
    cosine_similarity,
    compute_embedding,
    embed_ontology_kpis,
)
from app.services.ontology.kpi_extractor import (
    ExtractedKPI,
    extract_from_ai_summary,
    extract_kpis_per_worksheet,
)
from app.services.ontology.ontology_cache import OntologyCache
from app.services.ontology.taxonomy import (
    get_active_sectors,
    is_sector_active,
    normalize_scope,
)

logger = logging.getLogger(__name__)

MAX_PHASE3_CALLS_PER_EXTRACTION = 200
ONTOLOGY_VERSION = "v1"
PHASE3_MIN_CANDIDATE_SIM = 0.50
MAX_PHASE3_CANDIDATES_PER_KPI = int(os.getenv("ONTOLOGY_MAX_PHASE3_CANDIDATES", "30"))
ONTOLOGY_INCLUDE_ORPHANS = os.getenv("ONTOLOGY_INCLUDE_ORPHANS", "false").lower() == "true"
PHASE3_DEFINITION_MAX_CHARS = 120

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
    if agg == "CNT":
        return "COUNT"
    # COUNTD stays COUNTD so distinct-count lineage keys stay distinct from COUNT
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


def _needs_sector_fallback(result: dict) -> bool:
    status = result.get("mapping_status")
    conf = float(result.get("confidence_score") or 0.0)
    return status == "not_found" or conf < 0.50


def match_kpi_to_ontology(
    kpi: ExtractedKPI,
    ontology_kpis: list[dict],
    cache: OntologyCache,
    llm: Any = None,
    embedding_fn: Any = None,
    indexes: dict | None = None,
    *,
    scope_sector: str | None = None,
    scope_subdomain: str | None = None,
) -> dict:
    global _phase3_call_counter, _last_phase3_candidates
    embedding_fn = embedding_fn or compute_embedding

    cached = cache.get(
        kpi.resolved_lineage,
        kpi.aggregation_type,
        scope_sector,
        scope_subdomain,
    )
    if cached:
        cached["mapping_status"] = _status_from_confidence(cached.get("confidence_score") or 0.0)
        return cached

    phase1 = _phase1_match(kpi, ontology_kpis, indexes)
    if phase1:
        cache.set(
            kpi.resolved_lineage,
            kpi.aggregation_type,
            phase1,
            sector=scope_sector,
            subdomain=scope_subdomain,
            commit=False,
        )
        return phase1

    # Phase 2: embedding pre-filter; Phase 3 receives all slice candidates >= threshold
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
    eligible = [(sim, ok) for sim, ok in ranked if sim >= PHASE3_MIN_CANDIDATE_SIM]
    if len(eligible) > MAX_PHASE3_CANDIDATES_PER_KPI:
        logger.warning(
            "Phase 3 candidate truncation: %s eligible down to %s for KPI '%s'",
            len(eligible),
            MAX_PHASE3_CANDIDATES_PER_KPI,
            kpi.name,
        )
        eligible = eligible[:MAX_PHASE3_CANDIDATES_PER_KPI]
    llm_candidates = [
        {
            "kpi_id": ok["kpi_id"],
            "name": ok["name"],
            "score": sim,
            "definition": (ok.get("definition") or "")[:PHASE3_DEFINITION_MAX_CHARS],
        }
        for sim, ok in eligible
    ]

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
        cache.set(
            kpi.resolved_lineage,
            kpi.aggregation_type,
            result,
            sector=scope_sector,
            subdomain=scope_subdomain,
            commit=False,
        )
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
        cache.set(
            kpi.resolved_lineage,
            kpi.aggregation_type,
            result,
            sector=scope_sector,
            subdomain=scope_subdomain,
            commit=False,
        )
        return result

    # Phase 3: LLM judge on top-N candidates in scoped slice (sim >= 0.50)
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
        cache.set(
            kpi.resolved_lineage,
            kpi.aggregation_type,
            result,
            sector=scope_sector,
            subdomain=scope_subdomain,
            commit=False,
        )
        return result

    _phase3_call_counter += 1
    _last_phase3_candidates = llm_candidates
    candidates = [
        {
            "kpi_id": c["kpi_id"],
            "name": c["name"],
            "definition": c.get("definition") or "",
        }
        for c in llm_candidates
    ]
    report_ctx = {
        "name": kpi.name,
        "lineage": kpi.resolved_lineage,
        "agg": kpi.aggregation_type,
    }
    if getattr(kpi, "mark_type", None):
        report_ctx["mark_type"] = kpi.mark_type
    if getattr(kpi, "calculation_logic", None):
        report_ctx["calculation_logic"] = kpi.calculation_logic
    prompt = f"""Judge if report KPI maps to a canonical ontology KPI.
Report KPI: {json.dumps(report_ctx)}
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

    cache.set(
        kpi.resolved_lineage,
        kpi.aggregation_type,
        result,
        sector=scope_sector,
        subdomain=scope_subdomain,
        commit=False,
    )
    return result


def match_kpi_scoped(
    kpi: ExtractedKPI,
    subdomain_kpis: list[dict],
    sector_kpis: list[dict],
    cache: OntologyCache,
    llm: Any = None,
    embedding_fn: Any = None,
    *,
    sector: str,
    subdomain: str,
) -> dict:
    """Match against subdomain slice first, expand to sector slice on miss."""
    sub_indexes = build_ontology_match_indexes(subdomain_kpis) if subdomain_kpis else None
    result = match_kpi_to_ontology(
        kpi,
        subdomain_kpis,
        cache,
        llm,
        embedding_fn,
        indexes=sub_indexes,
        scope_sector=sector,
        scope_subdomain=subdomain,
    )
    if not _needs_sector_fallback(result):
        return result

    tried_ids = {k["kpi_id"] for k in subdomain_kpis}
    sector_only = [k for k in sector_kpis if k["kpi_id"] not in tried_ids]
    if not sector_only:
        return result

    sec_indexes = build_ontology_match_indexes(sector_only)
    sector_result = match_kpi_to_ontology(
        kpi,
        sector_only,
        cache,
        llm,
        embedding_fn,
        indexes=sec_indexes,
        scope_sector=sector,
        scope_subdomain="__sector__",
    )
    if sector_result.get("mapping_status") != "not_found" or (
        float(sector_result.get("confidence_score") or 0.0) > float(result.get("confidence_score") or 0.0)
    ):
        sector_result["confidence_rationale"] = (
            (sector_result.get("confidence_rationale") or "") + " (sector fallback)"
        ).strip()
        return sector_result
    return result


def _kpi_row_to_dict(r: OntologyKPI) -> dict:
    emb = blob_to_embedding(r.embedding) if r.embedding else None
    return {
        "kpi_id": r.kpi_id,
        "name": r.name,
        "definition": r.definition,
        "domain": r.domain,
        "sector": r.sector,
        "subdomain": r.subdomain,
        "aliases": _parse_aliases(r.aliases),
        "aliases_raw": r.aliases,
        "aggregation_type": r.aggregation_type,
        "representative_lineage": _parse_lineage(r.representative_lineage),
        "embedding": emb,
    }


def load_ontology_kpis(
    db: Session,
    *,
    sector: str | None = None,
    subdomain: str | None = None,
    active_sectors_only: bool = True,
) -> list[dict]:
    q = db.query(OntologyKPI).filter(OntologyKPI.status == "active")
    if active_sectors_only:
        active = get_active_sectors()
        q = q.filter(OntologyKPI.sector.in_(active))
    if sector:
        q = q.filter(OntologyKPI.sector == sector)
    if subdomain:
        q = q.filter(OntologyKPI.subdomain == subdomain)
    rows = q.all()
    return [_kpi_row_to_dict(r) for r in rows]


def load_scoped_ontology_for_dashboard(
    db: Session,
    sector: str | None,
    subdomain: str | None,
) -> tuple[list[dict], list[dict]]:
    """Return (subdomain_kpis, sector_kpis) for scoped matching."""
    sec, sub = normalize_scope(sector, subdomain)
    if not is_sector_active(sec):
        return [], []
    subdomain_kpis = load_ontology_kpis(db, sector=sec, subdomain=sub, active_sectors_only=False)
    sector_kpis = load_ontology_kpis(db, sector=sec, active_sectors_only=False)
    return subdomain_kpis, sector_kpis


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
    row.report_kpi_definition = kpi.definition or None
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
    sector, subdomain = normalize_scope(
        dashboard.ontology_sector,
        dashboard.ontology_subdomain,
        legacy_domain=dashboard.domain_classification,
    )

    if ontology_kpis is None:
        subdomain_kpis, sector_kpis = load_scoped_ontology_for_dashboard(db, sector, subdomain)
        if not sector_kpis:
            return 0
    else:
        subdomain_kpis = ontology_kpis
        sector_kpis = ontology_kpis

    if loaded_fresh:
        reset_phase3_counter()

    llm = llm if llm is not None else get_llm(temperature=0.0)
    cache = cache or OntologyCache(db)

    worksheet_rows = list(dashboard.worksheets)
    dash_ws_names = {ws.name for ws in worksheet_rows}
    if per_ws is None:
        per_ws = extract_kpis_per_worksheet(
            workbook_metadata,
            col_to_table_map or {},
            worksheet_db_rows=worksheet_rows,
            llm=llm,
            include_orphan_worksheets=ONTOLOGY_INCLUDE_ORPHANS,
        )

    # Collect names already extracted from Sources A/B/C/E for Source D dedup
    existing_names: set[str] = set()
    for ws_name, kpis in per_ws.items():
        if ws_name not in dash_ws_names:
            continue
        for kpi in kpis:
            existing_names.add(kpi.name.lower())

    # Source D: ai_summary LLM KPIs (dashboard-level, no structured lineage)
    ai_kpis = extract_from_ai_summary(dashboard.ai_summary)
    source_d: list[ExtractedKPI] = []
    for kpi in ai_kpis:
        if kpi.name.lower() in existing_names:
            continue
        existing_names.add(kpi.name.lower())
        source_d.append(kpi)

    report_id = str(dashboard_id)
    count = 0
    for ws_name, kpis in per_ws.items():
        if ws_name not in dash_ws_names:
            continue
        for kpi in kpis:
            match = match_kpi_scoped(
                kpi,
                subdomain_kpis,
                sector_kpis,
                cache,
                llm,
                sector=sector,
                subdomain=subdomain,
            )
            persist_mapping(db, report_id, kpi, match, commit=False)
            count += 1

    for kpi in source_d:
        match = match_kpi_scoped(
            kpi,
            subdomain_kpis,
            sector_kpis,
            cache,
            llm,
            sector=sector,
            subdomain=subdomain,
        )
        persist_mapping(db, report_id, kpi, match, commit=False)
        count += 1

    if count:
        cache.flush()
        db.commit()
    return count


def process_workbook_ontology(metadata, db, col_to_table_map: dict | None = None) -> int:
    """Run Stage -1 extraction for all dashboards in a synced workbook."""
    from app.core.llm import get_llm
    from app.models.postgres import Workbook, Worksheet

    wb = db.query(Workbook).filter(Workbook.source_file == metadata.source_file).first()
    if not wb:
        return 0

    reset_phase3_counter()
    llm = get_llm(temperature=0.0)
    cache = OntologyCache(db)

    ws_by_id: dict[int, Any] = {}
    for dash in wb.dashboards:
        for ws in dash.worksheets:
            ws_by_id[ws.id] = ws
    if ONTOLOGY_INCLUDE_ORPHANS:
        for ws in db.query(Worksheet).filter(Worksheet.workbook_id == wb.id).all():
            ws_by_id[ws.id] = ws

    per_ws = extract_kpis_per_worksheet(
        metadata,
        col_to_table_map or {},
        worksheet_db_rows=list(ws_by_id.values()),
        llm=llm,
        include_orphan_worksheets=ONTOLOGY_INCLUDE_ORPHANS,
    )

    total = 0
    for dash in wb.dashboards:
        total += process_dashboard_kpis(
            db,
            dash.id,
            metadata,
            col_to_table_map or {},
            llm=llm,
            cache=cache,
            per_ws=per_ws,
        )

    # Persist orphan-worksheet KPIs once against the first dashboard (report scope)
    if ONTOLOGY_INCLUDE_ORPHANS and wb.dashboards:
        first_dash = wb.dashboards[0]
        dash_ws_names = {ws.name for ws in first_dash.worksheets}
        sector, subdomain = normalize_scope(
            first_dash.ontology_sector,
            first_dash.ontology_subdomain,
            legacy_domain=first_dash.domain_classification,
        )
        subdomain_kpis, sector_kpis = load_scoped_ontology_for_dashboard(db, sector, subdomain)
        report_id = str(first_dash.id)
        orphan_count = 0
        for ws_name, kpis in per_ws.items():
            if ws_name in dash_ws_names:
                continue
            for kpi in kpis:
                if kpi.worksheet_id != "orphan":
                    continue
                match = match_kpi_scoped(
                    kpi,
                    subdomain_kpis,
                    sector_kpis,
                    cache,
                    llm,
                    sector=sector,
                    subdomain=subdomain,
                )
                persist_mapping(db, report_id, kpi, match, commit=False)
                orphan_count += 1
        if orphan_count:
            cache.flush()
            db.commit()
            total += orphan_count

    return total


def enrich_with_ontology_inventory(report_id: str | int, db: Session) -> dict | None:
    rows = db.query(ReportKPIMapping).filter(ReportKPIMapping.report_id == str(report_id)).all()
    if not rows:
        return None
    mapped = sum(1 for r in rows if r.mapping_status in ("auto_accepted", "human_accepted", "promoted"))
    ambiguous = sum(1 for r in rows if r.mapping_status == "pending_review")
    not_found = sum(1 for r in rows if r.mapping_status == "not_found")
    out = {
        "report_id": str(report_id),
        "total": len(rows),
        "mapped": mapped,
        "ambiguous": ambiguous,
        "not_found": not_found,
        "ontology_score": round(mapped / max(len(rows), 1), 3),
    }
    dash = db.query(Dashboard).filter(Dashboard.id == int(report_id)).first()
    if dash:
        out["ontology_sector"] = dash.ontology_sector
        out["ontology_subdomain"] = dash.ontology_subdomain
    return out
