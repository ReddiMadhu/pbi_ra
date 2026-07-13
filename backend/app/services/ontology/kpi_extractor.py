import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

AGG_PATTERN = re.compile(
    r"\b(SUM|AVG|AVERAGE|COUNT|COUNTD|MIN|MAX|MEDIAN|ATTR)\s*\(\s*([^)]+)\s*\)",
    re.IGNORECASE,
)
FIELD_REF = re.compile(r"\[([^\]]+)\]")


@dataclass
class ExtractedKPI:
    name: str
    resolved_lineage: list[str] = field(default_factory=list)
    aggregation_type: str = "UNKNOWN"
    definition: str = ""
    extraction_method: str = "unknown"


def _lineage_hash(lineage: list[str], aggregation: str) -> str:
    payload = json.dumps(sorted(lineage), sort_keys=True) + (aggregation or "").upper()
    return hashlib.sha256(payload.encode()).hexdigest()


def _dedupe_kpis(kpis: list[ExtractedKPI]) -> list[ExtractedKPI]:
    seen: set[str] = set()
    out: list[ExtractedKPI] = []
    for kpi in kpis:
        key = _lineage_hash(kpi.resolved_lineage, kpi.aggregation_type) + kpi.name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(kpi)
    return out


def _extract_via_regex(calculated_fields: list[dict]) -> list[ExtractedKPI]:
    results: list[ExtractedKPI] = []
    for cf in calculated_fields:
        formula = cf.get("formula") or ""
        name = cf.get("name") or cf.get("caption") or ""
        if not name:
            continue
        agg = "NONE"
        lineage: list[str] = []
        match = AGG_PATTERN.search(formula)
        if match:
            agg = match.group(1).upper()
            if agg == "AVERAGE":
                agg = "AVG"
            refs = FIELD_REF.findall(match.group(2))
            lineage = [r.strip() for r in refs if r.strip()]
        results.append(
            ExtractedKPI(
                name=name,
                resolved_lineage=lineage,
                aggregation_type=agg,
                definition=formula,
                extraction_method="regex",
            )
        )
    return results


def _extract_via_parser_metadata(
    calculated_fields: list[dict], col_to_table_map: dict[str, str]
) -> list[ExtractedKPI]:
    results: list[ExtractedKPI] = []
    for cf in calculated_fields:
        formula = cf.get("formula") or ""
        name = cf.get("name") or cf.get("caption") or ""
        if not name:
            continue
        lineage: list[str] = []
        for ref in FIELD_REF.findall(formula):
            ref = ref.strip()
            table = col_to_table_map.get(ref) or col_to_table_map.get(ref.lower())
            if table:
                lineage.append(f"{table}.{ref}")
            else:
                lineage.append(ref)
        agg = "NONE"
        m = AGG_PATTERN.search(formula)
        if m:
            agg = m.group(1).upper()
            if agg == "AVERAGE":
                agg = "AVG"
        results.append(
            ExtractedKPI(
                name=name,
                resolved_lineage=sorted(set(lineage)),
                aggregation_type=agg,
                definition=formula,
                extraction_method="parser",
            )
        )
    return results


def _extract_via_llm(calculated_fields: list[dict], llm: Any) -> list[ExtractedKPI]:
    if not llm or not calculated_fields:
        return []
    names = [cf.get("name") or cf.get("caption") for cf in calculated_fields if cf.get("name") or cf.get("caption")]
    if not names:
        return []
    prompt = f"""Extract KPI metadata from these Tableau calculated fields.
Return JSON array with objects: name, aggregation_type (SUM|AVG|COUNT|NONE), lineage (array of field refs).
Fields: {json.dumps(calculated_fields[:30])}
Return ONLY valid JSON array."""
    try:
        res = llm.invoke(prompt)
        content = (res.content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content).strip()
            content = content.rstrip("`").strip()
        parsed = json.loads(content)
        if not isinstance(parsed, list):
            return []
        out: list[ExtractedKPI] = []
        for item in parsed:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            out.append(
                ExtractedKPI(
                    name=item["name"],
                    resolved_lineage=item.get("lineage") or [],
                    aggregation_type=(item.get("aggregation_type") or "UNKNOWN").upper(),
                    definition=item.get("definition", ""),
                    extraction_method="llm",
                )
            )
        return out
    except Exception:
        return [
            ExtractedKPI(
                name=cf.get("name") or cf.get("caption") or "",
                resolved_lineage=[],
                aggregation_type="UNKNOWN",
                definition=cf.get("formula", ""),
                extraction_method="llm_fallback",
            )
            for cf in calculated_fields
            if cf.get("name") or cf.get("caption")
        ]


def extract_kpis_from_workbook(
    workbook_metadata: Any,
    col_to_table_map: dict[str, str] | None = None,
    llm: Any = None,
) -> list[ExtractedKPI]:
    """3-tier KPI extraction: regex → parser lineage → LLM fallback."""
    col_to_table_map = col_to_table_map or {}
    calculated_fields: list[dict] = []
    for ds in getattr(workbook_metadata, "datasources", []) or []:
        for cf in getattr(ds, "calculated_fields", []) or []:
            calculated_fields.append(
                {
                    "name": getattr(cf, "caption", None) or getattr(cf, "name", ""),
                    "caption": getattr(cf, "caption", None),
                    "formula": getattr(cf, "formula", "") or "",
                }
            )

    tier1 = _extract_via_regex(calculated_fields)
    tier2 = _extract_via_parser_metadata(calculated_fields, col_to_table_map)

    by_name: dict[str, ExtractedKPI] = {}
    for kpi in tier1:
        by_name[kpi.name.lower()] = kpi
    for kpi in tier2:
        existing = by_name.get(kpi.name.lower())
        if existing:
            has_resolved = any('.' in l for l in kpi.resolved_lineage)
            existing_has_resolved = any('.' in l for l in existing.resolved_lineage)
            if has_resolved or not existing_has_resolved:
                by_name[kpi.name.lower()] = kpi
        else:
            by_name[kpi.name.lower()] = kpi

    missing = [
        cf
        for cf in calculated_fields
        if (cf.get("name") or "").lower() not in by_name
    ]
    if missing and llm:
        for kpi in _extract_via_llm(missing, llm):
            by_name[kpi.name.lower()] = kpi
    elif missing:
        for cf in missing:
            name = cf.get("name") or ""
            if name:
                by_name[name.lower()] = ExtractedKPI(
                    name=name,
                    resolved_lineage=[],
                    aggregation_type="UNKNOWN",
                    definition=cf.get("formula", ""),
                    extraction_method="name_only",
                )

    return _dedupe_kpis(list(by_name.values()))
