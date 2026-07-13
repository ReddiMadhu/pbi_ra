# Feasibility & Implementation Roadmap
## Intelligence + Rationalization + Ontology View — onto Current Architecture

---

## ✅ Feasibility Verdict: **YES — Highly Feasible**

The three features map cleanly onto the existing stack. No rewrites needed.

| Feature | Feasibility | Effort |
|---|---|---|
| **Intelligence Layer** (KPI Ontology Bank + LLM matching) | ✅ High | Medium-High |
| **Rationalization Engine** (Report dedup + recommendations) | ✅ Already partially exists | Low-Medium |
| **Ontology View Page** (Separate frontend page) | ✅ Straightforward | Low |

> [!NOTE]
> `RecommendationsView.tsx` (66KB) already contains rationalization logic. The backend has `agents/`, `services/lineage/`, `services/parser/` directories. The frontend routing in `App.tsx` uses a simple `currentView` state — adding a new page is a single addition.

---

## Current Architecture Map

```
Frontend (React + Vite + TypeScript)
├── App.tsx             ← View router (state-based, no React Router)
├── components/
│   ├── RecommendationsView.tsx   ← RATIONALIZATION (already exists, 66KB)
│   ├── KPIDashboardGraph.tsx     ← KPI lineage graph (exists)
│   ├── LineageGraph.tsx          ← Lineage view (exists)
│   ├── Layout.tsx                ← Nav sidebar (add nav items here)
│   └── [other views]
└── store/                        ← State management

Backend (Python / FastAPI)
├── app/
│   ├── api/v1/
│   │   ├── agent.py              ← LLM agent calls (31KB)
│   │   ├── kpi_graph.py          ← KPI graph API (17KB)
│   │   ├── lineage.py            ← Lineage extraction (10KB)
│   │   └── upload.py             ← File upload & parsing
│   ├── services/
│   │   ├── lineage/              ← Lineage resolution service
│   │   └── parser/               ← AST/XML parser service
│   ├── models/
│   │   └── postgres.py           ← DB models
│   └── db/                       ← DB connection
```

---

## The Three Features Mapped to Architecture

### Feature 1 — Intelligence (KPI Ontology Bank)
> *"Stage -1" from ontology_plan.md: Per-report KPI extraction → LLM mapping → Ontology Bank*

**Where it lives:**
- **Backend:** New `app/services/ontology/` service + new `app/api/v1/ontology.py` endpoints
- **DB:** 3 new tables (`ontology_kpis`, `report_kpi_mappings`, `kpi_ontology_cache`)
- **Frontend:** New `OntologyView.tsx` page + KPI inventory badges on existing `DetailView.tsx`

### Feature 2 — Rationalization (Report Overlap + Decommission Recommendations)
> *Stage 2–4 from spec: Similarity scoring → Clustering → Decommission/Merge/Keep*

**Where it lives:**
- **Backend:** Extend `agent.py` with ontology-augmented scoring + new `app/api/v1/rationalization.py`
- **Frontend:** `RecommendationsView.tsx` already handles this — needs ontology score wired in

### Feature 3 — Ontology View Page
> *Separate page to browse/manage the KPI Ontology Bank*

**Where it lives:**
- **Frontend:** New `OntologyBankView.tsx` component + `'ontology'` view in `App.tsx`
- **Backend:** REST CRUD endpoints for `ontology_kpis` table

---

## Phased Implementation Plan

---

### 🟦 Phase 1 — Database Foundation
**Duration: 2–3 days**

> Everything else depends on the DB schema being in place first.

**Tasks:**
- [ ] Add 3 new tables to `postgres.py` / migration script:
  - `ontology_kpis` (canonical KPI bank)
  - `report_kpi_mappings` (per-report KPI → canonical mapping)
  - `kpi_ontology_cache` (LLM call cache)
- [ ] Add indexes for performance
- [ ] Seed initial ontology bank with domain expert KPIs (manual CSV/JSON import)
- [ ] Write migration script compatible with existing `tableau_gov.db` (SQLite) or Postgres

**Files to create/modify:**
- `backend/app/models/ontology.py` ← **NEW**
- `backend/app/db/migrations/001_ontology_tables.sql` ← **NEW**

---

### 🟦 Phase 2 — Intelligence Backend (Ontology Service)
**Duration: 4–5 days**

> The core LLM pipeline for KPI extraction and mapping.

**Tasks:**
- [ ] Build `OntologyService` with the three-phase matching pipeline:
  - **Phase 1:** Deterministic name/alias exact match (zero LLM calls)
  - **Phase 2:** Embedding cosine similarity pre-filter (zero LLM calls)
  - **Phase 3:** LLM judge for ambiguous cases only (cost-optimized)
- [ ] Extend existing `LLMAdapter` pattern in `agent.py` with `match_kpi_to_ontology()` method
- [ ] Add embedding computation (reuse existing embedding model or add `text-embedding-3-small`)
- [ ] Wire into existing `lineage/` service for KPI lineage resolution
- [ ] Build cache layer using `kpi_ontology_cache` table

**Files to create/modify:**
- `backend/app/services/ontology/ontology_service.py` ← **NEW**
- `backend/app/services/ontology/llm_adapter.py` ← **NEW**
- `backend/app/services/ontology/embedding_service.py` ← **NEW**
- `backend/app/api/v1/agent.py` ← **MODIFY** (add KPI matching method)

---

### 🟦 Phase 3 — Ontology REST API
**Duration: 2–3 days**

> Expose the ontology service through FastAPI endpoints.

**Endpoints to build:**

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/ontology/kpis` | List all canonical KPIs |
| `POST` | `/api/v1/ontology/kpis` | Add new canonical KPI |
| `PUT` | `/api/v1/ontology/kpis/{id}` | Update KPI definition |
| `GET` | `/api/v1/ontology/reports/{report_id}/kpis` | Get KPI inventory for a report |
| `POST` | `/api/v1/ontology/reports/{report_id}/extract` | Trigger Stage -1 extraction |
| `PUT` | `/api/v1/ontology/mappings/{mapping_id}` | HITL: accept/reject/reassign |
| `POST` | `/api/v1/ontology/mappings/{mapping_id}/promote` | Promote NF KPI to canonical |

**Files to create:**
- `backend/app/api/v1/ontology.py` ← **NEW**
- `backend/app/main.py` ← **MODIFY** (register new router)

---

### 🟦 Phase 4 — Rationalization Backend
**Duration: 3–4 days**

> Augment the existing similarity scoring with the ontology score (20% weight).

**Tasks:**
- [ ] Modify composite score formula to include `ontology_kpi_score` (20%) + `dax_structural_score` (10%)
- [ ] Remove Stage C (LLM Semantic Judgment) from existing DAX layer — save ~$3-8 LLM cost
- [ ] Build `compute_ontology_score()` (Jaccard on canonical KPI ID sets — pure set math, O(1))
- [ ] Update clustering logic with new 6-layer composite weights
- [ ] Add decommission recommendation logic: Clone → Merge → Keep → Decommission

**Files to create/modify:**
- `backend/app/api/v1/rationalization.py` ← **NEW**
- `backend/app/services/rationalization/` ← **NEW** (scoring, clustering, recommendations)
- `backend/app/api/v1/agent.py` ← **MODIFY** (update composite weights)

---

### 🟦 Phase 5 — Ontology View Page (Frontend)
**Duration: 3–4 days**

> Standalone page to browse, manage, and curate the KPI Ontology Bank.

**UI Sections:**
1. **KPI Bank Browser** — searchable table of all canonical KPIs with domain filters
2. **KPI Detail Drawer** — slide-out panel showing definition, aliases, aggregation type, domain
3. **Pending Review Queue** — list of `pending_review` mappings needing analyst attention
4. **HITL Resolution Panel** — inline accept / reject / reassign / promote actions
5. **KPI Inventory per Report** — `Report X: 10 mapped ✅ | 3 ambiguous ⚠️ | 2 NF ❌`

**Routing change in `App.tsx`:**
```typescript
// Add 'ontology' to the View type
type View = '...' | 'ontology';

// Add view render
{currentView === 'ontology' && <OntologyBankView />}
```

**Files to create/modify:**
- `frontend/src/components/OntologyBankView.tsx` ← **NEW**
- `frontend/src/components/Layout.tsx` ← **MODIFY** (add "Ontology" nav item)
- `frontend/src/App.tsx` ← **MODIFY** (add 'ontology' view + route)

---

### 🟦 Phase 6 — Rationalization Frontend
**Duration: 2–3 days**

> Wire the new ontology score into `RecommendationsView.tsx` + add explainability drawer.

**Tasks:**
- [ ] Update `RecommendationsView.tsx` to show ontology KPI overlap as a score breakdown
- [ ] Add KPI inventory badges to `DetailView.tsx` (mapped / ambiguous / NF counts)
- [ ] Add "Explainability Drawer" — slide-out panel showing per-KPI LLM rationales
- [ ] Connect HITL actions (accept/reject/promote) to new ontology API endpoints

**Files to modify:**
- `frontend/src/components/RecommendationsView.tsx` ← **MODIFY**
- `frontend/src/components/DetailView.tsx` ← **MODIFY**

---

### 🟦 Phase 7 — Integration, Testing & Polish
**Duration: 3–4 days**

**Tasks:**
- [ ] End-to-end test: upload workbook → Stage -1 extraction → KPI mapping → similarity scoring → recommendation
- [ ] Validate ontology matching accuracy against 50 hand-labeled KPIs (>85% target)
- [ ] Performance test: 961 dashboards × 15 KPIs = 14,400 KPIs through the three-phase pipeline
- [ ] Validate composite score regression: new 6-layer score ≥ old 5-layer score on F1
- [ ] UI polish: loading states, error boundaries, empty states for ontology bank

---

## Total Timeline Summary

| Phase | Feature | Duration | Dependencies |
|---|---|---|---|
| **Phase 1** | DB Schema (3 new tables) | 2–3 days | None — start here |
| **Phase 2** | Intelligence Backend (Ontology Service + LLM) | 4–5 days | Phase 1 |
| **Phase 3** | Ontology REST API | 2–3 days | Phase 1–2 |
| **Phase 4** | Rationalization Backend (updated scoring) | 3–4 days | Phase 1–2 |
| **Phase 5** | Ontology View Page (Frontend) | 3–4 days | Phase 3 |
| **Phase 6** | Rationalization Frontend (wiring) | 2–3 days | Phase 4–5 |
| **Phase 7** | Integration, Tests, Polish | 3–4 days | Phase 5–6 |
| **TOTAL** | | **~3–4 weeks** | |

> [!TIP]
> **Phases 2 and 5 can run in parallel** once Phase 1 is done — one person on backend service, one on frontend Ontology View page. This could shorten the timeline to ~2.5 weeks with two developers.

---

## What Reuses vs. What's New

| Existing Asset | Reuse How |
|---|---|
| `agent.py` (31KB, LLM calls) | Add `match_kpi_to_ontology()` method using same LLM adapter |
| `lineage.py` (10KB) | Feed resolved `table.column` refs into KPI extraction |
| `services/parser/` | Parse DAX/XML → provide AST lineage to Stage -1 |
| `RecommendationsView.tsx` (66KB) | Add ontology score breakdown + HITL actions |
| `KPIDashboardGraph.tsx` | Extend to show canonical KPI node overlays |
| `Layout.tsx` | Add "Ontology Bank" nav item |
| `App.tsx` view router | Add `'ontology'` view — 3 lines of change |
| `postgres.py` | Add 3 new table models |

---

## Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| DAX AST parser not fully working | Medium | Check `services/parser/` — if incomplete, use existing `kpi_graph.py` lineage data as fallback |
| LLM cost overrun for Phase 3 (LLM judge) | Low | Three-phase pipeline routes only 20–40% of KPIs to LLM; cache prevents re-scoring |
| Ontology bank cold-start (empty bank = no matches) | High | **Must seed manually before Phase 2 testing** — even 50 starter KPIs unblocks development |
| `RecommendationsView.tsx` complexity (66KB) | Medium | Treat as black box — only add ontology score data, don't refactor internals |

---

## Recommended Starting Order (Day 1 Action Items)

1. **Audit `services/parser/`** — confirm what lineage data is already available (determines Phase 2 scope)
2. **Collect 50–100 canonical KPIs** from domain experts to seed the ontology bank
3. **Create `backend/app/models/ontology.py`** — define the 3 new DB models
4. **Add `'ontology'` to `App.tsx` View type** — unblocks frontend development immediately
