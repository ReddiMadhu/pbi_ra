from sqlalchemy import Column, String, Float, Text, DateTime, LargeBinary, Index
from datetime import datetime
from app.db.session import Base


class OntologyKPI(Base):
    __tablename__ = "ontology_kpis"

    kpi_id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    definition = Column(Text, nullable=False)
    domain = Column(String, nullable=True)
    sector = Column(String, nullable=True, index=True)
    subdomain = Column(String, nullable=True, index=True)
    aliases = Column(Text, nullable=True)  # JSON array
    aggregation_type = Column(String, nullable=True)
    valid_dimensions = Column(Text, nullable=True)  # JSON array
    representative_lineage = Column(Text, nullable=True)  # JSON array
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="active")
    embedding = Column(LargeBinary, nullable=True)


Index(
    "idx_okpi_sector_subdomain_status",
    OntologyKPI.sector,
    OntologyKPI.subdomain,
    OntologyKPI.status,
)


class ReportKPIMapping(Base):
    __tablename__ = "report_kpi_mappings"

    mapping_id = Column(String, primary_key=True)
    report_id = Column(String, nullable=False, index=True)
    worksheet_id = Column(String, nullable=True, index=True)
    worksheet_name = Column(String, nullable=True)
    report_kpi_name = Column(String, nullable=False)
    report_kpi_lineage = Column(Text, nullable=True)  # JSON array
    report_kpi_aggregation = Column(String, nullable=True)
    report_kpi_definition = Column(Text, nullable=True)
    canonical_kpi_id = Column(String, nullable=True, index=True)
    similarity_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    similarity_rationale = Column(Text, nullable=True)
    confidence_rationale = Column(Text, nullable=True)
    mapping_status = Column(String, default="pending_review", index=True)
    resolved_by = Column(String, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    model_used = Column(String, nullable=True)
    ontology_version = Column(String, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow)


Index(
    "idx_rkm_report_ws_kpi",
    ReportKPIMapping.report_id,
    ReportKPIMapping.worksheet_id,
    ReportKPIMapping.report_kpi_name,
    unique=True,
)


class KPIOntologyCache(Base):
    __tablename__ = "kpi_ontology_cache"

    cache_key = Column(String, primary_key=True)
    canonical_kpi_id = Column(String, nullable=True)
    similarity_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    similarity_rationale = Column(Text, nullable=True)
    confidence_rationale = Column(Text, nullable=True)
    model_used = Column(String, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow)
