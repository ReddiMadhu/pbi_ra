"""Tests for the ontology pipeline fixes using REAL data from tableau_gov.db.

Each test case uses actual KPI names, definitions, lineage, aggregation types,
and ontology bank entries extracted from production data.
"""
import hashlib
import json
import math

from app.services.ontology.kpi_extractor import (
    ExtractedKPI,
    extract_from_ai_summary,
    _normalize_agg,
)
from app.services.ontology.embedding_service import (
    _hash_embedding,
    compute_embedding,
    cosine_similarity,
    clear_embedding_cache,
)
from app.services.ontology.ontology_cache import OntologyCache


# ═══════════════════════════════════════════════════════════════
# Real data from tableau_gov.db
# ═══════════════════════════════════════════════════════════════

# Real ontology KPIs from the insurance sector
REAL_ONTOLOGY_KPIS = [
    {
        "kpi_id": "7392499f-f0a0-4a87-ae60-01291ee896be",
        "name": "Severity",
        "definition": "Average loss per claim",
        "aggregation_type": "AVG",
        "sector": "insurance",
        "subdomain": "actuarial_and_risk",
        "aliases": ["Average Claim Amount", "Avg Claim Cost", "Average Loss"],
    },
    {
        "kpi_id": "f79c782f-3a27-4dbb-adc6-b1110e8099c4",
        "name": "Claims Severity",
        "definition": "Average cost per claim (incurred or paid)",
        "aggregation_type": "AVG",
        "sector": "insurance",
        "subdomain": "actuarial_and_risk",
        "aliases": [],
    },
    {
        "kpi_id": "0ad2cbd0-745c-4ae5-bba7-a1ab813b6300",
        "name": "Claims Frequency",
        "definition": "Number of claims per unit of exposure",
        "aggregation_type": "COUNT",
        "sector": "insurance",
        "subdomain": "actuarial_and_risk",
        "aliases": ["Claim Frequency", "Frequency Rate"],
    },
    {
        "kpi_id": "2dc0feb4-7802-462e-9fcd-f134b6cf6d02",
        "name": "Loss Severity",
        "definition": "Average cost per claim (incurred or paid)",
        "aggregation_type": "AVG",
        "sector": "insurance",
        "subdomain": "actuarial_and_risk",
        "aliases": [],
    },
    {
        "kpi_id": "970d8180-ba04-48bb-bc4d-fd9f869a216b",
        "name": "Nb Closed Claims",
        "definition": "Count of closed claims",
        "aggregation_type": "COUNTD",
        "sector": "insurance",
        "subdomain": "claims_management",
        "aliases": ["Closed Claims Count"],
    },
]

# Real AI summary from the Beneficiary Services IGO Aging dashboard
REAL_AI_SUMMARY = {
    "summary": "test",
    "kpis": [
        {
            "name": "Aging Bin by Case ID",
            "confidence": 80.0,
            "source_description": "Aging Bins worksheet",
            "calculation_logic": "COUNT(Case ID) by Aging Bin",
            "definition": "Distribution of cases across different aging bins.",
        },
        {
            "name": "Avg IGO Aging by Work Category",
            "confidence": 90.0,
            "source_description": "Bubble - Work Category worksheet",
            "calculation_logic": "AVG(IGO Aging) by Work Category",
            "definition": "Average time taken for IGO processing by work category.",
        },
        {
            "name": "External Pending Cases",
            "confidence": 85.0,
            "source_description": "KPI - External Pending worksheet",
            "calculation_logic": "COUNT(Case ID) where Case Status = 'External Pending'",
            "definition": "Number or proportion of cases pending externally.",
        },
        {
            "name": "Avg IGO Aging by Master Work Category",
            "confidence": 90.0,
            "source_description": "Master Category Aging worksheet",
            "calculation_logic": "AVG(IGO Aging) by Master Work Category",
            "definition": "Average IGO aging time by master work category.",
        },
    ],
}

# Real report KPI data from ontology_process.log
REAL_REPORT_KPI_AVG_CLAIM = ExtractedKPI(
    name="Avg Claim Cost",
    resolved_lineage=["Claim Filed (Table - Extract)", "Total Claim Amount (Table - Extract)"],
    aggregation_type="SUM",
    definition="SUM([Total Claim Amount (Table - Extract)])/COUNT([Claim Filed (Table - Extract)])",
    extraction_method="named_measure",
    worksheet_id="29",
    worksheet_name="State | Avg Claim Cost",
    mark_type="Line",
)

REAL_REPORT_KPI_NB_CLOSED = ExtractedKPI(
    name="Nb Closed Claims",
    resolved_lineage=["_Nb Closed Claims (Expression)"],
    aggregation_type="COUNTD",
    definition="COUNTD([_Nb Closed Claims (Expression)])",
    extraction_method="named_measure",
    worksheet_name="Top AGENT - Claims Reimbursed % - Minitrend",
)


# ═══════════════════════════════════════════════════════════════
# Issue #1 Tests: Embedding Dimension Fix
# ═══════════════════════════════════════════════════════════════


class TestEmbeddingDimensionFix:
    """Verify that the hash fallback produces 1536-dim vectors
    matching the ontology bank's API-generated dimension."""

    def test_hash_fallback_produces_1536_dim(self):
        """_hash_embedding must produce 1536-dim vectors to match
        the ontology bank which was embedded via text-embedding-3-small."""
        vec = _hash_embedding("Avg Claim Cost Average loss per claim")
        assert len(vec) == 1536, f"Expected 1536-dim, got {len(vec)}"

    def test_empty_text_sentinel_is_1536_dim(self):
        """Empty text must return a 1536-dim zero vector."""
        clear_embedding_cache()
        emb = compute_embedding("")
        assert len(emb) == 1536, f"Expected 1536-dim sentinel, got {len(emb)}"

    def test_cosine_similarity_same_dim_nonzero(self):
        """Two semantically related texts must produce non-zero similarity
        when both are 1536-dim hash embeddings."""
        a = _hash_embedding("Avg Claim Cost Average loss per claim")
        b = _hash_embedding("Claims Severity Average cost per claim")
        sim = cosine_similarity(a, b)
        assert sim > 0.0, f"Expected non-zero similarity, got {sim}"
        assert len(a) == len(b) == 1536

    def test_cosine_mismatched_dims_returns_zero(self):
        """Mismatched dimensions must return 0.0 (e.g. old 128 vs new 1536)."""
        a = _hash_embedding("test", dim=128)
        b = _hash_embedding("test", dim=1536)
        assert cosine_similarity(a, b) == 0.0

    def test_real_kpi_similarity_ranking(self):
        """Using real KPI names/definitions: 'Avg Claim Cost' should be
        more similar to 'Severity' or 'Claims Severity' than to
        'Claims Frequency', because they share cost/average semantics."""
        query = _hash_embedding(
            f"{REAL_REPORT_KPI_AVG_CLAIM.name} {REAL_REPORT_KPI_AVG_CLAIM.definition}"
        )
        # Build embeddings for real ontology KPIs
        scored = []
        for ok in REAL_ONTOLOGY_KPIS:
            emb = _hash_embedding(f"{ok['name']} {ok['definition']}")
            sim = cosine_similarity(query, emb)
            scored.append((sim, ok["name"]))
        scored.sort(key=lambda x: x[0], reverse=True)

        # The top result should NOT be Claims Frequency (which is count-based)
        top_names = [name for _, name in scored[:3]]
        assert "Claims Frequency" not in top_names, (
            f"'Claims Frequency' should not be in top 3 for 'Avg Claim Cost'. "
            f"Ranking: {scored}"
        )

    def test_nb_closed_claims_similarity(self):
        """'Nb Closed Claims' report KPI should rank 'Nb Closed Claims'
        ontology KPI higher than 'Severity'."""
        query = _hash_embedding(
            f"{REAL_REPORT_KPI_NB_CLOSED.name} {REAL_REPORT_KPI_NB_CLOSED.definition}"
        )
        sim_closed = cosine_similarity(
            query,
            _hash_embedding(f"Nb Closed Claims Count of closed claims"),
        )
        sim_severity = cosine_similarity(
            query,
            _hash_embedding(f"Severity Average loss per claim"),
        )
        assert sim_closed > sim_severity, (
            f"'Nb Closed Claims' should be more similar to 'Nb Closed Claims' "
            f"ontology KPI ({sim_closed:.4f}) than 'Severity' ({sim_severity:.4f})"
        )


# ═══════════════════════════════════════════════════════════════
# Issue #2 Tests: UNKNOWN Aggregation Inference
# ═══════════════════════════════════════════════════════════════


class TestAggregationInference:
    """Verify that extract_from_ai_summary now infers aggregation
    from real dashboard AI summary data instead of defaulting to UNKNOWN."""

    def test_real_aging_bin_infers_count(self):
        """Real KPI 'Aging Bin by Case ID' has calculation_logic
        'COUNT(Case ID) by Aging Bin' -> should infer COUNT."""
        kpis = extract_from_ai_summary(REAL_AI_SUMMARY)
        aging_kpi = next(k for k in kpis if k.name == "Aging Bin by Case ID")
        assert aging_kpi.aggregation_type == "COUNT", (
            f"Expected COUNT for 'COUNT(Case ID) by Aging Bin', "
            f"got '{aging_kpi.aggregation_type}'"
        )

    def test_real_avg_igo_aging_infers_avg(self):
        """Real KPI 'Avg IGO Aging by Work Category' has calculation_logic
        'AVG(IGO Aging) by Work Category' -> should infer AVG."""
        kpis = extract_from_ai_summary(REAL_AI_SUMMARY)
        igo_kpi = next(k for k in kpis if k.name == "Avg IGO Aging by Work Category")
        assert igo_kpi.aggregation_type == "AVG", (
            f"Expected AVG for 'AVG(IGO Aging) by Work Category', "
            f"got '{igo_kpi.aggregation_type}'"
        )

    def test_real_external_pending_infers_count(self):
        """Real KPI 'External Pending Cases' has calculation_logic
        'COUNT(Case ID) where Case Status = ...' -> should infer COUNT."""
        kpis = extract_from_ai_summary(REAL_AI_SUMMARY)
        ext_kpi = next(k for k in kpis if k.name == "External Pending Cases")
        assert ext_kpi.aggregation_type == "COUNT", (
            f"Expected COUNT for 'COUNT(Case ID) where ...', "
            f"got '{ext_kpi.aggregation_type}'"
        )

    def test_real_avg_master_category_infers_avg(self):
        """Real KPI 'Avg IGO Aging by Master Work Category' has calculation_logic
        'AVG(IGO Aging) by Master Work Category' -> should infer AVG."""
        kpis = extract_from_ai_summary(REAL_AI_SUMMARY)
        master_kpi = next(k for k in kpis if k.name == "Avg IGO Aging by Master Work Category")
        assert master_kpi.aggregation_type == "AVG", (
            f"Expected AVG, got '{master_kpi.aggregation_type}'"
        )

    def test_no_false_unknown_in_real_ai_summary(self):
        """All 4 real AI summary KPIs have explicit aggregation functions
        in their calculation_logic. None should remain UNKNOWN."""
        kpis = extract_from_ai_summary(REAL_AI_SUMMARY)
        unknowns = [k for k in kpis if k.aggregation_type == "UNKNOWN"]
        assert len(unknowns) == 0, (
            f"Expected 0 UNKNOWN KPIs from real AI summary, "
            f"got {len(unknowns)}: {[k.name for k in unknowns]}"
        )

    def test_string_kpi_with_avg_prefix(self):
        """A string-only KPI like 'Average Claim Amount by Car Make'
        should infer AVG from the keyword 'Average'."""
        ai = {"kpis": ["Average Claim Amount by Car Make"]}
        kpis = extract_from_ai_summary(ai)
        assert len(kpis) == 1
        assert kpis[0].aggregation_type == "AVG", (
            f"Expected AVG from keyword 'Average', got '{kpis[0].aggregation_type}'"
        )

    def test_string_kpi_with_total_prefix(self):
        """'Total Claim Amount by Car Model' should infer SUM."""
        ai = {"kpis": ["Total Claim Amount by Car Model"]}
        kpis = extract_from_ai_summary(ai)
        assert kpis[0].aggregation_type == "SUM", (
            f"Expected SUM from keyword 'Total', got '{kpis[0].aggregation_type}'"
        )

    def test_string_kpi_with_count_prefix(self):
        """'Count of Claims' should infer COUNT."""
        ai = {"kpis": ["Count of Claims"]}
        kpis = extract_from_ai_summary(ai)
        assert kpis[0].aggregation_type == "COUNT"

    def test_string_kpi_with_no_agg_signal(self):
        """A KPI with no aggregation signal should still remain UNKNOWN."""
        ai = {"kpis": ["Loss Ratio"]}
        kpis = extract_from_ai_summary(ai)
        assert kpis[0].aggregation_type == "UNKNOWN"

    def test_real_claim_frequency_definition(self):
        """Real definition 'Total frequency of claims made | SUM(Claim Freq)'
        should infer SUM from the calculation_logic."""
        ai = {
            "kpis": [
                {
                    "name": "Claim Frequency",
                    "definition": "Total frequency of claims made",
                    "calculation_logic": "SUM(Claim Freq)",
                    "source_description": "Claim Frequency worksheet",
                }
            ]
        }
        kpis = extract_from_ai_summary(ai)
        assert kpis[0].aggregation_type == "SUM"

    def test_countd_extraction(self):
        """Real definition with COUNTD should be preserved as COUNTD, not COUNT."""
        ai = {
            "kpis": [
                {
                    "name": "Case ID by Aging Bin",
                    "definition": "Number of cases in different aging bins",
                    "calculation_logic": "COUNTD(Case ID) grouped by Aging Bin",
                }
            ]
        }
        kpis = extract_from_ai_summary(ai)
        assert kpis[0].aggregation_type == "COUNTD", (
            f"Expected COUNTD, got '{kpis[0].aggregation_type}'"
        )


# ═══════════════════════════════════════════════════════════════
# Issue #3 Tests: Cache Key Normalization
# ═══════════════════════════════════════════════════════════════


class MockDB:
    """Minimal mock for SQLAlchemy Session used by OntologyCache."""
    def query(self, *a, **kw):
        return self
    def filter(self, *a, **kw):
        return self
    def first(self):
        return None
    def add(self, *a, **kw):
        pass
    def commit(self):
        pass
    def delete(self):
        return 0


class TestCacheKeyNormalization:
    """Verify that UNKNOWN/NONE aggregation types produce identical cache keys."""

    def _make_key(self, name, lineage, agg, sector=None, subdomain=None):
        cache = OntologyCache(MockDB())
        return cache._make_key(name, lineage, agg, sector, subdomain)

    def test_unknown_equals_none_key(self):
        """UNKNOWN and NONE aggregation should produce identical cache keys
        for the real KPI 'Avg Claim Cost | Region | Fixed'."""
        key_unknown = self._make_key(
            "Avg Claim Cost | Region | Fixed",
            ["Avg Claim Cost", "Incident Date (Table - Extract)", "Region (Table - Extract)"],
            "UNKNOWN",
            "insurance",
            "actuarial_and_risk",
        )
        key_none = self._make_key(
            "Avg Claim Cost | Region | Fixed",
            ["Avg Claim Cost", "Incident Date (Table - Extract)", "Region (Table - Extract)"],
            "NONE",
            "insurance",
            "actuarial_and_risk",
        )
        assert key_unknown == key_none, (
            f"UNKNOWN and NONE should produce same key.\n"
            f"  UNKNOWN: {key_unknown}\n  NONE: {key_none}"
        )

    def test_empty_agg_equals_unknown_key(self):
        """Empty string aggregation should also produce the same key as UNKNOWN."""
        key_empty = self._make_key("Aging Bin by Case ID", [], "", "insurance", "service_and_operations")
        key_unknown = self._make_key("Aging Bin by Case ID", [], "UNKNOWN", "insurance", "service_and_operations")
        assert key_empty == key_unknown

    def test_sum_differs_from_unknown(self):
        """SUM aggregation MUST produce a different key from UNKNOWN.
        This is intentional — SUM(Revenue) != UNKNOWN(Revenue)."""
        key_sum = self._make_key("Avg Claim Cost", ["Col.A"], "SUM", "insurance", "actuarial_and_risk")
        key_unknown = self._make_key("Avg Claim Cost", ["Col.A"], "UNKNOWN", "insurance", "actuarial_and_risk")
        assert key_sum != key_unknown

    def test_avg_differs_from_sum(self):
        """AVG and SUM must produce different keys (semantic difference)."""
        key_avg = self._make_key("Avg Claim Cost", ["Col.A"], "AVG", "insurance", "actuarial_and_risk")
        key_sum = self._make_key("Avg Claim Cost", ["Col.A"], "SUM", "insurance", "actuarial_and_risk")
        assert key_avg != key_sum

    def test_subdomain_vs_sector_scope_different_keys(self):
        """Real case: subdomain 'actuarial_and_risk' vs sector fallback '__sector__'
        must produce different keys (by design — different candidate pools)."""
        key_sub = self._make_key(
            "Avg Claim Cost | Region | Fixed",
            ["Avg Claim Cost", "Incident Date (Table - Extract)", "Region (Table - Extract)"],
            "NONE",
            "insurance",
            "actuarial_and_risk",
        )
        key_sector = self._make_key(
            "Avg Claim Cost | Region | Fixed",
            ["Avg Claim Cost", "Incident Date (Table - Extract)", "Region (Table - Extract)"],
            "NONE",
            "insurance",
            "__sector__",
        )
        assert key_sub != key_sector, "Different scopes must produce different cache keys"

    def test_lineage_order_invariant(self):
        """Real lineage from 'Avg Claim Cost': ordering should not affect key."""
        key_a = self._make_key(
            "Avg Claim Cost",
            ["Total Claim Amount (Table - Extract)", "Claim Filed (Table - Extract)"],
            "SUM", "insurance", "actuarial_and_risk",
        )
        key_b = self._make_key(
            "Avg Claim Cost",
            ["Claim Filed (Table - Extract)", "Total Claim Amount (Table - Extract)"],
            "SUM", "insurance", "actuarial_and_risk",
        )
        assert key_a == key_b, "Lineage order should not affect cache key"

    def test_name_case_invariant(self):
        """Cache key must be case-insensitive on name."""
        key_lower = self._make_key("avg claim cost", [], "SUM", "insurance", "actuarial_and_risk")
        key_mixed = self._make_key("Avg Claim Cost", [], "SUM", "insurance", "actuarial_and_risk")
        assert key_lower == key_mixed, "Name case should not affect cache key"

    def test_real_nb_closed_claims_key_stability(self):
        """The same real KPI inputs must always produce the same key."""
        key1 = self._make_key(
            "Nb Closed Claims",
            ["_Nb Closed Claims (Expression)"],
            "COUNTD",
            "insurance",
            "claims_management",
        )
        key2 = self._make_key(
            "Nb Closed Claims",
            ["_Nb Closed Claims (Expression)"],
            "COUNTD",
            "insurance",
            "claims_management",
        )
        assert key1 == key2
        assert len(key1) == 64  # SHA256 hex digest length


# ═══════════════════════════════════════════════════════════════
# Visual Context Matching Tests (Phase 1, 2, 3)
# ═══════════════════════════════════════════════════════════════

from unittest.mock import MagicMock

class TestVisualContextMatching:
    """Verify that sheet-level visual context (name, dimensions, filters)
    correctly alters Phase 1 matching, Phase 2 embeddings, and Phase 3 LLM prompt."""

    def test_phase1_virtual_alias_match(self):
        """Phase 1 must match combined sheet name + metric name (virtual alias)
        against the ontology index."""
        from app.services.ontology.ontology_service import match_kpi_to_ontology, build_ontology_match_indexes
        
        # Real-world scenario: KPI is 'Avg Claim Cost', worksheet is 'State | Avg Claim Cost'
        # Ontology has 'Claims Severity' with alias 'Avg Claim Cost'
        ontology_bank = [
            {
                "kpi_id": "k1",
                "name": "Loss Severity",
                "definition": "Average cost per claim",
                "aggregation_type": "AVG",
                "aliases": ["Avg Claim Cost by State", "State Avg Claim Cost"],
            }
        ]
        indexes = build_ontology_match_indexes(ontology_bank)
        
        kpi = ExtractedKPI(
            name="Avg Claim Cost",
            resolved_lineage=[],
            aggregation_type="AVG",
            worksheet_name="State | Avg Claim Cost",
        )
        
        result = match_kpi_to_ontology(kpi, ontology_bank, OntologyCache(MockDB()), indexes=indexes)
        assert result["matched_kpi_id"] == "k1"
        assert "Virtual alias match" in result["similarity_rationale"]

    def test_phase2_embedding_incorporates_visual_details(self):
        """Phase 2 embedding input text must differ when visual context is present
        to avoid semantic collisions for identical metrics."""
        # Generic metric 'Avg IGO Aging' on two different sheets (External vs Internal)
        kpi_ext = ExtractedKPI(
            name="Avg IGO Aging",
            resolved_lineage=["IGO Aging"],
            aggregation_type="AVG",
            worksheet_name="KPI - External Pending",
            dimensions=["Work Category"],
            filters=["Case Status"],
        )
        kpi_int = ExtractedKPI(
            name="Avg IGO Aging",
            resolved_lineage=["IGO Aging"],
            aggregation_type="AVG",
            worksheet_name="KPI - Internal Pending",
            dimensions=["Work Category"],
            filters=["Case Status"],
        )
        
        # We need mock embedding functions to capture what strings were passed
        captured_texts = []
        def mock_emb(text):
            captured_texts.append(text)
            return tuple([1.0] * 1536)
            
        from app.services.ontology.ontology_service import match_kpi_to_ontology
        # Run matching to trigger Phase 2 embedding text composition
        try:
            match_kpi_to_ontology(kpi_ext, [], OntologyCache(MockDB()), embedding_fn=mock_emb)
        except Exception:
            pass
            
        try:
            match_kpi_to_ontology(kpi_int, [], OntologyCache(MockDB()), embedding_fn=mock_emb)
        except Exception:
            pass
            
        assert len(captured_texts) >= 2
        assert "displayed on worksheet KPI - External Pending" in captured_texts[0]
        assert "displayed on worksheet KPI - Internal Pending" in captured_texts[1]
        assert captured_texts[0] != captured_texts[1], "Embeddings text must differ based on worksheet context"

    def test_phase3_llm_judge_receives_visual_context(self):
        """Phase 3 LLM Judge prompt must include worksheet_context,
        visual_breakdown_dimensions, and visual_filters fields."""
        kpi = ExtractedKPI(
            name="Avg IGO Aging",
            resolved_lineage=["IGO Aging"],
            aggregation_type="AVG",
            worksheet_name="KPI - External Pending",
            dimensions=["Work Category"],
            filters=["Case Status"],
        )
        
        class CustomMockLLM:
            def __init__(self):
                self.last_prompt = ""
            def invoke(self, prompt):
                self.last_prompt = prompt
                return MagicMock(content=json.dumps({
                    "matched_kpi_id": "k1",
                    "similarity_score": 0.85,
                    "confidence_score": 0.80,
                    "rationale": "Matches based on External visual filters",
                }))
                
        mock_llm = CustomMockLLM()
        from app.services.ontology.ontology_service import match_kpi_to_ontology
        
        # Force it past Phase 2 embedding by using a mock embedding function that returns mismatched scores (orthogonal vectors)
        def dummy_emb(text):
            return tuple([1.0] + [0.0] * 1535)
            
        match_kpi_to_ontology(
            kpi,
            [{"kpi_id": "k1", "name": "External Pending Cases", "definition": "x", "embedding": tuple([0.0] * 1535 + [1.0])}],
            OntologyCache(MockDB()),
            llm=mock_llm,
            embedding_fn=dummy_emb,
        )
        
        prompt_sent = mock_llm.last_prompt
        
        assert "worksheet_context" in prompt_sent
        assert "KPI - External Pending" in prompt_sent
        assert "visual_breakdown_dimensions" in prompt_sent
        assert "Work Category" in prompt_sent
        assert "visual_filters" in prompt_sent
        assert "Case Status" in prompt_sent
        assert "Use the worksheet_context and visual_filters to guide matching" in prompt_sent
