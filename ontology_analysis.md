# KPI Ontology Process Analysis: Structural and Cache Key Issues

This document compiles the technical findings, raw data examples, and structural issues identified in the Tableau BI Compass KPI ontology matching process.

---

## 1. Aggregation Type: "UNKNOWN"

### Root Cause
A significant portion (**26% or 93 out of 358**) of KPI mappings in the database are categorized under the `UNKNOWN` aggregation type. 

These records all originate from **Source D: LLM Summary extraction** (`extract_from_ai_summary` in [kpi_extractor.py](file:///c:/Users/madhu/Downloads/Tableu%20BI%20Compass/Tableu%20BI%20Compass/backend/app/services/ontology/kpi_extractor.py)). These KPIs are parsed out of unstructured natural language text summaries of the dashboard rather than Tableau's structured XML layout.

* **Empty Lineage**: All such records have empty lineages (`[]`).
* **Missing Worksheet context**: They are dashboard-level metrics and are not linked to any specific worksheet id (`None`).
* **Textual Aggregations**: The aggregation details (e.g., `AVG(IGO Aging)`) are present in the text description but are not extracted into the structured `aggregation_type` column, which defaults to `UNKNOWN`.

---

## 2. Embedding Dimension Mismatch (Critical Bug)

### The Problem
There is a dimensional mismatch in the vector database similarity search:
1. **Ontology Bank KPIs**: The canonical database was embedded using OpenAI's `text-embedding-3-small` API, producing **1536-dimensional** vectors.
2. **Report KPIs**: When report metrics are matched at runtime, the code fails back to the local MD5 hash function (`_hash_embedding` in [embedding_service.py](file:///c:/Users/madhu/Downloads/Tableu%20BI%20Compass/Tableu%20BI%20Compass/backend/app/services/ontology/embedding_service.py)), which generates a **128-dimensional** vector.

### The Impact
The cosine similarity score compares vectors `a` (128-dim) and `b` (1536-dim). The guard condition in `cosine_similarity()` immediately returns `0.0000` because the vector lengths do not match:
```python
if not a or not b or len(a) != len(b):
    return 0.0
```

Because **every similarity score is calculated as `0.0`**, the top 5 candidates sent to the Phase 3 LLM Judge are just the first 5 records in insertion order rather than actual semantic matches:

```
TOP 5 CANDIDATES for "Average Claim Amount" (all sim = 0.0000):
  1. '% Calls Agent Declined'
  2. 'Actual & Predicted Conversions'
  3. 'Actual & Predicted Response'
  4. 'Average Premium'
  5. 'AME Ratio'
```

This bug bypasses the Phase 2 pre-filter and forces **73% of all mappings** to be evaluated by the LLM Judge with random, noisy candidate inputs.

---

## 3. Cache Key Reconstructions and Redundant Matches

The local cache keys are generated in [ontology_cache.py](file:///c:/Users/madhu/Downloads/Tableu%20BI%20Compass/Tableu%20BI%20Compass/backend/app/services/ontology/ontology_cache.py) using a SHA256 hash of the following payload:
```python
payload = kpi_name.strip().lower() + sorted_lineage_json + aggregation.upper() + sector + subdomain + version
```

### Real Cache Key Examples from `ontology_process.log`

#### Example A: Subdomain Matching Key
* **KPI Name**: `"Avg Claim Cost | Region | Fixed"`
* **Lineage**: `["Avg Claim Cost", "Incident Date (Table - Extract)", "Region (Table - Extract)"]`
* **Aggregation**: `"NONE"`
* **Sector**: `"insurance"`
* **Subdomain**: `"actuarial_and_risk"`
* **Version**: `"v1"`
* **Raw Payload**:
  `'avg claim cost | region | fixed["Avg Claim Cost", "Incident Date (Table - Extract)", "Region (Table - Extract)"]NONEinsuranceactuarial_and_riskv1'`
* **SHA256 Key**: `d6d7765a9afac39d5dc23c5af352c494bf1991e4cfda2921471a1e98cfa12021` (Verified **YES** in DB)

#### Example B: Sector Fallback matching Key (Duplicate Key)
When the subdomain search fails to reach high confidence, the pipeline fallbacks to the sector:
* **KPI Name**: `"Avg Claim Cost | Region | Fixed"`
* **Lineage**: `["Avg Claim Cost", "Incident Date (Table - Extract)", "Region (Table - Extract)"]`
* **Aggregation**: `"NONE"`
* **Sector**: `"insurance"`
* **Subdomain**: `"__sector__"` (The fallback sector tag)
* **Version**: `"v1"`
* **Raw Payload**:
  `'avg claim cost | region | fixed["Avg Claim Cost", "Incident Date (Table - Extract)", "Region (Table - Extract)"]NONEinsurance__sector__v1'`
* **SHA256 Key**: `5460d92a5ef2c3b49a5dfc0d073903851fe8e0841048b84db1d2233d9915fb2f` (Verified **YES** in DB)

---

### Core Cache Vulnerabilities

1. **Duplicate Matching (Sector Fallback Keying)**
   As seen in Examples A and B, the same KPI is matched and cached twice. Because `subdomain` is concatenated in the payload, the subdomain match key (`d6d7765a...`) and the sector fallback key (`5460d92a...`) are completely distinct. This duplicates LLM scoring efforts.

2. **Aggregation Type Drift**
   If a visual is matched first as `UNKNOWN` aggregation and later refined to `SUM` or `AVG`, it generates different keys:
   * `UNKNOWN`: `046e07e96e45329d659e215109d5aa81ea696bbfc7a3e423c21fa5b19ac799c3`
   * `SUM`: `4cd06bd35ddec44c0cc23462ad3bf3a943785bab02a2ee865db4840d8c729c3f`
   
   This makes the cache highly sensitive to extraction precision, leading to unnecessary misses.
