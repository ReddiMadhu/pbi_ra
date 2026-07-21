import logging
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.session import engine, Base

import app.models.postgres  # noqa: F401 — ensures all models are registered with Base
import app.models.ontology  # noqa: F401
import app.models.rationalization  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create all SQLite tables on startup
    Base.metadata.create_all(bind=engine)

    # Run tracked schema migrations (replaces ad-hoc ALTER TABLE blocks)
    from app.db.migrations.runner import run_migrations

    try:
        applied = run_migrations(engine)
        logger.info("Schema migrations: %d newly applied", applied)
    except Exception as mig_err:
        logger.error("Schema migration failed: %s", mig_err, exc_info=True)
        raise  # Fail fast — don't start with an inconsistent schema

    # Auto-seed curated KPIs if database table is empty
    try:
        from app.db.session import SessionLocal
        from app.db.seeds.seeder import seed_ontology_kpis

        db_sess = SessionLocal()
        try:
            seed_ontology_kpis(db_sess)
        finally:
            db_sess.close()
    except Exception as seed_err:
        logger.error("Lifespan startup seeder failed: %s", seed_err)

    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = f"Exception: {str(exc)}\n{traceback.format_exc()}"

    # Log full traceback server-side
    logger.error("Unhandled exception on %s %s:\n%s", request.method, request.url.path, error_msg)

    # Also write to a local error log file (relative to project root, not a hardcoded path)
    try:
        log_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_path = os.path.join(log_dir, "error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- ERROR AT {datetime.now()} ---\n{error_msg}\n")
    except Exception:
        pass

    # Return a safe error response — no stack traces to the client
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check server logs for details."},
    )


@app.get("/")
def root():
    return {"message": "Welcome to Tableau Governance Platform API"}
