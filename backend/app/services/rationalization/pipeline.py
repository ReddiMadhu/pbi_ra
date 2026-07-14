"""Rationalization pipeline — persist pairwise scores."""

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.rationalization import PairwiseScore, ScoreDetail
from app.services.rationalization.scoring import (
    compute_composite_score,
    compute_data_source_score,
    compute_dax_structural_score,
    compute_filter_score,
    compute_ontology_score,
    compute_ontology_score_from_sets,
    compute_semantic_model_score,
    compute_visual_score,
)

LAYER_NAMES = [
    "data_source",
    "semantic_model",
    "ontology_kpi",
    "dax_structural",
    "visual",
    "filter",
]

LAYER_TO_DB = {
    "data_source": "data_source",
    "semantic_model": "semantic_model",
    "ontology_kpi": "ontology_kpi",
    "dax_structural": "dax_structural",
    "visual": "visuals",
    "filter": "filters",
}


def _canonical_pair_ids(report_a_id: str | int, report_b_id: str | int) -> tuple[str, str]:
    a_id = str(report_a_id)
    b_id = str(report_b_id)
    if a_id > b_id:
        a_id, b_id = b_id, a_id
    return a_id, b_id


def compute_pair_layers(
    d1: dict,
    d2: dict,
    db: Session,
    wb_ds_map: dict,
    kpi_overlap_fn,
    get_shared_ds_fn,
    kpi_sets: dict[str, set[str]] | None = None,
) -> tuple[dict, float]:
    """Compute 6-layer scores for a dashboard pair."""
    shared_ds = get_shared_ds_fn(d1["workbook_id"], d2["workbook_id"], wb_ds_map)
    ds_a = len(wb_ds_map.get(d1["workbook_id"], []))
    ds_b = len(wb_ds_map.get(d2["workbook_id"], []))
    kpi_sim = kpi_overlap_fn(d1, d2)

    if kpi_sets is not None:
        ontology_kpi = compute_ontology_score_from_sets(
            kpi_sets.get(str(d1["id"]), set()),
            kpi_sets.get(str(d2["id"]), set()),
        )
    else:
        ontology_kpi = compute_ontology_score(d1["id"], d2["id"], db)

    layers = {
        "data_source": compute_data_source_score(shared_ds, ds_a, ds_b),
        "semantic_model": compute_semantic_model_score(set(d1["tables"]), set(d2["tables"])),
        "ontology_kpi": ontology_kpi,
        "dax_structural": compute_dax_structural_score(kpi_sim),
        "visual": compute_visual_score(d1["worksheets_config"], d2["worksheets_config"]),
        "filter": compute_filter_score(d1["worksheets_config"], d2["worksheets_config"]),
    }
    composite = compute_composite_score(layers)
    return layers, composite


def persist_pairwise(
    db: Session,
    report_a_id: str | int,
    report_b_id: str | int,
    layers: dict,
    composite: float,
    classification: str = "review",
    *,
    commit: bool = True,
) -> None:
    a_id, b_id = _canonical_pair_ids(report_a_id, report_b_id)

    row = db.query(PairwiseScore).filter(
        PairwiseScore.report_a_id == a_id,
        PairwiseScore.report_b_id == b_id,
    ).first()
    if not row:
        row = PairwiseScore(report_a_id=a_id, report_b_id=b_id)
        db.add(row)

    row.data_source_score = layers.get("data_source")
    row.semantic_model_score = layers.get("semantic_model")
    row.ontology_kpi_score = layers.get("ontology_kpi")
    row.dax_structural_score = layers.get("dax_structural")
    row.visual_score = layers.get("visual")
    row.filter_score = layers.get("filter")
    row.composite_score = composite
    row.classification = classification
    row.computed_at = datetime.now(UTC)

    for layer_key in LAYER_NAMES:
        db_layer = LAYER_TO_DB[layer_key]
        detail = db.query(ScoreDetail).filter(
            ScoreDetail.report_a_id == a_id,
            ScoreDetail.report_b_id == b_id,
            ScoreDetail.layer == db_layer,
        ).first()
        if not detail:
            detail = ScoreDetail(report_a_id=a_id, report_b_id=b_id, layer=db_layer)
            db.add(detail)
        detail.score = layers.get(layer_key)
        detail.detail_json = json.dumps({"layer": layer_key, "score": layers.get(layer_key)})

    if commit:
        db.commit()


def persist_pairwise_scores(
    db: Session,
    pairs: list[tuple],
    wb_ds_map: dict,
    kpi_overlap_fn,
    get_shared_ds_fn,
    min_composite: float = 0.60,
    kpi_sets: dict[str, set[str]] | None = None,
) -> int:
    """Persist pairwise scores for evaluated pairs. Returns count persisted."""
    count = 0
    seen: set[tuple[str, str]] = set()
    for item in pairs:
        if len(item) >= 5:
            d1, d2, classification, layers, composite = item[:5]
        else:
            d1, d2, classification = item[:3]
            layers, composite = compute_pair_layers(
                d1, d2, db, wb_ds_map, kpi_overlap_fn, get_shared_ds_fn, kpi_sets=kpi_sets
            )

        pair_key = _canonical_pair_ids(d1["id"], d2["id"])
        if pair_key in seen:
            continue
        seen.add(pair_key)

        if composite < min_composite and classification not in ("merge", "functional_overlap"):
            continue
        persist_pairwise(db, d1["id"], d2["id"], layers, composite, classification, commit=False)
        count += 1

    if count:
        db.commit()
    return count
