"""Голосовой режим «всегда слышу»: Джарвис слушает, что происходит вокруг (урок, разговор), понимает тему
и сам решает, когда тихо подсказать в наушник.

Как у человека, три слоя памяти о услышанном:
  · сенсорный буфер — дословно, только последние 30 минут (таблица ambient_lines, старое стирается само);
  · «внутренний голос» (Haiku, копейки) — на каждую новую порцию речи решает: нужно ли вмешаться сейчас;
  · тема и главное — раз в ~10 минут и в конце сжимаются в факт и остаются навсегда.
Дорогое «сознание» (Sonnet) включается, только когда к Джарвису обратились или «внутренний голос» решил,
что подсказка нужна.
"""

from __future__ import annotations

import logging
import re
import time

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
KEEP_S = 30 * 60           # дословное — не дольше 30 минут
GATE_EVERY_S = 6           # «внутренний голос» — не чаще раза в 6 секунд
TOPIC_EVERY_S = 10 * 60    # сжатие темы в долгую память
ADDRESSED = re.compile(r"\bджарвис\w*", re.I)

GATE_SYSTEM = """Ты — внутренний голос Джарвиса. Он тихо слушает, что происходит рядом с человеком (урок, разговор,
встреча), через наушник человека. Тебе дают последние минуты услышанного. «я» — сам человек, «рядом» — другие.
Реши: нужно ли Джарвису СЕЙЧАС что-то сказать человеку в наушник. Да — если человеку задали вопрос или к нему
обратились и подсказка поможет, если прозвучало важное, что он может упустить (задание, срок, дата), если он
сам ошибся в факте. Нет — во всех остальных случаях: не комментируй, не пересказывай, не мешай слушать."""

TOPIC_SYSTEM = """Сожми услышанное в долгую память. Кратко: о чём шла речь (тема урока/разговора), ключевые понятия
и факты, задания и сроки. Без воды. Если ничего содержательного не было — worth=false."""


class Gate(BaseModel):
    act: bool = Field(description="Нужно ли Джарвису сейчас сказать что-то человеку.")
    reason: str = Field(description="Если да — что именно нужно (одной фразой).")


class Topic(BaseModel):
    worth: bool = Field(description="Было ли что-то содержательное.")
    topic: str = Field(description="Тема одной строкой.")
    summary: str = Field(description="Главное: понятия, факты, задания, сроки — 1–4 предложения.")


class Ambient:
    def __init__(self, jarvis, person: str):
        self.j, self.person = jarvis, person
        self.db = jarvis.memory.ctx.db
        self.db.execute("CREATE TABLE IF NOT EXISTS ambient_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "ts REAL NOT NULL, person TEXT NOT NULL, who TEXT NOT NULL, text TEXT NOT NULL)")
        self._gate_at = 0.0
        self._new = 0
        self._topic_from = time.time()

    # --- сенсорный буфер ---
    def add(self, who: str, text: str) -> None:
        now = time.time()
        self.db.execute("INSERT INTO ambient_lines(ts, person, who, text) VALUES (?,?,?,?)",
                        (now, self.person, who, text[:1000]))
        self.db.execute("DELETE FROM ambient_lines WHERE ts < ?", (now - KEEP_S,))
        self._new += 1

    def lines(self, minutes: float = 5, limit: int = 60) -> list[str]:
        rows = self.db.query("SELECT ts, who, text FROM ambient_lines WHERE person=? AND ts>=? ORDER BY id DESC LIMIT ?",
                             (self.person, time.time() - minutes * 60, limit))
        return [f"{time.strftime('%H:%M', time.localtime(r['ts']))} {r['who']}: {r['text']}" for r in reversed(rows)]

    def context(self) -> str:
        ls = self.lines(5, 40)
        return ("Слышу вокруг (последние минуты, «я» — человек, «рядом» — другие):\n" + "\n".join(ls)) if ls else ""

    # --- «внутренний голос» ---
    def gate(self) -> str | None:
        """Нужно ли вмешаться. → что сказать (повод для «сознания») или None. Дёшево и не чаще раза в 6 с."""
        llm = getattr(self.j.memory, "llm", None)
        if llm is None or not self._new or time.time() - self._gate_at < GATE_EVERY_S:
            return None
        self._gate_at, self._new = time.time(), 0
        ls = self.lines(3, 30)
        if not ls:
            return None
        d = llm.parse(system=GATE_SYSTEM, user="\n".join(ls), schema=Gate, purpose="ambient_gate", max_tokens=200)
        if not d.act:
            return None
        return d.reason.strip() or "нужна подсказка"

    # --- долгая память о теме ---
    def maybe_consolidate(self, force: bool = False) -> None:
        if not force and time.time() - self._topic_from < TOPIC_EVERY_S:
            return
        since = self._topic_from
        self._topic_from = time.time()
        rows = self.db.query("SELECT who, text FROM ambient_lines WHERE person=? AND ts>=? ORDER BY id",
                             (self.person, since))
        llm = getattr(self.j.memory, "llm", None)
        if llm is None or len(rows) < 6:
            return
        text = "\n".join(f"{r['who']}: {r['text']}" for r in rows)[-12000:]
        try:
            t = llm.parse(system=TOPIC_SYSTEM, user=text, schema=Topic, purpose="ambient_topic", max_tokens=500)
            if t.worth:
                day = time.strftime("%d.%m.%Y")
                self.j.memory.remember(self.person, f"Слышал рядом ({day}): {t.topic}. {t.summary}", importance=0.6)
        except Exception:  # noqa: BLE001
            log.exception("не удалось запомнить тему")


def addressed(text: str) -> bool:
    return bool(ADDRESSED.search(text))


def purge(memory) -> None:
    """Стереть дословное старше 30 минут (вызывается из пульса)."""
    try:
        memory.ctx.db.execute("DELETE FROM ambient_lines WHERE ts < ?", (time.time() - KEEP_S,))
    except Exception:  # noqa: BLE001 — таблицы ещё нет
        pass
