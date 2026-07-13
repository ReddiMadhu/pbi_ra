"""
In-memory lineage graph builder using pure Python.
Replaces Neo4j — no external graph database needed.
"""
from app.models.metadata import WorkbookMetadata


class InMemoryGraphBuilder:
    """
    Builds a lineage graph as plain Python dicts from parsed Tableau metadata.
    The result is stored in-memory and can be serialized to JSON for the frontend.
    """

    def __init__(self):
        self.nodes: dict = {}
        self.edges: list = []

    def build_from_metadata(self, workbook: WorkbookMetadata):
        wb_id = f"wb_{workbook.source_file}"
        self._add_node(wb_id, workbook.source_file, "Workbook")

        for db in workbook.dashboards:
            db_id = f"db_{workbook.source_file}_{db.name}"
            self._add_node(db_id, db.name, "Dashboard")
            self._add_edge(wb_id, db_id, "CONTAINS")

            for ws_name in db.worksheets:
                ws_id = f"ws_{workbook.source_file}_{ws_name}"
                self._add_node(ws_id, ws_name, "Worksheet")
                self._add_edge(db_id, ws_id, "USES")

        for ds in workbook.datasources:
            ds_id = f"ds_{workbook.source_file}_{ds.name}"
            self._add_node(ds_id, ds.name, "Datasource")

            for table in ds.tables:
                t_id = f"tbl_{workbook.source_file}_{ds.name}_{table.name}"
                self._add_node(t_id, table.name, "Table")
                self._add_edge(ds_id, t_id, "EXTRACTS_FROM")

            for cf in ds.calculated_fields:
                cf_id = f"cf_{workbook.source_file}_{ds.name}_{cf.name}"
                self._add_node(cf_id, cf.name, "CalculatedField")
                self._add_edge(ds_id, cf_id, "DEFINES")

                for col in ds.columns:
                    if f"[{col.name}]" in (cf.formula or ""):
                        col_id = f"col_{workbook.source_file}_{ds.name}_{col.name}"
                        self._add_node(col_id, col.name, "Column")
                        self._add_edge(cf_id, col_id, "COMPUTED_FROM")

        return {"nodes": list(self.nodes.values()), "edges": self.edges}

    def _add_node(self, node_id: str, label: str, node_type: str):
        if node_id not in self.nodes:
            self.nodes[node_id] = {"id": node_id, "label": label, "type": node_type}

    def _add_edge(self, source: str, target: str, label: str):
        edge_id = f"{source}__{label}__{target}"
        self.edges.append({"id": edge_id, "source": source, "target": target, "label": label})
