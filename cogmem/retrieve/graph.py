"""Ассоциативное вспоминание: персонализированный PageRank по графу памяти (как в HippoRAG).

Затравки — сущности, упомянутые в подсказке («мама», «Самара»). Активация растекается
по связям «сущность ↔ факт ↔ эпизод ↔ реплика», и находятся воспоминания, которые
не похожи на запрос словами, но связаны с ним по смыслу через общих людей/места.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from cogmem.context import Ctx

Node = tuple[str, int]
MAX_EDGES = 4000


def _edges_touching(ctx: Ctx, nodes: list[Node]) -> list[tuple[Node, Node, float]]:
    out: list[tuple[Node, Node, float]] = []
    by_type: dict[str, list[int]] = defaultdict(list)
    for t, i in nodes:
        by_type[t].append(i)
    for t, ids in by_type.items():
        ph = ",".join("?" * len(ids))
        for r in ctx.db.query(
            f"SELECT src_type, src_id, dst_type, dst_id, weight FROM links WHERE dst_type=? AND dst_id IN ({ph}) "
            f"UNION ALL SELECT src_type, src_id, dst_type, dst_id, weight FROM links WHERE src_type=? AND src_id IN ({ph})",
            (t, *ids, t, *ids),
        ):
            out.append(((r["src_type"], r["src_id"]), (r["dst_type"], r["dst_id"]), float(r["weight"])))
            if len(out) >= MAX_EDGES:
                return out
    return out


def personalized_pagerank(ctx: Ctx, seeds: list[int], *, hops: int = 2) -> dict[Node, float]:
    """Оценки узлов (0..1, нормированы на максимум), кроме самих затравок."""
    if not seeds:
        return {}
    seed_nodes: list[Node] = [("entity", s) for s in seeds]
    frontier = list(seed_nodes)
    seen: set[Node] = set(seed_nodes)
    edges: dict[tuple[Node, Node], float] = {}
    for _ in range(hops):
        new_edges = _edges_touching(ctx, frontier)
        nxt = []
        for a, b, w in new_edges:
            key = (a, b) if a <= b else (b, a)
            edges[key] = max(edges.get(key, 0.0), w)
            for n in (a, b):
                if n not in seen:
                    seen.add(n)
                    nxt.append(n)
        frontier = nxt
        if not frontier or len(edges) >= MAX_EDGES:
            break
    if not edges:
        return {}
    nodes = sorted(seen)
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)
    W = np.zeros((n, n), dtype=np.float32) if n <= 3000 else None
    if W is None:
        return {}
    for (a, b), w in edges.items():
        W[idx[a], idx[b]] += w
        W[idx[b], idx[a]] += w
    deg = W.sum(axis=1, keepdims=True)
    deg[deg == 0] = 1.0
    P = W / deg  # строки — переходы
    s = np.zeros(n, dtype=np.float32)
    for sn in seed_nodes:
        if sn in idx:
            s[idx[sn]] = 1.0
    s /= s.sum()
    alpha = ctx.cfg.ppr_alpha
    r = s.copy()
    for _ in range(ctx.cfg.ppr_iterations):
        r = alpha * s + (1 - alpha) * (P.T @ r)
    out = {}
    seed_set = set(seed_nodes)
    for node, i in idx.items():
        if node not in seed_set and r[i] > 0:
            out[node] = float(r[i])
    if out:
        m = max(out.values())
        out = {k: v / m for k, v in out.items()}
    return out
