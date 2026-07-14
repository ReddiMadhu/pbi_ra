"""
Import canonical KPIs from an Excel file into ontology_kpis (SQLite).

Expected Excel columns (header row required) — bank format:
  Measurement(KPI)                         | required | unique canonical KPI name
  Definition                               | required | business definition
  Fields required to create the Metric     | optional | comma-separated lineage fields
  Applicability with Sheet Names           | optional | e.g. Marketing, Claims_Litigation
                                           |         | → aliases + sector/subdomain

Also accepts legacy / alternate headers:
  name, definition, sector, subdomain, domain, aliases, aggregation_type,
  valid_dimensions, representative_lineage, status

Usage:
  py -3 -m app.services.ontology.import_ontology_excel path/to/kpi_bank.xlsx
  py -3 -m app.services.ontology.import_ontology_excel path/to/kpi_bank.xlsx --sheet "KPI Bank"
  py -3 -m app.services.ontology.import_ontology_excel path/to/kpi_bank.xlsx --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine, Base
from app.models.ontology import OntologyKPI
from app.services.ontology.embedding_service import embed_ontology_kpis
from app.services.ontology.taxonomy import (
    normalize_scope,
    suggest_scope_from_applicability,
    validate_sector,
    validate_subdomain,
)
import app.models.ontology  # noqa: F401

# Logical field → Excel header aliases (first match wins after normalization)
COLUMN_ALIASES: dict[str, list[str]] = {
    "name": [
        "Measurement(KPI)",
        "Measurement (KPI)",
        "Measurement",
        "name",
        "kpi",
        "kpi_name",
        "kpi name",
        "measure",
        "metric",
    ],
    "definition": ["Definition", "definition", "description", "business definition"],
    "fields_required": [
        "Fields required to create the Metric",
        "Fields Required to Create the Metric",
        "Fields required to create Metric",
        "Felids required to create the Metric",
        "fields_required",
        "required fields",
    ],
    "applicability": [
        "Applicability with Sheet Names",
        "Applicablity with Sheet Names",
        "Applicability",
        "applicable_sheets",
    ],
    "sector": ["sector"],
    "subdomain": ["subdomain", "sub domain"],
    "domain": ["domain"],
    "aliases": ["aliases", "alias"],
    "aggregation_type": ["aggregation_type", "aggregation", "agg"],
    "valid_dimensions": ["valid_dimensions", "dimensions"],
    "representative_lineage": ["representative_lineage", "lineage"],
    "created_by": ["created_by"],
    "status": ["status"],
}

REQUIRED_LOGICAL = {"name", "definition"}
VALID_AGGREGATIONS = {
    "SUM", "AVG", "AVERAGE", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN",
    "ATTR", "NONE", "UNKNOWN", "PCT", "STDEV", "VAR", "SUM_SQR",
}
VALID_STATUS = {"active", "stale"}


def _norm_header(h: str) -> str:
    text = str(h).strip().lower().replace("_", " ")
    text = re.sub(r"[()\[\]{}]", " ", text)
    text = re.sub(r"[^\w\s&+-]", " ", text)
    return " ".join(text.split())


def _resolve_headers(df: pd.DataFrame) -> dict[str, str | None]:
    index = {_norm_header(c): c for c in df.columns}
    resolved: dict[str, str | None] = {}
    for field, aliases in COLUMN_ALIASES.items():
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


def _split_list(value) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    for sep in (",", "|", ";"):
        if sep in text:
            return [part.strip() for part in text.split(sep) if part.strip()]
    return [text]


def _row_to_kpi(
    row: pd.Series,
    resolved: dict[str, str | None],
    created_by_default: str,
    *,
    excel_tab_name: str | None = None,
) -> OntologyKPI | None:
    name = _cell(row, resolved.get("name"))
    definition = _cell(row, resolved.get("definition"))
    if not name or not definition:
        return None

    domain = _cell(row, resolved.get("domain"))
    applicability = _cell(row, resolved.get("applicability"))
    if not applicability and excel_tab_name:
        applicability = excel_tab_name

    sector_raw = _cell(row, resolved.get("sector"))
    subdomain_raw = _cell(row, resolved.get("subdomain"))

    if not sector_raw and not subdomain_raw and applicability:
        sector_raw, subdomain_raw = suggest_scope_from_applicability(applicability)
        if not domain:
            domain = applicability

    sector = validate_sector(sector_raw or None)
    subdomain = validate_subdomain(sector, subdomain_raw or None) if sector else None
    if not sector or not subdomain:
        sector, subdomain = normalize_scope(
            sector_raw or None,
            subdomain_raw or None,
            legacy_domain=domain or None,
        )
    if not domain:
        domain = applicability or f"{sector}/{subdomain}"

    agg = (_cell(row, resolved.get("aggregation_type")) or "UNKNOWN").upper()
    if agg == "AVERAGE":
        agg = "AVG"
    if agg not in VALID_AGGREGATIONS:
        agg = "UNKNOWN"

    status = (_cell(row, resolved.get("status")) or "active").lower()
    if status not in VALID_STATUS:
        status = "active"

    created_by = _cell(row, resolved.get("created_by")) or created_by_default

    aliases = _split_list(_cell(row, resolved.get("aliases")))
    for sheet in _split_list(applicability):
        if sheet and sheet not in aliases and sheet.lower() != name.lower():
            aliases.append(sheet)
    if excel_tab_name and excel_tab_name not in aliases and excel_tab_name.lower() != name.lower():
        aliases.append(excel_tab_name)

    fields_required = _cell(row, resolved.get("fields_required"))
    lineage_raw = _cell(row, resolved.get("representative_lineage"))
    lineage = _split_list(lineage_raw) if lineage_raw else _split_list(fields_required)

    return OntologyKPI(
        kpi_id=str(uuid.uuid4()),
        name=name,
        definition=definition,
        domain=domain,
        sector=sector,
        subdomain=subdomain,
        aliases=json.dumps(aliases),
        aggregation_type=agg,
        valid_dimensions=json.dumps(_split_list(_cell(row, resolved.get("valid_dimensions")))),
        representative_lineage=json.dumps(lineage),
        created_by=created_by,
        status=status,
    )


def import_ontology_excel(
    excel_path: str | Path,
    sheet_name: str | int = 0,
    created_by_default: str = "excel_import",
    dry_run: bool = False,
    update_existing: bool = False,
    *,
    all_sheets: bool = False,
) -> dict:
    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    Base.metadata.create_all(bind=engine)

    xl = pd.ExcelFile(path)
    if all_sheets:
        frames: list[tuple[str, pd.DataFrame]] = [
            (name, pd.read_excel(path, sheet_name=name)) for name in xl.sheet_names
        ]
    else:
        df = pd.read_excel(path, sheet_name=sheet_name)
        tab = sheet_name if isinstance(sheet_name, str) else (
            xl.sheet_names[sheet_name] if isinstance(sheet_name, int) and 0 <= sheet_name < len(xl.sheet_names)
            else str(sheet_name)
        )
        frames = [(tab, df)]

    db: Session = SessionLocal()
    inserted = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    rows_read = 0
    sheets_processed: list[str] = []
    resolved_by_sheet: dict[str, dict] = {}

    try:
        for tab_name, df in frames:
            sheets_processed.append(tab_name)
            rows_read += len(df)
            resolved = _resolve_headers(df)
            resolved_by_sheet[tab_name] = resolved

            missing = [f for f in REQUIRED_LOGICAL if not resolved.get(f)]
            if missing:
                raise ValueError(
                    f"Sheet '{tab_name}' missing required columns for: {', '.join(missing)}. "
                    f"Need Measurement(KPI)/name and Definition. "
                    f"Detected headers: {list(df.columns)}. Resolved: {resolved}"
                )

            for _, row in df.iterrows():
                kpi = _row_to_kpi(row, resolved, created_by_default, excel_tab_name=tab_name)
                if not kpi:
                    skipped += 1
                    continue

                existing = db.query(OntologyKPI).filter(OntologyKPI.name == kpi.name).first()
                if existing:
                    if update_existing:
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
            embed_ontology_kpis(db)
    except Exception as exc:
        db.rollback()
        errors.append(str(exc))
        raise
    finally:
        db.close()

    return {
        "file": str(path),
        "all_sheets": all_sheets,
        "sheets_processed": sheets_processed,
        "resolved_map_by_sheet": resolved_by_sheet,
        "rows_read": rows_read,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "dry_run": dry_run,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import ontology KPIs from Excel into SQLite")
    parser.add_argument("excel_path", help="Path to .xlsx file")
    parser.add_argument("--sheet", default=0, help="Sheet name or index (default: 0)")
    parser.add_argument(
        "--all-sheets",
        action="store_true",
        help="Read EVERY worksheet (Marketing, Distribution, Claims_Litigation, ...)",
    )
    parser.add_argument("--created-by", default="excel_import", help="Default created_by value")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write to DB")
    parser.add_argument("--update-existing", action="store_true", help="Update rows that match by name")
    args = parser.parse_args(argv)

    sheet: str | int = args.sheet
    if isinstance(sheet, str) and sheet.isdigit():
        sheet = int(sheet)

    result = import_ontology_excel(
        excel_path=args.excel_path,
        sheet_name=sheet,
        created_by_default=args.created_by,
        dry_run=args.dry_run,
        update_existing=args.update_existing,
        all_sheets=args.all_sheets,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
