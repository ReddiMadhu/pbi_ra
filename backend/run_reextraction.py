import sys
import os
from sqlalchemy.orm import Session

# Add backend and app to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app'))

from app.db.session import SessionLocal
from app.models.postgres import Dashboard
from app.api.v1.ontology import trigger_extraction
from app.models.ontology import ReportKPIMapping, KPIOntologyCache

def reextract_all():
    db = SessionLocal()
    try:
        # 1. Clear existing cache and mappings in DB to start clean
        print("Clearing old KPI ontology cache...")
        db.query(KPIOntologyCache).delete()
        
        print("Clearing old report KPI mappings...")
        db.query(ReportKPIMapping).delete()
        db.commit()

        # 2. Find all dashboards
        dashboards = db.query(Dashboard).all()
        print(f"Found {len(dashboards)} dashboards to process.")

        # 3. Trigger extraction for each dashboard
        for dash in dashboards:
            print(f"\nTriggering extraction for Dashboard: {dash.name} (ID: {dash.id}, Sector: {dash.ontology_sector}, Subdomain: {dash.ontology_subdomain})...")
            try:
                res = trigger_extraction(str(dash.id), db)
                print(f"  Result: {res}")
            except Exception as e:
                print(f"  Error processing dashboard {dash.id}: {e}")

    finally:
        db.close()

if __name__ == "__main__":
    reextract_all()
