"""Рабочая память: отбор и упаковка найденного в жёсткий бюджет токенов.

Как у человека (Baddeley; Cowan 4±1): немного, но самое нужное, разложено по разделам.
Каждый пункт помечен ID ([F12], [E7], [M345]) — модель ссылается на них, а память
по этим ссылкам узнаёт, что реально пригодилось (переконсолидация).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from cogmem.config import Budgets
from cogmem.context import Ctx
from cogmem.retrieve.recall import RecallResult, fmt_date
from cogmem.text.ru import estimate_tokens
from cogmem.types import Recalled


@dataclass
class WorkingMemory:
    facts: list[Recalled] = field(default_factory=list)
    episodes: list[tuple[Recalled | None, list[Recalled]]] = field(default_factory=list)  # (эпизод, цитаты)
    entities: list[Recalled] = field(default_factory=list)
    intentions: list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)
    period_label: str | None = None
    tokens: int = 0

    def shown_refs(self) -> list[str]:
        refs = [f.ref for f in self.facts] + [e.ref for e in self.entities]
        for ep, quotes in self.episodes:
            if ep is not None:
                refs.append(ep.ref)
            refs += [q.ref for q in quotes]
        return refs

    def is_empty(self) -> bool:
        return not (self.facts or self.episodes or self.entities or self.intentions or self.procedures)

    def render(self) -> str:
        parts: list[str] = []
        if self.period_label:
            parts.append(f"Период, о котором спрашивают: {self.period_label}")
        if self.facts or self.entities:
            parts.append("Факты:")
            parts += [f"- [{f.ref}] {f.text}" for f in self.facts]
            parts += [f"- [{e.ref}] {e.text}" for e in self.entities]
        if self.episodes:
            parts.append("Эпизоды (воспоминания о событиях и разговорах):")
            for ep, quotes in self.episodes:
                if ep is not None:
                    parts.append(f"- [{ep.ref}] {ep.text}")
                    parts += [f"    · [{q.ref}] {q.text}" for q in quotes]
                else:
                    parts += [f"- [{q.ref}] {q.text}" for q in quotes]
        if self.intentions:
            parts.append("Намерения (не забыть):")
            parts += [f"- {i}" for i in self.intentions]
        if self.procedures:
            parts.append("Известные рецепты действий:")
            parts += [f"- {p}" for p in self.procedures]
        if not parts:
            return "Ничего относящегося к делу в памяти не найдено."
        return "\n".join(parts)


def _mmr(items: list[Recalled], ctx: Ctx, lam: float, limit: int) -> list[Recalled]:
    """Maximal Marginal Relevance: жадно берём по баллу, штрафуя похожесть на уже выбранное."""
    pool = list(items)
    chosen: list[Recalled] = []
    vecs: list[np.ndarray] = []
    while pool and len(chosen) < limit:
        best_i, best_val = 0, -1e9
        for i, it in enumerate(pool[:60]):
            v = ctx.index.get(it.unit_type, it.unit_id)
            red = max((float(v @ u) for u in vecs), default=0.0) if v is not None else 0.0
            if red > 0.95:
                continue  # почти дословный дубль
            val = lam * it.score - (1 - lam) * red
            if val > best_val:
                best_i, best_val = i, val
        if best_val == -1e9:
            break
        it = pool.pop(best_i)
        chosen.append(it)
        v = ctx.index.get(it.unit_type, it.unit_id)
        if v is not None:
            vecs.append(v)
    return chosen


def pack(ctx: Ctx, result: RecallResult, viewer: str, *, budgets: Budgets | None = None,
         intentions: list[str] | None = None, procedures: list[str] | None = None,
         exclude_refs: set[str] | None = None) -> WorkingMemory:
    """exclude_refs — уже показанное в этом разговоре (оно и так в истории; не повторяем)."""
    b = budgets or ctx.cfg.budgets
    wm = WorkingMemory(period_label=result.time_range.label if result.time_range else None)
    lam = ctx.cfg.mmr_lambda
    skip = exclude_refs or set()
    items = [r for r in result.items if r.ref not in skip]
    intentions = [i for i in intentions or [] if i.split("]")[0].lstrip("[") not in skip]
    procedures = [p for p in procedures or [] if p.split("]")[0].lstrip("[") not in skip]

    facts = _mmr([r for r in items if r.unit_type == "fact"], ctx, lam, 40)
    ents = [r for r in items if r.unit_type == "entity" and ":" in r.text]
    budget = b.facts
    for f in facts:
        cost = estimate_tokens(f.text) + 4
        if cost <= budget:
            wm.facts.append(f)
            budget -= cost
    for e in ents[:3]:
        cost = estimate_tokens(e.text) + 4
        if cost <= budget:
            wm.entities.append(e)
            budget -= cost

    # Эпизоды и дословные цитаты, сгруппированные по эпизоду.
    eps = [r for r in items if r.unit_type == "episode"]
    evs = [r for r in items if r.unit_type == "event"]
    by_ep: dict[int, list[Recalled]] = {}
    for ev in evs:
        by_ep.setdefault(ev.episode_id or -ev.unit_id, []).append(ev)
    groups: list[tuple[float, Recalled | None, list[Recalled]]] = []
    used_eps: set[int] = set()
    for ep in _mmr(eps, ctx, lam, 20):
        quotes = sorted(by_ep.get(ep.unit_id, []), key=lambda q: -q.score)[:2]
        top = max([ep.score] + [q.score for q in quotes])
        groups.append((top, ep, quotes))
        used_eps.add(ep.unit_id)
    loose = [ev for ev in _mmr(evs, ctx, lam, 30) if (ev.episode_id or -1) not in used_eps]
    for ev in loose:
        groups.append((ev.score, None, [ev]))
    groups.sort(key=lambda g: -g[0])
    budget = b.episodes
    for _, ep, quotes in groups:
        lines = ([ep.text] if ep else []) + [q.text for q in quotes]
        cost = sum(estimate_tokens(x) + 5 for x in lines)
        if cost > budget:
            # Попробуем без цитат.
            if ep is not None and estimate_tokens(ep.text) + 5 <= budget:
                wm.episodes.append((ep, []))
                budget -= estimate_tokens(ep.text) + 5
            continue
        wm.episodes.append((ep, quotes))
        budget -= cost

    budget = b.intentions
    for line in intentions:
        cost = estimate_tokens(line) + 2
        if cost <= budget:
            wm.intentions.append(line)
            budget -= cost
    budget = b.procedures
    for line in procedures:
        cost = estimate_tokens(line) + 2
        if cost <= budget:
            wm.procedures.append(line)
            budget -= cost
    wm.tokens = estimate_tokens(wm.render())
    return wm


__all__ = ["WorkingMemory", "pack", "fmt_date"]
