"""
hyper_reader.py
──────────────
Reads the embedded Tableau Hyper extract file (.hyper) found inside a .twbx
archive and returns the first N rows per table for preview purposes.
"""

import os
import zipfile
import tempfile
import shutil
from typing import Dict, List, Tuple

def _find_data_files(twbx_path: str, extract_dir: str) -> List[str]:
    """Unzip the .twbx and return paths to any .hyper, .csv, .txt, or .xlsx files inside."""
    data_paths = []
    with zipfile.ZipFile(twbx_path, 'r') as z:
        for name in z.namelist():
            lower_name = name.lower()
            if lower_name.endswith('.hyper') or lower_name.endswith('.csv') or lower_name.endswith('.txt') or lower_name.endswith('.xlsx'):
                z.extract(name, extract_dir)
                data_paths.append(os.path.join(extract_dir, name))
    return data_paths


def read_hyper_previews(twbx_path: str, max_rows: int = 5) -> Dict[str, Tuple[List[str], List[List[str]]]]:
    """
    Opens each .hyper file embedded in the .twbx and returns:
        { table_name: (column_headers, [[row1_val1, ...], [row2_val1, ...], ...]) }

    Falls back gracefully — returns empty dict if tableauhyperapi is not installed
    or if no hyper files are found.
    """
    results: Dict[str, Tuple[List[str], List[List[str]]]] = {}

    if not twbx_path.lower().endswith('.twbx'):
        return results

    try:
        from tableauhyperapi import HyperProcess, Telemetry, Connection, TableName
    except ImportError:
        return results  # Library not installed — skip silently

    extract_dir = tempfile.mkdtemp()
    try:
        data_files = _find_data_files(twbx_path, extract_dir)
        if not data_files:
            return results

        hyper_files = [f for f in data_files if f.lower().endswith('.hyper')]
        csv_files = [f for f in data_files if f.lower().endswith('.csv') or f.lower().endswith('.txt')]
        xlsx_files = [f for f in data_files if f.lower().endswith('.xlsx')]

        # Process .hyper files
        if hyper_files:
            try:
                from tableauhyperapi import HyperProcess, Telemetry, Connection, TableName
                with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
                    for hyper_path in hyper_files:
                        with Connection(hyper.endpoint, hyper_path) as conn:
                            catalog = conn.catalog
                            for schema_name in catalog.get_schema_names():
                                try:
                                    table_names = catalog.get_table_names(schema_name)
                                except Exception:
                                    continue
                                for tbl_name in table_names:
                                    try:
                                        tbl_def = catalog.get_table_definition(tbl_name)
                                        headers = [col.name.unescaped for col in tbl_def.columns]
                                        rows_raw = conn.execute_list_query(
                                            f"SELECT * FROM {tbl_name} LIMIT {max_rows}"
                                        )
                                        rows_str = [
                                            [str(v) if v is not None else '' for v in row]
                                            for row in rows_raw
                                        ]
                                        # Use both unescaped name and string representation for better matching
                                        results[tbl_name.name.unescaped] = (headers, rows_str)
                                        results[str(tbl_name)] = (headers, rows_str)
                                        # Store by filename for exact datasource matching
                                        base_name = os.path.splitext(os.path.basename(hyper_path))[0]
                                        results[base_name] = (headers, rows_str)
                                    except Exception:
                                        continue
            except ImportError:
                pass  # Fallback if tableauhyperapi is somehow not loadable

        # Process .csv and .txt files
        import csv
        for csv_path in csv_files:
            try:
                # Some files might be tab delimited if .txt
                is_tab = csv_path.lower().endswith('.txt')
                with open(csv_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                    reader = csv.reader(f, delimiter='\t' if is_tab else ',')
                    headers = next(reader, [])
                    rows_str = []
                    for _ in range(max_rows):
                        try:
                            row = next(reader)
                            rows_str.append([str(v) for v in row])
                        except StopIteration:
                            break
                    # Use filename without extension as table name
                    tbl_name = os.path.splitext(os.path.basename(csv_path))[0]
                    results[tbl_name] = (headers, rows_str)
            except Exception:
                continue

        # Process .xlsx files
        for xlsx_path in xlsx_files:
            try:
                import pandas as pd
                # Read all sheets
                excel_file = pd.ExcelFile(xlsx_path)
                for sheet_name in excel_file.sheet_names:
                    df = excel_file.parse(sheet_name, nrows=max_rows)
                    headers = [str(c) for c in df.columns]
                    rows_str = df.astype(str).values.tolist()
                    
                    # Store both by sheet name and file name for maximum matchability
                    results[sheet_name] = (headers, rows_str)
                    
                    # Fallback store by filename just in case
                    tbl_name = os.path.splitext(os.path.basename(xlsx_path))[0]
                    results[tbl_name] = (headers, rows_str)
            except Exception:
                continue

    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    return results
