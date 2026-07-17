import json
import re
from dataclasses import dataclass, field
from typing import Any

AGG_PATTERN = re.compile(
    r"\b(SUM|AVG|AVERAGE|COUNT|COUNTD|MIN|MAX|MEDIAN|ATTR|STDEV|VAR|PCT)\s*\(\s*([^)]+)\s*\)",
    re.IGNORECASE,
)
FIELD_REF = re.compile(r"\[([^\]]+)\]")

NON_KPI_PATTERNS = [
    # Constants (e.g. 0, 1, 100, 1.5)
    re.compile(r"^\s*\d+(?:\.\d+)?\s*$"),
    # Table calculations with no business meaning
    re.compile(r"^\s*(LAST|FIRST|INDEX|SIZE|RUNNING_)\s*\(", re.I),
    # Filter booleans: [Field] = [Parameter] or [Field] = 'Value'
    re.compile(r"^\s*\[[^\]]+\]\s*=\s*\[[^\]]+\]\s*$"),
    re.compile(r"^\s*\[[^\]]+\]\s*=\s*'[^']*'\s*$", re.I),
    # Pure date part extraction (not aggregated)
    re.compile(r"^\s*(YEAR|MONTH|DAY|DATEPART|DATENAME)\s*\(\s*\[", re.I),
    # Parameter reference/equality checks
    re.compile(r"\[Parameter\s*\d+\]", re.I),
]

NON_KPI_NAMES = {
    "last", "first", "one", "zero", "index", "disable highlighting",
    "region filter", "state filter", "year filter", "year filter max",
    "filter: performance card (claim close date)",
    "filter: performance kpi (claim close date)",
    "date calculation", "gender | text", "bin description",
    "bin max", "bin size | income"
}

NON_KPI_NAME_PATTERNS = [
    re.compile(r"\bfilter\b", re.I),
    re.compile(r"\bparameter\b", re.I),
    re.compile(r"^(period|main date):", re.I),
    re.compile(r"^(max|min|last|first)\s+(date|year|month|day)$", re.I),
]

def _is_non_kpi(name: str, formula: str | None = None) -> bool:
    name_clean = str(name).strip().lower()
    if name_clean in NON_KPI_NAMES:
        return True
    for p in NON_KPI_NAME_PATTERNS:
        if p.search(name_clean):
            return True
    if formula:
        formula_clean = str(formula).strip()
        for pattern in NON_KPI_PATTERNS:
            if pattern.search(formula_clean):
                return True
    return False


# Pattern to detect raw column references (just [ColumnName] with no aggregation)
RAW_COLUMN_REF = re.compile(r"^\s*\[[^\]]+\]\s*$")

# Patterns for CASE/IF switcher branches
CASE_BRANCH = re.compile(
    r"WHEN\s+['\"][^'\"]+['\"]\s+THEN\s+\[([^\]]+)\]",
    re.IGNORECASE,
)
IF_THEN_BRANCH = re.compile(
    r"THEN\s+\[([^\]]+)\]",
    re.IGNORECASE,
)


def _is_raw_column_ref(formula: str | None) -> bool:
    """True if the formula is just a bare column reference like [Claim Paid Amount]."""
    if not formula:
        return False
    return bool(RAW_COLUMN_REF.match(formula.strip()))


def _deconstruct_switcher(
    formula: str,
    calc_map: dict[str, dict],
    worksheet_id: str | None,
    worksheet_name: str,
    mark_type: str | None,
    parent_name: str,
    depth: int = 0,
    max_depth: int = 3,
) -> list["ExtractedKPI"]:
    """Recursively extract sub-measures referenced inside CASE/IF switcher formulas.

    Returns a list of ExtractedKPI entries for each resolved sub-measure,
    marked with is_dynamic=True and referencing the parent switcher.
    Recurses up to max_depth levels to resolve nested calculations.
    """
    if depth >= max_depth:
        return []

    results: list[ExtractedKPI] = []
    seen_refs: set[str] = set()

    # Extract field references from CASE WHEN ... THEN [FieldRef] branches
    for match in CASE_BRANCH.finditer(formula):
        seen_refs.add(match.group(1))

    # Extract field references from IF ... THEN [FieldRef] branches
    for match in IF_THEN_BRANCH.finditer(formula):
        seen_refs.add(match.group(1))

    for ref_name in seen_refs:
        meta = calc_map.get(ref_name.lower())
        if meta:
            ref_formula = meta["formula"]
            # Only recurse into genuine CASE switchers, not conditional aggregations
            # SUM(IF ... THEN [X]) is a real KPI, not a switcher
            is_agg_wrapped = bool(AGG_PATTERN.match(ref_formula.strip()))
            is_genuine_switcher = "CASE" in ref_formula.upper() and not is_agg_wrapped

            if is_genuine_switcher:
                results.extend(
                    _deconstruct_switcher(
                        ref_formula, calc_map, worksheet_id, worksheet_name,
                        mark_type, ref_name, depth + 1, max_depth,
                    )
                )
            elif not _is_raw_column_ref(ref_formula) and not _is_non_kpi(ref_name, ref_formula):
                results.append(
                    ExtractedKPI(
                        name=meta["name"],
                        resolved_lineage=meta["lineage"],
                        aggregation_type=meta["aggregation"],
                        definition=meta["formula"],
                        extraction_method="switcher_component",
                        worksheet_id=worksheet_id,
                        worksheet_name=worksheet_name,
                        mark_type=mark_type,
                        is_dynamic=True,
                        source_description=f"Extracted from switcher '{parent_name}'",
                    )
                )
        # If not in calc_map, it might be a direct measure reference
        elif not _is_non_kpi(ref_name):
            results.append(
                ExtractedKPI(
                    name=ref_name,
                    resolved_lineage=[],
                    aggregation_type="UNKNOWN",
                    definition="",
                    extraction_method="switcher_component",
                    worksheet_id=worksheet_id,
                    worksheet_name=worksheet_name,
                    mark_type=mark_type,
                    is_dynamic=True,
                    source_description=f"Extracted from switcher '{parent_name}'",
                )
            )
    return results


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
    is_dynamic: bool = False
    dimensions: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)


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
    dims = list(getattr(ws, "rows", []) or []) + list(getattr(ws, "columns", []) or [])
    filts = list(getattr(ws, "filters_and_marks", []) or [])
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
                    dimensions=dims,
                    filters=filts,
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
                dimensions=dims,
                filters=filts,
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

    dims = list(getattr(ws, "rows", []) or []) + list(getattr(ws, "columns", []) or [])
    filts = list(getattr(ws, "filters_and_marks", []) or [])
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
                    dimensions=dims,
                    filters=filts,
                )
            )
    return results


def _extract_visual_bindings(ws: Any, worksheet_id: str | None, worksheet_name: str) -> list[ExtractedKPI]:
    results: list[ExtractedKPI] = []
    mark_type = getattr(ws, "mark_type", None) or "Unknown"
    dims = list(getattr(ws, "rows", []) or []) + list(getattr(ws, "columns", []) or [])
    filts = list(getattr(ws, "filters_and_marks", []) or [])
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
                    dimensions=dims,
                    filters=filts,
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
    dims = list(getattr(ws, "rows", []) or []) + list(getattr(ws, "columns", []) or [])
    filts = list(getattr(ws, "filters_and_marks", []) or [])
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
                dimensions=dims,
                filters=filts,
            )
        )
    return results


def _infer_agg_from_text(text: str) -> str:
    """Try to extract an aggregation function from free-form text like 'AVG(IGO Aging)'."""
    if not text:
        return "UNKNOWN"
    m = AGG_PATTERN.search(text)
    if m:
        return _normalize_agg(m.group(1))
    # Fallback: check for common textual patterns
    text_lower = text.lower()
    for pattern, agg in [
        ("average ", "AVG"), ("avg ", "AVG"),
        ("sum of ", "SUM"), ("total ", "SUM"),
        ("count of ", "COUNT"), ("number of ", "COUNT"),
        ("distinct count", "COUNTD"),
        ("median ", "MEDIAN"),
        ("maximum ", "MAX"), ("max ", "MAX"),
        ("minimum ", "MIN"), ("min ", "MIN"),
    ]:
        if pattern in text_lower:
            return agg
    return "UNKNOWN"


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
            inferred_agg = _infer_agg_from_text(k.strip())
            results.append(
                ExtractedKPI(
                    name=k.strip(),
                    resolved_lineage=[],
                    aggregation_type=inferred_agg,
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
        inferred_agg = _infer_agg_from_text(
            calc_logic or definition or name
        )
        results.append(
            ExtractedKPI(
                name=name,
                resolved_lineage=[],
                aggregation_type=inferred_agg,
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
        # Filter non-KPIs and raw column references
        filtered_kpis = [
            k for k in kpis
            if not _is_non_kpi(k.name, k.definition or k.calculation_logic)
            and not _is_raw_column_ref(k.definition)
        ]

        # Deconstruct switcher calculations (CASE/IF) into component KPIs
        switcher_kpis: list[ExtractedKPI] = []
        for k in list(filtered_kpis):
            formula = k.definition or k.calculation_logic or ""
            if ("CASE" in formula.upper() or ("IF" in formula.upper() and "THEN" in formula.upper())) \
                    and ("WHEN" in formula.upper() or "THEN" in formula.upper()):
                components = _deconstruct_switcher(
                    formula, calc_map, worksheet_id, worksheet_name,
                    mark_type=getattr(ws, "mark_type", None),
                    parent_name=k.name,
                )
                if components:
                    switcher_kpis.extend(components)
        filtered_kpis.extend(switcher_kpis)

        deduped = _dedupe_worksheet_kpis(filtered_kpis)
        # Hide worksheets with zero KPIs entirely
        if deduped:
            result[worksheet_name] = deduped

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
