"""Ontology matching and scoring tests."""
import json
from unittest.mock import MagicMock

from app.models.metadata import WorksheetMetadata, WorkbookMetadata, DatasourceMetadata
from app.services.ontology.kpi_extractor import ExtractedKPI, extract_kpis_per_worksheet
from app.services.ontology.ontology_cache import OntologyCache
from app.services.ontology.ontology_service import (
    match_kpi_to_ontology,
    get_last_phase3_candidates,
    reset_phase3_counter,
)
from app.services.rationalization.blocking import should_skip_disjoint_pair
from app.services.rationalization.pipeline import persist_pairwise
from app.services.rationalization.scoring import (
    compute_composite_score,
    compute_ontology_score_from_sets,
)


class MockCache:
    def get(self, lineage, aggregation):
        return None

    def set(self, lineage, aggregation, result, **kwargs):
        pass

    def flush(self):
        pass


class MockLLM:
    def __init__(self):
        self.last_prompt = ""

    def invoke(self, prompt):
        self.last_prompt = prompt
        return MagicMock(content=json.dumps({
            "matched_kpi_id": "k2",
            "similarity_score": 0.75,
            "confidence_score": 0.75,
            "rationale": "test",
        }))


def test_phase1_exact_match():
    kpis = [{"kpi_id": "k1", "name": "Net Revenue", "aliases": ["Revenue"], "definition": "Revenue"}]
    result = match_kpi_to_ontology(
        kpi=ExtractedKPI(name="Net Revenue", resolved_lineage=[], aggregation_type="SUM"),
        ontology_kpis=kpis,
        cache=MockCache(),
        llm=None,
    )
    assert result["matched_kpi_id"] == "k1"
    assert result["similarity_score"] == 1.0


def test_phase1_alias_match():
    kpis = [{"kpi_id": "k1", "name": "Net Revenue", "aliases": ["Revenue"], "definition": "Revenue"}]
    result = match_kpi_to_ontology(
        kpi=ExtractedKPI(name="Revenue", resolved_lineage=[], aggregation_type="SUM"),
        ontology_kpis=kpis,
        cache=MockCache(),
        llm=None,
    )
    assert result["matched_kpi_id"] == "k1"


def test_phase1_lineage_match():
    kpis = [{
        "kpi_id": "k1",
        "name": "Revenue Metric",
        "aliases": [],
        "definition": "Revenue",
        "aggregation_type": "SUM",
        "representative_lineage": ["Sales.Amount"],
    }]
    result = match_kpi_to_ontology(
        kpi=ExtractedKPI(
            name="Different Name",
            resolved_lineage=["Sales.Amount"],
            aggregation_type="SUM",
        ),
        ontology_kpis=kpis,
        cache=MockCache(),
        llm=None,
    )
    assert result["matched_kpi_id"] == "k1"
    assert result["similarity_score"] == 1.0
    assert result["mapping_status"] == "auto_accepted"


def test_phase1_lineage_no_false_match():
    kpis = [{
        "kpi_id": "k1",
        "name": "Revenue",
        "aliases": [],
        "definition": "Revenue",
        "aggregation_type": "SUM",
        "representative_lineage": ["Sales.Amount"],
    }]
    result = match_kpi_to_ontology(
        kpi=ExtractedKPI(
            name="Revenue",
            resolved_lineage=["Returns.Amount"],
            aggregation_type="SUM",
        ),
        ontology_kpis=kpis,
        cache=MockCache(),
        llm=None,
        embedding_fn=lambda t: tuple([1.0] * 128) if "Returns" in t else tuple([0.0] * 128),
    )
    assert result.get("matched_kpi_id") != "k1" or result["similarity_rationale"] != "Phase 1 lineage+agg match"


def test_phase2_top5_candidates():
    reset_phase3_counter()
    ontology = []
    for i in range(10):
        emb = [0.0] * 128
        emb[(i + 1) % 128] = 1.0  # offset so k0 is not perfect match
        ontology.append({
            "kpi_id": f"k{i}",
            "name": f"KPI {i}",
            "aliases": [],
            "definition": f"Def {i}",
            "aggregation_type": "SUM",
            "representative_lineage": [],
            "embedding": emb,
        })

    kpi_emb = [0.0] * 128
    kpi_emb[0] = 1.0
    kpi_emb[1] = 0.7  # partial overlap with k1 -> sim in ambiguous zone
    llm = MockLLM()
    match_kpi_to_ontology(
        kpi=ExtractedKPI(name="Unknown KPI XYZ", resolved_lineage=["X"], aggregation_type="SUM"),
        ontology_kpis=ontology,
        cache=MockCache(),
        llm=llm,
        embedding_fn=lambda t: tuple(kpi_emb),
    )
    candidates = get_last_phase3_candidates()
    assert len(candidates) == 5
    assert "Candidates:" in llm.last_prompt


def test_per_visual_dedup():
    from app.models.metadata import CalculatedFieldMetadata

    ws = WorksheetMetadata(
        name="Sheet1",
        used_calculated_fields=["Revenue"],
        measure_bindings=[{
            "field": "Amount",
            "aggregation": "SUM",
            "table": "Sales",
            "lineage": "Sales.Amount",
        }],
    )
    ds = DatasourceMetadata(
        name="ds",
        caption=None,
        version=None,
        calculated_fields=[
            CalculatedFieldMetadata(
                name="Revenue",
                caption="Revenue",
                formula="SUM([Amount])",
                datatype="real",
            )
        ],
    )
    wb = WorkbookMetadata(
        source_file="test.twb",
        datasources=[ds],
        worksheets=[ws],
        dashboards=[],
    )
    per_ws = extract_kpis_per_worksheet(wb, {"Amount": "Sales"}, worksheet_db_rows=None)
    kpis = per_ws.get("Sheet1", [])
    assert len(kpis) == 1
    assert kpis[0].name == "Revenue"
    assert kpis[0].extraction_method == "named_measure"


def test_ontology_score_jaccard():
    kpis_a = {"k1", "k2", "k3"}
    kpis_b = {"k2", "k3", "k4"}
    score = compute_ontology_score_from_sets(kpis_a, kpis_b)
    assert abs(score - 0.5) < 0.001


def test_empty_kpi_sets():
    assert compute_ontology_score_from_sets(set(), set()) == 0.0


def test_fully_overlapping_kpi_sets():
    kpis = {"k1", "k2", "k3"}
    score = compute_ontology_score_from_sets(kpis, kpis)
    assert abs(score - 1.0) < 0.001


def test_composite_score_6_layers():
    composite = 0.25 * 1.0 + 0.20 * 1.0 + 0.20 * 1.0 + 0.10 * 1.0 + 0.15 * 1.0 + 0.10 * 1.0
    assert abs(compute_composite_score({
        "data_source": 1.0,
        "semantic_model": 1.0,
        "ontology_kpi": 1.0,
        "dax_structural": 1.0,
        "visual": 1.0,
        "filter": 1.0,
    }) - composite) < 0.001
    assert abs(composite - 1.0) < 0.001


def test_cache_invalidation():
    db = MagicMock()
    cache1 = OntologyCache(db, ontology_version="v1")
    cache2 = OntologyCache(db, ontology_version="v2")
    key1 = cache1._make_key(["Sales.Amount"], "SUM")
    key2 = cache2._make_key(["Sales.Amount"], "SUM")
    assert key1 != key2


def test_blocking_skips_disjoint():
    kpi_sets = {"1": {"k1"}, "2": set()}
    assert should_skip_disjoint_pair(1, 2, kpi_sets, []) is True
    assert should_skip_disjoint_pair(1, 2, kpi_sets, ["Shared DS"]) is False


def test_persist_pairwise_scores():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    layers = {
        "data_source": 0.5,
        "semantic_model": 0.5,
        "ontology_kpi": 0.5,
        "dax_structural": 0.5,
        "visual": 0.5,
        "filter": 0.5,
    }
    persist_pairwise(db, "1", "2", layers, 0.5, "functional_overlap")
    assert db.add.called
    assert db.commit.called
