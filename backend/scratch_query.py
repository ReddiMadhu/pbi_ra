import sys, os
sys.path.insert(0, os.getcwd())
from app.db.session import engine
from sqlalchemy import text

with engine.connect() as conn:
    r = conn.execute(text("SELECT name, definition, aliases FROM ontology_kpis WHERE name IN ('Policy Count', 'Claims Severity', 'Claims Frequency', 'Average Claim Settlement Time', 'Gross', 'Loss Ratio')"))
    for row in r.fetchall():
        print(f"NAME: {row[0]}")
        print(f"  DEF: {row[1]}")
        print(f"  ALIASES: {row[2]}")
        print()
