from sqlalchemy import Column, String, Float, Text, DateTime, LargeBinary, Integer
from datetime import datetime
from app.db.session import Base


class ReportFingerprint(Base):
    __tablename__ = "report_fingerprints"

    report_id = Column(String, primary_key=True)
    data_source_hash = Column(String, nullable=True)
    semantic_model_hash = Column(String, nullable=True)
    dax_minhash = Column(LargeBinary, nullable=True)
    dax_simhash = Column(LargeBinary, nullable=True)
    visual_hash = Column(String, nullable=True)
    filter_hash = Column(String, nullable=True)
    ontology_kpi_hash = Column(String, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow)


class PairwiseScore(Base):
    __tablename__ = "pairwise_scores"

    report_a_id = Column(String, primary_key=True)
    report_b_id = Column(String, primary_key=True)
    data_source_score = Column(Float, nullable=True)
    semantic_model_score = Column(Float, nullable=True)
    ontology_kpi_score = Column(Float, nullable=True)
    dax_structural_score = Column(Float, nullable=True)
    visual_score = Column(Float, nullable=True)
    filter_score = Column(Float, nullable=True)
    composite_score = Column(Float, nullable=True)
    classification = Column(String, nullable=True)
    subsumption = Column(String, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow)


class Cluster(Base):
    __tablename__ = "clusters"

    cluster_id = Column(Integer, primary_key=True)
    algorithm = Column(String, primary_key=True)
    report_id = Column(String, primary_key=True)
    is_golden = Column(Integer, default=0)
    golden_score = Column(Float, nullable=True)
    recommendation = Column(String, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow)


class ContentMigrationTask(Base):
    __tablename__ = "content_migration_tasks"

    source_report_id = Column(String, primary_key=True)
    target_report_id = Column(String, primary_key=True)
    content_type = Column(String, primary_key=True)
    content_id = Column(String, primary_key=True)
    content_name = Column(String, nullable=True)
    status = Column(String, default="pending")


class Explanation(Base):
    __tablename__ = "explanations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    context_type = Column(String, nullable=False)
    context_key = Column(String, nullable=False)
    explanation = Column(Text, nullable=False)
    model_used = Column(String, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow)


class ScoreDetail(Base):
    __tablename__ = "score_details"

    report_a_id = Column(String, primary_key=True)
    report_b_id = Column(String, primary_key=True)
    layer = Column(String, primary_key=True)
    score = Column(Float, nullable=True)
    detail_json = Column(Text, nullable=True)


class MeasureEquivalence(Base):
    __tablename__ = "measure_equivalences"

    measure_a_id = Column(String, primary_key=True)
    measure_b_id = Column(String, primary_key=True)
    match_method = Column(String, nullable=True)
    similarity_score = Column(Float, nullable=True)
    llm_explanation = Column(Text, nullable=True)


class GovernanceFlag(Base):
    __tablename__ = "governance_flags"

    report_a_id = Column(String, primary_key=True)
    report_b_id = Column(String, primary_key=True)
    flag_type = Column(String, primary_key=True)
    detail = Column(Text, nullable=True)
