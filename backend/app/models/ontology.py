from sqlalchemy import Column, String, Float, Text, DateTime, LargeBinary, Index, UniqueConstraint, Boolean
from datetime import datetime
from app.db.session import Base


class OntologyKPI(Base):
    __tablename__ = "ontology_kpis"
    __table_args__ = (
        UniqueConstraint(
            "name",
            "sector",
            "subdomain",
            name="uq_okpi_name_sector_subdomain",
        ),
    )

    kpi_id = Column(String, primary_key=True)
    # Name alone is NOT unique: same Measurement(KPI) can exist per subdomain
    # e.g. Average Premium in Marketing and Distribution
    name = Column(String, nullable=False, index=True)
    definition = Column(Text, nullable=False)
    domain = Column(String, nullable=True)
    sector = Column(String, nullable=True, index=True)
    subdomain = Column(String, nullable=True, index=True)
    line_of_business = Column(String, nullable=True, index=True)
    aliases = Column(Text, nullable=True)  # JSON array
    aggregation_type = Column(String, nullable=True)
    valid_dimensions = Column(Text, nullable=True)  # JSON array
    representative_lineage = Column(Text, nullable=True)  # JSON array
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="active")
    embedding = Column(LargeBinary, nullable=True)
    embedding_model = Column(String, nullable=True)  # Tracks which model generated this embedding


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
    is_dynamic = Column(Boolean, default=False)
    mapping_type = Column(String, nullable=True)  # exact, alias, formula_equivalent, semantic_match, no_match
    alternative_candidates = Column(Text, nullable=True)  # JSON array of top-5 candidates
    formula_similarity = Column(Float, nullable=True)  # 0.0–1.0 SequenceMatcher score
    warnings = Column(Text, nullable=True)  # JSON array of quality-check warnings
    approval_decision = Column(String, nullable=True)  # AUTO_APPROVE | REQUIRES_HUMAN_REVIEW


Index(
    "idx_rkm_report_ws_kpi",
    ReportKPIMapping.report_id,
    ReportKPIMapping.worksheet_id,
    ReportKPIMapping.report_kpi_name,
    unique=True,
)


class ReportKPILineageMetadata(Base):
    """Stores base field associations for KPIs (many-to-many).

    Used to track which raw database columns a KPI depends on,
    without cluttering the main KPI catalog.
    """
    __tablename__ = "report_kpi_lineage_metadata"

    id = Column(String, primary_key=True)
    report_kpi_mapping_id = Column(String, nullable=False, index=True)
    base_field_name = Column(String, nullable=False)
    formula = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


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
