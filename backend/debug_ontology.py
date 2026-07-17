import os
import sys
import traceback

# Add backend and app to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app'))

import app.models.ontology # Import to register models
from app.db.session import SessionLocal
from app.services.parser.tableau_parser import TableauParser
from app.services.ontology.ontology_service import process_workbook_ontology

SUBSET_DIR = r"c:\Users\madhu\Downloads\Tableu BI Compass\Tableu BI Compass\subset"

def debug_all():
    db = SessionLocal()
    try:
        files = [f for f in os.listdir(SUBSET_DIR) if f.endswith(('.twb', '.twbx'))]
        for filename in files:
            filepath = os.path.join(SUBSET_DIR, filename)
            print(f"\n==========================================")
            print(f"Processing: {filename}")
            print(f"==========================================")
            try:
                print(f"Parsing {filepath}...")
                with TableauParser(filepath) as parser:
                    metadata = parser.parse()
                    metadata.source_file = filename
                    metadata.file_size_bytes = os.path.getsize(filepath)
                    import time
                    metadata.last_modified = time.time()
                    col_to_table_map = dict(getattr(parser, "col_to_table_map", {}) or {})
                    
                print("Tableau parsing completed successfully.")
                print(f"Worksheets found: {[w.name for w in metadata.worksheets]}")
                print(f"Dashboards found: {[d.name for d in metadata.dashboards]}")
                
                print("Running process_workbook_ontology...")
                count = process_workbook_ontology(metadata, db, col_to_table_map)
                print(f"Completed. Processed {count} KPIs.")
            except Exception as e:
                print(f"Error processing {filename}:")
                traceback.print_exc()
        
    finally:
        db.close()

if __name__ == "__main__":
    debug_all()
