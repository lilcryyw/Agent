"""Сборка Джарвиса и его фоновая жизнь: пульс памяти, ночной «сон», напоминания, инициатива."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from cogmem.consolidate.encoder import EpisodeEncoder
from cogmem.consolidate.sleep import Sleep
from cogmem.llm import AnthropicStructuredLLM, StructuredLLM
from cogmem.memory import CognitiveMemory
from jarvis.brain.agent import Brain
from jarvis.brain.tools import ToolBox
from jarvis.config import Settings
from jarvis.devices import DeviceHub
from jarvis.devices.gateway import Gateway
from jarvis.keys import KeyRing
from jarvis.mind.initiative import Initiative
from jarvis.secrets import Vault
from jarvis.skills import SkillBank
from jarvis.workshop import Workshop, from_env as workshop_from_env

log = logging.getLogger(__name__)

Notifier = Callable[[str, str], None]  # (person_id, текст)
INITIATIVE_EVERY_S = 20 * 60


class Jarvis:
    def __init__(self, settings: Settings | None = None, *, client=None, embedder=None, clock=None,
                 workshop: Workshop | None = None, subconscious: StructuredLLM | None = None):
        self.s = settings or Settings.from_env()
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        data = Path(self.s.db_path).parent if self.s.db_path != ":memory:" else Path("data")
        m = self.memory = CognitiveMemory(self.s.db_path, embedder=embedder, clock=clock)
        m.llm = subconscious or AnthropicStructuredLLM(client, model=self.s.subconscious_model,
                                                       effort=self.s.subconscious_effort, usage_sink=m.record_usage)
        m.encoder = EpisodeEncoder(m.ctx, m.llm, m.entities, m.facts, m.episodes, m.retriever)
        m.sleeper = Sleep(m.ctx, m.llm, m.facts, m.core, m.intentions)
        m.add_person(self.s.owner_id, self.s.owner_name, role="owner", timezone=self.s.owner_timezone)
        for pid, (name, role, tz) in self.s.people.items():
            m.add_person(pid, name, role=role, timezone=tz)

        self.workshop = workshop or workshop_from_env()
        self.skills = SkillBank(m, self.workshop, data / "skills")
        self.keys = KeyRing(m)
        self.devices = DeviceHub()
        self.gateway = Gateway(m, self.devices, port=self.s.devices_port) if self.s.devices_port else None
        self.vault = Vault(data / "vault.bin")
        self.tools = ToolBox(m, workshop=self.workshop, skills=self.skills, keys=self.keys, devices=self.devices,
                             vault=self.vault, pairing=self.gateway.create_pairing if self.gateway else None,
                             devices_url=self.s.devices_url)
        self.brain = Brain(m, self.s, client, self.tools)
        self._notifiers: list[Notifier] = []
        self.initiative = Initiative(m, m.llm, self.brain.handle_stimulus, self._notify)
        self.voice = self._make_voice(data)
        self.api = None
        self._stop = threading.Event()
        self._last_sleep: dict[str, str] = {}
        self._last_initiative = 0.0

    @staticmethod
    def _make_voice(data: Path):
        try:
            import onnx_asr  # noqa: F401
            import piper  # noqa: F401
        except Exception:  # noqa: BLE001 — голосовые зависимости не установлены
            return None
        from jarvis.voice import Voice

        return Voice(data / "models")

    def on_notify(self, fn: Notifier) -> None:
        self._notifiers.append(fn)

    def _notify(self, person_id: str, text: str) -> None:
        for fn in self._notifiers:
            try:
                fn(person_id, text)
            except Exception:  # noqa: BLE001
                log.exception("не удалось отправить сообщение")

    def ask(self, person_id: str, text: str, **kw) -> str:
        return self.brain.handle(person_id, text, **kw).text

    # --- фон ---
    def pulse(self) -> None:
        """Один удар пульса: память, напоминания, сон по расписанию, инициатива."""
        m = self.memory
        try:
            m.tick()
        except Exception:  # noqa: BLE001
            log.exception("ошибка пульса памяти")
        for it in m.intentions.due():
            # Напоминание проходит через мышление: Джарвис сам решает, как и что сказать (и сделать).
            m.intentions.set_status(it.id, "fired", actor="runtime")
            try:
                res = self.brain.handle_stimulus(it.person_id, f"Наступил срок: {it.action_text} [I{it.id}]")
                if res.text and not res.silent:
                    self._notify(it.person_id, res.text)
            except Exception:  # noqa: BLE001 — нет сети/ключа: напомнить хотя бы дословно
                log.exception("мышление недоступно — напоминаю дословно")
                self._notify(it.person_id, f"Напоминание: {it.action_text}")
        now = m.ctx.clock.now()
        run_initiative = now - self._last_initiative >= INITIATIVE_EVERY_S
        if run_initiative:
            self._last_initiative = now
        for r in m.ctx.db.query("SELECT id, timezone FROM persons"):
            local = datetime.fromtimestamp(now, ZoneInfo(r["timezone"]))
            key = local.date().isoformat()
            if local.hour == self.s.sleep_hour_local and self._last_sleep.get(r["id"]) != key:
                self._last_sleep[r["id"]] = key
                try:
                    log.info("сон %s: %s", r["id"], m.sleep(r["id"]))
                except Exception:  # noqa: BLE001
                    log.exception("ошибка сна для %s", r["id"])
            if run_initiative:
                try:
                    self.initiative.check(r["id"])
                except Exception:  # noqa: BLE001
                    log.exception("ошибка инициативы для %s", r["id"])

    def start_background(self, interval_s: float = 60.0) -> threading.Thread:
        if self.gateway is not None and self.gateway.loop is None:
            self.gateway.start()
            log.info("шлюз устройств слушает порт %s", self.gateway.port)
        if self.s.api_port and self.api is None:
            from jarvis.channels.http_api import Api

            self.api = Api(self, port=self.s.api_port, voice=self.voice)
            self.api.start()
            log.info("HTTP-API слушает порт %s", self.api.port)

        def loop():
            while not self._stop.wait(interval_s):
                self.pulse()

        t = threading.Thread(target=loop, name="jarvis-pulse", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
