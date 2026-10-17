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
    goals: list[str] = field(default_factory=list)
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
        return not (self.facts or self.episodes or self.entities or self.intentions or self.procedures
                    or self.goals)

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
        if self.goals:
            parts.append("Твои текущие цели (довести до конца):")
            parts += [f"- {g}" for g in self.goals]
        if self.intentions:
            parts.append("Намерения (не забыть):")
            parts += [f"- {i}" for i in self.intentions]
        if self.procedures:
            parts.append("Подходящие навыки и рецепты (что ты уже умеешь):")
            parts += [f"- {p}" for p in self.procedures]
        if not parts:
            return "Ничего относящегося к делу в памяти не найдено."
        return "\n".join(parts)


_MARKS = (" [часть сведений отсюда", " [возможно, устарело", " [внешний текст")


def _strip_marks(s: str) -> str:
    for mk in _MARKS:
        s = s.split(mk, 1)[0]
    return s


def _textkey(r: Recalled) -> str:
    """Ключ для отсева дословных повторов («Какая погода?» десять раз — одно воспоминание).

    Реплика — по тексту в «»; эпизод — по заголовку И сути (у разных разговоров заголовок
    «Звонок маме» бывает одинаковым — раньше оставался только один из них); факт — по
    утверждению без служебного хвоста «(со слов, записано …)» — иначе дубли с разными датами
    не узнавались.
    """
    from cogmem.text.ru import stems

    text = _strip_marks(r.text)
    if r.unit_type == "fact":
        body = text.rsplit(" (", 1)[0]
    elif r.unit_type == "episode" and "«" in text:
        body = text.split("«", 1)[1]
    elif "«" in text:
        body = text.split("«", 1)[1].rsplit("»", 1)[0]
    else:
        body = text
    return " ".join(stems(body))


def _title_key(ep: Recalled) -> str:
    from cogmem.text.ru import stems

    meta = ep.extra.get("meta") or {}
    title = meta.get("title")
    if title is None and "«" in ep.text:
        title = ep.text.split("«", 1)[1].split("»", 1)[0]
    return " ".join(stems(title or ""))


def _dedupe(items: list[Recalled]) -> list[Recalled]:
    seen: set[str] = set()
    out = []
    for it in items:  # items уже отсортированы по баллу — остаётся лучший из повторов
        k = _textkey(it)
        if k and k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def _dup01(ctx: Ctx, cos: np.ndarray) -> np.ndarray:
    """Похожесть двух ЗАПИСЕЙ → 0..1. Шкала «запись↔запись» у моделей своя: у e5 даже несвязанные
    записи близки (~0.83), и калибровка «запрос↔запись» давала почти одинаковый штраф всем подряд."""
    e = ctx.embedder
    lo = getattr(e, "dup_floor", e.sim_floor)
    hi = getattr(e, "dup_ceil", e.sim_ceil)
    return np.clip((cos - lo) / ((hi - lo) or 1.0), 0.0, 1.0)


def _mmr(items: list[Recalled], ctx: Ctx, lam: float, limit: int) -> list[Recalled]:
    """Maximal Marginal Relevance: жадно берём по баллу, штрафуя похожесть на уже выбранное.

    Дословные повторы уже отсеяны по тексту; здесь только штраф, не запрет:
    «живёт в Самаре» и «переехала в Тольятти» похожи, но оба нужны.
    """
    pool = _dedupe(list(items))[: limit + 60]
    if not pool or limit <= 0:
        return []
    n = len(pool)
    dim = ctx.index.dim
    V = np.zeros((n, dim), dtype=np.float32)
    has = np.zeros(n, dtype=bool)
    by_type: dict[str, list[int]] = {}
    for i, it in enumerate(pool):
        by_type.setdefault(it.unit_type, []).append(i)
    for t, idxs in by_type.items():
        pos = {pool[i].unit_id: i for i in idxs}
        found, mat = ctx.index.get_many(t, [pool[i].unit_id for i in idxs])
        for uid, row in zip(found, mat):
            V[pos[uid]] = row
            has[pos[uid]] = True
    scores = np.array([it.score for it in pool], dtype=np.float64)
    maxsim = np.full(n, -np.inf)
    taken = np.zeros(n, dtype=bool)
    chosen: list[Recalled] = []
    while len(chosen) < min(limit, n):
        red = np.where(has & np.isfinite(maxsim), _dup01(ctx, np.where(np.isfinite(maxsim), maxsim, 0.0)), 0.0)
        val = np.where(taken, -np.inf, lam * scores - (1 - lam) * red)
        i = int(np.argmax(val))
        if not np.isfinite(val[i]):
            break
        taken[i] = True
        chosen.append(pool[i])
        if has[i]:
            maxsim = np.maximum(maxsim, V @ V[i])
    return chosen


def pack(ctx: Ctx, result: RecallResult, viewer: str, *, budgets: Budgets | None = None,
         intentions: list[str] | None = None, procedures: list[str] | None = None,
         exclude_refs: set[str] | None = None, goals: list[str] | None = None) -> WorkingMemory:
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
        # Цитата, повторяющая строку эпизода (заголовок незакодированного эпизода = первая реплика), — лишняя.
        tk = _title_key(ep)
        quotes = sorted((q for q in by_ep.get(ep.unit_id, []) if not tk or _textkey(q) != tk),
                        key=lambda q: -q.score)[:2]
        top = max([ep.score] + [q.score for q in by_ep.get(ep.unit_id, [])])  # и выброшенная цитата тянет вверх
        groups.append((top, ep, quotes))
        used_eps.add(ep.unit_id)
    loose = [ev for ev in _mmr(evs, ctx, lam, 30) if (ev.episode_id or -1) not in used_eps]
    for ev in loose:
        groups.append((ev.score, None, [ev]))
    groups.sort(key=lambda g: -g[0])
    budget = b.episodes
    seen_keys: set[str] = set()
    for _, ep, quotes in groups:
        keys = {_textkey(x) for x in ([ep] if ep else []) + quotes}
        if keys and keys <= seen_keys:
            continue  # то же самое уже показано другим эпизодом
        seen_keys |= keys
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
    wm.goals = list(goals or [])  # цели показываем всегда — это «то, чем я сейчас занят»
    wm.tokens = estimate_tokens(wm.render())
    return wm


__all__ = ["WorkingMemory", "pack", "fmt_date"]
