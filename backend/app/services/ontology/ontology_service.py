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
    is_using_hash_fallback,
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


AUTO_APPROVE_THRESHOLD = float(os.getenv("GOVERNANCE_AUTO_APPROVE_THRESHOLD", "0.95"))
REVIEW_THRESHOLD = float(os.getenv("GOVERNANCE_REVIEW_THRESHOLD", "0.80"))


def _status_from_confidence(confidence: float) -> str:
    if confidence >= AUTO_APPROVE_THRESHOLD:
        return "auto_accepted"
    if confidence >= REVIEW_THRESHOLD:
        return "pending_review"
    return "not_found"


def _classify_mapping_type(rationale: str, confidence: float) -> str:
    """Derive a structured mapping_type from the phase rationale string."""
    r = (rationale or "").lower()
    if "exact" in r and "match" in r:
        return "exact"
    if "alias" in r:
        return "alias"
    if "lineage" in r and "agg" in r:
        return "formula_equivalent"
    if "fuzzy" in r:
        return "alias"  # fuzzy is a variant of alias matching
    if "embedding" in r or "llm" in r or "phase 2" in r or "phase 3" in r:
        return "semantic_match"
    if confidence < REVIEW_THRESHOLD:
        return "no_match"
    return "semantic_match"


def _agg_key(aggregation: str) -> str:
    agg = (aggregation or "UNKNOWN").upper()
    if agg == "AVERAGE":
        return "AVG"
    if agg == "CNT":
        return "COUNT"
    # COUNTD stays COUNTD so distinct-count lineage keys stay distinct from COUNT
    return agg


# Additive totals/counts must not auto-map to averages or rates (and vice versa).
_AGG_FAMILY_AVERAGE = frozenset({"AVG", "MEDIAN", "AVERAGE"})
_AGG_FAMILY_ADDITIVE = frozenset({"SUM", "COUNT", "COUNTD", "CNT"})
_AGG_FAMILY_RATE = frozenset({"PCT", "RATIO"})
_AGG_FAMILY_TEMPORAL = frozenset({"MONTH-TRUNC", "YEAR-TRUNC", "DATETRUNC", "QUARTER-TRUNC"})

_NON_MAPPABLE_NAME_RE = re.compile(
    r"^(?:"
    r"month-trunc\b|year-trunc\b|datetrunc\b|"
    r"last\s+\d+\s+years?\b|"
    r"claim number$|"
    r"select kpi$|"
    r"currency$|"
    r"accelerator log$"
    r")",
    re.IGNORECASE,
)
_DERIVED_HELPER_RE = re.compile(
    r"^(Rank|Performance\s+Level)\s*\|\s*",
    re.IGNORECASE,
)

_DEBUG_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
    "debug-482d96.log",
)


def _agent_debug_log(hypothesis_id: str, location: str, message: str, data: dict | None = None) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "482d96",
            "runId": "post-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(datetime.utcnow().timestamp() * 1000),
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion


_OPAQUE_CALC_RE = re.compile(
    r"(?:^|\b)(?:sum|avg|count|countd|min|max)?\s*of\s*calculation_\d+\b|^calculation_\d+\b",
    re.IGNORECASE,
)
_MONEY_HINT_RE = re.compile(
    r"\b(amount|budget|bugdet|bdgt|premium|revenue|sales|invoice_amount|achieved_)\b",
    re.IGNORECASE,
)


def is_opaque_calculation_kpi(kpi: ExtractedKPI, *, original_name: str | None = None) -> bool:
    """Tableau internal Calculation_<id> measures lack business meaning for mapping."""
    text = f"{original_name or ''} {kpi.name or ''}".strip()
    return bool(_OPAQUE_CALC_RE.search(text))


def _looks_like_money_kpi(kpi: ExtractedKPI | None, *, original_name: str | None = None) -> bool:
    if kpi is None:
        return False
    text = " ".join(
        [
            original_name or "",
            kpi.name or "",
            getattr(kpi, "definition", None) or "",
            " ".join(kpi.resolved_lineage or []),
        ]
    )
    return bool(_MONEY_HINT_RE.search(text))


def aggregations_compatible(
    report_agg: str | None,
    ontology_agg: str | None,
    *,
    report_kpi: ExtractedKPI | None = None,
    original_name: str | None = None,
) -> bool:
    """Return False when report vs ontology aggregations are mathematically incompatible.

    SUM↔PCT is allowed only when the report looks like a true ratio formula
    (e.g. SUM(losses)/SUM(premium)). Plain SUM(field) must not map to PCT rates.
    Money SUM totals must not map to COUNT ontology KPIs.
    """
    r = _agg_key(report_agg or "UNKNOWN")
    o = _agg_key(ontology_agg or "UNKNOWN")
    if r in ("UNKNOWN", "NONE", "") or o in ("UNKNOWN", "NONE", ""):
        return True
    if r in _AGG_FAMILY_TEMPORAL and o not in _AGG_FAMILY_TEMPORAL:
        return False
    # Totals/averages must not cross-map
    if r in _AGG_FAMILY_AVERAGE and o in _AGG_FAMILY_ADDITIVE:
        return False
    if r in _AGG_FAMILY_ADDITIVE and o in _AGG_FAMILY_AVERAGE:
        return False
    # Counts must not map to rates
    count_like = frozenset({"COUNT", "COUNTD", "CNT"})
    if r in count_like and o in _AGG_FAMILY_RATE:
        return False
    if r in _AGG_FAMILY_RATE and o in count_like:
        return False
    # SUM totals must not map to PCT unless formula/name indicates a ratio
    if r == "SUM" and o in _AGG_FAMILY_RATE and not _looks_like_ratio_kpi(report_kpi):
        return False
    if r in _AGG_FAMILY_RATE and o == "SUM" and not _looks_like_ratio_kpi(report_kpi):
        return False
    # Dollar/budget SUM must not map to COUNT KPIs (e.g. Achieved_Cross_Sell → LOB Cross-sell COUNT)
    if r == "SUM" and o in count_like and _looks_like_money_kpi(report_kpi, original_name=original_name):
        return False
    return True


def _looks_like_ratio_kpi(kpi: ExtractedKPI | None) -> bool:
    if kpi is None:
        return False
    text = " ".join(
        [
            kpi.name or "",
            getattr(kpi, "definition", None) or "",
            getattr(kpi, "calculation_logic", None) or "",
        ]
    ).lower()
    if "/" in text or "÷" in text:
        return True
    return bool(re.search(r"\b(ratio|%|pct|percent|per\s+exposure)\b", text))


_BUDGET_TOKEN_RE = re.compile(r"\b(budget|bugdet|bdgt)\b", re.I)
_BUDGET_FALSE_FRIEND_ONTO_RE = re.compile(
    r"premium\s+opportunity|rounding\s+premium|renewal\s+premium|"
    r"marketing\s+spend|net\s+sales|"
    r"\blob\s+cross[-\s]?sell\b|cross\s+sell\s+total",
    re.I,
)

# Report-token → forbidden ontology-token pairs (business false friends)
_SEMANTIC_CONFLICTS: list[tuple[re.Pattern[str], re.Pattern[str], str]] = [
    (
        re.compile(r"invoice", re.I),
        re.compile(r"\b(outbound\s+call|call\s+attempt|calls?\b|mail|audit)", re.I),
        "invoice count must not map to call/mail/audit KPIs",
    ),
    (
        re.compile(r"meeting", re.I),
        re.compile(
            r"scheduled\s+calls|outbound\s+call|call\s+attempt|"
            r"no of mails|\bmails?\b|\bmail\b",
            re.I,
        ),
        "meeting count must not map to scheduled/outbound call or mail KPIs",
    ),
    (
        re.compile(r"claim[_\s]?amt|claim\s+amount|total\s+claim", re.I),
        re.compile(r"settlement\s+amount|disputed\s+amount", re.I),
        "claim amount must not map to settlement/disputed amount",
    ),
    (
        re.compile(r"household[_\s]?income", re.I),
        re.compile(r"loss\s+severity|claims?\s+severity|severity", re.I),
        "household income must not map to claim severity KPIs",
    ),
    (
        re.compile(r"household[_\s]?income", re.I),
        re.compile(
            r"account\s+size|average\s+premium\s+per\s+(?:customer|policy|account)|"
            r"avg\s+premium\s+per|average\s+account",
            re.I,
        ),
        "household income must not map to account size / average premium KPIs",
    ),
    (
        re.compile(
            r"revenue_amount|revenue\s+amount|gcrm_opportunity|"
            r"open\s+oppty|opportunit(?:y|ies).{0,40}revenue|revenue.{0,40}opportunit",
            re.I,
        ),
        re.compile(r"\b(net\s+sales|total\s+marketing\s+spend|marketing\s+spend)\b", re.I),
        "opportunity/pipeline revenue must not map to net sales or marketing spend",
    ),
    (
        re.compile(r"\b(opportunity|opportunities|revenue\s+amount)\b", re.I),
        re.compile(r"\b(open\s+activities|top of funnel)\b", re.I),
        "opportunity/revenue must not map to funnel/activity KPIs",
    ),
    (
        re.compile(r"\bopportunit", re.I),
        re.compile(r"quote\s+count|\bquotes?\b", re.I),
        "opportunity count must not map to quote count KPIs",
    ),
    (
        re.compile(r"\bstage\b", re.I),
        re.compile(r"cancellation\s+reason", re.I),
        "sales stage distribution must not map to cancellation reason",
    ),
]


def _report_onto_texts(
    kpi: ExtractedKPI, ok: dict, *, original_name: str | None = None
) -> tuple[str, str]:
    report_text = " ".join(
        [
            original_name or "",
            kpi.name or "",
            getattr(kpi, "definition", None) or "",
            " ".join(kpi.resolved_lineage or []),
            getattr(kpi, "worksheet_name", None) or "",
        ]
    )
    onto_text = " ".join(
        [
            str(ok.get("name") or ""),
            str(ok.get("definition") or ""),
            " ".join(str(a) for a in (ok.get("aliases") or [])),
        ]
    )
    return report_text, onto_text


def has_semantic_conflict(kpi: ExtractedKPI, ok: dict, *, original_name: str | None = None) -> str | None:
    """Return conflict reason if report and ontology KPIs are known false friends."""
    report_text, onto_text = _report_onto_texts(kpi, ok, original_name=original_name)

    # H13: budget/bugdet/bdgt must not map to premium opportunity / marketing spend / net sales
    if _BUDGET_TOKEN_RE.search(report_text) and _BUDGET_FALSE_FRIEND_ONTO_RE.search(onto_text):
        if not _BUDGET_TOKEN_RE.search(onto_text):
            return (
                "budget must not map to premium opportunity, marketing spend, "
                "net sales, or non-budget cross-sell KPIs"
            )

    for report_re, onto_re, reason in _SEMANTIC_CONFLICTS:
        if report_re.search(report_text) and onto_re.search(onto_text):
            return reason
    return None


def is_non_mappable_kpi(kpi: ExtractedKPI, *, original_name: str | None = None) -> bool:
    """Axes, filters, opaque Tableau calcs, and identifiers that must not map."""
    if _agg_key(kpi.aggregation_type) in _AGG_FAMILY_TEMPORAL:
        return True
    name = (kpi.name or "").strip()
    if _NON_MAPPABLE_NAME_RE.match(name):
        return True
    if is_opaque_calculation_kpi(kpi, original_name=original_name):
        return True
    return False


def is_derived_visual_helper(raw_name: str | None) -> bool:
    """Rank / Performance Level visuals are derived helpers, not canonical metrics."""
    return bool(raw_name and _DERIVED_HELPER_RE.match(raw_name.strip()))


def _not_found_result(kpi: ExtractedKPI, rationale: str) -> dict:
    return {
        "matched_kpi_id": None,
        "similarity_score": 0.0,
        "confidence_score": 0.0,
        "similarity_rationale": rationale,
        "confidence_rationale": rationale,
        "model_used": getattr(kpi, "extraction_method", None) or "quality_gate",
        "mapping_status": "not_found",
        "mapping_type": "no_match",
        "warnings": [rationale],
    }


def apply_mapping_quality_gates(
    kpi: ExtractedKPI,
    result: dict,
    ontology_by_id: dict[str, dict] | None = None,
    *,
    original_name: str | None = None,
) -> dict:
    """Post-match gates: reject non-KPIs, block agg conflicts, demote derived helpers."""
    if not result:
        return result

    if is_non_mappable_kpi(kpi, original_name=original_name):
        reason = (
            "Quality gate: opaque Tableau Calculation_* lacks business meaning"
            if is_opaque_calculation_kpi(kpi, original_name=original_name)
            else "Quality gate: non-mappable axis/filter/identifier"
        )
        gated = _not_found_result(kpi, reason)
        _agent_debug_log(
            "H8" if "opaque" in reason else "H4",
            "ontology_service.apply_mapping_quality_gates",
            "Rejected non-mappable KPI",
            {"kpi": original_name or kpi.name, "agg": kpi.aggregation_type, "reason": reason},
        )
        return gated

    matched_id = result.get("matched_kpi_id")
    ok = None
    if matched_id and ontology_by_id:
        ok = ontology_by_id.get(str(matched_id))

    if matched_id and not ok:
        # LLM returned an ID not in the current ontology slice (cross-scope or hallucinated);
        # gate checks cannot run — demote to pending_review, cap confidence.
        _agent_debug_log(
            "H12",
            "ontology_service.apply_mapping_quality_gates",
            "matched_kpi_id not in ontology_by_id — gates cannot verify, demoting",
            {"kpi": original_name or kpi.name, "matched_id": matched_id},
        )
        result = dict(result)
        result["mapping_status"] = "pending_review"
        result["confidence_score"] = min(float(result.get("confidence_score") or 0.0), 0.79)
        result["warnings"] = list(result.get("warnings") or []) + [
            "Phase 3 matched a KPI ID absent from the ontology slice — cannot verify gates"
        ]
        return result

    if ok and not aggregations_compatible(
        kpi.aggregation_type,
        ok.get("aggregation_type"),
        report_kpi=kpi,
        original_name=original_name,
    ):
        _agent_debug_log(
            "H9",
            "ontology_service.apply_mapping_quality_gates",
            "Blocked aggregation-incompatible match",
            {
                "kpi": original_name or kpi.name,
                "report_agg": kpi.aggregation_type,
                "onto": ok.get("name"),
                "onto_agg": ok.get("aggregation_type"),
                "money_hint": _looks_like_money_kpi(kpi, original_name=original_name),
                "prior_status": result.get("mapping_status"),
                "prior_conf": result.get("confidence_score"),
            },
        )
        return _not_found_result(
            kpi,
            f"Quality gate: aggregation mismatch "
            f"({_agg_key(kpi.aggregation_type)} vs {_agg_key(ok.get('aggregation_type'))} "
            f"for '{ok.get('name')}')",
        )

    if ok:
        conflict = has_semantic_conflict(kpi, ok, original_name=original_name)
        if conflict:
            hyp = "H13" if "budget" in conflict.lower() else "H11"
            _agent_debug_log(
                hyp,
                "ontology_service.apply_mapping_quality_gates",
                "Blocked semantic-conflict match",
                {"kpi": original_name or kpi.name, "onto": ok.get("name"), "reason": conflict},
            )
            return _not_found_result(kpi, f"Quality gate: semantic conflict — {conflict}")

    raw = original_name or kpi.name
    if is_derived_visual_helper(raw) and result.get("matched_kpi_id"):
        conf = min(float(result.get("confidence_score") or 0.0), 0.79)
        result = dict(result)
        result["confidence_score"] = conf
        result["mapping_status"] = "pending_review"
        result["warnings"] = list(result.get("warnings") or []) + [
            "Derived Rank/Performance Level helper — not auto-accepted"
        ]
        result["confidence_rationale"] = (
            (result.get("confidence_rationale") or "") + " | demoted: derived visual helper"
        ).strip(" |")
        _agent_debug_log(
            "H5",
            "ontology_service.apply_mapping_quality_gates",
            "Demoted derived visual helper",
            {"kpi": raw, "onto": (ok or {}).get("name"), "conf": conf},
        )

    # Never auto-accept fuzzy / weak similarity matches
    rationale = (result.get("similarity_rationale") or "").lower()
    if result.get("mapping_status") == "auto_accepted" and (
        "fuzzy" in rationale or float(result.get("similarity_score") or 0) < 0.98
    ):
        if "exact name match" not in rationale and "lineage+agg" not in rationale:
            result = dict(result)
            result["mapping_status"] = "pending_review"
            result["confidence_score"] = min(float(result.get("confidence_score") or 0.0), 0.88)
            result["warnings"] = list(result.get("warnings") or []) + [
                "Demoted: fuzzy/weak match cannot auto-accept"
            ]
            _agent_debug_log(
                "H7",
                "ontology_service.apply_mapping_quality_gates",
                "Demoted fuzzy/weak auto-accept",
                {"kpi": raw, "onto": (ok or {}).get("name"), "rationale": rationale[:80]},
            )

    return result


def _lineage_agg_match(kpi: ExtractedKPI, ok: dict) -> bool:
    rep = ok.get("representative_lineage") or []
    if not rep or not kpi.resolved_lineage:
        return False
    return sorted(rep) == sorted(kpi.resolved_lineage) and _agg_key(kpi.aggregation_type) == _agg_key(
        ok.get("aggregation_type") or "UNKNOWN"
    )


def _normalize_formula_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[\[\]\"']", "", text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned)
    tokens = sorted(cleaned.split())
    return " ".join(tokens)


def _compute_formula_similarity(kpi: ExtractedKPI, ok: dict) -> float:
    """Compute token-normalized SequenceMatcher similarity between KPI formula/lineage strings.

    Returns 0.0 if either side has no formula-like content.
    """
    kpi_formula = getattr(kpi, "calculation_logic", None) or ""
    if not kpi_formula and kpi.resolved_lineage:
        kpi_formula = " ".join(sorted(kpi.resolved_lineage))

    ok_lineage = ok.get("representative_lineage") or []
    ok_formula = " ".join(sorted(ok_lineage)) if ok_lineage else ""

    if not kpi_formula.strip() or not ok_formula.strip():
        return 0.0

    norm_kpi = _normalize_formula_text(kpi_formula)
    norm_ok = _normalize_formula_text(ok_formula)
    return SequenceMatcher(None, norm_kpi, norm_ok).ratio()


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


def _phase1_candidate(
    kpi: ExtractedKPI,
    ok: dict,
    *,
    similarity: float,
    confidence: float,
    sim_rationale: str,
    conf_rationale: str,
    mapping_status: str,
) -> dict | None:
    """Build a Phase 1 result only when aggregations are compatible."""
    if not aggregations_compatible(
        kpi.aggregation_type, ok.get("aggregation_type"), report_kpi=kpi
    ):
        _agent_debug_log(
            "H9",
            "ontology_service._phase1_candidate",
            "Skipped Phase 1 candidate due to aggregation mismatch",
            {
                "kpi": kpi.name,
                "report_agg": kpi.aggregation_type,
                "onto": ok.get("name"),
                "onto_agg": ok.get("aggregation_type"),
                "money_hint": _looks_like_money_kpi(kpi),
                "rationale": sim_rationale,
            },
        )
        return None
    conflict = has_semantic_conflict(kpi, ok)
    if conflict:
        _agent_debug_log(
            "H11",
            "ontology_service._phase1_candidate",
            "Skipped Phase 1 candidate due to semantic conflict",
            {"kpi": kpi.name, "onto": ok.get("name"), "reason": conflict},
        )
        return None
    return {
        "matched_kpi_id": ok["kpi_id"],
        "similarity_score": similarity,
        "confidence_score": confidence,
        "similarity_rationale": sim_rationale,
        "confidence_rationale": conf_rationale,
        "model_used": kpi.extraction_method,
        "mapping_status": mapping_status,
    }


def _phase1_match(
    kpi: ExtractedKPI,
    ontology_kpis: list[dict],
    indexes: dict | None,
) -> dict | None:
    if is_non_mappable_kpi(kpi):
        _agent_debug_log(
            "H8" if is_opaque_calculation_kpi(kpi) else "H4",
            "ontology_service._phase1_match",
            "Phase 1 skipped non-mappable KPI",
            {"kpi": kpi.name, "agg": kpi.aggregation_type, "opaque": is_opaque_calculation_kpi(kpi)},
        )
        return None

    name_lower = kpi.name.strip().lower()
    if indexes:
        ok = indexes["name"].get(name_lower)
        if ok:
            hit = _phase1_candidate(
                kpi, ok,
                similarity=1.0, confidence=1.0,
                sim_rationale="Exact name match",
                conf_rationale="Phase 1 exact match",
                mapping_status="auto_accepted",
            )
            if hit:
                return hit
        ok = indexes["alias"].get(name_lower)
        if ok:
            hit = _phase1_candidate(
                kpi, ok,
                similarity=0.98, confidence=0.95,
                sim_rationale=f"Alias match: {name_lower}",
                conf_rationale="Phase 1 alias match",
                mapping_status="auto_accepted",
            )
            if hit:
                _agent_debug_log(
                    "H2",
                    "ontology_service._phase1_match",
                    "Phase 1 alias match accepted after agg gate",
                    {"kpi": kpi.name, "onto": ok.get("name"), "agg": kpi.aggregation_type},
                )
                return hit
        if kpi.resolved_lineage:
            lineage_key = (tuple(sorted(kpi.resolved_lineage)), _agg_key(kpi.aggregation_type))
            ok = indexes["lineage"].get(lineage_key)
            if ok:
                hit = _phase1_candidate(
                    kpi, ok,
                    similarity=1.0, confidence=1.0,
                    sim_rationale="Phase 1 lineage+agg match",
                    conf_rationale="Phase 1 lineage+agg match",
                    mapping_status="auto_accepted",
                )
                if hit:
                    return hit

        # Virtual alias matching
        v_aliases = _generate_virtual_aliases(name_lower, getattr(kpi, "worksheet_name", None))
        for v_alias in v_aliases:
            ok = indexes["alias"].get(v_alias) or indexes["name"].get(v_alias)
            if ok:
                hit = _phase1_candidate(
                    kpi, ok,
                    similarity=0.95, confidence=0.90,
                    sim_rationale=f"Virtual alias match: '{v_alias}'",
                    conf_rationale="Phase 1 virtual alias match",
                    mapping_status="auto_accepted",
                )
                if hit:
                    return hit

        # Fuzzy name matching if indexed exact/alias/lineage failed
        for ok in ontology_kpis:
            ok_name = ok.get("name", "")
            if ok_name and _fuzzy_name_match(name_lower, ok_name):
                hit = _phase1_candidate(
                    kpi, ok,
                    similarity=0.95, confidence=0.90,
                    sim_rationale=f"Fuzzy name match: '{ok_name}' (typo tolerance)",
                    conf_rationale="Phase 1 fuzzy match",
                    mapping_status="pending_review",
                )
                if hit:
                    return hit
            for alias in ok.get("aliases") or []:
                if _fuzzy_name_match(name_lower, str(alias)):
                    hit = _phase1_candidate(
                        kpi, ok,
                        similarity=0.93, confidence=0.88,
                        sim_rationale=f"Fuzzy alias match: '{alias}' (typo tolerance)",
                        conf_rationale="Phase 1 fuzzy alias match",
                        mapping_status="pending_review",
                    )
                    if hit:
                        return hit
        return None

    for ok in ontology_kpis:
        if ok.get("name", "").strip().lower() == name_lower:
            hit = _phase1_candidate(
                kpi, ok,
                similarity=1.0, confidence=1.0,
                sim_rationale="Exact name match",
                conf_rationale="Phase 1 exact match",
                mapping_status="auto_accepted",
            )
            if hit:
                return hit
        for alias in ok.get("aliases") or []:
            if str(alias).strip().lower() == name_lower:
                hit = _phase1_candidate(
                    kpi, ok,
                    similarity=0.98, confidence=0.95,
                    sim_rationale=f"Alias match: {alias}",
                    conf_rationale="Phase 1 alias match",
                    mapping_status="auto_accepted",
                )
                if hit:
                    return hit
    for ok in ontology_kpis:
        if _lineage_agg_match(kpi, ok):
            hit = _phase1_candidate(
                kpi, ok,
                similarity=1.0, confidence=1.0,
                sim_rationale="Phase 1 lineage+agg match",
                conf_rationale="Phase 1 lineage+agg match",
                mapping_status="auto_accepted",
            )
            if hit:
                return hit

    # Virtual alias fallback without index
    v_aliases = _generate_virtual_aliases(name_lower, getattr(kpi, "worksheet_name", None))
    for ok in ontology_kpis:
        for alias in [ok.get("name", "")] + (ok.get("aliases") or []):
            alias_lower = str(alias).strip().lower()
            if alias_lower in v_aliases:
                hit = _phase1_candidate(
                    kpi, ok,
                    similarity=0.95, confidence=0.90,
                    sim_rationale=f"Virtual alias match: '{alias_lower}'",
                    conf_rationale="Phase 1 virtual alias match",
                    mapping_status="auto_accepted",
                )
                if hit:
                    return hit
    # Fuzzy name matching if sequential exact/alias/lineage failed
    for ok in ontology_kpis:
        ok_name = ok.get("name", "")
        if ok_name and _fuzzy_name_match(name_lower, ok_name):
            hit = _phase1_candidate(
                kpi, ok,
                similarity=0.95, confidence=0.90,
                sim_rationale=f"Fuzzy name match: '{ok_name}' (typo tolerance)",
                conf_rationale="Phase 1 fuzzy match",
                mapping_status="pending_review",
            )
            if hit:
                return hit
        for alias in ok.get("aliases") or []:
            if _fuzzy_name_match(name_lower, str(alias)):
                hit = _phase1_candidate(
                    kpi, ok,
                    similarity=0.93, confidence=0.88,
                    sim_rationale=f"Fuzzy alias match: '{alias}' (typo tolerance)",
                    conf_rationale="Phase 1 fuzzy alias match",
                    mapping_status="pending_review",
                )
                if hit:
                    return hit
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
    ontology_by_id = {str(ok.get("kpi_id")): ok for ok in ontology_kpis if ok.get("kpi_id")}

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

    if is_non_mappable_kpi(kpi, original_name=original_name):
        reason = (
            "Quality gate: opaque Tableau Calculation_* lacks business meaning"
            if is_opaque_calculation_kpi(kpi, original_name=original_name)
            else "Quality gate: non-mappable axis/filter/identifier"
        )
        early = _not_found_result(kpi, reason)
        _agent_debug_log(
            "H8" if "opaque" in reason else "H4",
            "ontology_service.match_kpi_to_ontology",
            "Early not_found for non-mappable KPI",
            {"kpi": original_name, "agg": kpi.aggregation_type, "reason": reason},
        )
        return early

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
        cached = apply_mapping_quality_gates(
            kpi, cached, ontology_by_id, original_name=original_name
        )
        log_data["cache_hit"] = True
        log_data["final_result"] = cached
        _write_to_ontology_log(log_data)
        return cached

    log_data["phases"]["phase1"]["executed"] = True
    t1 = time.time()
    phase1 = _phase1_match(kpi, ontology_kpis, indexes)
    log_data["phases"]["phase1"]["duration"] = time.time() - t1

    if phase1:
        phase1 = apply_mapping_quality_gates(
            kpi, phase1, ontology_by_id, original_name=original_name
        )
        log_data["phases"]["phase1"]["matched"] = bool(phase1.get("matched_kpi_id"))
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
        # CRITICAL: If using hash fallback, embeddings are NOT semantic.
        # Hash-based similarity scores are meaningless noise — never auto-accept.
        if is_using_hash_fallback():
            logger.warning(
                "Phase 2 would auto-accept '%s' (sim=%.3f) but hash fallback is active. "
                "Forcing pending_review to prevent garbage auto-approval.",
                kpi.name, best_sim,
            )
            result = {
                "matched_kpi_id": best_id,
                "similarity_score": best_sim,
                "confidence_score": 0.50,  # Cap confidence — hash similarity is unreliable
                "similarity_rationale": f"Embedding match to '{best_name}' (HASH FALLBACK — not semantic)",
                "confidence_rationale": "Phase 2b hash fallback — auto-accept blocked",
                "model_used": "hash_fallback",
                "mapping_status": "pending_review",
                "mapping_type": "no_match",
                "alternative_candidates": llm_candidates[:5],
            }
        else:
            # Differentiate confidence from similarity:
            # Embedding similarity 0.95+ is strong but confidence should factor in
            # whether we have supporting evidence (lineage, formula, etc.)
            has_lineage = bool(kpi.resolved_lineage)
            has_definition = bool(kpi.definition)
            evidence_bonus = 0.0
            if has_lineage:
                evidence_bonus += 0.02
            if has_definition:
                evidence_bonus += 0.01
            conf = min(1.0, best_sim * 0.95 + evidence_bonus)  # Slight discount from raw similarity

            result = {
                "matched_kpi_id": best_id,
                "similarity_score": best_sim,
                "confidence_score": conf,
                "similarity_rationale": f"Embedding match to '{best_name}'",
                "confidence_rationale": "Phase 2b embedding auto-accept",
                "model_used": "embedding",
                "mapping_status": _status_from_confidence(conf),
                "mapping_type": "semantic_match",
                "alternative_candidates": llm_candidates[:5],
            }
        log_data["phases"]["phase2"]["matched"] = True
        result = apply_mapping_quality_gates(
            kpi, result, ontology_by_id, original_name=original_name
        )
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
        # If hash fallback is active, cap confidence to prevent garbage auto-accept
        if is_using_hash_fallback():
            conf = min(best_sim, 0.50)
            model_used = "hash_fallback"
        else:
            conf = best_sim
            model_used = "embedding_fallback"
        status = _status_from_confidence(conf)
        if model_used == "embedding_fallback" and conf >= 0.70:
            status = "pending_review"

        result = {
            "matched_kpi_id": best_id if conf >= 0.70 else None,
            "similarity_score": best_sim,
            "confidence_score": conf,
            "similarity_rationale": "LLM cap reached; embedding-only decision",
            "confidence_rationale": "Phase 3 skipped" + (" (hash fallback)" if is_using_hash_fallback() else ""),
            "model_used": model_used,
            "mapping_status": status,
            "mapping_type": _classify_mapping_type("embedding", conf),
            "alternative_candidates": llm_candidates[:5],
        }
        result = apply_mapping_quality_gates(
            kpi, result, ontology_by_id, original_name=original_name
        )
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
        
    prompt = f"""You are an Enterprise KPI Governance Expert.
Compare the incoming Report Metric with the candidate Canonical Ontology KPIs.
Your job is precise governance matching — NOT nearest-neighbor guessing.

Report KPI Context:
{json.dumps(report_ctx, indent=2)}

Canonical Candidates:
{json.dumps(candidates, indent=2)}

Matching Guidelines:
1. Compare mathematical intent, calculation logic, aggregation, field lineage, AND business meaning.
2. Ignore minor visual naming variations (e.g., "Total Premium b" vs "Premium") only when the underlying measure is the same.
3. Use worksheet_context and visual_filters only as supporting context — never as the sole reason to force a match to an unrelated canonical KPI.
4. If no candidate genuinely matches the business logic, set matched_kpi_id to null and confidence_score below 0.80. Do NOT pick the "closest cousin."
5. HARD RULE — Aggregation compatibility:
   - Do NOT map SUM/COUNT/COUNTD totals to AVG severity/average KPIs.
   - Do NOT map COUNT/COUNTD claim volumes to PCT frequency/rate KPIs.
   - Do NOT map money/budget SUM totals to COUNT ontology KPIs.
   - Do NOT map date axes (MONTH-TRUNC), filters, or identifiers (e.g. Claim Number) to any KPI.
6. Rank | X and Performance Level | X are derived helpers — only match with confidence_score below 0.80.
7. HARD RULE — Semantic false friends (always reject; matched_kpi_id=null, confidence_score<0.80):
   - Household income ≠ Loss/Claims Severity, Account Size, or average premium per account.
   - Budget / bugdet / bdgt ≠ Premium Opportunity, Marketing Spend, Net Sales, or LOB Cross-sell COUNT.
   - renewal_budget / Renewal Budget ≠ Renewal Premium (budget planned spend ≠ earned policy premium).
   - Opportunity / pipeline revenue_amount ≠ Net Sales or Marketing Spend.
   - Meeting counts ≠ Scheduled Calls, Outbound Calls, or Mail KPIs (unless the canonical name/definition explicitly includes meetings).
   - Opportunity counts ≠ Quote Count.
   - Invoice counts ≠ Audits / Calls / Mail.
   - Sales stage distribution ≠ Cancellation Reason Distribution.
   - Field names with underscores carry full semantic meaning: gcrm_opportunity, opportunity_name, revenue_amount are CRM pipeline/sales data and must NOT map to booked insurance policy or call-center KPIs.
8. Ontology gaps are acceptable: prefer not_found (null) over inventing a mapping.

Return a valid JSON object matching this exact structure:
{{
  "matched_kpi_id": "<canonical_kpi_id or null>",
  "similarity_score": <float between 0.0 and 1.0>,
  "confidence_score": <float between 0.0 and 1.0>,
  "rationale": "<step-by-step business explanation for the match or rejection decision>"
}}"""

    log_data["phases"]["phase3"]["llm_prompt"] = prompt

    parsed_result = None
    structured_success = False

    # Try structured output first
    if llm and hasattr(llm, 'with_structured_output'):
        try:
            structured_llm = llm.with_structured_output(Phase3JudgeResult)
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
        rationale = parsed_result.get("rationale", "LLM judge")
        raw_matched = parsed_result.get("matched_kpi_id")
        # Treat explicit LLM null/empty as rejection — never backfill embedding best_id (H12)
        if raw_matched in (None, "", "null", "None"):
            matched_id = None
            if conf >= 0.70:
                _agent_debug_log(
                    "H12",
                    "ontology_service.match_kpi_to_ontology",
                    "LLM returned null — blocked embedding best_id backfill",
                    {
                        "kpi": original_name,
                        "llm_conf": conf,
                        "blocked_best_id": best_id,
                        "blocked_best_name": best_name,
                    },
                )
            conf = min(conf, 0.79) if matched_id is None else conf
        else:
            matched_id = str(raw_matched)
        result = {
            "matched_kpi_id": matched_id,
            "similarity_score": float(parsed_result.get("similarity_score", best_sim)),
            "confidence_score": conf if matched_id else min(conf, 0.79),
            "similarity_rationale": rationale,
            "confidence_rationale": "Phase 3 LLM" if structured_success else "Phase 3 LLM fallback",
            "model_used": "llm_judge",
            "mapping_status": _status_from_confidence(conf) if matched_id else "not_found",
            "mapping_type": _classify_mapping_type(rationale, conf) if matched_id else "no_match",
            "alternative_candidates": llm_candidates[:5],
        }
        log_data["phases"]["phase3"]["matched"] = matched_id is not None
        log_data["phases"]["phase3"]["result"] = result
        log_data["final_result"] = result
    else:
        # Fallback to embedding if LLM completely failed
        # If hash fallback active, cap confidence
        if is_using_hash_fallback():
            fb_conf = min(best_sim, 0.50)
            fb_model = "hash_fallback"
        else:
            fb_conf = best_sim
            fb_model = "embedding"
        result = {
            "matched_kpi_id": best_id if fb_conf >= 0.70 else None,
            "similarity_score": best_sim,
            "confidence_score": fb_conf,
            "similarity_rationale": f"Embedding best match '{best_name}'",
            "confidence_rationale": "Phase 3 LLM failed; embedding fallback" + (" (hash)" if is_using_hash_fallback() else ""),
            "model_used": fb_model,
            "mapping_status": _status_from_confidence(fb_conf),
            "mapping_type": _classify_mapping_type("embedding", fb_conf),
            "alternative_candidates": llm_candidates[:5],
        }
        log_data["phases"]["phase3"]["result"] = result
        log_data["final_result"] = result

    result = apply_mapping_quality_gates(
        kpi, result, ontology_by_id, original_name=original_name
    )
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
        "line_of_business": getattr(r, "line_of_business", None),
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
    line_of_business: str | None = None,
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
    if line_of_business:
        q = q.filter(OntologyKPI.line_of_business == line_of_business)
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
    # Persist mapping type and alternative candidates if columns exist
    if hasattr(row, "mapping_type"):
        row.mapping_type = match.get("mapping_type") or _classify_mapping_type(
            match.get("similarity_rationale", ""),
            float(match.get("confidence_score") or 0.0),
        )
    if hasattr(row, "alternative_candidates"):
        alt = match.get("alternative_candidates")
        if alt:
            row.alternative_candidates = json.dumps(alt)
    if hasattr(row, "formula_similarity"):
        row.formula_similarity = match.get("formula_similarity")
    if hasattr(row, "approval_decision"):
        row.approval_decision = match.get("approval_decision")
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
        # Retry commit for ReportKPIMapping rows in case of SQLite contention
        import time as _time
        from sqlalchemy.exc import OperationalError as _OpErr
        for _attempt in range(1, 6):
            try:
                db.commit()
                break
            except _OpErr as _exc:
                if "database is locked" in str(_exc) and _attempt < 5:
                    _wait = 0.5 * (2 ** (_attempt - 1))
                    logger.warning(
                        "database is locked in ontology commit (attempt %d/5), retrying in %.1fs...",
                        _attempt, _wait,
                    )
                    db.rollback()
                    # Re-add pending mappings since rollback cleared them
                    for kpi, match in matches_to_persist:
                        persist_mapping(db, report_id, kpi, match, commit=False)
                    _time.sleep(_wait)
                else:
                    raise
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

