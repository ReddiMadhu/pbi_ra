import json
import re
from dataclasses import dataclass, field
from typing import Any

AGG_PATTERN = re.compile(
    r"\b(SUM|AVG|AVERAGE|COUNT|COUNTD|MIN|MAX|MEDIAN|ATTR|STDEV|VAR|PCT)\s*\(\s*([^)]+)\s*\)",
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
    mark_type: str | None = None
    calculation_logic: str | None = None
    source_description: str | None = None


def _lineage_key(lineage: list[str], aggregation: str) -> str:
    return json.dumps(sorted(lineage), sort_keys=True) + (aggregation or "").upper()


def _normalize_agg(agg: str) -> str:
    agg = (agg or "UNKNOWN").upper()
    if agg == "AVERAGE":
        return "AVG"
    if agg == "CNT":
        return "COUNT"
    # COUNTD stays COUNTD (distinct count must not collapse into COUNT)
    if agg == "MEDIAN":
        return "MEDIAN"
    if agg == "SUM_SQR":
        return "SUM_SQR"
    return agg


def _strip_table_suffix(field: str) -> str:
    return str(field).split(" (Table - ")[0].strip()


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
    mark_type = getattr(ws, "mark_type", None) or None
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
                    mark_type=mark_type,
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
                mark_type=mark_type,
            )
        )
    return results


def _extract_dimension_breakdowns(
    ws: Any,
    measure_bindings: list[dict],
    worksheet_id: str | None,
    worksheet_name: str,
) -> list[ExtractedKPI]:
    """Source C: measure + shelf dimension → 'Metric by Dimension' KPIs."""
    if not measure_bindings:
        return []

    measure_fields = {str(b.get("field", "")).lower() for b in measure_bindings if b.get("field")}
    shelf_fields = list(getattr(ws, "rows", []) or []) + list(getattr(ws, "columns", []) or [])
    dimensions: list[str] = []
    seen_dims: set[str] = set()
    for field in shelf_fields:
        base = _strip_table_suffix(field)
        if not base or base.lower() in measure_fields:
            continue
        key = base.lower()
        if key in seen_dims:
            continue
        seen_dims.add(key)
        dimensions.append(base)

    if not dimensions:
        return []

    mark_type = getattr(ws, "mark_type", None) or "Unknown"
    results: list[ExtractedKPI] = []
    for binding in measure_bindings:
        if not isinstance(binding, dict):
            continue
        agg = _normalize_agg(binding.get("aggregation", "UNKNOWN"))
        field_name = binding.get("field", "")
        if isinstance(binding.get("lineage"), list):
            lineage_list = binding["lineage"]
        elif binding.get("lineage"):
            lineage_list = [str(binding["lineage"])]
        else:
            table = binding.get("table", "")
            lineage_list = [f"{table}.{field_name}" if table else str(field_name)]
        for dim in dimensions:
            name = f"{agg} of {field_name} by {dim}"
            results.append(
                ExtractedKPI(
                    name=name,
                    resolved_lineage=lineage_list,
                    aggregation_type=agg,
                    definition=f"{name} [{mark_type}]",
                    extraction_method="visual_breakdown",
                    worksheet_id=worksheet_id,
                    worksheet_name=worksheet_name,
                    mark_type=mark_type,
                )
            )
    return results


def _extract_visual_bindings(ws: Any, worksheet_id: str | None, worksheet_name: str) -> list[ExtractedKPI]:
    results: list[ExtractedKPI] = []
    mark_type = getattr(ws, "mark_type", None) or "Unknown"
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
                    definition=f"{name} [{mark_type}]",
                    extraction_method="visual_binding",
                    worksheet_id=worksheet_id,
                    worksheet_name=worksheet_name,
                    mark_type=mark_type,
                )
            )
    return results


def _extract_mark_card_measures(
    ws: Any,
    calc_map: dict[str, dict],
    worksheet_id: str | None,
    worksheet_name: str,
) -> list[ExtractedKPI]:
    """Source E: measures on Color/Size/Text/Tooltip/Detail via filters_and_marks."""
    results: list[ExtractedKPI] = []
    mark_type = getattr(ws, "mark_type", None) or "Unknown"
    seen: set[tuple[str, str]] = set()

    for field in getattr(ws, "filters_and_marks", []) or []:
        base = _strip_table_suffix(field)
        if not base:
            continue
        meta = calc_map.get(base.lower())
        if not meta:
            # Raw columns without an aggregation signal are too noisy — skip
            continue
        agg = meta.get("aggregation") or "UNKNOWN"
        if agg in ("NONE", "UNKNOWN", ""):
            continue
        name = meta["name"]
        dedupe = (name.lower(), _normalize_agg(agg))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        results.append(
            ExtractedKPI(
                name=name,
                resolved_lineage=list(meta.get("lineage") or []),
                aggregation_type=_normalize_agg(agg),
                definition=meta.get("formula") or f"{name} [{mark_type}]",
                extraction_method="mark_card",
                worksheet_id=worksheet_id,
                worksheet_name=worksheet_name,
                mark_type=mark_type,
            )
        )
    return results


def extract_from_ai_summary(ai_summary: str | dict | None) -> list[ExtractedKPI]:
    """Source D: LLM classification KPIs from Dashboard.ai_summary (no structured lineage)."""
    if not ai_summary:
        return []
    data: dict
    if isinstance(ai_summary, dict):
        data = ai_summary
    else:
        try:
            text = str(ai_summary).strip()
            if not text.startswith("{"):
                return []
            data = json.loads(text)
        except Exception:
            return []

    results: list[ExtractedKPI] = []
    for k in data.get("kpis") or []:
        if isinstance(k, str) and k.strip():
            results.append(
                ExtractedKPI(
                    name=k.strip(),
                    resolved_lineage=[],
                    aggregation_type="UNKNOWN",
                    definition=k.strip(),
                    extraction_method="llm_summary",
                )
            )
            continue
        if not isinstance(k, dict) or not k.get("name"):
            continue
        name = str(k["name"]).strip()
        definition = (k.get("definition") or "").strip() or name
        calc_logic = (k.get("calculation_logic") or "").strip() or None
        source_desc = (k.get("source_description") or "").strip() or None
        # Prepend definition for richer embedding text
        def_parts = [definition]
        if calc_logic:
            def_parts.append(calc_logic)
        if source_desc:
            def_parts.append(source_desc)
        results.append(
            ExtractedKPI(
                name=name,
                resolved_lineage=[],
                aggregation_type="UNKNOWN",
                definition=" | ".join(def_parts),
                extraction_method="llm_summary",
                calculation_logic=calc_logic,
                source_description=source_desc,
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
    seen_names: set[tuple[str, str]] = set()
    seen_name_agg: set[tuple[str, str]] = set()
    for kpi in kpis:
        if kpi.extraction_method in ("visual_binding", "visual_breakdown", "mark_card"):
            key = _lineage_key(kpi.resolved_lineage, kpi.aggregation_type)
            if key in named_keys and kpi.extraction_method in ("visual_binding", "mark_card"):
                continue
        dedupe_key = (kpi.worksheet_id or "", kpi.name.lower())
        if dedupe_key in seen_names:
            continue
        name_agg = (kpi.name.lower(), (kpi.aggregation_type or "").upper())
        if kpi.extraction_method == "mark_card" and name_agg in seen_name_agg:
            continue
        seen_names.add(dedupe_key)
        seen_name_agg.add(name_agg)
        out.append(kpi)
    return out


def extract_kpis_per_worksheet(
    workbook_metadata: Any,
    col_to_table_map: dict[str, str] | None = None,
    worksheet_db_rows: list[Any] | None = None,
    llm: Any = None,
    *,
    include_orphan_worksheets: bool = False,
) -> dict[str, list[ExtractedKPI]]:
    """
    Extract KPIs per worksheet (Sources A–C, E).
    Returns dict keyed by worksheet name.
    """
    col_map = col_to_table_map or {}
    workbook_metadata._col_to_table_map = col_map
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
        is_orphan = bool(dashboard_ws_names) and ws.name not in dashboard_ws_names
        if is_orphan and not include_orphan_worksheets:
            continue
        ws_row = ws_db_by_name.get(ws.name)
        if is_orphan:
            worksheet_id = "orphan"
        else:
            worksheet_id = str(ws_row.id) if ws_row else None
        worksheet_name = ws.name

        kpis: list[ExtractedKPI] = []
        bindings = getattr(ws, "measure_bindings", []) or []
        kpis.extend(_extract_named_on_worksheet(ws, calc_map, worksheet_id, worksheet_name))
        kpis.extend(_extract_visual_bindings(ws, worksheet_id, worksheet_name))
        kpis.extend(_extract_dimension_breakdowns(ws, bindings, worksheet_id, worksheet_name))
        kpis.extend(
            _extract_mark_card_measures(ws, calc_map, worksheet_id, worksheet_name)
        )
        result[worksheet_name] = _dedupe_worksheet_kpis(kpis)

    return result


def extract_kpis_from_workbook(
    workbook_metadata: Any,
    col_to_table_map: dict[str, str] | None = None,
    llm: Any = None,
    *,
    include_orphan_worksheets: bool = False,
) -> list[ExtractedKPI]:
    """Legacy flat list — all per-worksheet KPIs flattened."""
    per_ws = extract_kpis_per_worksheet(
        workbook_metadata,
        col_to_table_map,
        llm=llm,
        include_orphan_worksheets=include_orphan_worksheets,
    )
    flat: list[ExtractedKPI] = []
    for kpis in per_ws.values():
        flat.extend(kpis)
    return flat
