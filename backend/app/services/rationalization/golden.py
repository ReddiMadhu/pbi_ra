"""Golden report selection within a cluster."""


def normalize_scores(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    vmin = min(values.values())
    vmax = max(values.values())
    if vmax == vmin:
        return {k: 1.0 for k in values}
    return {k: (v - vmin) / (vmax - vmin) for k, v in values.items()}


def select_golden(
    members: list[str],
    completeness: dict[str, float],
    usage: dict[str, float],
    freshness: dict[str, float],
    governance: dict[str, float],
    recency: dict[str, float],
) -> tuple[str, dict[str, float]]:
    weights = {"completeness": 0.35, "usage": 0.25, "freshness": 0.20, "governance": 0.10, "recency": 0.10}
    normed = {
        "completeness": normalize_scores({m: completeness.get(m, 0) for m in members}),
        "usage": normalize_scores({m: usage.get(m, 0) for m in members}),
        "freshness": normalize_scores({m: freshness.get(m, 0) for m in members}),
        "governance": normalize_scores({m: governance.get(m, 0) for m in members}),
        "recency": normalize_scores({m: recency.get(m, 0) for m in members}),
    }
    totals: dict[str, float] = {}
    for m in members:
        totals[m] = sum(weights[k] * normed[k].get(m, 0) for k in weights)
    golden = max(members, key=lambda m: totals.get(m, 0))
    return golden, totals
