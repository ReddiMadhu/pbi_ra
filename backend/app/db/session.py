from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import os

# Dynamic path resolution: Use persistent /home/data on Azure Linux, fall back to local root in dev
if os.path.exists("/home") and ("WEBSITE_SITE_NAME" in os.environ or "WEBSITE_INSTANCE_ID" in os.environ):
    PERSISTENT_DIR = "/home/data"
    os.makedirs(PERSISTENT_DIR, exist_ok=True)
    DB_PATH = os.path.join(PERSISTENT_DIR, "tableau_gov.db")
    SQLITE_URL = f"sqlite:///{DB_PATH}"
else:
    SQLITE_URL = "sqlite:///./tableau_gov.db"
engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False, "timeout": 30}  # Required for SQLite with FastAPI/concurrency
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
