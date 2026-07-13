# KPI Ontology Bank Integration — Implementation Plan

## Goal

Integrate a **KPI Ontology Bank** into the existing Power BI Dashboard Rationalization Engine. The ontology layer **replaces the DAX layer's 30% weight** with two new layers: **Ontology KPI Score (20%)** and **DAX Structural Score (10%)**. The ontology bank is expert-curated, append-only, and supports a threshold-gated HITL workflow for analyst resolution.

> [!IMPORTANT]
> **Scope:** This plan covers **only** the ontology integration. The existing spec's structural comparison engine (v1.md/spec.md) — blocking, coarse filtering, visual/filter/data source comparison, clustering, explainability — is already specified and out of scope for this plan.

---

## Interview Summary — Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Architecture | Replace DAX layer (30%) → Ontology (20%) + DAX Structural (10%) | Keeps structural fidelity for 4 other layers, avoids double-counting DAX signal |
| Similarity formula denominator | True set union: \|A\| + \|B\| - \|matched\| | Penalizes size mismatch between reports |
| Ontology bootstrap | Domain experts manually curate initial bank | Ensures quality canonical definitions from day one |
| KPI definition | Visual-derived + Hybrid (named measures + unnamed visual aggregations) | Captures all business questions a report answers |
| Ontology structure | Flat table — each KPI variation is independent | 'Revenue' and 'Revenue YTD' are separate canonical KPIs |
| HITL trigger | Threshold-gated: auto-accept ≥90%, human review 50-89% and NF | Saves analyst time on obvious matches |
| Implementation divergence | Separate layers — ontology score is pure KPI overlap, DAX structural is separate 10% layer | Clean separation of business intent vs implementation |
| LLM provider | Model-agnostic with pluggable adapter | Supports Azure OpenAI, Gemini, or any future model |
| Caching | DB-backed (SQLite/PostgreSQL `kpi_ontology_cache` table) | Same infrastructure as existing spec, no Redis dependency |
| Mapping cardinality | 1:1 strict — each report KPI → exactly one canonical KPI or 'Not Found' | Simplifies scoring formula and UI |
| Ontology governance | Append-only log. Stale KPIs flagged but never deleted | No governance overhead for V1 |
| Cache invalidation | Manual — analyst triggers re-scoring for specific reports | Avoids cascading re-scoring costs |
| NF handling | Exclude NFs from numerator AND denominator | Only score based on mapped KPIs; NFs awaiting analyst resolution don't inflate/deflate scores |
| Ontology score type | Not pairwise — each report gets a KPI inventory. Pairwise overlap computed as Jaccard on canonical KPI ID sets at Stage 2 | O(1) per pair, no additional LLM calls |
| LLM prompt content | Parsed lineage (resolved `table.column` refs + aggregation type) | NOT raw DAX — cleaner signal for the LLM |
| HITL UX location | Inline in the comparison UI (side-by-side view) | Minimal context-switching for analysts |
| Frontend views | Report-level KPI inventory only for V1 | 'Report X has 15 KPIs: 10 mapped, 3 ambiguous, 2 NF' |
| DAX parser | V1 blocker — must be built/run before KPI extraction | Lineage resolution is a prerequisite |

---

## Proposed Changes

### 1. New Composite Weights

The existing composite formula changes from:

```diff
- composite = (0.25 × data_source) + (0.20 × semantic_model) + (0.30 × dax) + (0.15 × visuals) + (0.10 × filters)
+ composite = (0.25 × data_source) + (0.20 × semantic_model) + (0.20 × ontology_kpi) + (0.10 × dax_structural) + (0.15 × visuals) + (0.10 × filters)
```

| Layer | Old Weight | New Weight | Change |
|---|---|---|---|
| Data Source | 25% | 25% | — |
| Semantic Model | 20% | 20% | — |
| DAX Measures | 30% | — | **Removed** |
| Ontology KPI | — | 20% | **NEW** |
| DAX Structural | — | 10% | **NEW** (retains AST comparison, no LLM) |
| Visuals | 15% | 15% | — |
| Filters | 10% | 10% | — |

> [!NOTE]
> The **DAX Structural** layer retains Stage A (Signature Matching) and Stage B (AST Comparison) from the existing spec. Stage C (LLM Semantic Judgment) is **removed** — the ontology layer handles semantic equivalence. This eliminates the most expensive part of the DAX pipeline (~500 LLM calls for ambiguous-zone pairs).

---

### 2. Ontology Bank Schema

#### [NEW] `ontology_kpis` table

```sql
CREATE TABLE ontology_kpis (
    kpi_id          TEXT PRIMARY KEY,         -- UUID
    name            TEXT NOT NULL UNIQUE,      -- 'Net Revenue'
    definition      TEXT NOT NULL,             -- 'Total sales amount minus returns and discounts'
    domain          TEXT,                      -- 'Finance', 'Sales', 'Operations'
    aliases         TEXT[],                    -- ['Revenue', 'Net Sales', 'Total Revenue']
    aggregation_type TEXT,                     -- 'SUM', 'AVERAGE', 'COUNT', etc.
    valid_dimensions TEXT[],                   -- ['Region', 'Product', 'Time']
    created_by      TEXT NOT NULL,             -- 'domain_expert' or 'analyst_jane'
    created_at      TIMESTAMP DEFAULT NOW(),
    status          TEXT CHECK (status IN ('active', 'stale')) DEFAULT 'active',
    embedding       BYTEA                     -- Pre-computed embedding for fast retrieval
);
```

#### [NEW] `report_kpi_mappings` table

```sql
CREATE TABLE report_kpi_mappings (
    mapping_id      TEXT PRIMARY KEY,          -- UUID
    report_id       TEXT NOT NULL,
    report_kpi_name TEXT NOT NULL,             -- Original measure/visual name in the report
    report_kpi_lineage TEXT,                   -- Resolved table.column lineage (e.g., 'Sales.Amount, Returns.Amount')
    report_kpi_aggregation TEXT,               -- 'SUM', 'AVERAGE', etc.
    canonical_kpi_id TEXT,                     -- FK → ontology_kpis.kpi_id (NULL if NF)
    similarity_score REAL,                     -- 0.0 - 1.0 (NULL if NF)
    confidence_score REAL,                     -- 0.0 - 1.0
    similarity_rationale TEXT,                 -- LLM-generated explanation
    confidence_rationale TEXT,                 -- LLM-generated explanation
    mapping_status  TEXT CHECK (mapping_status IN 
                      ('auto_accepted', 'pending_review', 'human_accepted', 
                       'human_rejected', 'not_found', 'promoted')) DEFAULT 'pending_review',
    resolved_by     TEXT,                      -- NULL or analyst ID
    resolved_at     TIMESTAMP,
    model_used      TEXT,                      -- LLM model that produced this mapping
    ontology_version TEXT,                     -- Version hash of ontology bank at scoring time
    computed_at     TIMESTAMP DEFAULT NOW(),
    UNIQUE (report_id, report_kpi_name)
);
```

#### [NEW] `kpi_ontology_cache` table

```sql
CREATE TABLE kpi_ontology_cache (
    cache_key       TEXT PRIMARY KEY,          -- hash(kpi_lineage + kpi_aggregation + ontology_version)
    canonical_kpi_id TEXT,
    similarity_score REAL,
    confidence_score REAL,
    similarity_rationale TEXT,
    confidence_rationale TEXT,
    model_used      TEXT,
    computed_at     TIMESTAMP DEFAULT NOW()
);
```

#### Indexes

```sql
CREATE INDEX idx_rkm_report ON report_kpi_mappings (report_id);
CREATE INDEX idx_rkm_canonical ON report_kpi_mappings (canonical_kpi_id);
CREATE INDEX idx_rkm_status ON report_kpi_mappings (mapping_status);
CREATE INDEX idx_okpi_domain ON ontology_kpis (domain);
CREATE INDEX idx_okpi_status ON ontology_kpis (status);
```

---

### 3. Pipeline Integration — The "Stage -1" Architecture

The ontology layer executes as a **pre-stage** before the existing 5-stage pipeline, plus a lightweight pairwise score computation at Stage 2:

```
┌─────────────────────────────────────────────────────────────┐
│  Stage -1: Ontology KPI Extraction & Mapping (NEW)          │
│  Per-report: Parse visuals → extract KPIs → map to ontology │
│  O(N × K) LLM calls, cached. Run ONCE per report.          │
├─────────────────────────────────────────────────────────────┤
│  Stage 0: Blocking (existing, unchanged)                     │
│  + BONUS: Ontology KPI overlap as supplementary blocking     │
│  signal (reports sharing 0 canonical KPIs → different block) │
├─────────────────────────────────────────────────────────────┤
│  Stage 1: Coarse Filtering (existing, unchanged)             │
├─────────────────────────────────────────────────────────────┤
│  Stage 2: Deep Comparison (MODIFIED)                         │
│  6 layers instead of 5:                                      │
│  data_source + semantic_model + ontology_kpi + dax_structural│
│  + visuals + filters                                         │
│  Ontology score = Jaccard on canonical KPI ID sets (O(1))    │
├─────────────────────────────────────────────────────────────┤
│  Stage 3: Classification & Clustering (existing, unchanged)  │
│  Updated composite weights (see §1)                          │
├─────────────────────────────────────────────────────────────┤
│  Stage 4: Explainability (existing, unchanged)               │
└─────────────────────────────────────────────────────────────┘
```

---

### 4. KPI Extraction Algorithm (Stage -1)

#### 4.1 Per-Report KPI Extraction

For each report, extract KPIs from two sources:

**Source A: Named DAX Measures & Calculated Columns**
- Input: All DAX measures from the report's metadata DB
- Process: Run through the DAX AST parser to resolve lineage to deepest `table.column` level
- Output: `{name, resolved_lineage: [table.column, ...], aggregation_type}`

**Source B: Unnamed Visual Aggregations**
- Input: All visual bindings from the report's metadata DB
- Process: For each visual (including cards, gauges, KPI visuals, bar charts, tables, etc.):
  - If the visual is bound to a named measure → already captured in Source A
  - If the visual uses an implicit aggregation (e.g., `SUM(Sales[Amount])`) → extract as a KPI candidate
- Output: `{name: "SUM of Sales[Amount]", resolved_lineage: ["Sales.Amount"], aggregation_type: "SUM"}`

> [!NOTE]
> **Deduplication:** If a named measure and a visual aggregation resolve to the same lineage, keep only the named measure (richer metadata).

#### 4.2 KPI-to-Ontology Matching — Three-Phase "Retrieve-Identify-Prompt" Pipeline

Based on the state-of-the-art research on ontology matching at scale, the matching uses a **three-phase architecture** that minimizes LLM calls:

```
Phase 1: Deterministic Matching (zero LLM calls)
  → Exact name match against ontology aliases
  → Exact lineage + aggregation match
  → If match found: auto-accept, skip to next KPI

Phase 2: Embedding Pre-Filter (zero LLM calls)
  → Compute embedding of report KPI (lineage + aggregation + visual context)
  → Cosine similarity against pre-computed ontology KPI embeddings
  → Retrieve Top-5 candidates above threshold 0.5
  → If top candidate cosine > 0.95: auto-accept, skip to next KPI
  → If no candidates above 0.5: mark as "Not Found"

Phase 3: LLM Judge (expensive, only for ambiguous cases)
  → Send report KPI data + Top-5 ontology candidates to LLM
  → LLM returns: {matched_kpi_id, similarity_score, confidence_score, rationales}
  → Apply threshold gate: ≥90% → auto_accepted, 50-89% → pending_review, <50% → not_found
```

**LLM Prompt for Phase 3:**

```
You are a business intelligence KPI expert. Given a report's KPI definition and a list
of candidate canonical KPIs from our ontology bank, determine the best match.

Report KPI:
  Name: {report_kpi_name}
  Data Lineage: {resolved_table_column_references}
  Aggregation: {aggregation_type}
  Visual Context: {visual_type, page_title} (if available)

Candidate Canonical KPIs:
{for each candidate:}
  ID: {kpi_id}
  Name: {name}
  Definition: {definition}
  Aliases: {aliases}
  Aggregation: {aggregation_type}

Respond with JSON:
{
  "matched_kpi_id": string | null,
  "similarity_score": float (0-1),
  "confidence_score": float (0-1),
  "similarity_rationale": string,
  "confidence_rationale": string
}
```

#### 4.3 LLM Call Strategy — Cost Analysis

| Strategy | LLM Calls for 961 Reports × ~15 KPIs | When to Use |
|---|---|---|
| Per-visual (your original) | ~14,400 | Maximum accuracy, maximum cost |
| Per-page (batch) | ~3,000 (avg 5 pages/report) | Good balance — batch related visuals by page context |
| Per-report (batch all) | ~961 | Cheapest, but prompt may exceed context window for complex reports |
| **Three-phase (recommended)** | **~2,000-4,000** (only ambiguous KPIs hit LLM) | Best cost/accuracy — Phase 1 & 2 handle 60-80% of matches deterministically |

> [!TIP]
> **The three-phase pipeline is recommended** because it routes only ambiguous cases to the LLM. Empirically, 30-50% of KPIs will match deterministically (Phase 1: exact name/alias match), 20-30% will match via embedding similarity (Phase 2: cosine > 0.95), and only the remaining 20-40% require LLM judgment (Phase 3). For 961 reports × 15 KPIs = ~14,400 total KPIs, this means ~2,800-5,800 LLM calls instead of ~14,400.

---

### 5. Ontology Score Computation (Stage 2 Integration)

At Stage 2 (Deep Comparison), for each candidate pair (A, B):

```python
def compute_ontology_score(report_a_id, report_b_id, db):
    """
    Compute ontology-based KPI overlap between two reports.
    Uses pre-cached report_kpi_mappings from Stage -1.
    O(1) — no LLM calls, pure set intersection.
    """
    # Get mapped canonical KPI IDs for each report
    # Exclude NF (not_found) and pending_review mappings
    kpis_a = set(db.query(
        "SELECT canonical_kpi_id FROM report_kpi_mappings "
        "WHERE report_id = ? AND canonical_kpi_id IS NOT NULL "
        "AND mapping_status IN ('auto_accepted', 'human_accepted')",
        report_a_id
    ))
    kpis_b = set(db.query(
        "SELECT canonical_kpi_id FROM report_kpi_mappings "
        "WHERE report_id = ? AND canonical_kpi_id IS NOT NULL "
        "AND mapping_status IN ('auto_accepted', 'human_accepted')",
        report_b_id
    ))
    
    if len(kpis_a) == 0 and len(kpis_b) == 0:
        return 0.0  # Both reports have no mapped KPIs
    
    # True set union denominator: |A| + |B| - |A ∩ B|
    intersection = kpis_a & kpis_b
    union_size = len(kpis_a) + len(kpis_b) - len(intersection)
    
    # Score: Jaccard similarity on canonical KPI ID sets
    # SAME KPIs = intersection (100% each)
    # No "similar" KPIs in this layer — similarity is handled by the matching phase
    # A KPI either maps to the same canonical ID or it doesn't
    score = len(intersection) / union_size if union_size > 0 else 0.0
    
    return score
```

> [!NOTE]
> **Why Jaccard instead of the original formula with SIMILAR KPIs?** With 1:1 strict mapping and flat ontology, each report KPI maps to exactly one canonical KPI. Two report KPIs either map to the **same** canonical KPI (100% contribution) or to **different** canonical KPIs (0% contribution). The "similar KPIs at 90%" scenario from the spreadsheet doesn't apply — that was for comparing raw KPIs without an ontology. With the ontology as intermediary, similarity is absorbed into the mapping phase (Phase 3 LLM judgment). The pairwise score is purely a set intersection.

---

### 6. DAX Structural Layer (10% Weight)

The existing DAX comparison pipeline (Stage A: Signature + Stage B: AST) is retained but **simplified**:

```diff
- Stage A: Signature Matching → Stage B: AST Comparison → Stage C: LLM Semantic Judgment
+ Stage A: Signature Matching → Stage B: AST Comparison → DONE (no Stage C)
```

- **Stage C (LLM Semantic Judgment) is removed** — the ontology layer now handles semantic equivalence
- Score = AST-based structural similarity only
- Weight = 10% (down from 30%)
- All conditional rewrite routing logic is removed — no LLM calls in this layer

---

### 7. HITL Workflow — Inline Resolution

#### 7.1 Trigger Conditions

| Condition | Action | Mapping Status |
|---|---|---|
| Similarity ≥ 90% | Auto-accept mapping | `auto_accepted` |
| 50% ≤ Similarity < 90% | Surface in HITL queue | `pending_review` |
| Similarity < 50% or no match | Mark as Not Found | `not_found` |

#### 7.2 Analyst Actions (Inline in Comparison UI)

When viewing a report pair in the side-by-side comparison view:

1. **Accept mapping** — confirms the LLM's suggestion (status → `human_accepted`)
2. **Reject mapping** — analyst disagrees (status → `human_rejected`)
3. **Reassign** — analyst maps the KPI to a different canonical KPI
4. **Promote NF** — analyst creates a new canonical KPI from a "Not Found" entry:
   - Fills in: name, definition, domain, aliases, aggregation_type
   - New entry added to `ontology_kpis` with `created_by = analyst_id`
   - Original NF mapping updated to point to the new canonical KPI (status → `promoted`)
   - **No automatic re-scoring** — analyst manually triggers re-scoring for specific reports

#### 7.3 KPI Inventory View

For each report, the UI shows:

```
Report: "Sales Dashboard Q3"
KPIs: 15 total
  ✅ Mapped (auto): 10   — auto-accepted at ≥90%
  ⚠️ Ambiguous:     3    — pending analyst review (50-89%)
  ❌ Not Found:      2    — no match in ontology bank
```

---

### 8. LLM Adapter Interface

Model-agnostic interface for all LLM operations:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class KPIMatchResult:
    matched_kpi_id: str | None
    similarity_score: float
    confidence_score: float
    similarity_rationale: str
    confidence_rationale: str

class LLMAdapter(ABC):
    """Pluggable LLM interface for ontology operations."""
    
    @abstractmethod
    def match_kpi_to_ontology(
        self,
        report_kpi: dict,           # {name, lineage, aggregation, visual_context}
        candidate_kpis: list[dict],  # Top-K ontology candidates from embedding pre-filter
    ) -> KPIMatchResult:
        """Phase 3: LLM judge for ambiguous KPI matches."""
        ...
    
    @abstractmethod
    def compute_embedding(self, text: str) -> list[float]:
        """Compute embedding for Phase 2 pre-filtering."""
        ...

class AzureOpenAIAdapter(LLMAdapter):
    """Azure OpenAI GPT-4o / text-embedding-ada-002 implementation."""
    ...

class GeminiAdapter(LLMAdapter):
    """Google Gemini 1.5 Flash/Pro implementation."""
    ...
```

---

### 9. Spec Sections Affected

| Spec Section | Change |
|---|---|
| §3.3 DAX Measures Layer | Split into Ontology KPI (20%) + DAX Structural (10%). Remove Stage C (LLM) from DAX. |
| §4.1 TF-IDF | No change — TF-IDF still applies to DAX Structural layer's signature matching |
| §6.1 Composite Score | Update formula: 6 layers with new weights (see §1 above) |
| §9.1 Schema | Add `ontology_kpis`, `report_kpi_mappings`, `kpi_ontology_cache` tables |
| §10 Tech Stack | Add LLM Adapter interface, embedding model for Phase 2 |
| §12 Pseudocode | Add Stage -1 (ontology extraction), modify Stage 2 to include ontology score |
| §13 Key Decisions | Add ontology-specific decisions from interview |

---

### 10. Ontology Layer as Supplementary Blocking Signal

At Stage 0, after schema fingerprint blocking, apply an optional ontology-based blocking enhancement:

```python
def ontology_blocking(report_blocks, report_kpi_mappings):
    """
    Supplement schema-fingerprint blocks with ontology KPI overlap.
    Reports sharing 0 canonical KPIs across different source blocks
    can still be flagged if they share KPIs (cross-source functional overlap).
    """
    for block_id, report_ids in report_blocks.items():
        for i, r1 in enumerate(report_ids):
            for r2 in report_ids[i+1:]:
                kpis_r1 = get_canonical_kpi_ids(r1, report_kpi_mappings)
                kpis_r2 = get_canonical_kpi_ids(r2, report_kpi_mappings)
                if len(kpis_r1 & kpis_r2) == 0:
                    # No KPI overlap — can optionally deprioritize this pair
                    # (don't remove — structural layers may still find overlap)
                    pass
```

> [!NOTE]
> This is a **soft signal**, not a hard filter. Reports sharing 0 canonical KPIs can still be compared structurally (they might use the same data source with completely different metrics, which is still useful information). The ontology blocking signal is used to **prioritize** comparison order, not to eliminate pairs.

---

## Open Questions

> [!IMPORTANT]
> **1. Ontology Bank Seeding:** How large is the initial ontology bank expected to be? 50 canonical KPIs? 500? 2000? This determines the embedding index size and Phase 2 retrieval performance. A bank with 500+ entries may benefit from a vector database (e.g., pgvector extension) rather than brute-force cosine comparison.

> [!IMPORTANT]
> **2. DAX Parser Availability:** The DAX AST parser is a V1 blocker. Is there an existing parser implementation in the codebase, or does it need to be built from scratch? This is the single largest dependency for the ontology layer. Options include: (a) custom parser using ANTLR with a DAX grammar, (b) leveraging an existing open-source DAX parser, (c) using Tabular Editor's programmatic API for lineage extraction.

> [!WARNING]
> **3. Visual Aggregation Extraction:** Extracting unnamed visual aggregations requires parsing the `.pbix` report layout JSON (within the extracted metadata DB). Confirm that the existing metadata extraction pipeline captures visual-level field bindings (not just visual types). If not, the extraction pipeline needs to be extended.

> [!IMPORTANT]
> **4. Embedding Model Choice:** The existing spec uses `text-embedding-ada-002`. For Phase 2 (embedding pre-filter), should we reuse the same model, or use a specialized model better suited for short business metric descriptions (e.g., `text-embedding-3-small` which has better short-text performance)?

---

## Verification Plan

### Automated Tests

1. **Ontology matching accuracy test:**
   - Create a gold-standard dataset: 50 report KPIs with known canonical mappings (hand-labeled by domain experts)
   - Run the three-phase pipeline against the gold standard
   - Measure: Phase 1 recall (deterministic), Phase 2 recall (embedding), Phase 3 precision/recall (LLM)
   - Acceptance: Overall mapping accuracy > 85%

2. **Ontology score computation test:**
   - Mock two reports with known KPI inventories
   - Verify Jaccard computation matches expected score
   - Test edge cases: empty KPI sets, fully overlapping sets, disjoint sets

3. **Composite score regression test:**
   - Run existing calibration sample (200+ labeled pairs from §8) with new 6-layer composite
   - Verify precision/recall doesn't degrade vs. the original 5-layer composite
   - Acceptance: Same or better F1 for all classification tiers

4. **Cache correctness test:**
   - Verify that changing the ontology bank version hash invalidates stale cache entries
   - Verify that identical KPIs across different reports produce cache hits

### Manual Verification

1. **Domain expert review of ontology bank:** Experts validate the initial canonical KPI definitions
2. **HITL workflow walkthrough:** An analyst resolves 10 pending_review and 5 NF KPIs using the inline UI
3. **End-to-end KPI inventory verification:** Compare the system's KPI extraction against a hand-counted inventory for 5 sample reports

---

## Complexity & Cost Analysis

| Operation | Complexity | Estimated for N=961, K=15 |
|---|---|---|
| Stage -1: KPI Extraction | O(N × K) report-KPI parsing | ~14,400 KPIs extracted |
| Stage -1: Phase 1 (deterministic match) | O(N × K × \|aliases\|) | ~14,400 lookups (instant) |
| Stage -1: Phase 2 (embedding pre-filter) | O(N × K × \|ontology\|) cosine similarity | ~14,400 × 500 = 7.2M cosine ops (fast, vectorized) |
| Stage -1: Phase 3 (LLM judge) | O(ambiguous_count) | ~2,800-5,800 LLM calls (20-40% of KPIs) |
| Stage 2: Ontology score per pair | O(P × K) set intersection | ~5,000 pairs × 15 = trivial |
| **Total new LLM cost** | | **~$5-15** (at GPT-4o pricing, Phase 3 only) |
| **LLM savings from removing DAX Stage C** | | **~$3-8 saved** (no more 500 ambiguous-zone calls) |

> [!TIP]
> **Net LLM cost change:** The ontology layer adds ~$5-15 for KPI extraction but removes ~$3-8 from DAX Stage C. Net impact is approximately **+$2-7** — a small cost increase for dramatically better semantic matching and a reusable knowledge asset.
