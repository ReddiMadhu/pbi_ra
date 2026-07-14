"""Ontology matching and scoring tests."""
import json
from unittest.mock import MagicMock

from app.models.metadata import WorksheetMetadata, WorkbookMetadata, DatasourceMetadata
from app.services.ontology.kpi_extractor import ExtractedKPI, extract_kpis_per_worksheet
from app.services.ontology.ontology_cache import OntologyCache
from app.services.ontology.ontology_service import (
    match_kpi_to_ontology,
    match_kpi_scoped,
    get_last_phase3_candidates,
    reset_phase3_counter,
)
from app.services.ontology.taxonomy import normalize_scope, suggest_from_legacy_domain
from app.services.rationalization.blocking import should_skip_disjoint_pair
from app.services.rationalization.pipeline import persist_pairwise
from app.services.rationalization.scoring import (
    compute_composite_score,
    compute_ontology_score_from_sets,
)


class MockCache:
    def get(self, lineage, aggregation, *args, **kwargs):
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


def test_phase2_all_candidates_in_slice():
    reset_phase3_counter()
    import math
    ontology = []
    kpi_emb = [1.0] + [0.0] * 127
    for i in range(10):
        sim_target = 0.51 + (i * 0.02)  # 0.51 .. 0.69 — all in Phase 3 zone
        emb = [math.sqrt(sim_target)] + [math.sqrt(1 - sim_target)] + [0.0] * 126
        ontology.append({
            "kpi_id": f"k{i}",
            "name": f"KPI {i}",
            "aliases": [],
            "definition": f"Def {i}",
            "aggregation_type": "SUM",
            "representative_lineage": [],
            "embedding": emb,
        })

    llm = MockLLM()
    match_kpi_to_ontology(
        kpi=ExtractedKPI(name="Unknown KPI XYZ", resolved_lineage=["X"], aggregation_type="SUM"),
        ontology_kpis=ontology,
        cache=MockCache(),
        llm=llm,
        embedding_fn=lambda t: tuple(kpi_emb),
    )
    candidates = get_last_phase3_candidates()
    assert len(candidates) == 10
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


def test_visual_breakdown_extraction():
    ws = WorksheetMetadata(
        name="Loss by State",
        rows=["State"],
        columns=["Amount (Table - Sales)"],
        mark_type="Bar",
        measure_bindings=[{
            "field": "Amount",
            "aggregation": "SUM",
            "table": "Sales",
            "lineage": "Sales.Amount",
        }],
    )
    wb = WorkbookMetadata(source_file="test.twb", worksheets=[ws], dashboards=[])
    per_ws = extract_kpis_per_worksheet(wb, {"Amount": "Sales"})
    kpis = per_ws.get("Loss by State", [])
    names = {k.name for k in kpis}
    assert "SUM of Sales.Amount" in names or "SUM of Amount" in names
    assert any("by State" in n for n in names)


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


def test_cache_key_includes_scope():
    db = MagicMock()
    cache = OntologyCache(db)
    k1 = cache._make_key(["Sales.Amount"], "SUM", "insurance", "claims_litigation")
    k2 = cache._make_key(["Sales.Amount"], "SUM", "insurance", "underwriting")
    k3 = cache._make_key(["Sales.Amount"], "SUM", "banking", "retail")
    assert k1 != k2
    assert k1 != k3


def test_scoped_match_subdomain_hit():
    subdomain_kpis = [{"kpi_id": "c1", "name": "Loss Ratio", "aliases": [], "definition": "Claims"}]
    sector_kpis = subdomain_kpis + [{"kpi_id": "u1", "name": "IGO Rate", "aliases": [], "definition": "UW"}]
    result = match_kpi_scoped(
        ExtractedKPI(name="Loss Ratio", resolved_lineage=[], aggregation_type="SUM"),
        subdomain_kpis,
        sector_kpis,
        MockCache(),
        llm=None,
        sector="insurance",
        subdomain="claims_litigation",
    )
    assert result["matched_kpi_id"] == "c1"


def test_scoped_fallback_to_sector():
    subdomain_kpis = [{"kpi_id": "c1", "name": "Other Claims KPI", "aliases": [], "definition": "X"}]
    sector_kpis = subdomain_kpis + [{"kpi_id": "s1", "name": "Premium Volume", "aliases": [], "definition": "Shared"}]
    result = match_kpi_scoped(
        ExtractedKPI(name="Premium Volume", resolved_lineage=[], aggregation_type="SUM"),
        subdomain_kpis,
        sector_kpis,
        MockCache(),
        llm=None,
        sector="insurance",
        subdomain="claims_litigation",
    )
    assert result["matched_kpi_id"] == "s1"
    assert "sector fallback" in (result.get("confidence_rationale") or "")


def test_no_cross_sector_in_scoped_slices():
    insurance_sector = [{"kpi_id": "c1", "name": "Loss Ratio", "aliases": [], "definition": "Claims"}]
    result = match_kpi_scoped(
        ExtractedKPI(name="Net Revenue", resolved_lineage=[], aggregation_type="SUM"),
        [],
        insurance_sector,
        MockCache(),
        llm=None,
        sector="insurance",
        subdomain="claims_litigation",
    )
    assert result["mapping_status"] == "not_found"


def test_classification_taxonomy_normalize():
    sector, subdomain = normalize_scope("insurance", "claims_litigation", legacy_domain="Claims & Risk")
    assert sector == "insurance"
    assert subdomain == "claims_litigation"
    sector2, subdomain2 = suggest_from_legacy_domain("New Business Ops")
    assert sector2 == "insurance"
    assert subdomain2 == "underwriting"


def test_applicability_sheet_scope_mapping():
    from app.services.ontology.taxonomy import suggest_scope_from_applicability

    assert suggest_scope_from_applicability("Claims_Litigation") == ("insurance", "claims_litigation")
    assert suggest_scope_from_applicability("Actuarial & Risk") == ("insurance", "actuarial_and_risk")
    assert suggest_scope_from_applicability("Acturial & Risk") == ("insurance", "actuarial_and_risk")
    assert suggest_scope_from_applicability("Marketing") == ("insurance", "marketing")
    assert suggest_scope_from_applicability("Distribution") == ("insurance", "distribution")
    assert suggest_scope_from_applicability("Service & Operations") == ("insurance", "service_and_operations")
    assert suggest_scope_from_applicability("underwriting") == ("insurance", "underwriting")
    assert suggest_scope_from_applicability("CX & Digital") == ("insurance", "cx_and_digital")
    assert suggest_scope_from_applicability("CX&Digital") == ("insurance", "cx_and_digital")
    # Multiple sheets → first listed wins (not collapsed to a fake shared bucket)
    assert suggest_scope_from_applicability("Marketing, Claims_Litigation") == ("insurance", "marketing")


def test_bank_format_header_resolution():
    from scripts.seed_ontology_from_excel import resolve_column_map, COLUMN_MAP, row_to_kpi, _norm_header
    import pandas as pd

    assert _norm_header("Measurement(KPI)") == "measurement kpi"
    headers = [
        "Measurement(KPI)",
        "Definition",
        "Fields required to create the Metric",
        "Applicablity with Sheet Names",
    ]
    resolved = resolve_column_map(headers, COLUMN_MAP)
    assert resolved["name"] == "Measurement(KPI)"
    assert resolved["definition"] == "Definition"
    assert resolved["fields_required"] == "Fields required to create the Metric"
    assert resolved["applicability"] == "Applicablity with Sheet Names"

    row = pd.Series({
        "Measurement(KPI)": "Loss Ratio",
        "Definition": "Claims / Premium",
        "Fields required to create the Metric": "Paid Amount, Earned Premium, State",
        "Applicablity with Sheet Names": "Claims_Litigation",
    })
    kpi = row_to_kpi(row, resolved, {"sector": "insurance", "subdomain": "service_and_operations", "aggregation_type": "UNKNOWN", "status": "active", "created_by": "test"})
    assert kpi is not None
    assert kpi.name == "Loss Ratio"
    assert kpi.subdomain == "claims_litigation"
    assert "Paid Amount" in json.loads(kpi.representative_lineage)
    assert "Claims_Litigation" in json.loads(kpi.aliases)


def test_countd_not_collapsed_to_count():
    from app.services.ontology.kpi_extractor import _normalize_agg
    from app.services.ontology.ontology_service import _agg_key

    assert _normalize_agg("COUNTD") == "COUNTD"
    assert _normalize_agg("CNT") == "COUNT"
    assert _normalize_agg("COUNT") == "COUNT"
    assert _agg_key("COUNTD") == "COUNTD"
    assert _agg_key("CNT") == "COUNT"


def test_phase3_prompt_includes_definitions():
    reset_phase3_counter()
    import math
    kpi_emb = [1.0] + [0.0] * 127
    sim_target = 0.70
    emb = [math.sqrt(sim_target)] + [math.sqrt(1 - sim_target)] + [0.0] * 126
    ontology = [{
        "kpi_id": "k1",
        "name": "Loss Ratio",
        "aliases": [],
        "definition": "Claims paid divided by earned premium across the book",
        "aggregation_type": "NONE",
        "representative_lineage": [],
        "embedding": emb,
    }]
    llm = MockLLM()
    match_kpi_to_ontology(
        kpi=ExtractedKPI(
            name="Paid to Premium",
            resolved_lineage=[],
            aggregation_type="UNKNOWN",
            mark_type="Bar",
            calculation_logic="SUM(Paid)/SUM(Premium)",
            extraction_method="llm_summary",
        ),
        ontology_kpis=ontology,
        cache=MockCache(),
        llm=llm,
        embedding_fn=lambda t: tuple(kpi_emb),
    )
    assert "definition" in llm.last_prompt
    assert "mark_type" in llm.last_prompt
    assert "calculation_logic" in llm.last_prompt
    assert "Claims paid" in llm.last_prompt


def test_mark_card_extraction():
    from app.models.metadata import CalculatedFieldMetadata

    ws = WorksheetMetadata(
        name="Color Sheet",
        rows=["State"],
        columns=[],
        filters_and_marks=["Loss Ratio"],
        mark_type="Map",
        measure_bindings=[],
        used_calculated_fields=[],
    )
    ds = DatasourceMetadata(
        name="ds",
        caption=None,
        version=None,
        calculated_fields=[
            CalculatedFieldMetadata(
                name="Loss Ratio",
                caption="Loss Ratio",
                formula="SUM([Paid])/SUM([Premium])",
                datatype="real",
            )
        ],
    )
    wb = WorkbookMetadata(source_file="test.twb", datasources=[ds], worksheets=[ws], dashboards=[])
    per_ws = extract_kpis_per_worksheet(wb, {"Paid": "Claims", "Premium": "Premium"})
    kpis = per_ws.get("Color Sheet", [])
    assert any(k.extraction_method == "mark_card" and k.name == "Loss Ratio" for k in kpis)


def test_ai_summary_extraction_and_dedup():
    from app.services.ontology.kpi_extractor import extract_from_ai_summary

    ai = {
        "summary": "test",
        "kpis": [
            {
                "name": "Loss Ratio",
                "confidence": 90,
                "definition": "Claims / Premium",
                "calculation_logic": "SUM(Paid)/SUM(Earned)",
                "source_description": "From Claims dashboard",
            },
            {"name": "Already Extracted", "confidence": 80, "definition": "x"},
        ],
    }
    kpis = extract_from_ai_summary(ai)
    assert len(kpis) == 2
    assert kpis[0].extraction_method == "llm_summary"
    assert kpis[0].aggregation_type == "UNKNOWN"
    assert kpis[0].resolved_lineage == []
    assert "SUM(Paid)" in (kpis[0].calculation_logic or "")


def test_orphan_worksheets_flag():
    from app.models.metadata import DashboardMetadata

    orphan = WorksheetMetadata(
        name="Orphan Sheet",
        measure_bindings=[{
            "field": "Amount",
            "aggregation": "SUM",
            "table": "Sales",
            "lineage": "Sales.Amount",
        }],
    )
    on_dash = WorksheetMetadata(
        name="On Dash",
        measure_bindings=[{
            "field": "Amount",
            "aggregation": "SUM",
            "table": "Sales",
            "lineage": "Sales.Amount",
        }],
    )
    wb = WorkbookMetadata(
        source_file="test.twb",
        worksheets=[orphan, on_dash],
        dashboards=[DashboardMetadata(name="D1", worksheets=["On Dash"])],
    )
    per_default = extract_kpis_per_worksheet(wb, {"Amount": "Sales"})
    assert "Orphan Sheet" not in per_default
    assert "On Dash" in per_default

    per_orphans = extract_kpis_per_worksheet(
        wb, {"Amount": "Sales"}, include_orphan_worksheets=True
    )
    assert "Orphan Sheet" in per_orphans
    assert per_orphans["Orphan Sheet"][0].worksheet_id == "orphan"


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
