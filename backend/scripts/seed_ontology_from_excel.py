"""
Seed the ontology bank (ontology_kpis) from your own Excel files.

Supported bank format (primary):
  Measurement(KPI)                      → name
  Definition                            → definition
  Fields required to create the Metric  → representative_lineage (comma-separated)
  Applicability with Sheet Names        → aliases + sector/subdomain
      e.g. Marketing, Distribution, Actuarial & Risk,
           Claims_Litigation, Service & Operations

Usage (from backend/):
  py -3 scripts/seed_ontology_from_excel.py path/to/kpi_bank.xlsx
  py -3 scripts/seed_ontology_from_excel.py path/to/kpi_bank.xlsx --sheet "Marketing"
  py -3 scripts/seed_ontology_from_excel.py path/to/kpi_bank.xlsx --all-sheets
  py -3 scripts/seed_ontology_from_excel.py path/to/kpi_bank.xlsx --all-sheets --dry-run
  py -3 scripts/seed_ontology_from_excel.py path/to/kpi_bank.xlsx --all-sheets --update-existing
  py -3 scripts/seed_ontology_from_excel.py path/to/kpi_bank.xlsx --inspect --all-sheets
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import pandas as pd
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine, Base
from app.models.ontology import OntologyKPI
from app.services.ontology.embedding_service import embed_ontology_kpis
from app.services.ontology.taxonomy import (
    DEFAULT_SECTOR,
    DEFAULT_SUBDOMAIN,
    normalize_scope,
    suggest_scope_from_applicability,
    validate_sector,
    validate_subdomain,
)
import app.models.ontology  # noqa: F401

# ─────────────────────────────────────────────────────────────────────────────
# COLUMN_MAP — ontology field → Excel header aliases (first match wins)
# Tuned for: Measurement(KPI) | Definition | Fields required… | Applicability…
# ─────────────────────────────────────────────────────────────────────────────
COLUMN_MAP: dict[str, list[str]] = {
    "name": [
        "Measurement(KPI)",
        "Measurement (KPI)",
        "Measurement",
        "measurement kpi",
        "name",
        "kpi",
        "kpi_name",
        "kpi name",
        "measure",
        "measure_name",
        "measure name",
        "variable",
        "variable_name",
        "metric",
        "metric_name",
    ],
    "definition": [
        "Definition",
        "definition",
        "def",
        "description",
        "business_definition",
        "business definition",
        "meaning",
        "desc",
    ],
    # Comma-separated source fields → representative_lineage
    "fields_required": [
        "Fields required to create the Metric",
        "Fields required to create the Metric ",
        "Fields Required to Create the Metric",
        "Fields required to create Metric",
        "Felids required to create the Metric",  # common typo
        "Felids required to create Metric",
        "Fields Required",
        "fields_required",
        "fields required",
        "source fields",
        "required fields",
        "metric fields",
    ],
    # Sheet applicability → aliases + subdomain inference
    "applicability": [
        "Applicability with Sheet Names",
        "Applicablity with Sheet Names",  # common typo
        "Applicability with Sheet Name",
        "Applicability",
        "Applicable Sheets",
        "Sheet Names",
        "applicability",
        "applicable_sheets",
    ],
    "table_name": [
        "table",
        "table_name",
        "table name",
        "source_table",
        "source table",
        "datasource_table",
        "physical_table",
        "db_table",
    ],
    "column_name": [
        "column",
        "column_name",
        "column name",
        "field",
        "field_name",
        "field name",
        "source_field",
        "source field",
        "source_column",
        "attribute",
    ],
    "sector": ["sector", "industry", "vertical"],
    "subdomain": [
        "subdomain",
        "sub_domain",
        "sub domain",
        "domain_area",
        "area",
        "subject_area",
    ],
    "domain": ["domain", "business_domain", "legacy_domain"],
    "aliases": ["aliases", "alias", "aka", "synonyms", "alternate_names"],
    "aggregation_type": [
        "aggregation_type",
        "aggregation",
        "agg",
        "agg_type",
        "measure_agg",
    ],
    "valid_dimensions": [
        "valid_dimensions",
        "dimensions",
        "dims",
        "by_dimensions",
    ],
    "representative_lineage": [
        "representative_lineage",
        "lineage",
        "data_lineage",
        "source_lineage",
    ],
    "worksheet_name": [
        "worksheet",
        "worksheet_name",
        "sheet",
        "sheet_name",
        "visual",
        "view",
    ],
    "status": ["status"],
    "created_by": ["created_by", "owner", "author"],
}

DEFAULTS = {
    "sector": DEFAULT_SECTOR,
    "subdomain": DEFAULT_SUBDOMAIN,
    "aggregation_type": "UNKNOWN",
    "status": "active",
    "created_by": "excel_seed",
}

VALID_AGGREGATIONS = {
    "SUM", "AVG", "AVERAGE", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN",
    "ATTR", "NONE", "UNKNOWN", "PCT", "STDEV", "VAR", "SUM_SQR",
}
VALID_STATUS = {"active", "stale"}


def _norm_header(h: str) -> str:
    """Normalize Excel headers: Measurement(KPI) → measurement kpi."""
    text = str(h).strip().lower()
    text = text.replace("_", " ")
    text = re.sub(r"[()\[\]{}]", " ", text)
    text = re.sub(r"[^\w\s&+-]", " ", text)
    return " ".join(text.split())


def _build_header_index(columns: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in columns:
        out[_norm_header(c)] = c
    return out


def resolve_column_map(
    excel_columns: list,
    column_map: dict[str, list[str]],
) -> dict[str, str | None]:
    index = _build_header_index(excel_columns)
    resolved: dict[str, str | None] = {}
    for field, aliases in column_map.items():
        hit = None
        for alias in aliases:
            key = _norm_header(alias)
            if key in index:
                hit = index[key]
                break
        resolved[field] = hit
    return resolved


def _cell(row: pd.Series, col: str | None) -> str:
    if not col or col not in row.index:
        return ""
    val = row.get(col)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    text = str(val).strip()
    return "" if text.lower() == "nan" else text


def _split_list(text: str) -> list[str]:
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    for sep in (",", "|", ";"):
        if sep in text:
            return [p.strip() for p in text.split(sep) if p.strip()]
    return [text]


def _build_lineage(
    table: str,
    column: str,
    explicit: str,
    fields_required: str,
) -> list[str]:
    """Prefer explicit lineage, then Fields required (CSV), then table.column."""
    if explicit:
        return _split_list(explicit)
    if fields_required:
        return _split_list(fields_required)
    if table and column:
        return [f"{table}.{column}"]
    if column:
        return [column]
    return []


def _build_name(name: str, table: str, column: str, worksheet: str) -> str:
    if name:
        return name
    if table and column:
        return f"{column} ({table})"
    if column:
        return column
    if worksheet and column:
        return f"{column} [{worksheet}]"
    return ""


def _build_definition(definition: str, name: str, table: str, column: str, worksheet: str) -> str:
    if definition:
        return definition
    parts = [f"Canonical measure '{name}'"]
    if table and column:
        parts.append(f"sourced from {table}.{column}")
    elif column:
        parts.append(f"sourced from column {column}")
    if worksheet:
        parts.append(f"(worksheet: {worksheet})")
    return " ".join(parts)


def row_to_kpi(
    row: pd.Series,
    resolved: dict[str, str | None],
    defaults: dict,
    *,
    excel_tab_name: str | None = None,
) -> OntologyKPI | None:
    name = _cell(row, resolved.get("name"))
    definition = _cell(row, resolved.get("definition"))
    table = _cell(row, resolved.get("table_name"))
    column = _cell(row, resolved.get("column_name"))
    worksheet = _cell(row, resolved.get("worksheet_name"))
    lineage_raw = _cell(row, resolved.get("representative_lineage"))
    fields_required = _cell(row, resolved.get("fields_required"))
    applicability = _cell(row, resolved.get("applicability"))

    name = _build_name(name, table, column, worksheet)
    if not name:
        return None

    definition = _build_definition(definition, name, table, column, worksheet)
    lineage = _build_lineage(table, column, lineage_raw, fields_required)

    domain = _cell(row, resolved.get("domain"))
    sector_raw = _cell(row, resolved.get("sector"))
    subdomain_raw = _cell(row, resolved.get("subdomain"))

    # Scope priority for bank Excel:
    # 1) Explicit sector/subdomain columns
    # 2) Excel TAB name (each sheet = subdomain bank: Marketing, Claims_Litigation, …)
    # 3) Applicability cell (only if tab did not map — do NOT take first of a multi-list over the tab)
    # 4) Defaults last (avoid dumping everything into Service & Operations)
    tab_mapped = False
    if not sector_raw and not subdomain_raw and excel_tab_name:
        tab_sec, tab_sub = suggest_scope_from_applicability(excel_tab_name)
        # Only trust tab mapping when it isn't a blind DEFAULT for an unknown tab name
        from app.services.ontology.taxonomy import canonicalize_subdomain
        if canonicalize_subdomain(excel_tab_name):
            sector_raw, subdomain_raw = tab_sec, tab_sub
            tab_mapped = True
            if not domain:
                domain = excel_tab_name

    if not tab_mapped and not sector_raw and not subdomain_raw and applicability:
        # Single known value → use it; multi-value → prefer first that canonicalizes
        from app.services.ontology.taxonomy import canonicalize_subdomain
        parts = [p.strip() for p in applicability.replace("|", ",").replace(";", ",").split(",") if p.strip()]
        picked = None
        for part in parts:
            if canonicalize_subdomain(part):
                picked = part
                break
        if picked:
            sector_raw, subdomain_raw = suggest_scope_from_applicability(picked)
            if not domain:
                domain = applicability
        else:
            sector_raw, subdomain_raw = suggest_scope_from_applicability(applicability)

    if not sector_raw:
        sector_raw = defaults.get("sector")
    if not subdomain_raw:
        subdomain_raw = defaults.get("subdomain")

    sector = validate_sector(sector_raw)
    subdomain = validate_subdomain(sector, subdomain_raw) if sector else None
    if not sector or not subdomain:
        sector, subdomain = normalize_scope(
            sector_raw or None,
            subdomain_raw or None,
            legacy_domain=domain or excel_tab_name or None,
        )
    if not domain:
        domain = excel_tab_name or applicability or f"{sector}/{subdomain}"

    agg = (_cell(row, resolved.get("aggregation_type")) or defaults.get("aggregation_type", "UNKNOWN")).upper()
    if agg == "AVERAGE":
        agg = "AVG"
    if agg not in VALID_AGGREGATIONS:
        agg = "UNKNOWN"

    status = (_cell(row, resolved.get("status")) or defaults.get("status", "active")).lower()
    if status not in VALID_STATUS:
        status = "active"

    created_by = _cell(row, resolved.get("created_by")) or defaults.get("created_by", "excel_seed")
    aliases = _split_list(_cell(row, resolved.get("aliases")))

    for sheet in _split_list(applicability):
        if sheet and sheet not in aliases and sheet.lower() != name.lower():
            aliases.append(sheet)

    if worksheet and worksheet not in aliases and worksheet.lower() != name.lower():
        aliases.append(worksheet)
    if excel_tab_name and excel_tab_name not in aliases and excel_tab_name.lower() != name.lower():
        aliases.append(excel_tab_name)

    dims = _split_list(_cell(row, resolved.get("valid_dimensions")))

    return OntologyKPI(
        kpi_id=str(uuid.uuid4()),
        name=name,
        definition=definition,
        domain=domain,
        sector=sector,
        subdomain=subdomain,
        aliases=json.dumps(aliases),
        aggregation_type=agg,
        valid_dimensions=json.dumps(dims),
        representative_lineage=json.dumps(lineage),
        created_by=created_by,
        status=status,
    )


def list_excel_sheets(path: Path) -> list[str]:
    xl = pd.ExcelFile(path)
    return list(xl.sheet_names)


def inspect_excel(
    path: Path,
    sheet_name: str | int | None,
    column_map: dict,
    *,
    all_sheets: bool = False,
) -> dict:
    sheets = list_excel_sheets(path) if all_sheets or sheet_name is None else None
    if all_sheets:
        per_sheet = []
        for name in sheets or []:
            df = pd.read_excel(path, sheet_name=name)
            resolved = resolve_column_map(list(df.columns), column_map)
            per_sheet.append({
                "sheet": name,
                "excel_headers": [str(c) for c in df.columns],
                "resolved_map": resolved,
                "rows": len(df),
            })
        return {
            "file": str(path),
            "all_sheets": True,
            "sheet_names": sheets,
            "sheets": per_sheet,
            "hint": "Use --all-sheets to load every worksheet in this workbook.",
        }

    df = pd.read_excel(path, sheet_name=sheet_name if sheet_name is not None else 0)
    resolved = resolve_column_map(list(df.columns), column_map)
    unmatched = [c for c in df.columns if c not in resolved.values()]
    return {
        "file": str(path),
        "sheet": sheet_name,
        "sheet_names": list_excel_sheets(path),
        "excel_headers": [str(c) for c in df.columns],
        "resolved_map": resolved,
        "unmatched_excel_headers": [str(c) for c in unmatched],
        "rows": len(df),
        "hint": (
            "Expected headers: Measurement(KPI), Definition, "
            "Fields required to create the Metric, Applicability with Sheet Names. "
            "Pass --all-sheets to read every Excel tab."
        ),
    }


def _find_existing_kpi(db: Session, name: str, sector: str | None, subdomain: str | None):
    return (
        db.query(OntologyKPI)
        .filter(
            OntologyKPI.name == name,
            OntologyKPI.sector == sector,
            OntologyKPI.subdomain == subdomain,
        )
        .first()
    )


def _scope_key(name: str, sector: str | None, subdomain: str | None) -> tuple:
    return ((name or "").strip().lower(), sector or "", subdomain or "")


def _process_dataframe(
    db: Session,
    df: pd.DataFrame,
    column_map: dict[str, list[str]],
    defaults: dict,
    *,
    excel_tab_name: str | None,
    dry_run: bool,
    update_existing: bool,
    preview: list[dict],
    skip_if_invalid: bool = False,
    batch_seen: set | None = None,
) -> tuple[int, int, int, dict[str, str | None], bool]:
    """
    Returns (inserted, updated, skipped, resolved, processed).
    If skip_if_invalid and sheet lacks Measurement(KPI)/name → processed=False.
    Uniqueness is (name, sector, subdomain) — same KPI name OK across sheets.
    """
    resolved = resolve_column_map(list(df.columns), column_map)
    has_name = bool(resolved.get("name") or (resolved.get("table_name") and resolved.get("column_name")))
    if not has_name:
        if skip_if_invalid:
            return 0, 0, 0, resolved, False
        raise ValueError(
            f"Could not resolve Measurement(KPI) / name on sheet '{excel_tab_name}'. "
            f"Headers: {list(df.columns)}. Resolved: {resolved}."
        )

    seen = batch_seen if batch_seen is not None else set()
    inserted = updated = skipped = 0
    for _, row in df.iterrows():
        kpi = row_to_kpi(row, resolved, defaults, excel_tab_name=excel_tab_name)
        if not kpi:
            skipped += 1
            continue

        key = _scope_key(kpi.name, kpi.sector, kpi.subdomain)
        if len(preview) < 10:
            preview.append({
                "name": kpi.name,
                "sheet": excel_tab_name,
                "definition": (kpi.definition or "")[:80],
                "sector": kpi.sector,
                "subdomain": kpi.subdomain,
                "lineage": kpi.representative_lineage,
                "aliases": kpi.aliases,
                "aggregation_type": kpi.aggregation_type,
            })

        existing = _find_existing_kpi(db, kpi.name, kpi.sector, kpi.subdomain)
        if existing or key in seen:
            if existing and update_existing and not dry_run:
                existing.definition = kpi.definition
                existing.domain = kpi.domain
                existing.sector = kpi.sector
                existing.subdomain = kpi.subdomain
                existing.aliases = kpi.aliases
                existing.aggregation_type = kpi.aggregation_type
                existing.valid_dimensions = kpi.valid_dimensions
                existing.representative_lineage = kpi.representative_lineage
                existing.status = kpi.status
                updated += 1
            else:
                skipped += 1
            seen.add(key)
            continue

        seen.add(key)
        if not dry_run:
            db.add(kpi)
            db.flush()  # so later sheets see this row in the same transaction
        inserted += 1

    return inserted, updated, skipped, resolved, True


def seed_from_excel(
    excel_path: str | Path,
    sheet_name: str | int = 0,
    column_map: dict[str, list[str]] | None = None,
    defaults: dict | None = None,
    dry_run: bool = False,
    update_existing: bool = False,
    skip_embed: bool = False,
    *,
    all_sheets: bool = False,
) -> dict:
    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    column_map = column_map or COLUMN_MAP
    defaults = {**DEFAULTS, **(defaults or {})}

    Base.metadata.create_all(bind=engine)
    # Allow same KPI name per subdomain (Marketing vs Distribution)
    try:
        from app.db.migrations.ontology_tables import migrate_ontology_kpi_scoped_unique
        with engine.begin() as conn:
            migrate_ontology_kpi_scoped_unique(conn)
    except Exception:
        pass

    if all_sheets:
        sheet_names = list_excel_sheets(path)
        frames: list[tuple[str, pd.DataFrame]] = [
            (name, pd.read_excel(path, sheet_name=name)) for name in sheet_names
        ]
    else:
        df = pd.read_excel(path, sheet_name=sheet_name)
        tab = sheet_name if isinstance(sheet_name, str) else str(sheet_name)
        if isinstance(sheet_name, int):
            names = list_excel_sheets(path)
            tab = names[sheet_name] if 0 <= sheet_name < len(names) else tab
        frames = [(tab, df)]
        sheet_names = [tab]

    db: Session = SessionLocal()
    inserted = updated = skipped = 0
    preview: list[dict] = []
    resolved_by_sheet: dict[str, dict] = {}
    rows_read = 0
    sheets_loaded: list[str] = []
    sheets_skipped: list[dict] = []
    batch_seen: set = set()

    try:
        for tab_name, df in frames:
            rows_read += len(df)
            ins, upd, skip, resolved, processed = _process_dataframe(
                db,
                df,
                column_map,
                defaults,
                excel_tab_name=tab_name,
                dry_run=dry_run,
                update_existing=update_existing,
                preview=preview,
                skip_if_invalid=all_sheets,
                batch_seen=batch_seen,
            )
            resolved_by_sheet[tab_name] = resolved
            if not processed:
                sheets_skipped.append({
                    "sheet": tab_name,
                    "reason": "no Measurement(KPI)/name column",
                    "headers": [str(c) for c in df.columns],
                })
                continue
            sheets_loaded.append(tab_name)
            inserted += ins
            updated += upd
            skipped += skip

        if all_sheets and not sheets_loaded:
            raise ValueError(
                "No worksheet had Measurement(KPI)/name columns. "
                f"Skipped sheets: {sheets_skipped}. "
                "Run with --inspect --all-sheets to see each tab's headers."
            )

        if not dry_run:
            db.commit()
            if not skip_embed and (inserted or updated):
                embed_ontology_kpis(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {
        "file": str(path),
        "all_sheets": all_sheets,
        "sheets_processed": sheets_loaded,
        "sheets_skipped": sheets_skipped,
        "resolved_map_by_sheet": resolved_by_sheet,
        "rows_read": rows_read,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "dry_run": dry_run,
        "preview_first_10": preview[:10],
    }


def _load_map_json(path: str | None) -> dict[str, list[str]] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("--map-json must be an object of field → [aliases]")
    return {k: (v if isinstance(v, list) else [v]) for k, v in data.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed ontology_kpis from Measurement(KPI) Excel bank format"
    )
    parser.add_argument("excel_path", help="Path to .xlsx / .xls")
    parser.add_argument("--sheet", default="0", help="Sheet name or index (default: 0)")
    parser.add_argument(
        "--all-sheets",
        action="store_true",
        help="Read EVERY worksheet in the Excel file (Marketing, Distribution, Claims_Litigation, ...)",
    )
    parser.add_argument("--inspect", action="store_true", help="Show headers + resolved map only")
    parser.add_argument("--dry-run", action="store_true", help="Preview inserts; do not write")
    parser.add_argument("--update-existing", action="store_true", help="Update rows matched by name")
    parser.add_argument("--skip-embed", action="store_true", help="Skip embedding recomputation")
    parser.add_argument("--map-json", help="Optional JSON override for COLUMN_MAP")
    parser.add_argument("--sector", help=f"Default sector (default: {DEFAULT_SECTOR})")
    parser.add_argument("--subdomain", help=f"Default subdomain (default: {DEFAULT_SUBDOMAIN})")
    args = parser.parse_args(argv)

    sheet: str | int = args.sheet
    if isinstance(sheet, str) and sheet.isdigit():
        sheet = int(sheet)

    column_map = _load_map_json(args.map_json) or COLUMN_MAP
    defaults = dict(DEFAULTS)
    if args.sector:
        defaults["sector"] = args.sector.strip().lower()
    if args.subdomain:
        defaults["subdomain"] = args.subdomain.strip().lower()

    path = Path(args.excel_path)
    if args.inspect:
        print(json.dumps(
            inspect_excel(path, sheet, column_map, all_sheets=args.all_sheets),
            indent=2,
        ))
        return 0

    result = seed_from_excel(
        excel_path=path,
        sheet_name=sheet,
        column_map=column_map,
        defaults=defaults,
        dry_run=args.dry_run,
        update_existing=args.update_existing,
        skip_embed=args.skip_embed,
        all_sheets=args.all_sheets,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
