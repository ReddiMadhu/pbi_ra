"""Blocking candidates by schema fingerprint and ontology overlap."""


def block_by_schema(fingerprints: dict[str, dict]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for report_id, fp in fingerprints.items():
        key = fp.get("data_source_hash", "") + ":" + fp.get("semantic_model_hash", "")
        groups.setdefault(key, []).append(report_id)
    return {k: v for k, v in groups.items() if len(v) > 1}


def block_by_ontology(fingerprints: dict[str, dict]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for report_id, fp in fingerprints.items():
        key = fp.get("ontology_kpi_hash") or "none"
        groups.setdefault(key, []).append(report_id)
    return groups
