"""Clustering utilities for report similarity graphs."""

from collections import defaultdict


def build_adjacency(pairs: list[tuple[str, str, float]], threshold: float = 0.70) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for a, b, score in pairs:
        if score >= threshold:
            graph[a].add(b)
            graph[b].add(a)
    return graph


def connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    visited: set[str] = set()
    clusters: list[list[str]] = []

    for node in graph:
        if node in visited:
            continue
        stack = [node]
        component: list[str] = []
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            component.append(cur)
            stack.extend(graph.get(cur, []) - visited)
        clusters.append(sorted(component))

    return clusters


def louvain_clusters(pairs: list[tuple[str, str, float]], threshold: float = 0.70) -> list[list[str]]:
    """Simplified Louvain fallback: connected components on thresholded graph."""
    return connected_components(build_adjacency(pairs, threshold))
