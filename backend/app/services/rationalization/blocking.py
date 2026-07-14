"""Blocking candidates by schema fingerprint and ontology overlap."""


def block_by_schema(fingerprints: dict[str, dict]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for report_id, fp in fingerprints.items():
        key = fp.get("data_source_hash", "") + ":" + fp.get("semantic_model_hash", "")
        groups.setdefault(key, []).append(report_id)
    return {k: v for k, v in groups.items() if len(v) > 1}


def block_by_ontology(kpi_sets: dict[str, set[str]]) -> dict[str, list[str]]:
    """Group reports by sorted canonical KPI ID set."""
    groups: dict[str, list[str]] = {}
    for report_id, kpi_ids in kpi_sets.items():
        key = ",".join(sorted(kpi_ids)) if kpi_ids else "none"
        groups.setdefault(key, []).append(report_id)
    return groups


def order_pairs_by_ontology(
    pairs: list[tuple[int, int]],
    kpi_sets: dict[str, set[str]],
) -> list[tuple[int, int]]:
    """Sort pairs so those sharing canonical KPIs are evaluated first (soft blocking)."""

    def priority(pair: tuple[int, int]) -> int:
        a, b = str(pair[0]), str(pair[1])
        shared = len(kpi_sets.get(a, set()) & kpi_sets.get(b, set()))
        return -shared

    return sorted(pairs, key=priority)


def should_skip_disjoint_pair(
    d1_id: int,
    d2_id: int,
    kpi_sets: dict[str, set[str]],
    shared_datasources: list[str],
) -> bool:
    """Skip pairs with zero ontology overlap AND zero shared datasources."""
    a, b = str(d1_id), str(d2_id)
    ontology_overlap = len(kpi_sets.get(a, set()) & kpi_sets.get(b, set()))
    return ontology_overlap == 0 and not shared_datasources
