import logging
import time

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.metadata import WorkbookMetadata
from app.models.postgres import (
    Workbook, Dashboard, Worksheet, CalculatedField,
    DatasourceModel, TableModel, TableJoin
)
from app.models.ontology import ReportKPIMapping
from app.agents.workflows import run_governance_workflow

logger = logging.getLogger(__name__)


def _retry_commit(session: Session, *, max_retries: int = 5, label: str = ""):
    """Commit with exponential-backoff retry on SQLite 'database is locked'."""
    for attempt in range(1, max_retries + 1):
        try:
            session.commit()
            return
        except OperationalError as exc:
            if "database is locked" in str(exc) and attempt < max_retries:
                wait = 0.5 * (2 ** (attempt - 1))   # 0.5, 1, 2, 4, 8
                logger.warning(
                    "database is locked during %s (attempt %d/%d), retrying in %.1fs...",
                    label or "commit", attempt, max_retries, wait,
                )
                session.rollback()
                time.sleep(wait)
            else:
                raise


def sync_metadata_to_db(metadata: WorkbookMetadata, pg_session: Session):
    # ── 0. Dynamic Schema Migrations (Ensures DB schema is hotfixed without requiring a backend restart) ──
    from sqlalchemy import text
    from app.db.session import engine
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE worksheets ADD COLUMN workbook_id INTEGER REFERENCES workbooks(id);"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE tables ADD COLUMN columns JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE tables ADD COLUMN rows JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE worksheets ADD COLUMN columns JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE worksheets ADD COLUMN rows JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE worksheets ADD COLUMN filters_and_marks JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dashboards ADD COLUMN is_real_ai INTEGER DEFAULT 0;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dashboards ADD COLUMN raw_metadata JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE tables ADD COLUMN business_name VARCHAR;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE worksheets ADD COLUMN measure_bindings JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE report_kpi_mappings ADD COLUMN worksheet_id TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE report_kpi_mappings ADD COLUMN worksheet_name TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE report_kpi_mappings ADD COLUMN report_kpi_definition TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE ontology_kpis ADD COLUMN representative_lineage TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE ontology_kpis ADD COLUMN sector TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE ontology_kpis ADD COLUMN subdomain TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dashboards ADD COLUMN ontology_sector TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dashboards ADD COLUMN ontology_subdomain TEXT;"))
        except Exception:
            pass
        try:
            from app.db.migrations.ontology_tables import migrate_ontology_kpi_scoped_unique
            migrate_ontology_kpi_scoped_unique(conn)
        except Exception:
            pass
        try:
            conn.execute(text("DROP INDEX IF EXISTS idx_rkm_report_canonical;"))
        except Exception:
            pass
        try:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_rkm_report_ws_kpi "
                "ON report_kpi_mappings (report_id, worksheet_id, report_kpi_name);"
            ))
        except Exception:
            pass


    # Delete existing workbook
    existing_wb = pg_session.query(Workbook).filter(Workbook.source_file == metadata.source_file).first()
    if existing_wb:
        from app.models.postgres import GovernanceRisk
        # Delete related tables and joins first
        for ds in pg_session.query(DatasourceModel).filter(DatasourceModel.workbook_id == existing_wb.id).all():
            pg_session.query(TableJoin).filter(TableJoin.datasource_id == ds.id).delete()
            pg_session.query(TableModel).filter(TableModel.datasource_id == ds.id).delete()
        pg_session.query(DatasourceModel).filter(DatasourceModel.workbook_id == existing_wb.id).delete()
        
        # Delete related worksheets, calculated fields, risks, and ontology mappings
        for dash in pg_session.query(Dashboard).filter(Dashboard.workbook_id == existing_wb.id).all():
            pg_session.query(CalculatedField).filter(CalculatedField.dashboard_id == dash.id).delete()
            pg_session.query(GovernanceRisk).filter(GovernanceRisk.dashboard_id == dash.id).delete()
            # Fix #2: clean up ReportKPIMapping rows tied to old dashboard IDs
            pg_session.query(ReportKPIMapping).filter(
                ReportKPIMapping.report_id == str(dash.id)
            ).delete()
        pg_session.query(Worksheet).filter(Worksheet.workbook_id == existing_wb.id).delete()
        pg_session.query(Dashboard).filter(Dashboard.workbook_id == existing_wb.id).delete()
        
        # Delete the workbook itself
        pg_session.delete(existing_wb)
        pg_session.commit()

    # ── 1. Workbook ───────────────────────────────────────────────
    wb_db = Workbook(
        name=metadata.source_file,
        source_file=metadata.source_file,
        version=metadata.version
    )
    pg_session.add(wb_db)
    _retry_commit(pg_session, label=f"workbook {metadata.source_file}")
    pg_session.refresh(wb_db)

    # ── 2. Datasources, Tables, Joins ─────────────────────────────
    for ds_meta in metadata.datasources:
        ds_db = DatasourceModel(
            workbook_id=wb_db.id,
            name=ds_meta.name,
            caption=ds_meta.caption
        )
        pg_session.add(ds_db)
        _retry_commit(pg_session, label="datasource")
        pg_session.refresh(ds_db)

        # Tables
        table_name_to_id = {}
        for tbl in ds_meta.tables:
            tbl_db = TableModel(
                datasource_id=ds_db.id,
                name=tbl.name,
                columns=tbl.columns_preview,
                rows=tbl.rows_preview
            )
            pg_session.add(tbl_db)
            _retry_commit(pg_session, label="table")
            pg_session.refresh(tbl_db)
            table_name_to_id[tbl.name] = tbl_db.id

        # Join relationships
        for join in ds_meta.joins:
            join_db = TableJoin(
                datasource_id=ds_db.id,
                left_table=join.left_table,
                right_table=join.right_table,
                join_type=join.join_type,
                left_column=join.left_column,
                right_column=join.right_column
            )
            pg_session.add(join_db)

    _retry_commit(pg_session, label="joins")

    # ── 3. Dashboards, Worksheets, CalculatedFields ───────────────
    db_id_mapping = {}

    for db_meta in metadata.dashboards:
        raw_meta = {
            "worksheets": db_meta.worksheets,
            "tables": list({tbl.name for ds in metadata.datasources for tbl in ds.tables}),
            "calculated_fields": list({cf.caption or cf.name for ds in metadata.datasources for cf in ds.calculated_fields})
        }
        
        dash_db = Dashboard(
            workbook_id=wb_db.id, 
            name=db_meta.name,
            raw_metadata=raw_meta
        )
        pg_session.add(dash_db)
        _retry_commit(pg_session, label="dashboard")
        pg_session.refresh(dash_db)
        db_id_mapping[db_meta.name] = dash_db.id

        for ws_name in db_meta.worksheets:
            ws_obj = next((w for w in metadata.worksheets if w.name == ws_name), None)
            if ws_obj:
                pg_session.add(Worksheet(
                    workbook_id=wb_db.id,
                    dashboard_id=dash_db.id, 
                    name=ws_name,
                    used_calculated_fields=ws_obj.used_calculated_fields,
                    rows=ws_obj.rows,
                    columns=ws_obj.columns,
                    filters_and_marks=ws_obj.filters_and_marks,
                    mark_type=ws_obj.mark_type,
                    measure_bindings=ws_obj.measure_bindings,
                ))
            else:
                pg_session.add(Worksheet(workbook_id=wb_db.id, dashboard_id=dash_db.id, name=ws_name))

    # Save orphaned worksheets (those not attached to any dashboard)
    used_worksheets = {ws_name for db in metadata.dashboards for ws_name in db.worksheets}
    for ws_obj in metadata.worksheets:
        if ws_obj.name not in used_worksheets:
            pg_session.add(Worksheet(
                workbook_id=wb_db.id,
                dashboard_id=None,
                name=ws_obj.name,
                used_calculated_fields=ws_obj.used_calculated_fields,
                rows=ws_obj.rows,
                columns=ws_obj.columns,
                filters_and_marks=ws_obj.filters_and_marks,
                mark_type=ws_obj.mark_type,
                measure_bindings=ws_obj.measure_bindings,
            ))

    # Calculated fields — attach to every dashboard that references them
    cf_names = set()
    for ds_meta in metadata.datasources:
        for cf in ds_meta.calculated_fields:
            cf_name = cf.caption or cf.name
            if cf_name in cf_names:
                continue
            cf_names.add(cf_name)
            attached = False
            for dash_db_obj in wb_db.dashboards:
                dash_ws_names = {ws.name for ws in dash_db_obj.worksheets}
                uses_cf = any(
                    cf_name in (getattr(ws_obj, 'used_calculated_fields', None) or [])
                    for ws_obj in metadata.worksheets
                    if ws_obj.name in dash_ws_names
                )
                if uses_cf:
                    pg_session.add(CalculatedField(
                        dashboard_id=dash_db_obj.id,
                        name=cf_name,
                        formula=cf.formula,
                        datatype=cf.datatype,
                    ))
                    attached = True
            # Fallback: attach to first dashboard if no worksheet match found
            if not attached and wb_db.dashboards:
                pg_session.add(CalculatedField(
                    dashboard_id=wb_db.dashboards[0].id,
                    name=cf_name,
                    formula=cf.formula,
                    datatype=cf.datatype,
                ))

    _retry_commit(pg_session, label="worksheets & calc_fields")

    # ── 4. AI Governance Workflow ─────────────────────────────────
    try:
        run_governance_workflow(metadata, pg_session, db_id_mapping)
    except OperationalError as e:
        if "database is locked" in str(e):
            logger.warning(
                "Governance workflow commit failed (database locked) for %s — "
                "metadata is saved; AI summary will be populated on next upload.",
                metadata.source_file,
            )
            pg_session.rollback()
        else:
            raise
