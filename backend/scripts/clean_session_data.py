"""Wipe all session and rationalization data from SQLite database, keeping only curated ontology KPIs."""

import os
import sys

# Ensure backend root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.ontology import ReportKPIMapping, KPIOntologyCache, OntologyKPI
from app.models.rationalization import (
    ReportFingerprint, PairwiseScore, Cluster, ContentMigrationTask,
    Explanation, ScoreDetail, MeasureEquivalence, GovernanceFlag
)
from app.models.postgres import (
    ScanHistory, Workbook, Dashboard, Worksheet, 
    CalculatedField, DatasourceModel, TableModel, TableJoin, GovernanceRisk
)

def clean_session_data():
    db = SessionLocal()
    try:
        print("Cleaning up rationalization tables...")
        db.query(ReportFingerprint).delete()
        db.query(PairwiseScore).delete()
        db.query(Cluster).delete()
        db.query(ContentMigrationTask).delete()
        db.query(Explanation).delete()
        db.query(ScoreDetail).delete()
        db.query(MeasureEquivalence).delete()
        db.query(GovernanceFlag).delete()
        
        print("Cleaning up session metadata tables...")
        db.query(ReportKPIMapping).delete()
        db.query(KPIOntologyCache).delete()
        db.query(GovernanceRisk).delete()
        db.query(CalculatedField).delete()
        db.query(Worksheet).delete()
        db.query(Dashboard).delete()
        db.query(TableJoin).delete()
        db.query(TableModel).delete()
        db.query(DatasourceModel).delete()
        db.query(Workbook).delete()
        db.query(ScanHistory).delete()
        
        db.commit()
        
        # Verify counts
        print("\nVerification - Database Counts:")
        print(f" - Curated Ontology KPIs: {db.query(OntologyKPI).count()}")
        print(f" - Active Mappings: {db.query(ReportKPIMapping).count()}")
        print(f" - Active Cache Entries: {db.query(KPIOntologyCache).count()}")
        print(f" - Workbooks: {db.query(Workbook).count()}")
        print(f" - Dashboards: {db.query(Dashboard).count()}")
        print(f" - Scan History: {db.query(ScanHistory).count()}")
        
        print("\nSession data cleared successfully. Curated Ontology KPI bank is fully preserved.")
        
    except Exception as e:
        db.rollback()
        print(f"Error executing database clean-up: {e}")
    finally:
        db.close()

if __name__ == '__main__':
    clean_session_data()
