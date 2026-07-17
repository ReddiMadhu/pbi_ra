import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from difflib import SequenceMatcher

class Phase3JudgeResult(BaseModel):
    """Pydantic schema for Phase 3 LLM structured output."""
    matched_kpi_id: Optional[str] = Field(
        None,
        description="The kpi_id of the best matching canonical KPI, or null if no match"
    )
    similarity_score: float = Field(
        description="Semantic similarity score between 0.0 and 1.0"
    )
    confidence_score: float = Field(
        description="Confidence in the match between 0.0 and 1.0"
    )
    rationale: str = Field(
        description="Brief explanation of why this match was chosen or rejected"
    )

def _fuzzy_name_match(name1: str, name2: str, threshold: float = 0.85) -> bool:
    """Check if two names are close enough to be a typo match."""
    return SequenceMatcher(None, name1.lower(), name2.lower()).ratio() >= threshold


def normalize_kpi_name(raw_name: str) -> str:
    """Strip dimensional suffixes, rank prefixes, and table references
    so the core metric name is used for matching."""
    name = raw_name.strip()
    # Strip "| <anything> (Table - <anything>)" table references
    name = re.sub(r'\s*\|.*?\(Table\s*-.*?\).*$', '', name, flags=re.IGNORECASE)
    # Strip "| Old", "| New" etc. standalone suffixes
    name = re.sub(r'\s*\|\s*(Old|New)\b.*$', '', name, flags=re.IGNORECASE)
    # Strip "Rank | ", "Performance Level | " prefixes
    name = re.sub(r'^(Rank|Performance\s+Level)\s*\|\s*', '', name, flags=re.IGNORECASE)
    # Strip "Top AGENT - " or "Top <WORD> - " prefixes
    name = re.sub(r'^Top\s+\w+\s*[-\u2013]\s*', '', name, flags=re.IGNORECASE)
    # Strip trailing " b" or " a" (Tableau widget suffixes like "Total Paid b")
    name = re.sub(r'\s+[ba]$', '', name)
    # Strip "by <Dimension>" suffixes (e.g., "Total Paid by Agent")
    name = re.sub(r'\s+by\s+\w[\w\s]*$', '', name, flags=re.IGNORECASE)
    return name.strip()


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
PHASE3_MIN_CANDIDATE_SIM = 0.15
PHASE3_TOP_N_CANDIDATES = 5
MAX_PHASE3_CANDIDATES_PER_KPI = int(os.getenv("ONTOLOGY_MAX_PHASE3_CANDIDATES", "30"))
ONTOLOGY_INCLUDE_ORPHANS = os.getenv("ONTOLOGY_INCLUDE_ORPHANS", "false").lower() == "true"
PHASE3_DEFINITION_MAX_CHARS = 120

_phase3_call_counter = 0
_last_phase3_candidates: list[dict] = []


def _write_to_ontology_log(log_data: dict) -> None:
    try:
        log_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        log_path = os.path.join(log_dir, "ontology_process.log")
        
        # Build a beautiful, structured log string
        lines = []
        lines.append("=" * 80)
        lines.append(f"TIMESTAMP: {log_data['timestamp']}")
        kpi = log_data["extracted_kpi"]
        lines.append(f"TARGET KPI: '{kpi['name']}'")
        lines.append(f"  - Worksheet ID: {kpi['worksheet_id']}")
        lines.append(f"  - Worksheet Name: {kpi['worksheet_name']}")
        lines.append(f"  - Sector Scope: {log_data['scope']['sector']}")
        lines.append(f"  - Subdomain Scope: {log_data['scope']['subdomain']}")
        lines.append(f"  - Lineage: {kpi['resolved_lineage']}")
        lines.append(f"  - Aggregation Type: {kpi['aggregation_type']}")
        lines.append(f"  - Definition: {kpi['definition']}")
        lines.append(f"  - Extraction Method: {kpi['extraction_method']}")
        if kpi.get("mark_type"):
            lines.append(f"  - Mark Type: {kpi['mark_type']}")
        if kpi.get("calculation_logic"):
            lines.append(f"  - Calculation Logic: {kpi['calculation_logic']}")
            
        if log_data["cache_hit"]:
            lines.append(f"\n>>> RESULT: CACHE HIT (Duration: {log_data.get('cache_duration', 0.0):.4f}s)")
            lines.append(f"  - Cached Match: {json.dumps(log_data['final_result'])}")
        else:
            p1 = log_data["phases"]["phase1"]
            lines.append(f"\n--- PHASE 1: EXACT & ALIAS MATCHING (Duration: {p1.get('duration', 0.0):.4f}s) ---")
            lines.append(f"  - Executed: {p1['executed']}")
            if p1["executed"]:
                lines.append(f"  - Matched: {p1['matched']}")
                if p1["matched"]:
                    lines.append(f"  - Match Result: {json.dumps(p1['result'])}")
                    
            if not p1["matched"]:
                p2 = log_data["phases"]["phase2"]
                lines.append(f"\n--- PHASE 2: EMBEDDING SIMILARITY FILTER (Duration: {p2.get('duration', 0.0):.4f}s) ---")
                lines.append(f"  - Executed: {p2['executed']}")
                if p2["executed"]:
                    lines.append("  - Top Candidates:")
                    for idx, cand in enumerate(p2["top_candidates"], 1):
                        lines.append(f"    {idx}. ID: {cand['kpi_id']} | Name: '{cand['name']}' | Similarity: {cand['similarity_score']:.4f}")
                    lines.append(f"  - Match Result: {json.dumps(p2['result'])}")
                    
                if not p2["matched"] and not (p2["result"] and p2["result"].get("mapping_status") == "not_found"):
                    p3 = log_data["phases"]["phase3"]
                    lines.append(f"\n--- PHASE 3: LLM JUDGE DECISION (Duration: {p3.get('duration', 0.0):.4f}s) ---")
                    lines.append(f"  - Executed: {p3['executed']}")
                    if p3["executed"]:
                        if p3.get("skipped_reason"):
                            lines.append(f"  - Skipped: {p3['skipped_reason']}")
                        else:
                            lines.append("  - Candidates sent to LLM:")
                            for cand in p3["candidates"]:
                                lines.append(f"    - ID: {cand['kpi_id']} | Name: '{cand['name']}' | Similarity: {cand['score']:.4f}")
                            lines.append(f"  - LLM Prompt: {p3['llm_prompt']}")
                            lines.append(f"  - LLM Response: {p3['llm_response']}")
                            if p3.get("error"):
                                lines.append(f"  - LLM Error: {p3['error']}")
                            lines.append(f"  - Match Result: {json.dumps(p3['result'])}")
                            
        lines.append("\nFINAL DECISION:")
        if log_data["final_result"]:
            lines.append(f"  - Matched Canonical KPI ID: {log_data['final_result'].get('matched_kpi_id')}")
            lines.append(f"  - Similarity Score: {log_data['final_result'].get('similarity_score')}")
            lines.append(f"  - Confidence Score: {log_data['final_result'].get('confidence_score')}")
            lines.append(f"  - Status: {log_data['final_result'].get('mapping_status')}")
            lines.append(f"  - Rationale: {log_data['final_result'].get('similarity_rationale')}")
            lines.append(f"  - Confidence Rationale: {log_data['final_result'].get('confidence_rationale')}")
        else:
            lines.append("  - None")
        lines.append("=" * 80 + "\n")
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        logger.error("Failed to write to ontology process log: %s", e)


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


def _clean_ws_name(ws_name: str | None) -> str:
    if not ws_name:
        return ""
    # Strip common visual prefixes (e.g. "KPI - ", "Sheet ")
    cleaned = re.sub(r"^(kpi\s*-\s*|kpi:\s*|sheet\s*|table\s*-\s*)", "", ws_name, flags=re.IGNORECASE)
    # Remove special characters
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", cleaned)
    return " ".join(cleaned.split()).lower()


def _generate_virtual_aliases(name_lower: str, ws_name: str | None) -> list[str]:
    if not ws_name:
        return []
    v_aliases = []
    clean_ws = _clean_ws_name(ws_name)
    if len(clean_ws) > 3:
        v_aliases.append(clean_ws)
        v_aliases.append(f"{clean_ws} {name_lower}")
        v_aliases.append(f"{name_lower} by {clean_ws}")
    
    # Try splitting by common delimiters like '|', '-', '/'
    parts = [p.strip() for p in re.split(r"[|\-/]", ws_name) if p.strip()]
    clean_parts = [_clean_ws_name(p) for p in parts]
    clean_parts = [cp for cp in clean_parts if len(cp) > 2]
    if len(clean_parts) > 1:
        p1, p2 = clean_parts[0], clean_parts[1]
        v_aliases.append(f"{p1} {p2}")
        v_aliases.append(f"{p2} {p1}")
        v_aliases.append(f"{p1} by {p2}")
        v_aliases.append(f"{p2} by {p1}")
        
    return list(set(v_aliases))


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
        
        # Virtual alias matching
        v_aliases = _generate_virtual_aliases(name_lower, getattr(kpi, "worksheet_name", None))
        for v_alias in v_aliases:
            ok = indexes["alias"].get(v_alias) or indexes["name"].get(v_alias)
            if ok:
                return {
                    "matched_kpi_id": ok["kpi_id"],
                    "similarity_score": 0.95,
                    "confidence_score": 0.90,
                    "similarity_rationale": f"Virtual alias match: '{v_alias}'",
                    "confidence_rationale": "Phase 1 virtual alias match",
                    "model_used": kpi.extraction_method,
                    "mapping_status": "auto_accepted",
                }
        
        # Fuzzy name matching if indexed exact/alias/lineage failed
        for ok in ontology_kpis:
            ok_name = ok.get("name", "")
            if ok_name and _fuzzy_name_match(name_lower, ok_name):
                return {
                    "matched_kpi_id": ok["kpi_id"],
                    "similarity_score": 0.95,
                    "confidence_score": 0.90,
                    "similarity_rationale": f"Fuzzy name match: '{ok_name}' (typo tolerance)",
                    "confidence_rationale": "Phase 1 fuzzy match",
                    "model_used": kpi.extraction_method,
                    "mapping_status": "auto_accepted",
                }
            for alias in ok.get("aliases") or []:
                if _fuzzy_name_match(name_lower, str(alias)):
                    return {
                        "matched_kpi_id": ok["kpi_id"],
                        "similarity_score": 0.93,
                        "confidence_score": 0.88,
                        "similarity_rationale": f"Fuzzy alias match: '{alias}' (typo tolerance)",
                        "confidence_rationale": "Phase 1 fuzzy alias match",
                        "model_used": kpi.extraction_method,
                        "mapping_status": "pending_review",
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
    
    # Virtual alias fallback without index
    v_aliases = _generate_virtual_aliases(name_lower, getattr(kpi, "worksheet_name", None))
    for ok in ontology_kpis:
        for alias in [ok.get("name", "")] + (ok.get("aliases") or []):
            alias_lower = str(alias).strip().lower()
            if alias_lower in v_aliases:
                return {
                    "matched_kpi_id": ok["kpi_id"],
                    "similarity_score": 0.95,
                    "confidence_score": 0.90,
                    "similarity_rationale": f"Virtual alias match: '{alias_lower}'",
                    "confidence_rationale": "Phase 1 virtual alias match",
                    "model_used": kpi.extraction_method,
                    "mapping_status": "auto_accepted",
                }
    # Fuzzy name matching if sequential exact/alias/lineage failed
    for ok in ontology_kpis:
        ok_name = ok.get("name", "")
        if ok_name and _fuzzy_name_match(name_lower, ok_name):
            return {
                "matched_kpi_id": ok["kpi_id"],
                "similarity_score": 0.95,
                "confidence_score": 0.90,
                "similarity_rationale": f"Fuzzy name match: '{ok_name}' (typo tolerance)",
                "confidence_rationale": "Phase 1 fuzzy match",
                "model_used": kpi.extraction_method,
                "mapping_status": "auto_accepted",
            }
        for alias in ok.get("aliases") or []:
            if _fuzzy_name_match(name_lower, str(alias)):
                return {
                    "matched_kpi_id": ok["kpi_id"],
                    "similarity_score": 0.93,
                    "confidence_score": 0.88,
                    "similarity_rationale": f"Fuzzy alias match: '{alias}' (typo tolerance)",
                    "confidence_rationale": "Phase 1 fuzzy alias match",
                    "model_used": kpi.extraction_method,
                    "mapping_status": "pending_review",
                }
    return None


def _needs_sector_fallback(result: dict) -> bool:
    status = result.get("mapping_status")
    conf = float(result.get("confidence_score") or 0.0)
    # Trigger fallback if the subdomain match is not auto_accepted (confidence < 0.90)
    return status == "not_found" or conf < 0.90


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
    import time
    global _phase3_call_counter, _last_phase3_candidates
    embedding_fn = embedding_fn or compute_embedding

    # Normalize the KPI name to strip dimensions, prefixes, and table refs
    original_name = kpi.name
    normalized_name = normalize_kpi_name(kpi.name)
    if normalized_name != kpi.name:
        logger.info("KPI name normalized: '%s' -> '%s'", kpi.name, normalized_name)
        kpi = ExtractedKPI(
            name=normalized_name,
            resolved_lineage=kpi.resolved_lineage,
            aggregation_type=kpi.aggregation_type,
            definition=kpi.definition,
            extraction_method=getattr(kpi, 'extraction_method', None),
            worksheet_id=getattr(kpi, 'worksheet_id', None),
            worksheet_name=getattr(kpi, 'worksheet_name', None),
            mark_type=getattr(kpi, 'mark_type', None),
            calculation_logic=getattr(kpi, 'calculation_logic', None),
            dimensions=getattr(kpi, 'dimensions', []),
            filters=getattr(kpi, 'filters', []),
        )

    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "extracted_kpi": {
            "name": kpi.name,
            "worksheet_id": getattr(kpi, "worksheet_id", None),
            "worksheet_name": getattr(kpi, "worksheet_name", None),
            "resolved_lineage": kpi.resolved_lineage,
            "aggregation_type": kpi.aggregation_type,
            "definition": getattr(kpi, "definition", None),
            "extraction_method": getattr(kpi, "extraction_method", None),
            "mark_type": getattr(kpi, "mark_type", None),
            "calculation_logic": getattr(kpi, "calculation_logic", None),
        },
        "scope": {
            "sector": scope_sector,
            "subdomain": scope_subdomain,
        },
        "cache_duration": 0.0,
        "phases": {
            "phase1": {"executed": False, "matched": False, "result": None, "duration": 0.0},
            "phase2": {"executed": False, "matched": False, "result": None, "top_candidates": [], "duration": 0.0},
            "phase3": {"executed": False, "matched": False, "result": None, "llm_prompt": None, "llm_response": None, "candidates": [], "duration": 0.0}
        },
        "final_result": None,
        "cache_hit": False
    }

    t0 = time.time()
    cached = cache.get(
        kpi.name,
        kpi.resolved_lineage,
        kpi.aggregation_type,
        scope_sector,
        scope_subdomain,
    )
    log_data["cache_duration"] = time.time() - t0

    if cached:
        cached["mapping_status"] = _status_from_confidence(cached.get("confidence_score") or 0.0)
        log_data["cache_hit"] = True
        log_data["final_result"] = cached
        _write_to_ontology_log(log_data)
        return cached

    log_data["phases"]["phase1"]["executed"] = True
    t1 = time.time()
    phase1 = _phase1_match(kpi, ontology_kpis, indexes)
    log_data["phases"]["phase1"]["duration"] = time.time() - t1

    if phase1:
        log_data["phases"]["phase1"]["matched"] = True
        log_data["phases"]["phase1"]["result"] = phase1
        log_data["final_result"] = phase1
        _write_to_ontology_log(log_data)

        cache.set(
            kpi.name,
            kpi.resolved_lineage,
            kpi.aggregation_type,
            phase1,
            sector=scope_sector,
            subdomain=scope_subdomain,
            commit=False,
        )
        return phase1

    # Phase 2: embedding pre-filter; Phase 3 receives all slice candidates >= threshold
    log_data["phases"]["phase2"]["executed"] = True
    t2 = time.time()
    
    text_parts = [kpi.name]
    if kpi.definition:
        text_parts.append(kpi.definition)
    if getattr(kpi, "worksheet_name", None):
        text_parts.append(f"displayed on worksheet {kpi.worksheet_name}")
    if getattr(kpi, "dimensions", None) and len(kpi.dimensions) > 0:
        text_parts.append(f"broken down by {' '.join(kpi.dimensions)}")
    if getattr(kpi, "filters", None) and len(kpi.filters) > 0:
        text_parts.append(f"filtered by {' '.join(kpi.filters)}")
    if kpi.resolved_lineage:
        text_parts.append(" ".join(kpi.resolved_lineage))
        
    kpi_text = " ".join(text_parts)
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

    # Collect top candidates (up to 5) for logging
    top_candidates = []
    for sim, ok in ranked[:5]:
        top_candidates.append({
            "kpi_id": ok.get("kpi_id"),
            "name": ok.get("name"),
            "similarity_score": sim
        })
    log_data["phases"]["phase2"]["top_candidates"] = top_candidates

    best_sim = ranked[0][0] if ranked else 0.0
    best_id = ranked[0][1]["kpi_id"] if ranked else None
    best_name = ranked[0][1].get("name", "") if ranked else ""
    # Always take top N candidates for LLM Phase 3 — no hard cutoff
    eligible = ranked[:PHASE3_TOP_N_CANDIDATES]
    llm_candidates = [
        {
            "kpi_id": ok["kpi_id"],
            "name": ok["name"],
            "score": sim,
            "definition": (ok.get("definition") or "")[:PHASE3_DEFINITION_MAX_CHARS],
        }
        for sim, ok in eligible
    ]

    log_data["phases"]["phase2"]["duration"] = time.time() - t2

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
        log_data["phases"]["phase2"]["matched"] = True
        log_data["phases"]["phase2"]["result"] = result
        log_data["final_result"] = result
        _write_to_ontology_log(log_data)

        cache.set(
            kpi.name,
            kpi.resolved_lineage,
            kpi.aggregation_type,
            result,
            sector=scope_sector,
            subdomain=scope_subdomain,
            commit=False,
        )
        return result

    # Phase 3: LLM judge on top-N candidates in scoped slice (sim >= 0.50)
    log_data["phases"]["phase3"]["executed"] = True
    log_data["phases"]["phase3"]["candidates"] = llm_candidates
    t3 = time.time()

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
        log_data["phases"]["phase3"]["skipped_reason"] = "LLM cap reached or LLM not provided"
        log_data["phases"]["phase3"]["result"] = result
        log_data["final_result"] = result
        log_data["phases"]["phase3"]["duration"] = time.time() - t3
        _write_to_ontology_log(log_data)

        cache.set(
            kpi.name,
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
    if getattr(kpi, "worksheet_name", None):
        report_ctx["worksheet_context"] = kpi.worksheet_name
    if getattr(kpi, "dimensions", None) and len(kpi.dimensions) > 0:
        report_ctx["visual_breakdown_dimensions"] = kpi.dimensions
    if getattr(kpi, "filters", None) and len(kpi.filters) > 0:
        report_ctx["visual_filters"] = kpi.filters
        
    prompt = f"""Judge if report KPI maps to a canonical ontology KPI.
Report KPI: {json.dumps(report_ctx)}
Candidates: {json.dumps(candidates)}
Return JSON: matched_kpi_id (or null), similarity_score, confidence_score, rationale

Use the worksheet_context and visual_filters to guide matching when the raw metric name is generic."""

    log_data["phases"]["phase3"]["llm_prompt"] = prompt

    parsed_result = None
    structured_success = False

    # Try structured output first
    base_llm = getattr(llm, 'base_llm', llm)
    if base_llm and hasattr(base_llm, 'with_structured_output'):
        try:
            structured_llm = base_llm.with_structured_output(Phase3JudgeResult)
            res = structured_llm.invoke(prompt)
            if res:
                parsed_result = {
                    "matched_kpi_id": res.matched_kpi_id,
                    "similarity_score": res.similarity_score,
                    "confidence_score": res.confidence_score,
                    "rationale": res.rationale
                }
                log_data["phases"]["phase3"]["llm_response"] = json.dumps(parsed_result)
                structured_success = True
        except Exception as str_err:
            logger.warning("with_structured_output failed, falling back to string prompt: %s", str_err)

    if not structured_success:
        # Standard raw string prompt fallback
        try:
            res = llm.invoke(prompt)
            content = (res.content or "").strip()
            log_data["phases"]["phase3"]["llm_response"] = content
            
            # Robust JSON extraction from text (looks for first '{' and last '}')
            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                parsed_json = json.loads(json_str)
                parsed_result = {
                    "matched_kpi_id": parsed_json.get("matched_kpi_id"),
                    "similarity_score": float(parsed_json.get("similarity_score", best_sim)),
                    "confidence_score": float(parsed_json.get("confidence_score", best_sim)),
                    "rationale": parsed_json.get("rationale", "LLM judge")
                }
            else:
                raise ValueError("No JSON object found in LLM response")
        except Exception as e:
            logger.error("Phase 3 LLM failed: %s", e)
            log_data["phases"]["phase3"]["error"] = str(e)

    if parsed_result:
        conf = float(parsed_result.get("confidence_score", best_sim))
        result = {
            "matched_kpi_id": parsed_result.get("matched_kpi_id") or (best_id if conf >= 0.70 else None),
            "similarity_score": float(parsed_result.get("similarity_score", best_sim)),
            "confidence_score": conf,
            "similarity_rationale": parsed_result.get("rationale", "LLM judge"),
            "confidence_rationale": "Phase 3 LLM" if structured_success else "Phase 3 LLM fallback",
            "model_used": "llm_judge",
            "mapping_status": _status_from_confidence(conf),
        }
        log_data["phases"]["phase3"]["matched"] = parsed_result.get("matched_kpi_id") is not None
        log_data["phases"]["phase3"]["result"] = result
        log_data["final_result"] = result
    else:
        # Fallback to embedding if LLM completely failed
        result = {
            "matched_kpi_id": best_id,
            "similarity_score": best_sim,
            "confidence_score": best_sim,
            "similarity_rationale": f"Embedding best match '{best_name}'",
            "confidence_rationale": "Phase 3 LLM failed; embedding fallback",
            "model_used": "embedding",
            "mapping_status": _status_from_confidence(best_sim),
        }
        log_data["phases"]["phase3"]["result"] = result
        log_data["final_result"] = result

    log_data["phases"]["phase3"]["duration"] = time.time() - t3
    _write_to_ontology_log(log_data)

    cache.set(
        kpi.name,
        kpi.resolved_lineage,
        kpi.aggregation_type,
        result,
        sector=scope_sector,
        subdomain=scope_subdomain,
        commit=False,
    )
    return result


MAX_CROSS_SUBDOMAIN_CANDIDATES = 10


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
    """Match against subdomain slice first, expand to sector slice on miss.

    Cross-subdomain fallback pre-filters candidates to the top 3 by embedding
    similarity before sending to Phase 3 LLM, managing API budget while
    maximizing recall. Auto-accept threshold is identical (>= 0.90).
    """
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

    # Pre-filter: rank cross-subdomain candidates by embedding similarity,
    # keep only top N to limit LLM Phase 3 budget
    _emb_fn = embedding_fn or compute_embedding
    
    text_parts = [kpi.name]
    if kpi.definition:
        text_parts.append(kpi.definition)
    if getattr(kpi, "worksheet_name", None):
        text_parts.append(f"displayed on worksheet {kpi.worksheet_name}")
    if getattr(kpi, "dimensions", None) and len(kpi.dimensions) > 0:
        text_parts.append(f"broken down by {' '.join(kpi.dimensions)}")
    if getattr(kpi, "filters", None) and len(kpi.filters) > 0:
        text_parts.append(f"filtered by {' '.join(kpi.filters)}")
    if kpi.resolved_lineage:
        text_parts.append(" ".join(kpi.resolved_lineage))
        
    kpi_text = " ".join(text_parts)
    kpi_emb = _emb_fn(kpi_text)
    scored = []
    for ok in sector_only:
        aliases_list = ok.get("aliases") or []
        ok_text = f"{ok.get('name', '')} {ok.get('definition', '')} {' '.join(aliases_list)}"
        ok_emb = ok.get("embedding")
        if ok_emb is None:
            ok_emb = _emb_fn(ok_text)
        sim = cosine_similarity(kpi_emb, ok_emb)
        scored.append((sim, ok))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_sector = [ok for _, ok in scored[:MAX_CROSS_SUBDOMAIN_CANDIDATES]]

    if not top_sector:
        return result

    sec_indexes = build_ontology_match_indexes(top_sector)
    sector_result = match_kpi_to_ontology(
        kpi,
        top_sector,
        cache,
        llm,
        embedding_fn,
        indexes=sec_indexes,
        scope_sector=sector,
        scope_subdomain="__sector__",
    )
    
    # Calculate actual confidences (treating not_found as 0.0 confidence)
    sub_conf = 0.0 if result.get("mapping_status") == "not_found" else float(result.get("confidence_score") or 0.0)
    sec_conf = 0.0 if sector_result.get("mapping_status") == "not_found" else float(sector_result.get("confidence_score") or 0.0)
    
    if sec_conf > sub_conf:
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
    row.is_dynamic = getattr(kpi, "is_dynamic", False)
    row.ontology_version = ONTOLOGY_VERSION
    row.computed_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(row)
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
        # Reset embedding failure counter so Azure gets a fresh chance each run
        from app.services.ontology.embedding_service import reset_embedding_failures
        reset_embedding_failures()

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

    # Batch embed all dashboard KPIs to minimize individual API roundtrips
    kpis_to_embed = []
    for ws_name, kpis in per_ws.items():
        if ws_name not in dash_ws_names:
            continue
        kpis_to_embed.extend(kpis)
    kpis_to_embed.extend(source_d)

    if kpis_to_embed:
        from app.services.ontology.embedding_service import compute_embeddings_batch
        texts_to_embed = []
        for k in kpis_to_embed:
            norm_name = normalize_kpi_name(k.name)
            parts = [norm_name]
            if k.definition:
                parts.append(k.definition)
            if getattr(k, "worksheet_name", None):
                parts.append(f"displayed on worksheet {k.worksheet_name}")
            if getattr(k, "dimensions", None) and len(k.dimensions) > 0:
                parts.append(f"broken down by {' '.join(k.dimensions)}")
            if getattr(k, "filters", None) and len(k.filters) > 0:
                parts.append(f"filtered by {' '.join(k.filters)}")
            if k.resolved_lineage:
                parts.append(" ".join(k.resolved_lineage))
            texts_to_embed.append(" ".join(parts))
        logger.info("Batch embedding %d dashboard KPIs...", len(texts_to_embed))
        compute_embeddings_batch(texts_to_embed)

    report_id = str(dashboard_id)
    count = 0
    matches_to_persist = []
    # Defer write-flushing during Phase 3 LLM and Phase 2 embedding calls to avoid database write locks
    with db.no_autoflush:
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
                matches_to_persist.append((kpi, match))
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
            matches_to_persist.append((kpi, match))
            count += 1

    if matches_to_persist:
        for kpi, match in matches_to_persist:
            persist_mapping(db, report_id, kpi, match, commit=False)
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
        # Batch embed all orphan KPIs to minimize individual API roundtrips
        orphan_kpis_to_embed = []
        for ws_name, kpis in per_ws.items():
            if ws_name in dash_ws_names:
                continue
            for kpi in kpis:
                if kpi.worksheet_id == "orphan":
                    orphan_kpis_to_embed.append(kpi)
        if orphan_kpis_to_embed:
            from app.services.ontology.embedding_service import compute_embeddings_batch
            texts_to_embed = []
            for k in orphan_kpis_to_embed:
                norm_name = normalize_kpi_name(k.name)
                parts = [norm_name]
                if k.definition:
                    parts.append(k.definition)
                if getattr(k, "worksheet_name", None):
                    parts.append(f"displayed on worksheet {k.worksheet_name}")
                if getattr(k, "dimensions", None) and len(k.dimensions) > 0:
                    parts.append(f"broken down by {' '.join(k.dimensions)}")
                if getattr(k, "filters", None) and len(k.filters) > 0:
                    parts.append(f"filtered by {' '.join(k.filters)}")
                if k.resolved_lineage:
                    parts.append(" ".join(k.resolved_lineage))
                texts_to_embed.append(" ".join(parts))
            logger.info("Batch embedding %d orphan KPIs...", len(texts_to_embed))
            compute_embeddings_batch(texts_to_embed)

        report_id = str(first_dash.id)
        orphan_count = 0
        orphan_matches_to_persist = []
        with db.no_autoflush:
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
                    orphan_matches_to_persist.append((kpi, match))
                    orphan_count += 1
        if orphan_matches_to_persist:
            for kpi, match in orphan_matches_to_persist:
                persist_mapping(db, report_id, kpi, match, commit=False)
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


import queue
import threading

_ontology_queue = queue.Queue()
_worker_thread = None

def _ontology_worker():
    logger.info("Ontology matching background worker thread started.")
    while True:
        try:
            job = _ontology_queue.get()
            if job is None:
                break
            metadata, col_to_table_map = job
            logger.info("Processing background ontology matching for workbook: %s", metadata.source_file)
            
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                process_workbook_ontology(metadata, db, col_to_table_map)
                logger.info("Background ontology matching completed for workbook: %s", metadata.source_file)
            except Exception as e:
                logger.error("Error processing ontology in background for %s: %s", metadata.source_file, e, exc_info=True)
            finally:
                db.close()
                _ontology_queue.task_done()
        except Exception as e:
            logger.error("Fatal error in ontology worker loop: %s", e)

def enqueue_ontology_matching(metadata, col_to_table_map):
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_ontology_worker, daemon=True, name="OntologyWorker")
        _worker_thread.start()
    
    _ontology_queue.put((metadata, col_to_table_map))
    logger.info("Workbook %s enqueued for background ontology matching.", metadata.source_file)

