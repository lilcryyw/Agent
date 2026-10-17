"""Ассоциативное вспоминание: персонализированный PageRank по графу памяти (как в HippoRAG).

Затравки — сущности, упомянутые в подсказке («мама», «Самара»). Активация растекается
по связям «сущность ↔ факт ↔ эпизод ↔ реплика», и находятся воспоминания, которые
не похожи на запрос словами, но связаны с ним по смыслу через общих людей/места.

Граф хранится списком рёбер (разреженно): итерация — O(рёбер), без плотной матрицы n×n.
У «узловых» сущностей («мама» — тысячи упоминаний) берём самые сильные и свежие связи,
а не первые попавшиеся: раньше рёбра обрезались в порядке записи (старые вытесняли новые),
а при >3000 узлов граф молча выключался — именно для самых важных людей.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from cogmem.context import Ctx

Node = tuple[str, int]
MAX_EDGES = 6000          # всего рёбер в подграфе
MAX_EDGES_PER_NODE = 400  # с одного узла (на втором шаге — меньше, см. ниже)


def _edges_touching(ctx: Ctx, nodes: list[Node], per_node: int, budget: int) -> list[tuple[Node, Node, float]]:
    out: list[tuple[Node, Node, float]] = []
    for t, i in nodes:
        if len(out) >= budget:
            break
        rows = ctx.db.query(
            "SELECT src_type, src_id, dst_type, dst_id, weight, updated_at FROM links WHERE dst_type=? AND dst_id=? "
            "UNION ALL SELECT src_type, src_id, dst_type, dst_id, weight, updated_at FROM links "
            "WHERE src_type=? AND src_id=? ORDER BY weight DESC, updated_at DESC LIMIT ?",
            (t, i, t, i, min(per_node, budget - len(out))),
        )
        out += [((r["src_type"], r["src_id"]), (r["dst_type"], r["dst_id"]), float(r["weight"])) for r in rows]
    return out


def personalized_pagerank(ctx: Ctx, seeds: list[int], *, hops: int = 2, top: int | None = 80) -> dict[Node, float]:
    """Оценки узлов (0..1, нормированы на максимум), кроме самих затравок; top — сколько лучших вернуть."""
    if not seeds:
        return {}
    seed_nodes: list[Node] = [("entity", s) for s in seeds]
    frontier = list(seed_nodes)
    seen: set[Node] = set(seed_nodes)
    edges: dict[tuple[Node, Node], float] = {}
    per_node = MAX_EDGES_PER_NODE
    for _ in range(hops):
        new_edges = _edges_touching(ctx, frontier, per_node, MAX_EDGES - len(edges))
        nxt = []
        for a, b, w in new_edges:
            key = (a, b) if a <= b else (b, a)
            edges[key] = max(edges.get(key, 0.0), w)
            for n in (a, b):
                if n not in seen:
                    seen.add(n)
                    nxt.append(n)
        frontier = nxt
        per_node = max(8, per_node // 10)  # дальше от затравки — только сильнейшие связи
        if not frontier or len(edges) >= MAX_EDGES:
            break
    if not edges:
        return {}
    nodes = sorted(seen)
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)
    src = np.fromiter((idx[a] for a, _ in edges), dtype=np.int64, count=len(edges))
    dst = np.fromiter((idx[b] for _, b in edges), dtype=np.int64, count=len(edges))
    w = np.fromiter(edges.values(), dtype=np.float64, count=len(edges))
    # Неориентированный граф: каждое ребро в обе стороны.
    rows, cols, ws = np.concatenate([src, dst]), np.concatenate([dst, src]), np.concatenate([w, w])
    deg = np.zeros(n)
    np.add.at(deg, rows, ws)
    deg[deg == 0] = 1.0
    pw = ws / deg[rows]  # вероятность перехода rows → cols
    s = np.zeros(n)
    for sn in seed_nodes:
        if sn in idx:
            s[idx[sn]] = 1.0
    s /= s.sum()
    alpha = ctx.cfg.ppr_alpha
    r = s.copy()
    for _ in range(ctx.cfg.ppr_iterations):
        nr = np.zeros(n)
        np.add.at(nr, cols, pw * r[rows])
        r = alpha * s + (1 - alpha) * nr
    seed_set = set(seed_nodes)
    out = {node: float(r[i]) for node, i in idx.items() if node not in seed_set and r[i] > 0}
    if top is not None and len(out) > top:
        out = dict(sorted(out.items(), key=lambda kv: -kv[1])[:top])
    if out:
        m = max(out.values())
        out = {k: v / m for k, v in out.items()}
    return out
