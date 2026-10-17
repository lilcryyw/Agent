"""Переконсолидация (Nader 2000; REALM 2026): вспомненное перестраивается по итогам использования.

После ответа модель сообщает, какие воспоминания реально пригодились ([F12], [E7]...).
  • использованным — след обращения (активация растёт, ACT-R);
  • показанным, но не использованным — слабый след «извлечено»;
  • между совместно использованными — связь усиливается: w ← clip(w + η·c), η = 1 − w
    (новая связь создаётся с w = 0.8·c) — «вместе вспоминались — вместе связаны» (Хебб).
"""

from __future__ import annotations

from itertools import combinations

from cogmem.context import Ctx
from cogmem.types import parse_ref

W_MIN = 0.05


def _strengthen(ctx: Ctx, a: tuple[str, int], b: tuple[str, int], c: float) -> None:
    if a == b:
        return
    a, b = sorted([a, b])
    now = ctx.clock.now()
    row = ctx.db.one("SELECT weight FROM links WHERE src_type=? AND src_id=? AND dst_type=? AND dst_id=? AND kind='co'",
                     (a[0], a[1], b[0], b[1]))
    if row is None:
        ctx.db.execute("INSERT INTO links(src_type, src_id, dst_type, dst_id, kind, weight, updated_at) "
                       "VALUES (?,?,?,?,'co',?,?)", (a[0], a[1], b[0], b[1], 0.8 * c, now))
    else:
        w = float(row["weight"])
        w = min(1.0, max(W_MIN, w + (1 - w) * c))
        ctx.db.execute("UPDATE links SET weight=?, updated_at=? WHERE src_type=? AND src_id=? AND dst_type=? "
                       "AND dst_id=? AND kind='co'", (w, now, a[0], a[1], b[0], b[1]))


def apply_feedback(ctx: Ctx, shown: list[str], used: list[str], confidence: float = 0.5) -> dict:
    shown_u = [u for u in (parse_ref(r) for r in shown) if u]
    # Учитываем только то, что действительно показывали (защита от выдуманных ID).
    used_u = [u for u in (parse_ref(r) for r in used) if u and u in shown_u]
    used_set = set(used_u)
    with ctx.db.tx():
        for u in used_set:
            ctx.trace(u[0], u[1], "used")
        for u in shown_u:
            if u not in used_set:
                ctx.trace(u[0], u[1], "retrieved")
        for a, b in combinations(sorted(used_set), 2):
            _strengthen(ctx, a, b, confidence)
    return {"used": len(used_set), "shown": len(shown_u)}
