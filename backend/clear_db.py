from app.db.session import engine, Base, SessionLocal
import app.models.postgres
import app.models.ontology
import app.models.rationalization
from app.db.seeds.seeder import seed_ontology_kpis

print("Dropping all tables...")
Base.metadata.drop_all(bind=engine)
print("Creating all tables...")
Base.metadata.create_all(bind=engine)

# Re-create unique mappings index normally handled in lifespan migrations
from sqlalchemy import text
with engine.begin() as conn:
    try:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_rkm_report_ws_kpi "
            "ON report_kpi_mappings (report_id, worksheet_id, report_kpi_name);"
        ))
    except Exception:
        pass

print("Seeding curated ontology KPIs...")
db = SessionLocal()
try:
    seed_ontology_kpis(db)
finally:
    db.close()

print("Database cleared and auto-seeded successfully.")
