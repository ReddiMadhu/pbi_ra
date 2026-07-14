"""
Import canonical KPIs from an Excel file into ontology_kpis (SQLite).

Expected Excel columns (header row required):
  name              | required | unique canonical KPI name
  definition        | required | business definition
  sector            | required | insurance | banking | finance | operational
  subdomain         | required | e.g. claims, actuarial, underwriting (per sector)
  domain            | optional | legacy display label; defaults to sector/subdomain
  aliases           | optional | comma-separated: "Revenue, Net Sales"
  aggregation_type  | optional | SUM | AVG | COUNT | NONE | UNKNOWN
  valid_dimensions  | optional | comma-separated: "Region, Time"
  representative_lineage  | optional | comma-separated or JSON: "Sales.Amount"
  status            | optional | active | stale (default: active)

Usage:
  py -3 -m app.services.ontology.import_ontology_excel path/to/kpi_bank.xlsx
  py -3 -m app.services.ontology.import_ontology_excel path/to/kpi_bank.xlsx --sheet "KPI Bank"
  py -3 -m app.services.ontology.import_ontology_excel path/to/kpi_bank.xlsx --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine, Base
from app.models.ontology import OntologyKPI
from app.services.ontology.embedding_service import embed_ontology_kpis
from app.services.ontology.taxonomy import normalize_scope, validate_sector, validate_subdomain
import app.models.ontology  # noqa: F401

REQUIRED_COLUMNS = {"name", "definition", "sector", "subdomain"}
OPTIONAL_COLUMNS = {
    "domain",
    "aliases",
    "aggregation_type",
    "valid_dimensions",
    "representative_lineage",
    "created_by",
    "status",
}
VALID_AGGREGATIONS = {
    "SUM", "AVG", "AVERAGE", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN",
    "ATTR", "NONE", "UNKNOWN", "PCT", "STDEV", "VAR", "SUM_SQR",
}
VALID_STATUS = {"active", "stale"}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _split_list(value) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _row_to_kpi(row: pd.Series, created_by_default: str) -> OntologyKPI | None:
    name = str(row.get("name", "")).strip()
    definition = str(row.get("definition", "")).strip()
    if not name or not definition or name.lower() == "nan" or definition.lower() == "nan":
        return None

    domain = str(row.get("domain", "")).strip()
    if domain.lower() == "nan" or not domain:
        domain = ""

    sector_raw = row.get("sector")
    subdomain_raw = row.get("subdomain")
    sector = validate_sector(str(sector_raw).strip() if sector_raw is not None and str(sector_raw).lower() != "nan" else None)
    subdomain = validate_subdomain(sector, str(subdomain_raw).strip() if subdomain_raw is not None and str(subdomain_raw).lower() != "nan" else None) if sector else None
    if not sector or not subdomain:
        sector, subdomain = normalize_scope(
            str(sector_raw) if sector_raw is not None else None,
            str(subdomain_raw) if subdomain_raw is not None else None,
            legacy_domain=domain or None,
        )
    if not domain:
        domain = f"{sector}/{subdomain}"

    agg = str(row.get("aggregation_type", "UNKNOWN")).strip().upper()
    if agg == "AVERAGE":
        agg = "AVG"
    if agg not in VALID_AGGREGATIONS:
        agg = "UNKNOWN"

    status = str(row.get("status", "active")).strip().lower()
    if status not in VALID_STATUS:
        status = "active"

    created_by = str(row.get("created_by", created_by_default)).strip() or created_by_default

    return OntologyKPI(
        kpi_id=str(uuid.uuid4()),
        name=name,
        definition=definition,
        domain=domain,
        sector=sector,
        subdomain=subdomain,
        aliases=json.dumps(_split_list(row.get("aliases"))),
        aggregation_type=agg,
        valid_dimensions=json.dumps(_split_list(row.get("valid_dimensions"))),
        representative_lineage=json.dumps(_split_list(row.get("representative_lineage"))),
        created_by=created_by,
        status=status,
    )


def import_ontology_excel(
    excel_path: str | Path,
    sheet_name: str | int = 0,
    created_by_default: str = "excel_import",
    dry_run: bool = False,
    update_existing: bool = False,
) -> dict:
    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    Base.metadata.create_all(bind=engine)

    df = pd.read_excel(path, sheet_name=sheet_name)
    df = _normalize_columns(df)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    db: Session = SessionLocal()
    inserted = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    try:
        for idx, row in df.iterrows():
            kpi = _row_to_kpi(row, created_by_default)
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
        "rows_read": len(df),
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
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
