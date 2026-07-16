import sys, os
sys.path.insert(0, os.getcwd())
from app.db.session import engine
from sqlalchemy import text

with engine.connect() as conn:
    r = conn.execute(text("""
        SELECT m.report_kpi_name, o.name, m.similarity_score, m.confidence_score, m.mapping_status, m.similarity_rationale, m.report_id
        FROM report_kpi_mappings m
        LEFT JOIN ontology_kpis o ON m.canonical_kpi_id = o.kpi_id
    """))
    rows = r.fetchall()
    print(f"Total mappings in DB: {len(rows)}")
    for i, row in enumerate(rows, 1):
        print(f"[{i}] Dashboard ID: {row[6]}")
        print(f"  Report KPI:  '{row[0]}'")
        print(f"  Matched to:  '{row[1]}'")
        print(f"  Sim: {row[2]} | Conf: {row[3]} | Status: {row[4]}")
        print(f"  Rationale: {row[5]}")
        print("-" * 50)
