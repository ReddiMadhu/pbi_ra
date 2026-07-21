from fastapi import APIRouter
from app.api.v1.upload import router as upload_router
from app.api.v1.lineage import router as lineage_router
from app.api.v1.agent import router as agent_router
from app.api.v1.chat import router as chat_router
from app.api.v1.kpi_graph import router as kpi_graph_router
from app.api.v1.ontology import router as ontology_router
from app.api.v1.governance import router as governance_router

api_router = APIRouter()

@api_router.get("/health")
def health_check():
    return {"status": "ok"}

api_router.include_router(upload_router, prefix="/upload", tags=["upload"])
api_router.include_router(lineage_router, prefix="/lineage", tags=["lineage"])
api_router.include_router(agent_router, prefix="/agent", tags=["agent"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(kpi_graph_router, prefix="/kpi-graph", tags=["kpi-graph"])
api_router.include_router(ontology_router, prefix="/ontology", tags=["ontology"])
api_router.include_router(governance_router, prefix="/governance", tags=["governance"])


