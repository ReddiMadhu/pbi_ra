import os
from datetime import datetime
from app.services.parser.tableau_parser import TableauParser
from app.db.session import SessionLocal
from app.services.parser.sync_to_db import sync_metadata_to_db
from app.models.postgres import ScanHistory


def scan_repository_task(directory_path: str, scan_id: int):
    """
    Plain background function — no Celery or Redis needed.
    FastAPI's BackgroundTasks runs this automatically in a thread pool.
    Recursively scans a directory for .twb and .twbx files, parses metadata,
    and persists everything to SQLite.
    """
    total_files = 0
    processed_files = 0
    errors = []
    scan_record = None

    db = SessionLocal()

    try:
        scan_record = db.query(ScanHistory).filter(ScanHistory.id == scan_id).first()
        if not scan_record:
            return

        scan_record.status = "processing"
        db.commit()

        # First pass: count all .twb/.twbx files
        for root, _, files in os.walk(directory_path):
            for file in files:
                if file.endswith('.twb') or file.endswith('.twbx'):
                    total_files += 1

        scan_record.total_files = total_files
        db.commit()

        if total_files == 0:
            scan_record.status = "completed"
            scan_record.completed_at = datetime.utcnow()
            db.commit()
            return

        # Second pass: parse each file and sync to SQLite
        for root, _, files in os.walk(directory_path):
            for file in files:
                if file.endswith('.twb') or file.endswith('.twbx'):
                    file_path = os.path.join(root, file)
                    try:
                        with TableauParser(file_path) as parser:
                            metadata = parser.parse()
                            metadata.source_file = file
                            col_to_table_map = dict(getattr(parser, "col_to_table_map", {}) or {})

                        sync_metadata_to_db(metadata, db)
                        try:
                            from app.services.ontology.ontology_service import enqueue_ontology_matching
                            enqueue_ontology_matching(metadata, col_to_table_map)
                        except Exception:
                            pass
                        processed_files += 1
                        scan_record.processed_files = processed_files
                        db.commit()

                    except Exception as e:
                        errors.append({"file": file_path, "error": str(e)})

        scan_record.status = "completed"
        scan_record.errors = errors
        scan_record.completed_at = datetime.utcnow()
        db.commit()

    except Exception as e:
        if scan_record:
            scan_record.status = "failed"
            scan_record.errors = [{"fatal": str(e)}]
            scan_record.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
