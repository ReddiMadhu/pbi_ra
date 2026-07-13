# Complete Technical Implementation Plan
## Tableau BI Compass — Intelligence + Rationalization + Ontology View

**Version:** Final  
**Spec Sources:** v3.md (comparison engine), ontology_plan.md (KPI bank), ontolgoy.md (architecture overview), implementation_plan.md (hybrid design)  
**Codebase:** `backend/app/` (FastAPI + SQLAlchemy + SQLite) | `frontend/src/` (React + Vite + TypeScript)

---

## 1. Executive Summary

Three features are being added to the existing Tableau BI Compass platform:

| Feature | What It Does | v3.md Reference |
|---|---|---|
| **Intelligence** | KPI Ontology Bank — per-report KPI extraction → LLM mapping → canonical KPI catalog | §3.3 Stage -1, §10.1 |
| **Rationalization** | 6-layer similarity scoring → cluster → Decommission/Merge/Keep recommendations | §6.1 composite update, ontology_plan.md §1 |
| **Ontology View** | Standalone UI page to browse, curate, and manage the KPI bank + HITL resolution | ontology_plan.md §7, ontolgoy.md §5 |

> [!IMPORTANT]
> **Nothing is rewritten.** Every feature is an additive layer on the existing architecture:
> - `tableau_parser.py` already extracts calculated fields → feeds KPI extraction
> - `kpi_graph.py` already clusters KPIs via LLM (`get_kpi_clusters`) → seeds the ontology bank
> - `agent.py` already computes similarity → composite formula is updated, not replaced
> - `RecommendationsView.tsx` already handles rationalization → ontology score is injected via optional fields
> - `Layout.tsx` + `App.tsx` already handle navigation → one new nav item, one new view

---

## 2. System Architecture After Implementation

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite + TypeScript)                                   │
│                                                                         │
│  Layout.tsx ──── navItems[ BI Explore | Dashboard Overview | Landscape  │
│                             Recommendations | BI Assist | Ontology Bank ]│
│                                                                         │
│  App.tsx ─── View Router ──────────────────────────────────────────────┐│
│                │                                                        ││
│   [existing]  ├── 'areas'           → BusinessAreasView                ││
│               ├── 'overview'        → DashboardOverviewView             ││
│               ├── 'landscape'       → LandscapeView                    ││
│               ├── 'recommendations' → RecommendationsView [MODIFIED]   ││
│               ├── 'bi_assist'       → BIAssistView                     ││
│               ├── 'kpiGraph'        → KPIDashboardGraph                 ││
│               ├── 'detail'          → DetailView [MODIFIED]            ││
│   [NEW]       └── 'ontology'        → OntologyBankView [NEW]           ││
│                                                                         ││
│  New Components:                                                        ││
│  ├── OntologyBankView.tsx    ← KPI bank browser + HITL resolution      ││
│  ├── OntologyScoreBadge.tsx  ← Inline KPI inventory badge              ││
│  └── HITLResolutionPanel.tsx ← Accept/Reject/Promote drawer            ││
└─────────────────────────────────────────────────────────────────────────┘
                              │ REST API calls
┌─────────────────────────────────────────────────────────────────────────┐
│  Backend (FastAPI + SQLAlchemy + SQLite)                                │
│                                                                         │
│  main.py ──── Lifespan: auto-creates tables on startup                 │
│  api.py  ──── Routers: upload | lineage | agent | chat | kpi-graph     │
│                                     + ontology [NEW]                    │
│                                                                         │
│  api/v1/                                                                │
│  ├── ontology.py [NEW]       ← 7 REST endpoints (CRUD + HITL)          │
│  ├── agent.py   [MODIFIED]   ← enrich_with_ontology_inventory()        │
│  │                              6-layer composite scoring               │
│  └── upload.py  [MODIFIED]   ← trigger Stage -1 after parse            │
│                                                                         │
│  services/ontology/ [NEW]                                               │
│  ├── kpi_extractor.py        ← 3-tier extraction (regex→parser→LLM)   │
│  ├── ontology_service.py     ← 3-phase matching (exact→embed→LLM)     │
│  ├── ontology_cache.py       ← DB-backed KPI-level cache               │
│  ├── embedding_service.py    ← thin wrapper on existing LLM embeddings │
│  └── bootstrap_ontology.py  ← one-time seed from kpi_graph.py data    │
│                                                                         │
│  models/                                                                │
│  ├── postgres.py [MODIFIED]  ← 3 new SQLAlchemy models                 │
│  └── ontology.py [NEW]       ← OntologyKPI, ReportKPIMapping, Cache   │
│                                                                         │
│  core/llm.py    [UNCHANGED]  ← CachedLLM reused for Phase 3 LLM calls │
│  core/cache.py  [UNCHANGED]  ← prompt-level cache still active         │
└─────────────────────────────────────────────────────────────────────────┘
                              │ SQLAlchemy ORM
┌─────────────────────────────────────────────────────────────────────────┐
│  Database (SQLite dev / PostgreSQL prod)                                │
│                                                                         │
│  [existing tables — untouched]                                          │
│  scans │ workbooks │ dashboards │ worksheets │ calculated_fields        │
│  datasources │ tables │ table_joins │ governance_risks                  │
│                                                                         │
│  [new tables from v3.md §9.1 + ontology_plan.md §2]                    │
│  ├── ontology_kpis          ← canonical KPI definitions                │
│  ├── report_kpi_mappings    ← per-dashboard KPI → canonical mapping    │
│  └── kpi_ontology_cache     ← KPI-level cache (lineage+agg hash)       │
│                                                                         │
│  [v3.md comparison tables — added in Phase 4]                          │
│  ├── report_fingerprints    ← MinHash, SimHash, visual hash per report  │
│  ├── pairwise_scores        ← 6-layer composite per candidate pair      │
│  ├── clusters               ← cluster assignments per algorithm         │
│  ├── score_details          ← per-layer breakdown with detail JSON      │
│  ├── measure_equivalences   ← measure-level match method + score        │
│  ├── governance_flags       ← RLS/refresh/gateway flags per pair        │
│  ├── content_migration_tasks← items to migrate when golden ⊂ decom    │
│  └── explanations           ← LLM-generated cluster/merge summaries     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Complete Data Flow

```
User uploads .twb/.twbx
        │
        ▼
upload.py → TableauParser.parse()
   • Returns WorkbookMetadata with calculated_fields[], datasources[]
   • col_to_table_map built inside parser (already exists)
        │
        ▼ [NEW — Stage -1]
kpi_extractor.extract_kpis_from_workbook()
   • Tier 1: regex (SUM/AVG patterns)    → ~60% coverage
   • Tier 2: parser col_to_table_map     → ~25% more
   • Tier 3: LLM fallback via get_llm() → ~15% remainder
   • Deduplication by lineage hash
        │
        ▼ [NEW]
ontology_service.match_kpi_to_ontology()
   • Phase 1: exact name/alias match     → zero LLM
   • Phase 2: DB cache → embedding cosine filter → zero LLM if >0.95
   • Phase 3: LLM judge (ambiguous only, ~20-40% of KPIs)
        │
        ▼
report_kpi_mappings table
   • mapping_status: auto_accepted | pending_review | not_found
        │
        ▼
agent.py /recommendations endpoint
   • Existing: worksheet similarity, KPI overlap, table overlap
   • NEW: enrich_with_ontology_inventory() adds ontology_score
   • NEW: 6-layer composite (adds 0.20 × ontology_kpi_score)
   • Existing: decommission / merge / keep classification
        │
        ▼
Frontend
   • RecommendationsView.tsx: optional ontology_inventory field rendered
   • OntologyScoreBadge.tsx: 10 mapped ✅ | 3 ambiguous ⚠️ | 2 NF ❌
   • OntologyBankView.tsx: HITL resolution queue, KPI bank browser
```

---

## 4. Database Schema (Complete)

### 4.1 New Tables for Ontology Layer

```sql
-- Canonical KPI definitions (the "source of truth" — ontology_plan.md §2)
CREATE TABLE ontology_kpis (
    kpi_id           TEXT PRIMARY KEY,   -- UUID
    name             TEXT NOT NULL UNIQUE,
    definition       TEXT NOT NULL,
    domain           TEXT,               -- 'Finance', 'Sales', 'Operations', etc.
    aliases          TEXT,               -- JSON array: '["Revenue", "Net Sales"]'
    aggregation_type TEXT,               -- 'SUM', 'AVERAGE', 'COUNT', 'NONE'
    valid_dimensions TEXT,               -- JSON array: '["Region", "Time"]'
    created_by       TEXT NOT NULL,      -- 'bootstrap_script' | analyst ID
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status           TEXT DEFAULT 'active' CHECK (status IN ('active', 'stale')),
    embedding        BLOB                -- pre-computed float[] for Phase 2
);

-- Per-dashboard KPI → canonical mapping
CREATE TABLE report_kpi_mappings (
    mapping_id           TEXT PRIMARY KEY,
    report_id            TEXT NOT NULL,   -- dashboard.id as string
    report_kpi_name      TEXT NOT NULL,   -- original name in the dashboard
    report_kpi_lineage   TEXT,            -- JSON: '["Sales.Amount","Returns.Amount"]'
    report_kpi_aggregation TEXT,
    canonical_kpi_id     TEXT,            -- FK → ontology_kpis (NULL if NF)
    similarity_score     REAL,
    confidence_score     REAL,
    similarity_rationale TEXT,
    confidence_rationale TEXT,
    mapping_status       TEXT DEFAULT 'pending_review' CHECK (
                           mapping_status IN (
                             'auto_accepted','pending_review','human_accepted',
                             'human_rejected','not_found','promoted'
                           )
                         ),
    resolved_by          TEXT,
    resolved_at          TIMESTAMP,
    model_used           TEXT,           -- extraction_method from kpi_extractor.py
    ontology_version     TEXT,
    computed_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (report_id, report_kpi_name)
);

-- KPI-level LLM result cache (separate from prompt-level cache.py)
CREATE TABLE kpi_ontology_cache (
    cache_key            TEXT PRIMARY KEY,  -- SHA256(sorted_lineage+agg+ont_version)
    canonical_kpi_id     TEXT,
    similarity_score     REAL,
    confidence_score     REAL,
    similarity_rationale TEXT,
    confidence_rationale TEXT,
    model_used           TEXT,
    computed_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_rkm_report   ON report_kpi_mappings (report_id);
CREATE INDEX idx_rkm_canonical ON report_kpi_mappings (canonical_kpi_id);
CREATE INDEX idx_rkm_status   ON report_kpi_mappings (mapping_status);
CREATE INDEX idx_okpi_domain  ON ontology_kpis (domain);
CREATE INDEX idx_okpi_status  ON ontology_kpis (status);
```

### 4.2 New Tables for Rationalization Layer (v3.md §9.1)

```sql
-- Per-report fingerprints (Stage 0-1)
CREATE TABLE report_fingerprints (
    report_id            TEXT PRIMARY KEY,
    data_source_hash     TEXT,
    semantic_model_hash  TEXT,
    dax_minhash          BLOB,
    dax_simhash          BLOB,
    visual_hash          TEXT,
    filter_hash          TEXT,
    ontology_kpi_hash    TEXT,       -- NEW: hash of sorted canonical_kpi_id set
    computed_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6-layer pairwise scores (Stage 2 — updated composite formula)
CREATE TABLE pairwise_scores (
    report_a_id          TEXT NOT NULL,
    report_b_id          TEXT NOT NULL,
    data_source_score    REAL,
    semantic_model_score REAL,
    ontology_kpi_score   REAL,       -- NEW (20%)
    dax_structural_score REAL,       -- RENAMED from dax_score, now 10%
    visual_score         REAL,
    filter_score         REAL,
    composite_score      REAL,
    classification       TEXT CHECK (classification IN (
                           'exact_clone','near_clone','functional_overlap',
                           'unrelated','review'
                         )),
    subsumption          TEXT,
    computed_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (report_a_id, report_b_id)
);

-- Cluster assignments
CREATE TABLE clusters (
    cluster_id     INTEGER NOT NULL,
    algorithm      TEXT CHECK (algorithm IN ('louvain','hierarchical','dbscan')),
    report_id      TEXT NOT NULL,
    is_golden      INTEGER DEFAULT 0,
    golden_score   REAL,
    recommendation TEXT CHECK (recommendation IN (
                     'keep','decommission','merge','review',
                     'strong_decommission','merge_content_into_golden'
                   )),
    computed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cluster_id, algorithm, report_id)
);

-- Content migration tasks (v3.md §4.3 gap analysis)
CREATE TABLE content_migration_tasks (
    source_report_id TEXT NOT NULL,
    target_report_id TEXT NOT NULL,
    content_type     TEXT CHECK (content_type IN ('measure','visual','filter','drillthrough')),
    content_id       TEXT NOT NULL,
    content_name     TEXT,
    status           TEXT DEFAULT 'pending' CHECK (status IN ('pending','in_progress','done')),
    PRIMARY KEY (source_report_id, target_report_id, content_type, content_id)
);

-- LLM explanations cache (cluster summaries, merge recommendations)
CREATE TABLE explanations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    context_type TEXT CHECK (context_type IN ('dax_equivalence','cluster_summary','merge_recommendation')),
    context_key  TEXT NOT NULL,
    explanation  TEXT NOT NULL,
    model_used   TEXT,
    computed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (context_type, context_key)
);

-- Per-layer score breakdowns
CREATE TABLE score_details (
    report_a_id TEXT NOT NULL,
    report_b_id TEXT NOT NULL,
    layer       TEXT CHECK (layer IN ('data_source','semantic_model','ontology_kpi',
                              'dax_structural','visuals','filters')),
    score       REAL,
    detail_json TEXT,   -- JSON for SQLite (JSONB for Postgres)
    PRIMARY KEY (report_a_id, report_b_id, layer)
);

-- Measure-level equivalences (for explainability drill-down)
CREATE TABLE measure_equivalences (
    measure_a_id     TEXT NOT NULL,
    measure_b_id     TEXT NOT NULL,
    match_method     TEXT CHECK (match_method IN ('exact','signature','ast','llm')),
    similarity_score REAL,
    llm_explanation  TEXT,
    PRIMARY KEY (measure_a_id, measure_b_id)
);

-- Governance flags per report pair (v3.md §3.6)
CREATE TABLE governance_flags (
    report_a_id TEXT NOT NULL,
    report_b_id TEXT NOT NULL,
    flag_type   TEXT CHECK (flag_type IN (
                  'RLS_CONFLICT','REFRESH_MISMATCH',
                  'GATEWAY_DIFFERENT','PERMISSION_DIVERGENCE'
                )),
    detail      TEXT,
    PRIMARY KEY (report_a_id, report_b_id, flag_type)
);
```

### 4.3 Auto-Migration in `main.py` lifespan

All new tables are added to the `Base.metadata.create_all(bind=engine)` call
by importing the new `ontology.py` model file. No separate migration tool needed
(matches existing pattern in `main.py`).

---

## 5. Updated Composite Score Formula

Per **ontology_plan.md §1** (replacing v3.md §6.1):

```
Old (5-layer):
composite = 0.25×data_source + 0.20×semantic_model + 0.30×dax + 0.15×visuals + 0.10×filters

New (6-layer):
composite = 0.25×data_source                  (unchanged)
          + 0.20×semantic_model               (unchanged)
          + 0.20×ontology_kpi_score           [NEW — Jaccard on canonical KPI ID sets]
          + 0.10×dax_structural_score         [REDUCED from 0.30, Stage C LLM removed]
          + 0.15×visuals                      (unchanged)
          + 0.10×filters                      (unchanged)
```

**KPI overlap formula** (ontology_plan.md §5):
```python
ontology_kpi_score = len(kpis_a ∩ kpis_b) / (len(kpis_a) + len(kpis_b) - len(kpis_a ∩ kpis_b))
# Pure Jaccard on canonical_kpi_id sets. O(1), zero LLM calls at Stage 2.
# Only includes auto_accepted and human_accepted mappings (not pending/NF).
```

**DAX Structural** retains Stages A+B from v3.md §3.3 (signature + AST text normalization).
Stage C (LLM Semantic Judgment for 50-90% ambiguous DAX pairs) is **removed** — the
ontology layer now handles semantic equivalence.

---

## 6. New API Endpoints

### Ontology Router (`/api/v1/ontology`)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| `GET` | `/kpis` | List all canonical KPIs (paginated, filterable by domain/status) | — |
| `POST` | `/kpis` | Create new canonical KPI (domain expert or HITL promote) | — |
| `PUT` | `/kpis/{kpi_id}` | Update KPI definition, aliases, aggregation_type | — |
| `GET` | `/reports/{report_id}/kpis` | Get KPI inventory for one dashboard (mapped/ambiguous/NF counts) | — |
| `POST` | `/reports/{report_id}/extract` | Trigger Stage -1 extraction for this dashboard | — |
| `PUT` | `/mappings/{mapping_id}` | HITL: accept, reject, or reassign a mapping | — |
| `POST` | `/mappings/{mapping_id}/promote` | Promote a Not-Found KPI to new canonical entry | — |

### Modified Agent Router (`/api/v1/agent`)

| Method | Path | Change |
|---|---|---|
| `GET` | `/recommendations` | Add `ontology_inventory` field per dashboard item |

---

## 7. Implementation Phases

---

### Phase 1 — Database Foundation
**Duration: 2 days**  
**Dependency:** None — start here on Day 1

#### Tasks

- [ ] **Create `backend/app/models/ontology.py`** — SQLAlchemy models for `OntologyKPI`,
  `ReportKPIMapping`, `KPICache` (mirrors exact SQL schema above)
- [ ] **Modify `backend/app/models/postgres.py`** — add `report_kpi_mappings` relationship
  to `Dashboard` model: `kpi_mappings = relationship("ReportKPIMapping", ...)`
- [ ] **Modify `backend/app/main.py`** — add `import app.models.ontology` to lifespan
  (matches existing `import app.models.postgres` pattern on line 7); add `ALTER TABLE`
  guards for the new columns following the existing try/except pattern (lines 15-31)
- [ ] **Add `backend/app/db/migrations/ontology_tables.py`** — standalone script for
  environments that need explicit migration (Azure, prod)
- [ ] Run locally, confirm all 3 new tables created on startup

#### Files Changed
| File | Action |
|---|---|
| `backend/app/models/ontology.py` | **CREATE** |
| `backend/app/models/postgres.py` | **MODIFY** — add relationship |
| `backend/app/main.py` | **MODIFY** — import + lifespan guards |

#### Acceptance Criteria
- App starts, SQLite DB has `ontology_kpis`, `report_kpi_mappings`, `kpi_ontology_cache` tables
- `GET /api/v1/health` still returns `{"status":"ok"}`
- All existing endpoints unaffected

---

### Phase 2 — Intelligence Backend (Ontology Service)
**Duration: 4-5 days**  
**Dependency:** Phase 1

#### Tasks

- [ ] **Create `backend/app/services/ontology/kpi_extractor.py`**
  - 3-tier fallback: `_extract_via_regex()` → `_extract_via_parser_metadata()` → `_extract_via_llm()`
  - `extract_kpis_from_workbook(workbook, col_to_table_map, llm)` public entry
  - Deduplication by `frozenset(lineage)` hash

- [ ] **Create `backend/app/services/ontology/embedding_service.py`**
  - `compute_embedding(text) → list[float]` using existing `get_llm()` LLM provider
  - Batch support: `compute_embeddings_batch(texts) → list[list[float]]`
  - In-memory LRU cache (`@functools.lru_cache(maxsize=5000)`) to avoid re-embedding same KPI

- [ ] **Create `backend/app/services/ontology/ontology_cache.py`**
  - `OntologyCache(db, ontology_version)`
  - `get(lineage, aggregation) → dict | None`
  - `set(lineage, aggregation, result)` with `ON CONFLICT DO NOTHING`
  - Cache key: `SHA256(sorted_lineage_json + agg.upper() + ontology_version)`

- [ ] **Create `backend/app/services/ontology/ontology_service.py`**
  - `match_kpi_to_ontology(kpi, ontology_kpis, cache, llm, embedding_fn) → dict`
  - Phase 1: exact name + alias match (zero LLM)
  - Phase 2a: DB cache lookup (zero LLM)
  - Phase 2b: embedding cosine pre-filter (zero LLM; auto-accept >0.95, NF if <0.5)
  - Phase 3: LLM judge via existing `get_llm()` + `CachedLLM` (only ~20-40% of KPIs)
  - HITL threshold gate: ≥90% → `auto_accepted`, 50-89% → `pending_review`, <50% → `not_found`

- [ ] **Create `backend/app/services/ontology/bootstrap_ontology.py`**
  - Mine existing `Dashboard.ai_summary` JSON (already populated) for KPI names
  - Run through existing `get_kpi_clusters()` in `kpi_graph.py` for deduplication
  - Insert into `ontology_kpis` with `created_by='bootstrap_script'`
  - **Run this ONCE before Phase 2 testing** — provides initial seed data

- [ ] **Modify `backend/app/api/v1/upload.py`**
  - After `TableauParser.parse()` returns, call `extract_kpis_from_workbook()`
  - Persist extracted KPIs to `report_kpi_mappings` via `ontology_service.match_kpi_to_ontology()`
  - If ontology bank is empty, skip gracefully (no crash)

#### LLM Cost Control (built into the implementation)
```python
MAX_PHASE3_CALLS_PER_EXTRACTION = 200  # per dashboard upload
# In ontology_service.match_kpi_to_ontology():
#   if phase3_calls >= MAX_PHASE3_CALLS_PER_EXTRACTION:
#       return {"matched_kpi_id": None, "mapping_status": "not_found", ...}
```

#### Files Changed
| File | Action |
|---|---|
| `backend/app/services/ontology/kpi_extractor.py` | **CREATE** |
| `backend/app/services/ontology/embedding_service.py` | **CREATE** |
| `backend/app/services/ontology/ontology_cache.py` | **CREATE** |
| `backend/app/services/ontology/ontology_service.py` | **CREATE** |
| `backend/app/services/ontology/bootstrap_ontology.py` | **CREATE** |
| `backend/app/api/v1/upload.py` | **MODIFY** — add post-parse KPI extraction |

#### Acceptance Criteria
- `python -m app.services.ontology.bootstrap_ontology` seeds at least 30 KPIs from existing data
- Upload a `.twbx` → `report_kpi_mappings` populated with rows for that dashboard
- Phase 1 hits observed in logs for known KPI names (e.g. "Revenue")
- LLM call count ≤ 40% of total KPIs per dashboard

---

### Phase 3 — Ontology REST API
**Duration: 2-3 days**  
**Dependency:** Phase 1–2

#### Tasks

- [ ] **Create `backend/app/api/v1/ontology.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.ontology import OntologyKPI, ReportKPIMapping
import uuid, json
from datetime import datetime

router = APIRouter()

@router.get("/kpis")
def list_kpis(domain: str = None, status: str = "active",
              skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(OntologyKPI).filter(OntologyKPI.status == status)
    if domain:
        q = q.filter(OntologyKPI.domain == domain)
    return q.offset(skip).limit(limit).all()

@router.post("/kpis")
def create_kpi(body: dict, db: Session = Depends(get_db)):
    kpi = OntologyKPI(
        kpi_id=str(uuid.uuid4()),
        name=body["name"],
        definition=body["definition"],
        domain=body.get("domain", "General"),
        aliases=json.dumps(body.get("aliases", [])),
        aggregation_type=body.get("aggregation_type", "UNKNOWN"),
        created_by=body.get("created_by", "analyst"),
    )
    db.add(kpi); db.commit(); db.refresh(kpi)
    return kpi

@router.get("/reports/{report_id}/kpis")
def get_report_kpi_inventory(report_id: str, db: Session = Depends(get_db)):
    rows = db.query(ReportKPIMapping).filter(
        ReportKPIMapping.report_id == report_id
    ).all()
    mapped    = sum(1 for r in rows if r.mapping_status in ("auto_accepted","human_accepted"))
    ambiguous = sum(1 for r in rows if r.mapping_status == "pending_review")
    not_found = sum(1 for r in rows if r.mapping_status == "not_found")
    return {
        "report_id": report_id, "total": len(rows),
        "mapped": mapped, "ambiguous": ambiguous, "not_found": not_found,
        "ontology_score": round(mapped / max(len(rows), 1), 3),
        "items": [r.__dict__ for r in rows]
    }

@router.post("/reports/{report_id}/extract")
def trigger_extraction(report_id: str, db: Session = Depends(get_db)):
    """Manually trigger Stage -1 for a specific dashboard."""
    from app.models.postgres import Dashboard
    from app.services.ontology.kpi_extractor import extract_kpis_from_workbook
    from app.services.ontology.ontology_service import match_kpi_to_ontology
    from app.services.ontology.ontology_cache import OntologyCache
    from app.core.llm import get_llm
    dashboard = db.query(Dashboard).filter(
        Dashboard.id == int(report_id)
    ).first()
    if not dashboard:
        raise HTTPException(404, "Dashboard not found")
    # ... extraction logic (same as upload.py) ...
    return {"status": "extraction_triggered", "report_id": report_id}

@router.put("/mappings/{mapping_id}")
def update_mapping(mapping_id: str, body: dict, db: Session = Depends(get_db)):
    """HITL: accept/reject/reassign a mapping."""
    row = db.query(ReportKPIMapping).filter(
        ReportKPIMapping.mapping_id == mapping_id
    ).first()
    if not row:
        raise HTTPException(404, "Mapping not found")
    action = body.get("action")  # "accept" | "reject" | "reassign"
    if action == "accept":
        row.mapping_status = "human_accepted"
    elif action == "reject":
        row.mapping_status = "human_rejected"
    elif action == "reassign":
        row.canonical_kpi_id = body["canonical_kpi_id"]
        row.mapping_status = "human_accepted"
    row.resolved_by = body.get("analyst_id", "analyst")
    row.resolved_at = datetime.utcnow()
    db.commit()
    return row

@router.post("/mappings/{mapping_id}/promote")
def promote_nf_kpi(mapping_id: str, body: dict, db: Session = Depends(get_db)):
    """Promote a Not-Found KPI to a new canonical ontology entry."""
    row = db.query(ReportKPIMapping).filter(
        ReportKPIMapping.mapping_id == mapping_id,
        ReportKPIMapping.mapping_status == "not_found"
    ).first()
    if not row:
        raise HTTPException(404, "Not-Found mapping not found")
    new_kpi = OntologyKPI(
        kpi_id=str(uuid.uuid4()),
        name=body["name"],
        definition=body["definition"],
        domain=body.get("domain", "General"),
        aliases=json.dumps(body.get("aliases", [row.report_kpi_name])),
        aggregation_type=row.report_kpi_aggregation or "UNKNOWN",
        created_by=body.get("analyst_id", "analyst"),
    )
    db.add(new_kpi)
    row.canonical_kpi_id = new_kpi.kpi_id
    row.mapping_status = "promoted"
    row.resolved_by = body.get("analyst_id", "analyst")
    row.resolved_at = datetime.utcnow()
    db.commit()
    return {"new_kpi": new_kpi, "updated_mapping": row}
```

- [ ] **Modify `backend/app/api/v1/api.py`** — register new router:
```python
from app.api.v1.ontology import router as ontology_router
api_router.include_router(ontology_router, prefix="/ontology", tags=["ontology"])
```

#### Files Changed
| File | Action |
|---|---|
| `backend/app/api/v1/ontology.py` | **CREATE** |
| `backend/app/api/v1/api.py` | **MODIFY** — add router registration (1 line) |

#### Acceptance Criteria
- `GET /api/v1/ontology/kpis` returns the seeded KPIs from Phase 2 bootstrap
- `PUT /api/v1/ontology/mappings/{id}` with `{"action":"accept"}` updates `mapping_status`
- `POST /api/v1/ontology/mappings/{id}/promote` creates a new `ontology_kpis` row

---

### Phase 4 — Rationalization Backend
**Duration: 3-4 days**  
**Dependency:** Phase 1–2

#### Tasks

- [ ] **Create `backend/app/services/rationalization/` package**
  - `scoring.py` — 6-layer composite formula, `compute_ontology_score()` (Jaccard)
  - `fingerprints.py` — MinHash (datasketch, `params=(32,8)`), SimHash, visual hash, filter hash
  - `blocking.py` — schema fingerprint grouping, ontology blocking (soft signal per ontology_plan.md §10)
  - `clustering.py` — Louvain/hierarchical/DBSCAN via `networkx` + `scikit-learn`
  - `golden.py` — multi-factor golden selection (completeness/usage/freshness/governance/recency)

- [ ] **Modify `backend/app/api/v1/agent.py`**
  - Add `enrich_with_ontology_inventory(dashboard_id, db) → dict | None` helper
  - Inject `ontology_inventory` into `/recommendations` response for each dashboard item
  - Update composite formula: replace `0.70 * kpi_sim + 0.30 * table_sim` with the new
    6-layer formula when ontology data is available (graceful degradation if not)

- [ ] **Implement `compute_ontology_score(report_a_id, report_b_id, db)`** per ontology_plan.md §5:
```python
def compute_ontology_score(report_a_id: str, report_b_id: str, db) -> float:
    """Jaccard on canonical KPI ID sets. O(1), zero LLM. (ontology_plan.md §5)"""
    def get_kpi_set(report_id):
        return set(
            row[0] for row in db.execute(
                "SELECT canonical_kpi_id FROM report_kpi_mappings "
                "WHERE report_id = ? AND canonical_kpi_id IS NOT NULL "
                "AND mapping_status IN ('auto_accepted','human_accepted')",
                (str(report_id),)
            ).fetchall()
        )
    kpis_a, kpis_b = get_kpi_set(report_a_id), get_kpi_set(report_b_id)
    if not kpis_a and not kpis_b:
        return 0.0
    intersection = kpis_a & kpis_b
    union_size = len(kpis_a) + len(kpis_b) - len(intersection)
    return len(intersection) / union_size if union_size > 0 else 0.0
```

- [ ] **Implement subsumption detection** (v3.md §4.3):
  - `check_subsumption(report_a, report_b, threshold=0.90) → 'A⊂B' | 'B⊂A' | None`
  - Check measures, visuals, filters separately (90% set inclusion each)

- [ ] **Implement golden report selection** (v3.md §6.4):
  - Multi-factor scoring: completeness (0.35) + usage (0.25) + freshness (0.20) +
    governance (0.10) + recency (0.10)
  - All sub-scores normalized within cluster
  - Subsumption override: `merge_content_into_golden` when usage favors subset

- [ ] **Implement staleness prioritization** (v3.md §6.5):
  - `days_since_refresh > 90 AND max_similarity_to_active > 70%` → `strong_decommission`

#### Files Changed
| File | Action |
|---|---|
| `backend/app/services/rationalization/scoring.py` | **CREATE** |
| `backend/app/services/rationalization/fingerprints.py` | **CREATE** |
| `backend/app/services/rationalization/blocking.py` | **CREATE** |
| `backend/app/services/rationalization/clustering.py` | **CREATE** |
| `backend/app/services/rationalization/golden.py` | **CREATE** |
| `backend/app/api/v1/agent.py` | **MODIFY** — enrich + 6-layer composite |

#### Acceptance Criteria
- `compute_ontology_score()` returns 1.0 for two reports with identical canonical KPI sets
- `compute_ontology_score()` returns 0.5 for 2 shared KPIs out of 4 total (Jaccard = 2/4)
- `/recommendations` response includes `ontology_inventory` field for each dashboard
- Composite score changes when `ontology_kpi_score` differs from old DAX score

---

### Phase 5 — Ontology View Page (Frontend)
**Duration: 3-4 days**  
**Dependency:** Phase 3 (APIs must be live)
> **Can run in parallel with Phase 4** — two developers

#### Tasks

- [ ] **Modify `frontend/src/App.tsx`**:
```typescript
// Line 13: add 'ontology' to View type
type View = 'hub' | 'upload' | 'inventory' | 'overview' | 'detail'
          | 'landscape' | 'bi_assist' | 'areas' | 'areaDetail'
          | 'kpiGraph' | 'recommendations' | 'ontology';  // ← ADD

// After line 251: add ontology view render
{currentView === 'ontology' && (
  <div className="animate-in fade-in slide-in-from-right-4 duration-300">
    <OntologyBankView />
  </div>
)}
```

- [ ] **Modify `frontend/src/components/Layout.tsx`** — add nav item:
```typescript
// Line 2: add BookOpen icon
import { ..., BookOpen } from 'lucide-react';

// After line 8 (Sparkles/Recommendations): add
{ icon: BookOpen, label: 'Ontology Bank', id: 'ontology' },
```

- [ ] **Create `frontend/src/components/OntologyBankView.tsx`** with:
  - **KPI Bank Browser** — searchable table of canonical KPIs, domain filter pills,
    status badges (active/stale), aliases preview
  - **KPI Detail Drawer** — slide-out panel with full definition, aliases, aggregation,
    valid dimensions, created_by, creation date
  - **HITL Pending Queue** — count badge on nav item, sorted by confidence score ASC
  - **KPI Inventory per Report** — `Report X: 10 mapped ✅ | 3 ⚠️ | 2 ❌` with click to resolve
  - **Promote Panel** — inline form to create a new canonical KPI from a Not-Found entry

```typescript
// OntologyBankView.tsx — key interfaces
interface CanonicalKPI {
  kpi_id: string;
  name: string;
  definition: string;
  domain: string;
  aliases: string[];
  aggregation_type: string;
  status: 'active' | 'stale';
  created_by: string;
  created_at: string;
}

interface MappingRow {
  mapping_id: string;
  report_kpi_name: string;
  report_kpi_lineage: string[];
  canonical_kpi_id: string | null;
  similarity_score: number;
  confidence_score: number;
  similarity_rationale: string;
  mapping_status: 'auto_accepted' | 'pending_review' | 'human_accepted'
                | 'human_rejected' | 'not_found' | 'promoted';
}

// Tabs: 'bank' | 'pending_review' | 'not_found' | 'settings'
```

- [ ] **Create `frontend/src/components/OntologyScoreBadge.tsx`** (from risk_fixes.md §Risk4):
  - Compact mode: `Brain icon + 72% KPI overlap`
  - Full mode: 3-column grid (mapped ✅ / ambiguous ⚠️ / not_found ❌) + progress bar

- [ ] **Create `frontend/src/components/HITLResolutionPanel.tsx`**:
  - Slide-out drawer triggered from `OntologyBankView` or `DetailView`
  - Shows: KPI name, lineage, LLM rationale, confidence score
  - Actions: Accept / Reject / Reassign (dropdown of canonical KPIs) / Promote to New KPI
  - Calls: `PUT /api/v1/ontology/mappings/{id}` or `POST /ontology/mappings/{id}/promote`

#### Files Changed
| File | Action |
|---|---|
| `frontend/src/App.tsx` | **MODIFY** — add 'ontology' to View type + view render |
| `frontend/src/components/Layout.tsx` | **MODIFY** — add BookOpen nav item |
| `frontend/src/components/OntologyBankView.tsx` | **CREATE** |
| `frontend/src/components/OntologyScoreBadge.tsx` | **CREATE** |
| `frontend/src/components/HITLResolutionPanel.tsx` | **CREATE** |

#### Acceptance Criteria
- "Ontology Bank" appears in sidebar, navigates to `OntologyBankView`
- Canonical KPIs from the seeded bank are visible and searchable
- Clicking a `pending_review` mapping opens `HITLResolutionPanel`
- Accept action updates the row status (confirm via `GET /reports/{id}/kpis`)
- Promote action creates new KPI (visible in bank browser)

---

### Phase 6 — Rationalization Frontend (Wiring)
**Duration: 2-3 days**  
**Dependency:** Phase 4 (ontology_inventory in API response) + Phase 5 (badge component)

#### Tasks

- [ ] **Modify `frontend/src/components/RecommendationsView.tsx`**:
  - Add `OntologyKPIInventory` and `ontology_inventory?: OntologyKPIInventory` to
    `DashboardItem` interface (optional — backwards compatible)
  - Import `OntologyScoreBadge` and render it inside each recommendation card
    *below* the existing `reasons` list — no other changes to the component
  - Add `ontology_overlap_kpis?: string[]` to show shared canonical KPIs in merge modal

- [ ] **Modify `frontend/src/components/DetailView.tsx`**:
  - Fetch `GET /api/v1/ontology/reports/{dashboard.id}/kpis` on mount
  - Render `OntologyScoreBadge` in the dashboard metadata section (compact mode)
  - "Resolve KPIs" button → navigate to `OntologyBankView` filtered to this report

#### Files Changed
| File | Action |
|---|---|
| `frontend/src/components/RecommendationsView.tsx` | **MODIFY** — interface + badge |
| `frontend/src/components/DetailView.tsx` | **MODIFY** — fetch inventory + badge |

#### Acceptance Criteria
- Recommendation cards show `OntologyScoreBadge` for dashboards with ontology data
- Cards without ontology data show "KPI mapping pending" state (graceful fallback)
- Detail view shows the KPI inventory breakdown for each dashboard

---

### Phase 7 — Integration, Testing & Polish
**Duration: 3-4 days**  
**Dependency:** Phases 5–6

#### Backend Tests

```python
# backend/tests/test_ontology_matching.py

def test_phase1_exact_match():
    """Phase 1: exact name match returns 100% similarity."""
    kpis = [{"kpi_id": "k1", "name": "Net Revenue", "aliases": ["Revenue"]}]
    result = match_kpi_to_ontology(
        kpi=ExtractedKPI(name="Net Revenue", resolved_lineage=[], aggregation_type="SUM"),
        ontology_kpis=kpis, cache=MockCache(), llm=None
    )
    assert result["matched_kpi_id"] == "k1"
    assert result["similarity_score"] == 1.0

def test_phase1_alias_match():
    """Phase 1: alias match returns high confidence."""
    kpis = [{"kpi_id": "k1", "name": "Net Revenue", "aliases": ["Revenue"]}]
    result = match_kpi_to_ontology(
        kpi=ExtractedKPI(name="Revenue", resolved_lineage=[], aggregation_type="SUM"),
        ontology_kpis=kpis, cache=MockCache(), llm=None
    )
    assert result["matched_kpi_id"] == "k1"

def test_ontology_score_jaccard():
    """Jaccard score computation — ontology_plan.md §5."""
    # 2 shared out of 4 total → Jaccard = 2/(2+2+0) ... wait: |A|=3, |B|=3, |A∩B|=2
    # union = 3+3-2 = 4, score = 2/4 = 0.5
    kpis_a = {"k1","k2","k3"}
    kpis_b = {"k2","k3","k4"}
    score = len(kpis_a & kpis_b) / (len(kpis_a) + len(kpis_b) - len(kpis_a & kpis_b))
    assert abs(score - 0.5) < 0.001

def test_empty_kpi_sets():
    """Edge case: both reports have no mapped KPIs."""
    assert compute_ontology_score_from_sets(set(), set()) == 0.0

def test_fully_overlapping_kpi_sets():
    """Edge case: 100% overlap."""
    kpis = {"k1","k2","k3"}
    score = len(kpis & kpis) / (len(kpis) + len(kpis) - len(kpis & kpis))
    assert abs(score - 1.0) < 0.001

def test_composite_score_6_layers():
    """6-layer composite sums to 1.0 when all layers are 1.0."""
    composite = (0.25*1.0 + 0.20*1.0 + 0.20*1.0 + 0.10*1.0 + 0.15*1.0 + 0.10*1.0)
    assert abs(composite - 1.0) < 0.001

def test_cache_invalidation():
    """Different ontology_version produces different cache key."""
    cache1 = OntologyCache(db, ontology_version="v1")
    cache2 = OntologyCache(db, ontology_version="v2")
    key1 = cache1._make_key(["Sales.Amount"], "SUM")
    key2 = cache2._make_key(["Sales.Amount"], "SUM")
    assert key1 != key2
```

#### End-to-End Test Checklist

- [ ] Upload a `.twbx` → confirm `report_kpi_mappings` has rows for that dashboard
- [ ] `GET /api/v1/ontology/reports/{id}/kpis` returns correct counts
- [ ] Accept a `pending_review` mapping → status changes to `human_accepted`
- [ ] Promote a `not_found` mapping → new row in `ontology_kpis`
- [ ] `/recommendations` response includes `ontology_inventory` for each item
- [ ] `OntologyBankView` loads, renders KPI list, search filters work
- [ ] `HITLResolutionPanel` accept/reject/promote actions work end-to-end
- [ ] `RecommendationsView` renders `OntologyScoreBadge` without breaking existing layout

#### Performance Validation (v3.md §11 calibration)
- [ ] Upload 50 dashboards → measure Phase 3 LLM call count (target: <40% of total KPIs)
- [ ] Verify cache hits logged on second upload of same workbook
- [ ] `compute_ontology_score()` for 5,000 pairs completes in <1 second (pure set math)

---

## 8. File-Level Change Summary

### New Files (Backend — 10 files)
| File | Purpose |
|---|---|
| `backend/app/models/ontology.py` | SQLAlchemy ORM for 3 new tables |
| `backend/app/api/v1/ontology.py` | 7 REST endpoints (CRUD + HITL) |
| `backend/app/services/ontology/kpi_extractor.py` | 3-tier KPI extraction |
| `backend/app/services/ontology/ontology_service.py` | 3-phase LLM matching |
| `backend/app/services/ontology/ontology_cache.py` | DB-backed KPI cache |
| `backend/app/services/ontology/embedding_service.py` | Embedding wrapper |
| `backend/app/services/ontology/bootstrap_ontology.py` | One-time seed script |
| `backend/app/services/rationalization/scoring.py` | 6-layer composite |
| `backend/app/services/rationalization/clustering.py` | Louvain/DBSCAN/hierarchical |
| `backend/app/services/rationalization/golden.py` | Golden report selection |

### Modified Files (Backend — 4 files)
| File | Change |
|---|---|
| `backend/app/models/postgres.py` | Add `kpi_mappings` relationship to Dashboard |
| `backend/app/main.py` | Import ontology models + table guards |
| `backend/app/api/v1/api.py` | Register ontology router (1 line) |
| `backend/app/api/v1/agent.py` | `enrich_with_ontology_inventory()` + 6-layer formula |
| `backend/app/api/v1/upload.py` | Trigger Stage -1 after parse |

### New Files (Frontend — 3 files)
| File | Purpose |
|---|---|
| `frontend/src/components/OntologyBankView.tsx` | KPI bank browser + HITL page |
| `frontend/src/components/OntologyScoreBadge.tsx` | Inline inventory badge |
| `frontend/src/components/HITLResolutionPanel.tsx` | Accept/reject/promote drawer |

### Modified Files (Frontend — 3 files)
| File | Change |
|---|---|
| `frontend/src/App.tsx` | Add `'ontology'` view type + render |
| `frontend/src/components/Layout.tsx` | Add BookOpen nav item |
| `frontend/src/components/RecommendationsView.tsx` | Optional interface extension + badge |
| `frontend/src/components/DetailView.tsx` | Fetch inventory + compact badge |

---

## 9. Risk Mitigations (Built Into Each Phase)

| Risk | Phase | Mitigation |
|---|---|---|
| **Parser can't parse DAX** | Phase 2 | 3-tier fallback in `kpi_extractor.py`: regex → parser metadata → LLM. Name-only fallback ensures Phase 1 name match still works. |
| **LLM cost overrun** | Phase 2 | DB-backed `OntologyCache` prevents re-scoring same lineage; embedding pre-filter gates 60-80% of KPIs before LLM; per-dashboard call cap (`MAX_PHASE3_CALLS=200`) |
| **Cold-start empty bank** | Phase 2 (Day 1) | `bootstrap_ontology.py` runs before any testing — mines existing `ai_summary` JSON from `Dashboard` table via `get_kpi_clusters()` which is already populated |
| **RecommendationsView complexity** | Phase 6 | All fields added as `optional` to `DashboardItem`; `OntologyScoreBadge` is a separate component; no internals touched |
| **Ontology bank never grows past bootstrap** | Ongoing | `HITLResolutionPanel` Promote action → `POST /ontology/mappings/{id}/promote` adds to bank in real time |
| **Stage -1 slows down uploads** | Phase 2 | Run extraction as a background task (FastAPI `BackgroundTasks`) — upload API returns immediately, extraction runs async |

---

## 10. Timeline

```
Week 1
  Day 1-2  │ Phase 1: DB schema, ontology models, main.py import      [2 days]
  Day 3-7  │ Phase 2: Ontology service + KPI extractor + bootstrap    [4-5 days]

Week 2
  Day 8-10 │ Phase 3: Ontology REST API (7 endpoints)                 [2-3 days]
  Day 8-11 │ Phase 4: Rationalization backend (6-layer, clustering)    [3-4 days]
            │         ↑ Parallel with Phase 3

Week 3
  Day 12-15│ Phase 5: Ontology View page (frontend)                   [3-4 days]
  Day 14-16│ Phase 6: Rationalization frontend wiring                  [2-3 days]
            │         ↑ Partial parallel with Phase 5

Week 3-4
  Day 16-19│ Phase 7: Integration, tests, polish, calibration         [3-4 days]
```

| Resource | Week 1 | Week 2 | Week 3 | Week 4 |
|---|---|---|---|---|
| **Dev A (Backend)** | Phase 1→2 | Phase 3→4 | Phase 4 (finish) | Phase 7 |
| **Dev B (Frontend)** | Phase 1 support | Phase 5 start | Phase 5→6 | Phase 7 |
| **Domain Expert** | Seed 50 KPIs for bootstrap | Review bank | HITL walkthrough | Sign-off |

**Total: ~3 weeks (2 devs) / 4 weeks (1 dev)**

---

## 11. Key Design Decisions

| Decision | Choice | Source |
|---|---|---|
| Architecture | Additive layers — no rewrites | implementation_plan.md |
| Composite weights | 6-layer (add 20% ontology, reduce DAX to 10%) | ontology_plan.md §1 |
| Ontology score formula | Jaccard on canonical KPI ID sets (O(1), no LLM at Stage 2) | ontology_plan.md §5 |
| KPI mapping cardinality | 1:1 strict — each report KPI → one canonical or NF | ontology_plan.md §25 |
| HITL trigger | Auto-accept ≥90%, review 50-89%, NF <50% | ontology_plan.md §7.1 |
| LLM caching | Two layers: prompt-level (cache.py) + KPI-level (OntologyCache) | risk_fixes.md |
| Parser strategy | 3-tier fallback — no full DAX AST needed for V1 | v3.md §10.1 Option C |
| Cold-start | Bootstrap from existing `get_kpi_clusters()` output | risk_fixes.md |
| DAX Stage C | Removed — ontology layer handles semantic equivalence | ontology_plan.md §6 |
| Frontend isolation | OntologyScoreBadge injected via optional interface fields | risk_fixes.md |
| Ontology governance | Append-only, stale flagged but never deleted (V1) | ontology_plan.md §26 |
| Subsumption | 90% set inclusion, directional, gap analysis output | v3.md §4.3 |
| Golden selection | 5-factor normalized score with subsumption override | v3.md §6.4 |
| Clustering | All 3 algorithms available: Louvain (default), hierarchical, DBSCAN | v3.md §6.3 |
