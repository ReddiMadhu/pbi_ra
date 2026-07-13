from celery import Celery
from app.core.config import settings

# Initialize Celery app
# Defaults to local Redis if env variables are not set
celery_app = Celery(
    "tableau_gov_worker",
    broker=getattr(settings, "CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=getattr(settings, "CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    # Include the modules where our tasks are defined
    imports=["app.worker.tasks"]
)
