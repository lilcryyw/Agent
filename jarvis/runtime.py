"""Сборка Джарвиса и фоновая жизнь: пульс памяти, ночной «сон», срабатывание напоминаний."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from cogmem.llm import AnthropicStructuredLLM
from cogmem.memory import CognitiveMemory
from jarvis.brain.agent import Brain
from jarvis.config import Settings

log = logging.getLogger(__name__)

Notifier = Callable[[str, str], None]  # (person_id, текст)


class Jarvis:
    def __init__(self, settings: Settings | None = None, *, client=None, embedder=None, clock=None):
        self.s = settings or Settings.from_env()
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.memory = CognitiveMemory(self.s.db_path, embedder=embedder, clock=clock)
        self.memory.llm = AnthropicStructuredLLM(client, model=self.s.subconscious_model,
                                                 effort=self.s.subconscious_effort,
                                                 usage_sink=self.memory.record_usage)
        # Пересоздаём подсознание с моделью.
        from cogmem.consolidate.encoder import EpisodeEncoder
        from cogmem.consolidate.sleep import Sleep

        m = self.memory
        m.encoder = EpisodeEncoder(m.ctx, m.llm, m.entities, m.facts, m.episodes, m.retriever)
        m.sleeper = Sleep(m.ctx, m.llm, m.facts, m.core, m.intentions)
        m.add_person(self.s.owner_id, self.s.owner_name, role="owner", timezone=self.s.owner_timezone)
        for pid, (name, role, tz) in self.s.people.items():
            m.add_person(pid, name, role=role, timezone=tz)
        self.brain = Brain(self.memory, self.s, client)
        self._stop = threading.Event()
        self._notifiers: list[Notifier] = []
        self._last_sleep: dict[str, str] = {}

    def on_notify(self, fn: Notifier) -> None:
        self._notifiers.append(fn)

    def ask(self, person_id: str, text: str, **kw) -> str:
        return self.brain.handle(person_id, text, **kw).text

    # --- фон ---
    def pulse(self) -> None:
        """Один «удар пульса»: закрыть затихшие эпизоды, закодировать, напоминания, сон по расписанию."""
        try:
            self.memory.tick()
        except Exception:  # noqa: BLE001
            log.exception("ошибка пульса памяти")
        for it in self.memory.intentions.due():
            text = f"Напоминание: {it.action_text}"
            for fn in self._notifiers:
                try:
                    fn(it.person_id, text)
                except Exception:  # noqa: BLE001
                    log.exception("не удалось отправить напоминание")
            self.memory.intentions.set_status(it.id, "fired", actor="runtime")
        for r in self.memory.ctx.db.query("SELECT id, timezone FROM persons"):
            local = datetime.fromtimestamp(self.memory.ctx.clock.now(), ZoneInfo(r["timezone"]))
            key = local.date().isoformat()
            if local.hour == self.s.sleep_hour_local and self._last_sleep.get(r["id"]) != key:
                self._last_sleep[r["id"]] = key
                try:
                    rep = self.memory.sleep(r["id"])
                    log.info("сон %s: %s", r["id"], rep)
                except Exception:  # noqa: BLE001
                    log.exception("ошибка сна для %s", r["id"])

    def start_background(self, interval_s: float = 60.0) -> threading.Thread:
        def loop():
            while not self._stop.wait(interval_s):
                self.pulse()

        t = threading.Thread(target=loop, name="jarvis-pulse", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
