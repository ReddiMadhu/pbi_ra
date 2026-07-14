"""
Seed the ontology bank (ontology_kpis) from your own Excel files.

Your Excel headers are often inconsistent. Edit COLUMN_MAP below so each
ontology field points at the header name(s) that appear in YOUR file.

Typical use cases:
  A) KPI list          → name + definition (+ sector/subdomain)
  B) Table/column catalog → table_name + column_name → lineage "Table.Column"
     and kpi name from column / worksheet variable

Usage (from backend/):
  py -3 scripts/seed_ontology_from_excel.py path/to/file.xlsx
  py -3 scripts/seed_ontology_from_excel.py path/to/file.xlsx --sheet "Sheet1"
  py -3 scripts/seed_ontology_from_excel.py path/to/file.xlsx --dry-run
  py -3 scripts/seed_ontology_from_excel.py path/to/file.xlsx --update-existing
  py -3 scripts/seed_ontology_from_excel.py path/to/file.xlsx --inspect
      # print detected headers + suggested mapping (no DB write)

Examples of COLUMN_MAP for messy files:
  # File has "KPI Name", "Business Definition", "Source Table", "Source Field"
  COLUMN_MAP = {
      "name": ["KPI Name", "kpi_name", "Measure Name", "Variable"],
      "definition": ["Business Definition", "Description", "Def"],
      "table_name": ["Source Table", "Table", "Datasource Table"],
      "column_name": ["Source Field", "Column", "Field Name"],
      "sector": ["Sector", "LOB Sector"],
      "subdomain": ["Sub Domain", "Subdomain", "Area"],
  }
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

# Allow running as: py -3 scripts/seed_ontology_from_excel.py ...
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
    validate_sector,
    validate_subdomain,
)
import app.models.ontology  # noqa: F401

# ─────────────────────────────────────────────────────────────────────────────
# EDIT THIS SECTION for each Excel file (or pass --map-json)
# ─────────────────────────────────────────────────────────────────────────────
#
# Keys = ontology / script fields
# Values = list of Excel header aliases (first match wins; case/space-insensitive)
#
# Required (one of):
#   name  OR  (table_name + column_name)  — name can be auto-built from lineage
#   definition  OR it will default to "name from table.column"
#
COLUMN_MAP: dict[str, list[str]] = {
    # KPI identity
    "name": [
        "name",
        "kpi",
        "kpi_name",
        "kpi name",
        "measure",
        "measure_name",
        "measure name",
        "variable",
        "variable_name",
        "variable name",
        "worksheet_kpi",
        "metric",
        "metric_name",
    ],
    "definition": [
        "definition",
        "def",
        "description",
        "business_definition",
        "business definition",
        "meaning",
        "desc",
    ],
    # Lineage: Table.Column  (from your worksheets / tables inventory)
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
    # Scope
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
    # Optional enrichment
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

# Defaults applied when Excel has no sector/subdomain columns
DEFAULTS = {
    "sector": DEFAULT_SECTOR,          # insurance | banking | finance | operational
    "subdomain": DEFAULT_SUBDOMAIN,    # e.g. claims | shared | actuarial
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
    return " ".join(str(h).strip().lower().replace("_", " ").split())


def _build_header_index(columns: list) -> dict[str, str]:
    """normalized header → original column name in dataframe."""
    out: dict[str, str] = {}
    for c in columns:
        out[_norm_header(c)] = c
    return out


def resolve_column_map(
    excel_columns: list,
    column_map: dict[str, list[str]],
) -> dict[str, str | None]:
    """
    Map ontology field → actual Excel column name (or None if not found).
    First alias that matches an Excel header wins.
    """
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
    # support comma or pipe or semicolon
    for sep in (",", "|", ";"):
        if sep in text:
            return [p.strip() for p in text.split(sep) if p.strip()]
    return [text]


def _build_lineage(table: str, column: str, explicit: str) -> list[str]:
    if explicit:
        return _split_list(explicit)
    if table and column:
        return [f"{table}.{column}"]
    if column:
        return [column]
    return []


def _build_name(name: str, table: str, column: str, worksheet: str) -> str:
    if name:
        return name
    # Auto-name from table.column / worksheet context when Excel is a field catalog
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
) -> OntologyKPI | None:
    name = _cell(row, resolved.get("name"))
    definition = _cell(row, resolved.get("definition"))
    table = _cell(row, resolved.get("table_name"))
    column = _cell(row, resolved.get("column_name"))
    worksheet = _cell(row, resolved.get("worksheet_name"))
    lineage_raw = _cell(row, resolved.get("representative_lineage"))

    name = _build_name(name, table, column, worksheet)
    if not name:
        return None

    definition = _build_definition(definition, name, table, column, worksheet)
    lineage = _build_lineage(table, column, lineage_raw)

    domain = _cell(row, resolved.get("domain"))
    sector_raw = _cell(row, resolved.get("sector")) or defaults.get("sector")
    subdomain_raw = _cell(row, resolved.get("subdomain")) or defaults.get("subdomain")

    sector = validate_sector(sector_raw)
    subdomain = validate_subdomain(sector, subdomain_raw) if sector else None
    if not sector or not subdomain:
        sector, subdomain = normalize_scope(
            sector_raw or None,
            subdomain_raw or None,
            legacy_domain=domain or None,
        )
    if not domain:
        domain = f"{sector}/{subdomain}"

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
    # Keep worksheet name as an alias so matching can use it later
    if worksheet and worksheet not in aliases and worksheet.lower() != name.lower():
        aliases.append(worksheet)

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


def inspect_excel(path: Path, sheet_name: str | int, column_map: dict) -> dict:
    df = pd.read_excel(path, sheet_name=sheet_name)
    resolved = resolve_column_map(list(df.columns), column_map)
    unmatched = [c for c in df.columns if c not in resolved.values()]
    return {
        "file": str(path),
        "sheet": sheet_name,
        "excel_headers": [str(c) for c in df.columns],
        "resolved_map": resolved,
        "unmatched_excel_headers": [str(c) for c in unmatched],
        "rows": len(df),
        "hint": (
            "Edit COLUMN_MAP at the top of this script so each ontology field "
            "lists the Excel header names you see under excel_headers."
        ),
    }


def seed_from_excel(
    excel_path: str | Path,
    sheet_name: str | int = 0,
    column_map: dict[str, list[str]] | None = None,
    defaults: dict | None = None,
    dry_run: bool = False,
    update_existing: bool = False,
    skip_embed: bool = False,
) -> dict:
    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    column_map = column_map or COLUMN_MAP
    defaults = {**DEFAULTS, **(defaults or {})}

    Base.metadata.create_all(bind=engine)
    df = pd.read_excel(path, sheet_name=sheet_name)
    resolved = resolve_column_map(list(df.columns), column_map)

    if not resolved.get("name") and not (resolved.get("table_name") and resolved.get("column_name")):
        raise ValueError(
            "Could not resolve a KPI name source. Map either 'name' or both "
            f"'table_name' + 'column_name'. Detected headers: {list(df.columns)}. "
            f"Resolved: {resolved}. Run with --inspect and edit COLUMN_MAP."
        )

    db: Session = SessionLocal()
    inserted = 0
    updated = 0
    skipped = 0
    preview: list[dict] = []

    try:
        for _, row in df.iterrows():
            kpi = row_to_kpi(row, resolved, defaults)
            if not kpi:
                skipped += 1
                continue

            preview.append({
                "name": kpi.name,
                "definition": (kpi.definition or "")[:80],
                "sector": kpi.sector,
                "subdomain": kpi.subdomain,
                "lineage": kpi.representative_lineage,
                "aggregation_type": kpi.aggregation_type,
            })

            existing = db.query(OntologyKPI).filter(OntologyKPI.name == kpi.name).first()
            if existing:
                if update_existing and not dry_run:
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
                continue

            if not dry_run:
                db.add(kpi)
            inserted += 1

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
        "sheet": sheet_name,
        "resolved_map": resolved,
        "rows_read": len(df),
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
        description="Seed ontology_kpis from inconsistent Excel (editable COLUMN_MAP)"
    )
    parser.add_argument("excel_path", help="Path to .xlsx / .xls")
    parser.add_argument("--sheet", default="0", help="Sheet name or index (default: 0)")
    parser.add_argument("--inspect", action="store_true", help="Show headers + resolved map only")
    parser.add_argument("--dry-run", action="store_true", help="Preview inserts; do not write")
    parser.add_argument("--update-existing", action="store_true", help="Update rows matched by name")
    parser.add_argument("--skip-embed", action="store_true", help="Skip embedding recomputation")
    parser.add_argument(
        "--map-json",
        help="Optional JSON file overriding COLUMN_MAP, e.g. "
             '{"name":["KPI Name"],"table_name":["Table"],"column_name":["Field"]}',
    )
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
        print(json.dumps(inspect_excel(path, sheet, column_map), indent=2))
        return 0

    result = seed_from_excel(
        excel_path=path,
        sheet_name=sheet,
        column_map=column_map,
        defaults=defaults,
        dry_run=args.dry_run,
        update_existing=args.update_existing,
        skip_embed=args.skip_embed,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
