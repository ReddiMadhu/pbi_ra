from sqlalchemy.orm import Session
from app.models.metadata import WorkbookMetadata
from app.models.postgres import (
    Workbook, Dashboard, Worksheet, CalculatedField,
    DatasourceModel, TableModel, TableJoin
)
from app.agents.workflows import run_governance_workflow


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
        
        # Delete related worksheets, calculated fields, and risks
        for dash in pg_session.query(Dashboard).filter(Dashboard.workbook_id == existing_wb.id).all():
            pg_session.query(CalculatedField).filter(CalculatedField.dashboard_id == dash.id).delete()
            pg_session.query(GovernanceRisk).filter(GovernanceRisk.dashboard_id == dash.id).delete()
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
    pg_session.commit()
    pg_session.refresh(wb_db)

    # ── 2. Datasources, Tables, Joins ─────────────────────────────
    for ds_meta in metadata.datasources:
        ds_db = DatasourceModel(
            workbook_id=wb_db.id,
            name=ds_meta.name,
            caption=ds_meta.caption
        )
        pg_session.add(ds_db)
        pg_session.commit()
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
            pg_session.commit()
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

    pg_session.commit()

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
        pg_session.commit()
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

    # Calculated fields — attach to first dashboard as before
    for ds_meta in metadata.datasources:
        for cf in ds_meta.calculated_fields:
            dash_id = wb_db.dashboards[0].id if wb_db.dashboards else None
            if dash_id:
                pg_session.add(CalculatedField(
                    dashboard_id=dash_id,
                    name=cf.caption or cf.name,
                    formula=cf.formula,
                    datatype=cf.datatype
                ))

    pg_session.commit()

    # ── 4. AI Governance Workflow ─────────────────────────────────
    run_governance_workflow(metadata, pg_session, db_id_mapping)
