"""Ontology matching and scoring tests."""
from unittest.mock import MagicMock

from app.services.ontology.kpi_extractor import ExtractedKPI
from app.services.ontology.ontology_cache import OntologyCache
from app.services.ontology.ontology_service import match_kpi_to_ontology
from app.services.rationalization.scoring import (
    compute_composite_score,
    compute_ontology_score_from_sets,
)


class MockCache:
    def get(self, lineage, aggregation):
        return None

    def set(self, lineage, aggregation, result):
        pass


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
