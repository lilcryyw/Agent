"""Инициатива — Джарвис сам замечает, когда пора действовать («проблема активации», 2026).

Три ступени, чтобы инициатива стоила копейки и не была навязчивой:
  1. Код: есть ли вообще повод (подошёл срок цели, событие устройства, близкая дата)? Нет — ничего не делаем.
  2. Haiku 5.5: стоит ли будить «сознание» сейчас (тихие часы, давно ли говорили, важно ли)?
  3. Opus: полноценный ход с поводом — может молча сделать, сказать или решить промолчать (⟦молчу⟧).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, Field

from cogmem.llm import StructuredLLM
from cogmem.memory import CognitiveMemory
from cogmem.retrieve.recall import fmt_date

log = logging.getLogger(__name__)

QUIET_FROM, QUIET_TO = 22, 8
WAKE_SYSTEM = """Ты — внутренний голос ассистента Джарвиса. Тебе показывают поводы, которые накопились
(цели, сроки, события устройств). Реши: стоит ли СЕЙЧАС разбудить основное мышление Джарвиса, чтобы
он что-то сделал или сказал человеку. Будь тактичен: не дёргай по мелочам, в тихие часы — только срочное,
не повторяй то, о чём недавно уже говорили. Но не упускай важное: сроки, обещания, здоровье, близкие."""


class WakeDecision(BaseModel):
    wake: bool = Field(description="Будить ли основное мышление сейчас.")
    urgent: bool = Field(description="Срочно ли (можно и в тихие часы).")
    focus: str = Field(description="Коротко: чем заняться и почему сейчас.")


@dataclass
class Initiative:
    memory: CognitiveMemory
    llm: StructuredLLM | None
    brain_stimulus: Callable[[str, str], object]   # (person_id, повод) → TurnResult
    notify: Callable[[str, str], None]

    def reasons(self, person_id: str) -> list[str]:
        """Ступень 1 — поводы без ИИ."""
        m = self.memory
        tz = m.person(person_id)["timezone"]
        out = [f"Цель [G{g.id}] «{g.title}»: пора вернуться (заметки: {g.notes[:200] or '—'})"
               for g in m.goals.due(person_id)]
        now = m.ctx.clock.now()
        for r in m.ctx.db.query(
            "SELECT text, ts FROM events WHERE person_id=? AND speaker='device' AND ts>? ORDER BY ts DESC LIMIT 5",
            (person_id, now - 3600)):
            out.append(f"Событие устройства {fmt_date(r['ts'], tz, True)}: {r['text']}")
        return out

    def last_contact_hours(self, person_id: str) -> float:
        ts = self.memory.ctx.db.scalar(
            "SELECT MAX(ts) FROM events WHERE person_id=? AND speaker IN ('user','assistant')", (person_id,))
        return (self.memory.ctx.clock.now() - ts) / 3600 if ts else 1e9

    def check(self, person_id: str) -> str | None:
        """Один «удар» инициативы. → текст, отправленный человеку, или None."""
        reasons = self.reasons(person_id)
        if not reasons:
            return None
        local = self.memory.local_now(person_id)
        quiet = local.hour >= QUIET_FROM or local.hour < QUIET_TO
        if self.llm is not None:
            d = self.llm.parse(
                system=WAKE_SYSTEM,
                user=(f"Сейчас {local:%Y-%m-%d %H:%M} ({'тихие часы' if quiet else 'день'}). "
                      f"С последнего разговора прошло {self.last_contact_hours(person_id):.1f} ч.\nПоводы:\n- "
                      + "\n- ".join(reasons)),
                schema=WakeDecision, purpose="initiative")
            if not d.wake or (quiet and not d.urgent):
                self._postpone(person_id)
                return None
            focus = d.focus
        else:
            if quiet:
                return None
            focus = "; ".join(reasons)
        res = self.brain_stimulus(person_id, focus + "\nПоводы:\n- " + "\n- ".join(reasons))
        self._postpone(person_id)
        text = getattr(res, "text", "")
        if text and not getattr(res, "silent", False):
            self.notify(person_id, text)
            return text
        return None

    def _postpone(self, person_id: str) -> None:
        """Цели с наступившим сроком, которые «сознание» не перенесло само, — отложить на сутки (без зацикливания)."""
        now = self.memory.ctx.clock.now()
        for g in self.memory.goals.due(person_id):
            self.memory.goals.update(g.id, next_check=now + 86400)
