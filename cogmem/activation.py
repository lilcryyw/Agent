"""Активация по ACT-R (Anderson & Lebiere 1998; Anderson & Schooler 1991).

Базовая активация воспоминания: B = ln( Σ w_k · (t − t_k)^(−d) ),
где t_k — моменты обращений, d ≈ 0.5. Частое и недавнее — доступнее; редкое и давнее —
«тускнеет», но не стирается. Каждое использование добавляет след — так работает эффект повторения.
"""

from __future__ import annotations

import math
from collections import defaultdict

from cogmem.context import Ctx

TRACE_WEIGHT = {"created": 1.0, "used": 1.0, "retrieved": 0.3}


def base_levels(ctx: Ctx, units: list[tuple[str, int]]) -> dict[tuple[str, int], float]:
    """Активация B для набора единиц (одним запросом к базе)."""
    if not units:
        return {}
    now = ctx.clock.now()
    d = ctx.cfg.decay_d
    by_type: dict[str, list[int]] = defaultdict(list)
    for t, i in units:
        by_type[t].append(i)
    sums: dict[tuple[str, int], float] = defaultdict(float)
    for t, ids in by_type.items():
        for chunk_start in range(0, len(ids), 500):
            chunk = ids[chunk_start : chunk_start + 500]
            rows = ctx.db.query(
                f"SELECT unit_id, ts, kind FROM access_traces WHERE unit_type=? AND unit_id IN ({','.join('?' * len(chunk))})",
                (t, *chunk),
            )
            for r in rows:
                age = max(1.0, now - r["ts"])  # секунды; минимум 1 с
                sums[(t, r["unit_id"])] += TRACE_WEIGHT.get(r["kind"], 0.5) * age ** (-d)
    return {u: (math.log(sums[u]) if sums.get(u) else -12.0) for u in units}


def squash(b: float, tau: float) -> float:
    """Перевод активации в 0..1 (логистика вокруг порога τ)."""
    return 1.0 / (1.0 + math.exp(-(b - tau)))
