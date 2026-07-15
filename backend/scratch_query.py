import sys, os
sys.path.insert(0, os.getcwd())
from app.db.session import engine
from sqlalchemy import text
import json

with engine.connect() as conn:
    # Check a few key KPIs to see if aliases were expanded
    key_kpis = ['Policy Count', 'Claims Severity', 'Average Claim Settlement Time', 'Loss Ratio', 'Retention Rate']
    
    for name in key_kpis:
        r = conn.execute(text("SELECT name, aliases FROM ontology_kpis WHERE name = :n"), {"n": name})
        rows = r.fetchall()
        for row in rows:
            aliases = json.loads(row[1]) if row[1] else []
            print(f"\n{row[0]}: {len(aliases)} aliases")
            for a in aliases:
                print(f"  - {a}")
    
    # Count total aliases across all KPIs
    r2 = conn.execute(text("SELECT aliases FROM ontology_kpis WHERE status = 'active'"))
    total_aliases = 0
    kpis_with_many = 0
    for row in r2.fetchall():
        aliases = json.loads(row[0]) if row[0] else []
        total_aliases += len(aliases)
        if len(aliases) > 5:
            kpis_with_many += 1
    
    print(f"\n--- Summary ---")
    print(f"Total aliases across all KPIs: {total_aliases}")
    print(f"KPIs with > 5 aliases (expanded): {kpis_with_many}")
