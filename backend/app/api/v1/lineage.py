from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.postgres import Dashboard, Workbook, DatasourceModel, TableModel, TableJoin

router = APIRouter()

@router.get("/workbook/{workbook_name}")
def get_workbook_lineage(workbook_name: str, view_type: str = "full", db: Session = Depends(get_db)):
    """
    Builds a lineage graph at the Workbook level (Datasources, Tables, Joins).
    """
    workbook = db.query(Workbook).filter(Workbook.name == workbook_name).first()
    if not workbook:
        raise HTTPException(status_code=404, detail=f"Workbook '{workbook_name}' not found")

    nodes = []
    edges = []

    wb_id = f"workbook_{workbook.id}"
    nodes.append({"id": wb_id, "label": workbook.name, "type": "Workbook"})

    if view_type in ["full", "worksheets"]:
        # Dashboards & Worksheets
        from app.models.postgres import Dashboard, Worksheet
        dashboards = db.query(Dashboard).filter(Dashboard.workbook_id == workbook.id).all()
        
        ws_usage_count = {}
        for db_node in dashboards:
            for ws in db_node.worksheets:
                ws_usage_count[ws.name] = ws_usage_count.get(ws.name, 0) + 1

        for db_node in dashboards:
            db_id = f"dashboard_{db_node.id}"
            nodes.append({"id": db_id, "label": db_node.name, "type": "Dashboard"})
            edges.append({"id": f"e_{wb_id}__{db_id}", "source": wb_id, "target": db_id, "label": "CONTAINS"})
            
            for ws in db_node.worksheets:
                ws_id = f"ws_name_{ws.name}"
                is_duplicate = ws_usage_count[ws.name] > 1
                node_type = "Worksheet (Duplicate)" if is_duplicate else "Worksheet"
                nodes.append({"id": ws_id, "label": ws.name, "type": node_type})
                edges.append({"id": f"e_{db_id}__{ws_id}", "source": db_id, "target": ws_id, "label": "RENDERS"})

                fields = []
                if ws.columns: fields.extend(ws.columns)
                if ws.rows: fields.extend(ws.rows)
                if getattr(ws, 'filters_and_marks', None): fields.extend(ws.filters_and_marks)
                fields = list(set([f for f in fields if f]))
                
                if fields:
                    fields_node_id = f"fields_{ws_id}"
                    nodes.append({"id": fields_node_id, "label": "Fields Used", "type": "Table", "columns": fields})
                    edges.append({"id": f"e_{ws_id}__{fields_node_id}", "source": ws_id, "target": fields_node_id, "label": "USES FIELDS"})

        all_worksheets = db.query(Worksheet).filter(Worksheet.workbook_id == workbook.id).all()
        for ws in all_worksheets:
            if ws.dashboard_id is None:
                ws_id = f"ws_name_{ws.name}"
                nodes.append({"id": ws_id, "label": ws.name, "type": "Worksheet"})
                edges.append({"id": f"e_{wb_id}__{ws_id}", "source": wb_id, "target": ws_id, "label": "CONTAINS (Orphan)"})

    if view_type in ["full", "tables"]:
        datasources = db.query(DatasourceModel).filter(DatasourceModel.workbook_id == workbook.id).all()
        for ds in datasources:
            ds_id = f"ds_{ds.id}"
            ds_label = ds.caption or ds.name
            nodes.append({"id": ds_id, "label": ds_label, "type": "Datasource"})
            edges.append({"id": f"e_{wb_id}__{ds_id}", "source": wb_id, "target": ds_id, "label": "CONTAINS"})

            tables = db.query(TableModel).filter(TableModel.datasource_id == ds.id).all()
            for tbl in tables:
                tbl_id = f"tbl_{tbl.id}"
                nodes.append({"id": tbl_id, "label": tbl.name, "type": "Table", "columns": tbl.columns or [], "rows_preview": tbl.rows or []})
                edges.append({"id": f"e_{ds_id}__{tbl_id}", "source": ds_id, "target": tbl_id, "label": "FROM"})

            joins = db.query(TableJoin).filter(TableJoin.datasource_id == ds.id).all()
            for join in joins:
                left_tbl = next((t for t in tables if t.name == join.left_table), None)
                right_tbl = next((t for t in tables if t.name == join.right_table), None)

                if left_tbl and right_tbl:
                    left_id = f"tbl_{left_tbl.id}"
                    right_id = f"tbl_{right_tbl.id}"
                    edge_label = f"{join.join_type.upper()} JOIN\n{join.left_column} = {join.right_column}"
                    edges.append({
                        "id": f"e_join_{left_id}__{right_id}",
                        "source": left_id,
                        "target": right_id,
                        "label": edge_label,
                        "edge_type": "join",
                        "join_type": join.join_type,
                        "left_column": join.left_column,
                        "right_column": join.right_column,
                    })

    seen = set()
    unique_nodes = [n for n in nodes if not (n["id"] in seen or seen.add(n["id"]))]
    return {"nodes": unique_nodes, "edges": edges}

@router.get("/{dashboard_name}")
def get_lineage(dashboard_name: str, db: Session = Depends(get_db)):
    """
    Builds a full lineage graph from SQLite — no file re-parsing needed.

    Node hierarchy:
      Workbook → Dashboard → Worksheet
      Workbook → Datasource → Table ──(JOIN on col=col)──► Table
      Dashboard → CalculatedField
    """
    dashboard = db.query(Dashboard).filter(Dashboard.name == dashboard_name).first()
    if not dashboard:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_name}' not found")

    nodes = []
    edges = []

    # ── Dashboard ───────────────────────────────────────────────
    db_node_id = f"dashboard_{dashboard.id}"
    nodes.append({"id": db_node_id, "label": dashboard.name, "type": "Dashboard"})

    # ── Workbook ────────────────────────────────────────────────
    workbook = db.query(Workbook).filter(Workbook.id == dashboard.workbook_id).first()
    if workbook:
        wb_id = f"workbook_{workbook.id}"
        nodes.append({"id": wb_id, "label": workbook.name, "type": "Workbook"})
        edges.append({"id": f"e_{wb_id}__{db_node_id}", "source": wb_id, "target": db_node_id, "label": "CONTAINS"})

        # ── Datasources + Tables + Joins (from DB) ──────────────
        datasources = db.query(DatasourceModel).filter(DatasourceModel.workbook_id == workbook.id).all()
        for ds in datasources:
            ds_id = f"ds_{ds.id}"
            ds_label = ds.caption or ds.name
            nodes.append({"id": ds_id, "label": ds_label, "type": "Datasource"})
            edges.append({"id": f"e_{db_node_id}__{ds_id}", "source": db_node_id, "target": ds_id, "label": "USES"})

            # Tables
            tables = db.query(TableModel).filter(TableModel.datasource_id == ds.id).all()
            for tbl in tables:
                tbl_id = f"tbl_{tbl.id}"
                nodes.append({"id": tbl_id, "label": tbl.name, "type": "Table"})
                edges.append({"id": f"e_{ds_id}__{tbl_id}", "source": ds_id, "target": tbl_id, "label": "FROM"})

            # Table → Table JOIN edges (the key lineage relationships)
            joins = db.query(TableJoin).filter(TableJoin.datasource_id == ds.id).all()
            for join in joins:
                # Find table node IDs by name within this datasource
                left_tbl = next((t for t in tables if t.name == join.left_table), None)
                right_tbl = next((t for t in tables if t.name == join.right_table), None)

                if left_tbl and right_tbl:
                    left_id = f"tbl_{left_tbl.id}"
                    right_id = f"tbl_{right_tbl.id}"
                    edge_label = f"{join.join_type.upper()} JOIN\n{join.left_column} = {join.right_column}"
                    edges.append({
                        "id": f"e_join_{left_id}__{right_id}",
                        "source": left_id,
                        "target": right_id,
                        "label": edge_label,
                        "edge_type": "join",
                        "join_type": join.join_type,
                        "left_column": join.left_column,
                        "right_column": join.right_column,
                    })

    # ── Worksheets ──────────────────────────────────────────────
    for ws in dashboard.worksheets:
        ws_id = f"ws_{ws.id}"
        nodes.append({"id": ws_id, "label": ws.name, "type": "Worksheet"})
        edges.append({"id": f"e_{db_node_id}__{ws_id}", "source": db_node_id, "target": ws_id, "label": "RENDERS"})

        fields = []
        if ws.columns: fields.extend(ws.columns)
        if ws.rows: fields.extend(ws.rows)
        if getattr(ws, 'filters_and_marks', None): fields.extend(ws.filters_and_marks)
        fields = list(set([f for f in fields if f]))
        
        if fields:
            fields_node_id = f"fields_{ws.id}"
            nodes.append({"id": fields_node_id, "label": "Fields Used", "type": "Table", "columns": fields})
            edges.append({"id": f"e_{ws_id}__{fields_node_id}", "source": ws_id, "target": fields_node_id, "label": "USES FIELDS"})

    # Deduplicate nodes
    seen = set()
    unique_nodes = [n for n in nodes if not (n["id"] in seen or seen.add(n["id"]))]

    return {"nodes": unique_nodes, "edges": edges}
