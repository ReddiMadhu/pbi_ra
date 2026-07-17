import tempfile
import os
import shutil
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.services.parser.tableau_parser import TableauParser
from app.models.metadata import (
    WorkbookMetadata, DatasourceMetadata, TableMetadata, 
    CalculatedFieldMetadata, JoinRelationship, WorksheetMetadata, DashboardMetadata
)
from app.db.session import get_db
from app.services.parser.sync_to_db import sync_metadata_to_db
from app.worker.tasks import scan_repository_task
from app.models.postgres import (
    ScanHistory, Workbook, Dashboard, Worksheet, 
    CalculatedField, DatasourceModel, TableModel, TableJoin, GovernanceRisk
)
from app.models.ontology import ReportKPIMapping, OntologyKPI, KPIOntologyCache
from app.models.rationalization import (
    ReportFingerprint, PairwiseScore, Cluster, ContentMigrationTask,
    Explanation, ScoreDetail, MeasureEquivalence, GovernanceFlag
)

router = APIRouter()

@router.post("/clear")
async def clear_database(db: Session = Depends(get_db)):
    """Clears all session and rationalization data but preserves the curated Ontology KPI Bank."""
    # Preserved: OntologyKPI
    
    # 1. Clear rationalization tables
    db.query(ReportFingerprint).delete()
    db.query(PairwiseScore).delete()
    db.query(Cluster).delete()
    db.query(ContentMigrationTask).delete()
    db.query(Explanation).delete()
    db.query(ScoreDetail).delete()
    db.query(MeasureEquivalence).delete()
    db.query(GovernanceFlag).delete()
    
    # 2. Clear session tables
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

    # Clear in-memory caches
    try:
        from app.services.ontology.embedding_service import clear_embedding_cache
        from app.api.v1.kpi_graph import clear_kpi_cluster_cache
        clear_embedding_cache()
        clear_kpi_cluster_cache()
    except Exception:
        pass

    return {"message": "Session data cleared (Ontology Bank and caches reset)"}

@router.post("/clear-all")
async def clear_all_database(db: Session = Depends(get_db)):
    """Clears ALL data including the Ontology KPI Bank. Use only when you want a full reset."""
    # 1. Clear rationalization tables
    db.query(ReportFingerprint).delete()
    db.query(PairwiseScore).delete()
    db.query(Cluster).delete()
    db.query(ContentMigrationTask).delete()
    db.query(Explanation).delete()
    db.query(ScoreDetail).delete()
    db.query(MeasureEquivalence).delete()
    db.query(GovernanceFlag).delete()
    
    # 2. Clear session tables
    db.query(ReportKPIMapping).delete()
    db.query(KPIOntologyCache).delete()
    db.query(OntologyKPI).delete()
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

    # Clear in-memory caches
    try:
        from app.services.ontology.embedding_service import clear_embedding_cache
        from app.api.v1.kpi_graph import clear_kpi_cluster_cache
        clear_embedding_cache()
        clear_kpi_cluster_cache()
    except Exception:
        pass

    return {"message": "All data cleared including Ontology Bank and caches"}

class ScanRequest(BaseModel):
    directory_path: str

@router.post("/scan-directory")
async def scan_directory(
    request: ScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Initiates a FastAPI background scan of a local directory."""
    if not os.path.exists(request.directory_path) or not os.path.isdir(request.directory_path):
        raise HTTPException(status_code=400, detail="Invalid directory path")

    new_scan = ScanHistory(directory_path=request.directory_path, status="pending")
    db.add(new_scan)
    db.commit()
    db.refresh(new_scan)

    background_tasks.add_task(scan_repository_task, request.directory_path, new_scan.id)

    return {"message": "Scan initiated", "scan_id": new_scan.id}

@router.get("/scans")
async def get_scans(db: Session = Depends(get_db)):
    """Retrieve history of all repository scans."""
    scans = db.query(ScanHistory).order_by(ScanHistory.started_at.desc()).all()
    return scans

@router.post("/parse", response_model=WorkbookMetadata)
async def parse_tableau_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if not (file.filename.endswith('.twb') or file.filename.endswith('.twbx')):
        raise HTTPException(status_code=400, detail="Only .twb and .twbx files are supported.")

    fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(file.filename)[1])
    os.close(fd)

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        with TableauParser(temp_path) as parser:
            metadata = parser.parse()
            metadata.source_file = os.path.basename(file.filename)
            metadata.file_size_bytes = file.size or os.path.getsize(temp_path)
            import time
            metadata.last_modified = time.time()
            col_to_table_map = dict(getattr(parser, "col_to_table_map", {}) or {})

        sync_metadata_to_db(metadata, db)

        # Enqueue for background ontology matching to avoid SQLite race conditions
        # and prevent HTTP request timeout during long-running matching loops.
        try:
            from app.services.ontology.ontology_service import enqueue_ontology_matching
            enqueue_ontology_matching(metadata, col_to_table_map)
        except Exception as ont_err:
            import logging
            logging.getLogger(__name__).error(
                "Failed to enqueue ontology matching for %s: %s",
                file.filename, ont_err, exc_info=True,
            )
            # Non-fatal: file parsing succeeded, ontology matching enqueuing failed

        new_scan = ScanHistory(
            directory_path=file.filename,
            status="completed",
            total_files=1,
            processed_files=1
        )
        db.add(new_scan)
        db.commit()

        return metadata
    except Exception as e:
        import traceback
        try:
            log_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            with open(os.path.join(log_dir, "error.log"), "a") as f:
                f.write(f"\n--- ERROR IN PARSE ---\n{traceback.format_exc()}\n")
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/unzip-debug")
async def unzip_debug():
    import zipfile
    zip_path = r"c:\Users\91798\.gemini\antigravity\scratch\tableau_gov_platform\tableau governacne.zip"
    extract_path = r"c:\Users\91798\.gemini\antigravity\scratch\tableau_gov_platform\tableau governacne_extracted"
    
    if not os.path.exists(zip_path):
        return {"error": "Zip file not found"}
        
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_path)
            
        # Find extracted twb/twbx files
        extracted_files = []
        for root, dirs, files in os.walk(extract_path):
            for file in files:
                if file.endswith(('.twb', '.twbx')):
                    extracted_files.append(os.path.join(root, file))
                    
        return {
            "message": "Unzipped successfully",
            "extracted_files": extracted_files
        }
    except Exception as e:
        return {"error": str(e)}

