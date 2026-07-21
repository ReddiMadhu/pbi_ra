from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text, JSON, cast
from sqlalchemy.orm import relationship, foreign
from datetime import datetime
from app.db.session import Base

class ScanHistory(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    directory_path = Column(String, index=True)
    status = Column(String, default="pending")
    total_files = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)
    errors = Column(JSON, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    workbooks = relationship("Workbook", back_populates="scan")

class Workbook(Base):
    __tablename__ = "workbooks"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=True)
    name = Column(String, index=True)
    source_file = Column(String)
    version = Column(String)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    scan = relationship("ScanHistory", back_populates="workbooks")
    dashboards = relationship("Dashboard", back_populates="workbook")
    worksheets = relationship("Worksheet", back_populates="workbook")
    datasources = relationship("DatasourceModel", back_populates="workbook")

class Dashboard(Base):
    __tablename__ = "dashboards"

    id = Column(Integer, primary_key=True, index=True)
    workbook_id = Column(Integer, ForeignKey("workbooks.id"))
    name = Column(String, index=True)
    domain_classification = Column(String, nullable=True)
    ontology_sector = Column(String, nullable=True, index=True)
    ontology_subdomain = Column(String, nullable=True, index=True)
    line_of_business = Column(String, nullable=True)
    user_groups = Column(JSON, nullable=True)
    complexity_score = Column(Float, nullable=True)
    ai_summary = Column(Text, nullable=True)
    raw_metadata = Column(JSON, nullable=True)
    is_real_ai = Column(Integer, default=0)
    scope_status = Column(String, default="pending_approval", index=True)

    workbook = relationship("Workbook", back_populates="dashboards")
    worksheets = relationship("Worksheet", back_populates="dashboard")
    calculated_fields = relationship("CalculatedField", back_populates="dashboard")
    risks = relationship("GovernanceRisk", back_populates="dashboard")
    kpi_mappings = relationship(
        "ReportKPIMapping",
        primaryjoin="cast(Dashboard.id, String) == foreign(ReportKPIMapping.report_id)",
        viewonly=True,
    )

class Worksheet(Base):
    __tablename__ = "worksheets"

    id = Column(Integer, primary_key=True, index=True)
    workbook_id = Column(Integer, ForeignKey("workbooks.id"))
    dashboard_id = Column(Integer, ForeignKey("dashboards.id"), nullable=True)
    name = Column(String, index=True)
    used_calculated_fields = Column(JSON, default=list)
    rows = Column(JSON, default=list)
    columns = Column(JSON, default=list)
    filters_and_marks = Column(JSON, default=list)
    mark_type = Column(String, nullable=True)
    measure_bindings = Column(JSON, default=list)

    dashboard = relationship("Dashboard", back_populates="worksheets")
    workbook = relationship("Workbook", back_populates="worksheets")

class CalculatedField(Base):
    __tablename__ = "calculated_fields"

    id = Column(Integer, primary_key=True, index=True)
    dashboard_id = Column(Integer, ForeignKey("dashboards.id"))
    name = Column(String)
    formula = Column(Text)
    datatype = Column(String)

    dashboard = relationship("Dashboard", back_populates="calculated_fields")

class GovernanceRisk(Base):
    __tablename__ = "governance_risks"

    id = Column(Integer, primary_key=True, index=True)
    dashboard_id = Column(Integer, ForeignKey("dashboards.id"))
    risk_type = Column(String)
    description = Column(Text)
    severity = Column(String)

    dashboard = relationship("Dashboard", back_populates="risks")

class DatasourceModel(Base):
    """Persists datasource metadata per workbook for lineage purposes."""
    __tablename__ = "datasources"

    id = Column(Integer, primary_key=True, index=True)
    workbook_id = Column(Integer, ForeignKey("workbooks.id"))
    name = Column(String, index=True)
    caption = Column(String, nullable=True)

    workbook = relationship("Workbook", back_populates="datasources")
    tables = relationship("TableModel", back_populates="datasource")
    joins = relationship("TableJoin", back_populates="datasource")

class TableModel(Base):
    """Persists individual tables within a datasource."""
    __tablename__ = "tables"

    id = Column(Integer, primary_key=True, index=True)
    datasource_id = Column(Integer, ForeignKey("datasources.id"))
    name = Column(String, index=True)
    business_name = Column(String, nullable=True)
    columns = Column(JSON, nullable=True)
    rows = Column(JSON, nullable=True)

    datasource = relationship("DatasourceModel", back_populates="tables")

class TableJoin(Base):
    """Persists join relationships between tables (the core of lineage)."""
    __tablename__ = "table_joins"

    id = Column(Integer, primary_key=True, index=True)
    datasource_id = Column(Integer, ForeignKey("datasources.id"))
    left_table = Column(String)
    right_table = Column(String)
    join_type = Column(String)       # inner, left, right, full
    left_column = Column(String)     # column on left table
    right_column = Column(String)    # column on right table

    datasource = relationship("DatasourceModel", back_populates="joins")
