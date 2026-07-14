from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.api import api_router
from app.core.config import settings
from app.db.session import engine, Base
import app.models.postgres  # noqa: F401 — ensures all models are registered with Base
import app.models.ontology  # noqa: F401
import app.models.rationalization  # noqa: F401

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create all SQLite tables on startup (no migrations needed!)
    Base.metadata.create_all(bind=engine)
    
    from sqlalchemy import text
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE worksheets ADD COLUMN workbook_id INTEGER REFERENCES workbooks(id);"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE tables ADD COLUMN columns JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE tables ADD COLUMN rows JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dashboards ADD COLUMN is_real_ai INTEGER DEFAULT 0;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE worksheets ADD COLUMN measure_bindings JSON;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE report_kpi_mappings ADD COLUMN worksheet_id TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE report_kpi_mappings ADD COLUMN worksheet_name TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE ontology_kpis ADD COLUMN representative_lineage TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE ontology_kpis ADD COLUMN sector TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE ontology_kpis ADD COLUMN subdomain TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dashboards ADD COLUMN ontology_sector TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dashboards ADD COLUMN ontology_subdomain TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE report_kpi_mappings ADD COLUMN report_kpi_definition TEXT;"))
        except Exception:
            pass
        try:
            conn.execute(text("DROP INDEX IF EXISTS idx_rkm_report_canonical;"))
        except Exception:
            pass
        try:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_rkm_report_ws_kpi "
                "ON report_kpi_mappings (report_id, worksheet_id, report_kpi_name);"
            ))
        except Exception:
            pass

    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

from fastapi import Request
from fastapi.responses import JSONResponse
from datetime import datetime
import traceback

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = f"Exception: {str(exc)}\n{traceback.format_exc()}"
    try:
        with open(r"c:\Users\91798\.gemini\antigravity\scratch\tableau_gov_platform\backend\error.log", "a") as f:
            f.write(f"\n--- ERROR AT {datetime.now()} ---\n{error_msg}\n")
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "traceback": traceback.format_exc()}
    )

@app.get("/")
def root():
    return {"message": "Welcome to Tableau Governance Platform API"}
