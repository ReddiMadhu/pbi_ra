from pydantic import BaseModel
from typing import List, Optional, Any

class ColumnMetadata(BaseModel):
    name: str
    datatype: str
    role: str
    type: str

class CalculatedFieldMetadata(BaseModel):
    name: str
    caption: Optional[str] = None
    formula: str
    datatype: str

class TableMetadata(BaseModel):
    name: str
    class_name: Optional[str] = None
    columns_preview: List[str] = []          # column header names
    rows_preview: List[List[str]] = []       # up to 5 data rows (stringified values)

class JoinRelationship(BaseModel):
    """Represents a join between two tables extracted from the Tableau datasource."""
    left_table: str
    right_table: str
    join_type: str          # inner, left, right, full
    left_column: str        # column used on left side of join
    right_column: str       # column used on right side of join

class DatasourceMetadata(BaseModel):
    name: str
    caption: Optional[str] = None
    version: Optional[str] = None
    tables: List[TableMetadata] = []
    columns: List[ColumnMetadata] = []
    calculated_fields: List[CalculatedFieldMetadata] = []
    joins: List[JoinRelationship] = []      # NEW: table-to-table join graph

class WorksheetMetadata(BaseModel):
    name: str
    used_calculated_fields: List[str] = []
    rows: List[str] = []
    columns: List[str] = []
    filters_and_marks: List[str] = []
    mark_type: Optional[str] = None
    measure_bindings: List[dict] = []  # {field, aggregation, table}

class DashboardMetadata(BaseModel):
    name: str
    worksheets: List[str] = []
    domain: Optional[str] = None
    line_of_business: Optional[str] = None
    user_groups: List[str] = []
    kpis: Optional[Any] = None

class WorkbookMetadata(BaseModel):
    source_file: str
    version: Optional[str] = None
    file_size_bytes: Optional[int] = 0
    last_modified: Optional[float] = 0.0
    datasources: List[DatasourceMetadata] = []
    worksheets: List[WorksheetMetadata] = []
    dashboards: List[DashboardMetadata] = []
