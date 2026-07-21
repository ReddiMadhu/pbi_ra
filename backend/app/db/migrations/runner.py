"""Lightweight schema migration runner for SQLite.

Tracks applied migrations in a ``schema_migrations`` table so each
migration runs exactly once.  Errors are logged with full context
instead of being silently swallowed.

Usage from the app lifespan::

    from app.db.migrations.runner import run_migrations
    run_migrations(engine)
"""

import logging
from datetime import datetime

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Each migration is a (unique_id, description, SQL_statement) tuple.
# New migrations MUST be appended at the end — never reorder or remove.
# ---------------------------------------------------------------------------
MIGRATIONS: list[tuple[str, str, str]] = [
    (
        "001_ws_workbook_id",
        "Add workbook_id FK to worksheets",
        "ALTER TABLE worksheets ADD COLUMN workbook_id INTEGER REFERENCES workbooks(id);",
    ),
    (
        "002_tables_columns",
        "Add columns JSON to tables",
        "ALTER TABLE tables ADD COLUMN columns JSON;",
    ),
    (
        "003_tables_rows",
        "Add rows JSON to tables",
        "ALTER TABLE tables ADD COLUMN rows JSON;",
    ),
    (
        "004_dashboards_is_real_ai",
        "Add is_real_ai flag to dashboards",
        "ALTER TABLE dashboards ADD COLUMN is_real_ai INTEGER DEFAULT 0;",
    ),
    (
        "005_ws_measure_bindings",
        "Add measure_bindings JSON to worksheets",
        "ALTER TABLE worksheets ADD COLUMN measure_bindings JSON;",
    ),
    (
        "006_rkm_worksheet_id",
        "Add worksheet_id to report_kpi_mappings",
        "ALTER TABLE report_kpi_mappings ADD COLUMN worksheet_id TEXT;",
    ),
    (
        "007_rkm_worksheet_name",
        "Add worksheet_name to report_kpi_mappings",
        "ALTER TABLE report_kpi_mappings ADD COLUMN worksheet_name TEXT;",
    ),
    (
        "008_okpi_representative_lineage",
        "Add representative_lineage to ontology_kpis",
        "ALTER TABLE ontology_kpis ADD COLUMN representative_lineage TEXT;",
    ),
    (
        "009_okpi_sector",
        "Add sector to ontology_kpis",
        "ALTER TABLE ontology_kpis ADD COLUMN sector TEXT;",
    ),
    (
        "010_okpi_subdomain",
        "Add subdomain to ontology_kpis",
        "ALTER TABLE ontology_kpis ADD COLUMN subdomain TEXT;",
    ),
    (
        "011_dashboards_ontology_sector",
        "Add ontology_sector to dashboards",
        "ALTER TABLE dashboards ADD COLUMN ontology_sector TEXT;",
    ),
    (
        "012_dashboards_ontology_subdomain",
        "Add ontology_subdomain to dashboards",
        "ALTER TABLE dashboards ADD COLUMN ontology_subdomain TEXT;",
    ),
    (
        "013_rkm_report_kpi_definition",
        "Add report_kpi_definition to report_kpi_mappings",
        "ALTER TABLE report_kpi_mappings ADD COLUMN report_kpi_definition TEXT;",
    ),
    (
        "014_drop_old_rkm_index",
        "Drop legacy idx_rkm_report_canonical index",
        "DROP INDEX IF EXISTS idx_rkm_report_canonical;",
    ),
    (
        "015_create_rkm_ws_kpi_unique_index",
        "Create unique index on (report_id, worksheet_id, report_kpi_name)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_rkm_report_ws_kpi "
        "ON report_kpi_mappings (report_id, worksheet_id, report_kpi_name);",
    ),
    (
        "017_rkm_mapping_type",
        "Add mapping_type to report_kpi_mappings",
        "ALTER TABLE report_kpi_mappings ADD COLUMN mapping_type TEXT;",
    ),
    (
        "018_rkm_alternative_candidates",
        "Add alternative_candidates to report_kpi_mappings",
        "ALTER TABLE report_kpi_mappings ADD COLUMN alternative_candidates TEXT;",
    ),
    (
        "019_okpi_embedding_model",
        "Add embedding_model to ontology_kpis",
        "ALTER TABLE ontology_kpis ADD COLUMN embedding_model TEXT;",
    ),
    (
        "020_create_mapping_audit_log",
        "Create mapping_audit_log table for governance trail",
        "CREATE TABLE IF NOT EXISTS mapping_audit_log ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  mapping_id TEXT NOT NULL,"
        "  field_changed TEXT NOT NULL,"
        "  original_value TEXT,"
        "  new_value TEXT,"
        "  reason TEXT,"
        "  approval_user TEXT NOT NULL DEFAULT 'analyst',"
        "  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP"
        ");",
    ),
    (
        "021_rkm_formula_similarity",
        "Add formula_similarity to report_kpi_mappings",
        "ALTER TABLE report_kpi_mappings ADD COLUMN formula_similarity REAL;",
    ),
    (
        "022_rkm_warnings",
        "Add warnings to report_kpi_mappings",
        "ALTER TABLE report_kpi_mappings ADD COLUMN warnings TEXT;",
    ),
    (
        "023_rkm_approval_decision",
        "Add approval_decision to report_kpi_mappings",
        "ALTER TABLE report_kpi_mappings ADD COLUMN approval_decision TEXT;",
    ),
    (
        "024_audit_log_mapping_id_index",
        "Index mapping_audit_log by mapping_id",
        "CREATE INDEX IF NOT EXISTS idx_audit_mapping_id ON mapping_audit_log (mapping_id);",
    ),
    (
        "025_okpi_line_of_business",
        "Add line_of_business to ontology_kpis",
        "ALTER TABLE ontology_kpis ADD COLUMN line_of_business TEXT;",
    ),
    (
        "026_dashboard_scope_status",
        "Add scope_status to dashboards table",
        "ALTER TABLE dashboards ADD COLUMN scope_status TEXT DEFAULT 'pending_approval';",
    ),
]

# Special migrations that need Python logic (not raw SQL)
PYTHON_MIGRATIONS: list[tuple[str, str]] = [
    (
        "016_okpi_scoped_unique",
        "Rebuild ontology_kpis for UNIQUE(name, sector, subdomain)",
    ),
]


def _ensure_tracking_table(conn) -> None:
    """Create the migration tracking table if it doesn't exist."""
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_id TEXT PRIMARY KEY,
                description  TEXT NOT NULL,
                applied_at   TEXT NOT NULL
            )
            """
        )
    )


def _is_applied(conn, migration_id: str) -> bool:
    """Check if a migration has already been applied."""
    row = conn.execute(
        text("SELECT 1 FROM schema_migrations WHERE migration_id = :mid"),
        {"mid": migration_id},
    ).fetchone()
    return row is not None


def _mark_applied(conn, migration_id: str, description: str) -> None:
    """Record a migration as applied."""
    conn.execute(
        text(
            "INSERT INTO schema_migrations (migration_id, description, applied_at) "
            "VALUES (:mid, :desc, :ts)"
        ),
        {
            "mid": migration_id,
            "desc": description,
            "ts": datetime.utcnow().isoformat(),
        },
    )


def _column_exists(conn, table: str, column: str) -> bool:
    """Check if a column already exists on a SQLite table."""
    rows = conn.execute(text(f"PRAGMA table_info('{table}')")).fetchall()
    return any(r[1] == column for r in rows)


def run_migrations(engine) -> int:
    """Run all pending migrations. Returns count of newly applied migrations."""
    applied = 0

    with engine.begin() as conn:
        _ensure_tracking_table(conn)

        # --- SQL migrations -------------------------------------------
        for mid, desc, sql in MIGRATIONS:
            if _is_applied(conn, mid):
                continue

            # For ALTER TABLE ADD COLUMN, check if column already exists
            # (handles databases created before the tracker was introduced)
            if "ADD COLUMN" in sql.upper():
                parts = sql.upper().split("ADD COLUMN")
                table_part = parts[0].replace("ALTER TABLE", "").strip()
                col_part = parts[1].strip().split()[0]
                if _column_exists(conn, table_part.lower(), col_part.lower()):
                    logger.info(
                        "Migration %s: column already exists, marking as applied",
                        mid,
                    )
                    _mark_applied(conn, mid, desc)
                    continue

            try:
                conn.execute(text(sql))
                _mark_applied(conn, mid, desc)
                applied += 1
                logger.info("Migration %s applied: %s", mid, desc)
            except Exception as exc:
                # Check for "duplicate column" which means the column was added
                # outside the tracker — mark it applied and move on
                err_msg = str(exc).lower()
                if "duplicate column" in err_msg or "already exists" in err_msg:
                    logger.info(
                        "Migration %s: already applied (detected from error), marking",
                        mid,
                    )
                    _mark_applied(conn, mid, desc)
                else:
                    logger.error(
                        "Migration %s FAILED: %s | SQL: %s",
                        mid,
                        exc,
                        sql,
                    )
                    raise  # Stop on real errors — don't silently continue

        # --- Python migrations ----------------------------------------
        for mid, desc in PYTHON_MIGRATIONS:
            if _is_applied(conn, mid):
                continue
            try:
                from app.db.migrations.ontology_tables import (
                    migrate_ontology_kpi_scoped_unique,
                )

                rebuilt = migrate_ontology_kpi_scoped_unique(conn)
                _mark_applied(conn, mid, desc)
                applied += 1
                logger.info(
                    "Migration %s applied: %s (rebuilt=%s)", mid, desc, rebuilt
                )
            except Exception as exc:
                logger.error("Migration %s FAILED: %s", mid, exc)
                raise

    logger.info(
        "Schema migrations complete: %d newly applied, %d total tracked",
        applied,
        len(MIGRATIONS) + len(PYTHON_MIGRATIONS),
    )
    return applied
