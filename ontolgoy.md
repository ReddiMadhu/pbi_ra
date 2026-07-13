# AI-Driven Report Rationalization Architecture

Implement a highly scalable, AI-driven report rationalization system leveraging a centralized KPI Ontology Bank. The system parses BI visual components down to their root data lineage, calculates similarity scores using an LLM router architecture, and computes report-level overlap. The frontend will handle massive scale (e.g., 961 dashboards) using hierarchical clustering and provide a seamless Human-in-the-loop (HITL) inline resolution experience.

## User Review Required

> [!IMPORTANT]  
> **BI Platform Support for AST Parsing**
> We plan to use deterministic AST (Abstract Syntax Tree) parsing to extract lineage (e.g., `C = D+K+V+L`). This requires specific parsers depending on your BI tools (e.g., SQLGlot for SQL, specialized parsers for DAX/PowerBI or Tableau XML). We need to prioritize the specific BI platforms for V1.

> [!TIP]  
> **LLM Cost Control**
> Using on-the-fly similarity scoring ensures high context accuracy and avoids maintaining a massive pre-computed matrix. To manage costs, we will heavily utilize a fast router model (like Gemini 1.5 Flash) for chart extraction, and implement aggressive Redis caching so the heavier model (like Gemini 1.5 Pro) doesn't re-score previously compared pairs.

## Proposed Changes

Based on our architectural interview, here is the technical blueprint:

### 1. Data Extraction & Lineage Parsing (Backend)
- **Deepest-Level Extraction:** Use an AST parser to trace calculated fields and visuals down to their lowest `table.column` representations. 
- **Noise Reduction:** Eliminate static text elements, non-data-bound shapes, and purely decorative visuals from the LLM prompt payload.

### 2. LLM Pipeline (Router Architecture)
- **Extraction Phase (Fast Model):** Send parsed AST lineage of individual charts to a fast model to identify potential KPI intent.
- **Reconciliation Phase (Heavy Model):** When a report comparison is actively requested, a heavy model dynamically evaluates the extraction against the Ontology Bank to generate:
  - Similarity Score
  - Similarity Rationale
  - Confidence Score
  - Confidence Rationale

### 3. Ontology Bank & HITL Workflow
- **Ontology Schema:** Store canonical KPIs with comprehensive semantic definitions (aggregation rules, valid dimensions, formatting, and acceptable aliases).
- **Inline HITL Resolution:** If a KPI has a low confidence score or is "Not Found" (0%), the UI flags it as requiring human input. Analysts resolve these directly within the side-by-side comparison view.
- **KPI Promotion:** Validated "Not Found" KPIs are formally promoted to become net-new canonical metrics in the global Ontology Bank.

### 4. Report Similarity Algorithm
- **Formula:** 
  `Similarity Score = (100% * SAME_KPIS + Similarity_Score * SIMILAR_KPIS) / Union(Total KPIs A, Total KPIs B)`
- Uses the Union (A U B) denominator to strictly penalize size mismatches between reports (e.g., comparing a 20-chart dashboard to a 10-chart dashboard).

### 5. Frontend UI/UX (Scale & Explainability)
- **Scale Visualization (961 Dashboards):** Utilize a hierarchical clustering visualization (e.g., `ClusterDetailView.jsx`) to group highly overlapping reports into consolidated "rationalization candidate buckets", preventing user overload from looking at a 1-million pair matrix.
- **Explainability Drawer:** Clicking any KPI mapping row triggers a slide-out side panel displaying the full LLM Markdown rationales for its similarity and confidence scoring, along with the traced lineage.

## Verification Plan

### Automated Tests
- Unit testing the AST lineage parser against known complex DAX/SQL structures to ensure `C=A+B` correctly resolves to `C=D+K+V+L`.
- Mocking the LLM router model to verify the Similarity Formula calculates correctly with Union denominators.

### Manual Verification
- Deploying the frontend with mock data for 961 dashboards to verify the rendering performance of the hierarchical clustering view.
- Testing the slide-out drawer UX and the inline HITL KPI promotion workflow.
