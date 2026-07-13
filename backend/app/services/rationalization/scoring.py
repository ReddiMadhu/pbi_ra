"""6-layer composite scoring and ontology Jaccard overlap."""

from sqlalchemy.orm import Session

from app.models.ontology import ReportKPIMapping

ACCEPTED_STATUSES = ("auto_accepted", "human_accepted", "promoted")

WEIGHTS = {
    "data_source": 0.25,
    "semantic_model": 0.20,
    "ontology_kpi": 0.20,
    "dax_structural": 0.10,
    "visual": 0.15,
    "filter": 0.10,
}


def get_kpi_set(report_id: str | int, db: Session) -> set[str]:
    rows = (
        db.query(ReportKPIMapping.canonical_kpi_id)
        .filter(
            ReportKPIMapping.report_id == str(report_id),
            ReportKPIMapping.canonical_kpi_id.isnot(None),
            ReportKPIMapping.mapping_status.in_(ACCEPTED_STATUSES),
        )
        .all()
    )
    return {r[0] for r in rows if r[0]}


def compute_ontology_score_from_sets(kpis_a: set[str], kpis_b: set[str]) -> float:
    if not kpis_a and not kpis_b:
        return 0.0
    intersection = kpis_a & kpis_b
    union_size = len(kpis_a) + len(kpis_b) - len(intersection)
    return len(intersection) / union_size if union_size > 0 else 0.0


def compute_ontology_score(report_a_id: str | int, report_b_id: str | int, db: Session) -> float:
    return compute_ontology_score_from_sets(get_kpi_set(report_a_id, db), get_kpi_set(report_b_id, db))


def compute_composite_score(layers: dict[str, float]) -> float:
    return sum(WEIGHTS[k] * layers.get(k, 0.0) for k in WEIGHTS)


def compute_data_source_score(shared_ds: list[str], ds_a_count: int, ds_b_count: int) -> float:
    if not shared_ds:
        return 0.0
    union = max(ds_a_count + ds_b_count - len(shared_ds), 1)
    return len(shared_ds) / union


def compute_semantic_model_score(tables_a: set[str], tables_b: set[str]) -> float:
    if not tables_a and not tables_b:
        return 0.0
    return compute_ontology_score_from_sets(tables_a, tables_b)


def compute_dax_structural_score(kpi_sim: float) -> float:
    """Proxy from legacy KPI name/formula similarity (Stages A+B)."""
    return kpi_sim


def compute_visual_score(ws_a: list[dict], ws_b: list[dict]) -> float:
    if not ws_a or not ws_b:
        return 0.0
    names_a = {w.get("name", "").lower() for w in ws_a}
    names_b = {w.get("name", "").lower() for w in ws_b}
    return compute_ontology_score_from_sets(names_a, names_b)


def compute_filter_score(ws_a: list[dict], ws_b: list[dict]) -> float:
    marks_a = set()
    marks_b = set()
    for w in ws_a:
        for m in w.get("filters_and_marks") or []:
            marks_a.add(str(m).lower())
    for w in ws_b:
        for m in w.get("filters_and_marks") or []:
            marks_b.add(str(m).lower())
    if not marks_a and not marks_b:
        return 0.5
    return compute_ontology_score_from_sets(marks_a, marks_b)


def check_subsumption(set_a: set, set_b: set, threshold: float = 0.90) -> str | None:
    if not set_a or not set_b:
        return None
    if len(set_a & set_b) / len(set_a) >= threshold:
        return "A⊂B"
    if len(set_a & set_b) / len(set_b) >= threshold:
        return "B⊂A"
    return None
