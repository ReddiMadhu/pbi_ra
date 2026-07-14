import hashlib
import json
import re
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
    worksheet_id: str | None = None
    worksheet_name: str | None = None


def _lineage_key(lineage: list[str], aggregation: str) -> str:
    return json.dumps(sorted(lineage), sort_keys=True) + (aggregation or "").upper()


def _normalize_agg(agg: str) -> str:
    agg = (agg or "UNKNOWN").upper()
    if agg == "AVERAGE":
        return "AVG"
    if agg in ("CNT", "COUNTD"):
        return "COUNT"
    if agg == "MEDIAN":
        return "MEDIAN"
    return agg


def _build_calc_field_map(workbook_metadata: Any) -> dict[str, dict]:
    """Map calc field name -> {formula, lineage, aggregation}."""
    col_to_table_map: dict[str, str] = getattr(workbook_metadata, "_col_to_table_map", {}) or {}
    out: dict[str, dict] = {}
    for ds in getattr(workbook_metadata, "datasources", []) or []:
        for cf in getattr(ds, "calculated_fields", []) or []:
            name = getattr(cf, "caption", None) or getattr(cf, "name", "")
            if not name:
                continue
            formula = getattr(cf, "formula", "") or ""
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
                agg = _normalize_agg(m.group(1))
            out[name.lower()] = {
                "name": name,
                "formula": formula,
                "lineage": sorted(set(lineage)),
                "aggregation": agg,
            }
    return out


def _extract_named_on_worksheet(
    ws: Any,
    calc_map: dict[str, dict],
    worksheet_id: str | None,
    worksheet_name: str,
) -> list[ExtractedKPI]:
    results: list[ExtractedKPI] = []
    for cf_name in getattr(ws, "used_calculated_fields", []) or []:
        meta = calc_map.get(str(cf_name).lower())
        if not meta:
            results.append(
                ExtractedKPI(
                    name=cf_name,
                    resolved_lineage=[],
                    aggregation_type="UNKNOWN",
                    definition="",
                    extraction_method="named_measure",
                    worksheet_id=worksheet_id,
                    worksheet_name=worksheet_name,
                )
            )
            continue
        results.append(
            ExtractedKPI(
                name=meta["name"],
                resolved_lineage=meta["lineage"],
                aggregation_type=meta["aggregation"],
                definition=meta["formula"],
                extraction_method="named_measure",
                worksheet_id=worksheet_id,
                worksheet_name=worksheet_name,
            )
        )
    return results


def _extract_visual_bindings(ws: Any, worksheet_id: str | None, worksheet_name: str) -> list[ExtractedKPI]:
    results: list[ExtractedKPI] = []
    for binding in getattr(ws, "measure_bindings", []) or []:
        if isinstance(binding, dict):
            lineage = binding.get("lineage") or binding.get("field", "")
            agg = _normalize_agg(binding.get("aggregation", "UNKNOWN"))
            field_name = binding.get("field", lineage)
            if isinstance(lineage, list):
                lineage_list = lineage
            elif "." in str(lineage):
                lineage_list = [str(lineage)]
            else:
                table = binding.get("table", "")
                lineage_list = [f"{table}.{lineage}" if table else str(lineage)]
            name = f"{agg} of {lineage_list[0]}" if lineage_list else f"{agg} of {field_name}"
            results.append(
                ExtractedKPI(
                    name=name,
                    resolved_lineage=lineage_list,
                    aggregation_type=agg,
                    definition=name,
                    extraction_method="visual_binding",
                    worksheet_id=worksheet_id,
                    worksheet_name=worksheet_name,
                )
            )
    return results


def _dedupe_worksheet_kpis(kpis: list[ExtractedKPI]) -> list[ExtractedKPI]:
    """Named measures win over visual bindings with same lineage+agg on same worksheet."""
    named_keys: set[str] = set()
    for kpi in kpis:
        if kpi.extraction_method == "named_measure":
            named_keys.add(_lineage_key(kpi.resolved_lineage, kpi.aggregation_type))

    out: list[ExtractedKPI] = []
    seen_names: set[str] = set()
    for kpi in kpis:
        if kpi.extraction_method == "visual_binding":
            key = _lineage_key(kpi.resolved_lineage, kpi.aggregation_type)
            if key in named_keys:
                continue
        dedupe_key = (kpi.worksheet_id or "", kpi.name.lower())
        if dedupe_key in seen_names:
            continue
        seen_names.add(dedupe_key)
        out.append(kpi)
    return out


def extract_kpis_per_worksheet(
    workbook_metadata: Any,
    col_to_table_map: dict[str, str] | None = None,
    worksheet_db_rows: list[Any] | None = None,
    llm: Any = None,
) -> dict[str, list[ExtractedKPI]]:
    """
    Extract KPIs per worksheet (Source A: named measures, Source B: visual bindings).
    Returns dict keyed by worksheet name.
    """
    workbook_metadata._col_to_table_map = col_to_table_map or {}
    calc_map = _build_calc_field_map(workbook_metadata)

    ws_db_by_name: dict[str, Any] = {}
    if worksheet_db_rows:
        for ws_row in worksheet_db_rows:
            ws_db_by_name[ws_row.name] = ws_row

    dashboard_ws_names: set[str] = set()
    for db in getattr(workbook_metadata, "dashboards", []) or []:
        for ws_name in getattr(db, "worksheets", []) or []:
            dashboard_ws_names.add(ws_name)

    result: dict[str, list[ExtractedKPI]] = {}
    for ws in getattr(workbook_metadata, "worksheets", []) or []:
        if ws.name not in dashboard_ws_names and dashboard_ws_names:
            continue
        ws_row = ws_db_by_name.get(ws.name)
        worksheet_id = str(ws_row.id) if ws_row else None
        worksheet_name = ws.name

        kpis: list[ExtractedKPI] = []
        kpis.extend(_extract_named_on_worksheet(ws, calc_map, worksheet_id, worksheet_name))
        kpis.extend(_extract_visual_bindings(ws, worksheet_id, worksheet_name))
        result[worksheet_name] = _dedupe_worksheet_kpis(kpis)

    return result


def extract_kpis_from_workbook(
    workbook_metadata: Any,
    col_to_table_map: dict[str, str] | None = None,
    llm: Any = None,
) -> list[ExtractedKPI]:
    """Legacy flat list — all per-worksheet KPIs flattened."""
    per_ws = extract_kpis_per_worksheet(workbook_metadata, col_to_table_map, llm=llm)
    flat: list[ExtractedKPI] = []
    for kpis in per_ws.values():
        flat.extend(kpis)
    return flat
