import os
import zipfile
import xml.etree.ElementTree as ET
import tempfile
import shutil
from typing import Optional

from app.models.metadata import (
    WorkbookMetadata, DatasourceMetadata, TableMetadata,
    ColumnMetadata, CalculatedFieldMetadata, WorksheetMetadata,
    DashboardMetadata, JoinRelationship
)

class TableauParser:
    """
    Parses Tableau Workbook (.twb) and Packaged Workbook (.twbx) files
    to extract metadata about dashboards, worksheets, datasources, and fields.
    """
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.is_twbx = file_path.lower().endswith('.twbx')
        self.temp_dir: Optional[str] = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def cleanup(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def get_twb_file(self) -> str:
        """Extracts .twb from .twbx or returns .twb path directly."""
        if not self.is_twbx:
            return self.file_path

        # Unzip twbx to find and ONLY extract the twb file (skipping heavy data extracts)
        self.temp_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(self.file_path, 'r') as zip_ref:
            for name in zip_ref.namelist():
                if name.lower().endswith('.twb'):
                    zip_ref.extract(name, self.temp_dir)
                    return os.path.join(self.temp_dir, name)
                        
        raise FileNotFoundError("No .twb file found inside the .twbx archive.")

    def parse(self) -> WorkbookMetadata:
        twb_path = self.get_twb_file()
        tree = ET.parse(twb_path)
        root = tree.getroot()

        workbook = WorkbookMetadata(
            source_file=os.path.basename(self.file_path),
            version=root.attrib.get('version')
        )

        self._parse_datasources(root, workbook)
        self._parse_worksheets(root, workbook)
        self._parse_dashboards(root, workbook)

        # If this is a .twbx with embedded extracts, attach row previews
        if self.is_twbx:
            from app.services.parser.hyper_reader import read_hyper_previews
            previews = read_hyper_previews(self.file_path, max_rows=5)
            for ds in workbook.datasources:
                import re
                def super_clean(s):
                    return re.sub(r'[^a-z0-9]', '', s.lower())

                ds_name_clean = super_clean(ds.name)
                for tbl in ds.tables:
                    tbl_clean = super_clean(tbl.name)
                    
                    match = None
                    for k, v in previews.items():
                        k_clean = super_clean(k)
                        if (k_clean and tbl_clean and (
                            k_clean == tbl_clean or 
                            tbl_clean.endswith(k_clean) or 
                            k_clean.endswith(tbl_clean) or 
                            k_clean in tbl_clean or 
                            tbl_clean in k_clean
                        )) or (k_clean and ds_name_clean and k_clean == ds_name_clean):
                            match = v
                            break
                    
                    if match:
                        tbl.columns_preview, tbl.rows_preview = match

        return workbook

    def _parse_datasources(self, root: ET.Element, workbook: WorkbookMetadata):
        datasources_el = root.find('datasources')
        if datasources_el is None:
            return

        # Build universal col_to_table mapping from metadata records
        col_to_table_map = {}
        for ds_el in datasources_el.findall('datasource'):
            for m in ds_el.iter('metadata-record'):
                if m.attrib.get('class') == 'column':
                    local_name_el = m.find('local-name')
                    family_el = m.find('family')
                    if local_name_el is not None and family_el is not None:
                        clean_col = local_name_el.text.strip('[]')
                        col_to_table_map[clean_col] = family_el.text
        self.col_to_table_map = col_to_table_map

        # Collect ds_field_map first for formula replacement
        for ds_el in datasources_el.findall('datasource'):
            ds_field_map = {}
            for col_el in ds_el.findall('column'):
                col_name = col_el.attrib.get('name', '')
                caption = col_el.attrib.get('caption')
                tbl_part = None
                col_part = col_name.strip('[]')
                if col_name.startswith('[') and '].[' in col_name:
                    tbl_part = col_name.split('].[')[0].strip('[')
                    col_part = col_name.split('].[')[1].strip(']')
                
                real_table = getattr(self, 'col_to_table_map', {}).get(col_part)
                if not real_table and tbl_part and not any(x in tbl_part.lower() for x in ['excel-direct', 'federated', 'sqlproxy', 'parameters', 'action', 'multiple values']):
                    real_table = tbl_part
                friendly_name = caption or col_part
                if real_table:
                    friendly_name = f"{friendly_name} (Table - {real_table})"
                ds_field_map[col_part] = friendly_name
                ds_field_map[col_name.strip('[]')] = friendly_name

            ds_name = ds_el.attrib.get('name', 'Unknown')
            ds_caption = ds_el.attrib.get('caption')
            if ds_name == 'Parameters':
                continue
            
            ds_meta = DatasourceMetadata(
                name=ds_name,
                caption=ds_caption,
                version=ds_el.attrib.get('version')
            )
            
            # Parse connections (tables)
            connection_el = ds_el.find('connection')
            if connection_el is not None:
                # Handle nested connections (e.g. federation)
                # First collect direct table relations
                for rel in connection_el.iter('relation'):
                    tbl_name = rel.attrib.get('name', '')
                    tbl_class = rel.attrib.get('class', '')
                    rel_type = rel.attrib.get('type', '')
                    if tbl_name and rel_type == 'table':
                        if not any(t.name == tbl_name for t in ds_meta.tables):
                            ds_meta.tables.append(TableMetadata(name=tbl_name, class_name=tbl_class))

                # Then extract join relationships
                for join_rel in connection_el.iter('relation'):
                    if join_rel.attrib.get('type') == 'join':
                        join_type = join_rel.attrib.get('join', 'inner').lower()
                        # Get the two child table relations
                        child_tables = [
                            r for r in join_rel
                            if r.tag == 'relation' and r.attrib.get('type') == 'table'
                        ]
                        # Get join clause columns
                        clause = join_rel.find('clause')
                        if clause is not None and len(child_tables) >= 2:
                            expr = clause.find('expression')
                            if expr is not None:
                                left_expr = expr.find('expression')
                                right_expr = None
                                exprs = list(expr.findall('expression'))
                                if len(exprs) >= 2:
                                    left_expr, right_expr = exprs[0], exprs[1]
                                    left_col = left_expr.attrib.get('column', '').strip('[]').split('.')[-1]
                                    right_col = right_expr.attrib.get('column', '').strip('[]').split('.')[-1]
                                    ds_meta.joins.append(JoinRelationship(
                                        left_table=child_tables[0].attrib.get('name', 'Unknown'),
                                        right_table=child_tables[1].attrib.get('name', 'Unknown'),
                                        join_type=join_type,
                                        left_column=left_col,
                                        right_column=right_col
                                    ))
                    
            # Parse columns & calculated fields
            for col_el in ds_el.findall('column'):
                col_name = col_el.attrib.get('name', '')
                col_datatype = col_el.attrib.get('datatype', '')
                col_role = col_el.attrib.get('role', '')
                col_type = col_el.attrib.get('type', '')
                caption = col_el.attrib.get('caption')
                
                tbl_part = None
                col_part = col_name.strip('[]')
                if col_name.startswith('[') and '].[' in col_name:
                    tbl_part = col_name.split('].[')[0].strip('[')
                    col_part = col_name.split('].[')[1].strip(']')
                
                real_table = getattr(self, 'col_to_table_map', {}).get(col_part)
                if not real_table and tbl_part and not any(x in tbl_part.lower() for x in ['excel-direct', 'federated', 'sqlproxy', 'parameters', 'action', 'multiple values']):
                    real_table = tbl_part

                friendly_name = ds_field_map.get(col_part) or (caption or col_part)
                
                calc_el = col_el.find('calculation')
                if calc_el is not None:
                    formula = calc_el.attrib.get('formula', '')
                    import re
                    def replace_ref(match):
                        t_part = match.group(1)
                        c_part = match.group(2)
                        
                        mapped = ds_field_map.get(c_part)
                        if mapped:
                            return f"[{mapped}]"
                            
                        r_table = getattr(self, 'col_to_table_map', {}).get(c_part)
                        if not r_table and t_part and not any(x in t_part.lower() for x in ['excel-direct', 'federated', 'sqlproxy', 'parameters']):
                            r_table = t_part
                            
                        if r_table:
                            return f"[{c_part} (Table - {r_table})]"
                        else:
                            return f"[{c_part}]"
                    if formula:
                        formula = re.sub(r'(?:\[([^\]]+)\]\.)?\[([^\]]+)\]', replace_ref, formula)
                        
                    ds_meta.calculated_fields.append(CalculatedFieldMetadata(
                        name=friendly_name,
                        caption=caption,
                        formula=formula,
                        datatype=col_datatype
                    ))
                else:
                    col_meta = ColumnMetadata(
                        name=friendly_name,
                        datatype=col_datatype,
                        role=col_role,
                        type=col_type
                    )
                    ds_meta.columns.append(col_meta)
                    
                    # Infer table assignment if format is [TableName].[ColumnName]
                    if tbl_part:
                        for t in ds_meta.tables:
                            if t.name == tbl_part and col_part not in t.columns_preview:
                                t.columns_preview.append(col_part)

            # Fallback: if only 1 table and no columns were inferred, assign all plain columns to it
            if len(ds_meta.tables) == 1 and not ds_meta.tables[0].columns_preview:
                for col in ds_meta.columns:
                    col_clean = col.name.split(' (Table -')[0].strip('[]')
                    if ' (Table -' not in col.name and col_clean:
                        ds_meta.tables[0].columns_preview.append(col_clean)
            
            workbook.datasources.append(ds_meta)

    def _parse_worksheets(self, root: ET.Element, workbook: WorkbookMetadata):
        worksheets_el = root.find('worksheets')
        if worksheets_el is None:
            return

        # Build a mapping from internal names to friendly captions
        field_map = {}
        for col_el in root.iter('column'):
            c_name = col_el.attrib.get('name', '')
            c_caption = col_el.attrib.get('caption')
            if c_name:
                tbl_part = None
                col_part = c_name.strip('[]')
                if '].[' in c_name:
                    tbl_part = c_name.split('].[')[0].strip('[')
                    col_part = c_name.split('].[')[1].strip(']')
                    
                final_name = c_caption or col_part
                if c_caption in ['0', '1', '-1', '0.0', '1.0']:
                    final_name = col_part
                    
                real_table = getattr(self, 'col_to_table_map', {}).get(col_part)
                if not real_table and tbl_part and not any(x in tbl_part.lower() for x in ['excel-direct', 'federated', 'sqlproxy', 'parameters', 'action']):
                    real_table = tbl_part
                    
                if real_table:
                    final_name = f"{final_name} (Table - {real_table})"
                    
                field_map[c_name] = final_name
                field_map[c_name.strip('[]')] = final_name
                if col_part:
                    field_map[col_part] = final_name

        # Collect all friendly names of calculated fields across all datasources
        known_calcs = set()
        for ds in workbook.datasources:
            for cf in ds.calculated_fields:
                known_calcs.add(cf.name) # We set this to caption or name earlier

        for ws_el in worksheets_el.findall('worksheet'):
            ws_name = ws_el.attrib.get('name', '')
            if ws_name:
                ws_meta = WorksheetMetadata(name=ws_name)
                
                import re
                
                # Find all columns used in this worksheet
                all_used_fields = []
                for col_el in ws_el.iter('column'):
                    col_name = col_el.attrib.get('name', '')
                    if not col_name or 'Parameters' in col_name or 'Action' in col_name or 'Multiple Values' in col_name:
                        continue
                        
                    clean_name = col_name.strip('[]')
                    if '].[' in col_name:
                        clean_name = col_name.split('].[')[-1].strip('[]')
                        
                    if ':' in clean_name:
                        parts = clean_name.split(':')
                        clean_name = parts[1] if len(parts) >= 2 else clean_name
                        
                    caption = col_el.attrib.get('caption')
                    if caption in ['0', '1', '-1', '0.0', '1.0']:
                        caption = None
                        
                    friendly_name = caption or field_map.get(clean_name) or clean_name
                    
                    if friendly_name not in all_used_fields:
                        all_used_fields.append(friendly_name)
                    
                    if friendly_name in known_calcs and friendly_name not in ws_meta.used_calculated_fields:
                        ws_meta.used_calculated_fields.append(friendly_name)

                # Extract Visual Details (Rows, Columns, Mark Type)
                def extract_fields(text: str) -> list:
                    if not text:
                        return []
                    fields = []
                    matches = re.findall(r'(?:\[[^\]]+\]\.)?\[[^\]]+\]', text)
                    for raw in matches:
                        if 'Parameters' in raw or 'Action' in raw or 'Multiple Values' in raw:
                            continue
                            
                        tbl_part = None
                        col_part = raw.strip('[]')
                        if '].[' in raw:
                            tbl_part = raw.split('].[')[0].strip('[')
                            col_part = raw.split('].[')[1].strip(']')
                            
                        parts = col_part.split(':')
                        clean_col_part = parts[1] if len(parts) >= 2 else col_part
                        
                        mapped_name = field_map.get(raw, field_map.get(clean_col_part, clean_col_part))
                        
                        if mapped_name == clean_col_part:
                            r_table = getattr(self, 'col_to_table_map', {}).get(clean_col_part)
                            if not r_table and tbl_part and not any(x in tbl_part.lower() for x in ['excel-direct', 'federated', 'sqlproxy', 'parameters']):
                                r_table = tbl_part
                            if r_table:
                                mapped_name = f"{clean_col_part} (Table - {r_table})"
                                
                        if mapped_name not in fields:
                            fields.append(mapped_name)
                    return fields

                cols_el = ws_el.find('.//cols')
                if cols_el is not None and cols_el.text:
                    ws_meta.columns = extract_fields(cols_el.text)
                
                rows_el = ws_el.find('.//rows')
                if rows_el is not None and rows_el.text:
                    ws_meta.rows = extract_fields(rows_el.text)

                def extract_measure_bindings(cols_text: str, rows_text: str) -> list:
                    bindings = []
                    seen = set()
                    agg_pattern = re.compile(
                        r'(?i)(sum|avg|cnt|count|countd|min|max|attr|median):\s*\[([^\]]+)\]'
                    )
                    for raw_text in (cols_text or "", rows_text or ""):
                        for match in agg_pattern.finditer(raw_text):
                            agg = match.group(1).upper()
                            if agg == "COUNT":
                                agg = "COUNT"
                            elif agg == "CNT":
                                agg = "COUNT"
                            field_ref = match.group(2).strip()
                            col_part = field_ref
                            if '].[' in field_ref:
                                col_part = field_ref.split('].[')[-1].strip(']')
                            parts = col_part.split(':')
                            clean_col = parts[1] if len(parts) >= 2 else col_part
                            table = getattr(self, 'col_to_table_map', {}).get(clean_col)
                            if not table and '].[' in field_ref:
                                tbl_part = field_ref.split('].[')[0].strip('[')
                                if tbl_part and not any(
                                    x in tbl_part.lower() for x in ['excel-direct', 'federated', 'sqlproxy', 'parameters']
                                ):
                                    table = tbl_part
                            lineage = f"{table}.{clean_col}" if table else clean_col
                            key = (agg, lineage)
                            if key in seen:
                                continue
                            seen.add(key)
                            bindings.append({
                                "field": clean_col,
                                "aggregation": agg,
                                "table": table or "",
                                "lineage": lineage,
                            })
                    return bindings

                cols_raw = cols_el.text if cols_el is not None and cols_el.text else ""
                rows_raw = rows_el.text if rows_el is not None and rows_el.text else ""
                ws_meta.measure_bindings = extract_measure_bindings(cols_raw, rows_raw)

                if not ws_meta.columns and not ws_meta.rows and all_used_fields:
                    ws_meta.columns = all_used_fields
                else:
                    remaining_fields = [f for f in all_used_fields if f not in ws_meta.columns and f not in ws_meta.rows]
                    ws_meta.filters_and_marks = remaining_fields

                view_el = ws_el.find('.//view')
                
                # Mark Type — lives in <style><mark class="..."/> NOT in <view>
                mark_class = 'Automatic'
                # Try the correct location first: worksheet > style > mark
                style_mark_el = ws_el.find('.//style/mark')
                if style_mark_el is not None:
                    mark_class = style_mark_el.attrib.get('class', 'Automatic')
                else:
                    # Fallback: search anywhere in the worksheet
                    mark_el = ws_el.find('.//mark')
                    if mark_el is not None:
                        mark_class = mark_el.attrib.get('class', 'Automatic')

                cols_text_val = cols_el.text if cols_el is not None and cols_el.text is not None else ""
                rows_text_val = rows_el.text if rows_el is not None and rows_el.text is not None else ""
                raw_text = (cols_text_val + " " + rows_text_val).lower()
                has_measures = any(agg in raw_text for agg in ['sum:', 'avg:', 'cnt:', 'count:', 'min:', 'max:', 'attr:'])
                has_dates = any(dt in raw_text for dt in ['yr:', 'mn:', 'dy:', 'qr:', 'wk:', 'mdy:', 'date:'])

                if mark_class.lower() in ['pie', 'shape', 'map', 'polygon', 'circle', 'line', 'bar', 'text', 'ganttbar']:
                    pass
                elif mark_class == 'Automatic':
                    if has_dates and has_measures:
                        mark_class = 'Line'
                    elif has_measures and len(ws_meta.columns) > 0 and len(ws_meta.rows) > 0:
                        cols_text = (cols_el.text or "").lower()
                        rows_text = (rows_el.text or "").lower()
                        cols_has_measure = any(agg in cols_text for agg in ['sum:', 'avg:', 'cnt:', 'count:', 'min:', 'max:'])
                        rows_has_measure = any(agg in rows_text for agg in ['sum:', 'avg:', 'cnt:', 'count:', 'min:', 'max:'])
                        if cols_has_measure and rows_has_measure:
                            mark_class = 'Scatter Plot'
                        else:
                            mark_class = 'Bar'
                    elif has_measures:
                        mark_class = 'Text Table / KPI'
                    elif len(ws_meta.columns) > 0 and len(ws_meta.rows) > 0:
                        mark_class = 'Text Table'
                    else:
                        mark_class = 'Text / Value'

                if mark_class.lower() == 'ganttbar':
                    mark_class = 'Gantt Bar'

                ws_meta.mark_type = mark_class.capitalize()
                        
                workbook.worksheets.append(ws_meta)

    def _parse_dashboards(self, root: ET.Element, workbook: WorkbookMetadata):
        dashboards_el = root.find('dashboards')
        if dashboards_el is None:
            return

        for db_el in dashboards_el.findall('dashboard'):
            db_name = db_el.attrib.get('name', '')
            if not db_name:
                continue

            db_meta = DashboardMetadata(name=db_name)
            
            # Extract worksheets used in dashboard
            zones_el = db_el.find('zones')
            if zones_el is not None:
                all_ws_names = {ws.name for ws in workbook.worksheets}
                for zone in zones_el.iter('zone'):
                    # Check explicit type flags
                    if zone.attrib.get('type-v2') == 'worksheet' or zone.attrib.get('type') == 'worksheet':
                        ws_ref = zone.attrib.get('name')
                        if ws_ref and ws_ref not in db_meta.worksheets:
                            db_meta.worksheets.append(ws_ref)
                    else:
                        # Fallback: Does the zone name match a known worksheet?
                        z_name = zone.attrib.get('name')
                        if z_name and z_name in all_ws_names and z_name not in db_meta.worksheets:
                            db_meta.worksheets.append(z_name)
            
            workbook.dashboards.append(db_meta)
