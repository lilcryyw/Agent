"""Сборка Джарвиса и его фоновая жизнь: пульс памяти, ночной «сон», напоминания, инициатива."""

from __future__ import annotations

import logging
import os
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


def _valid_tz(tz: str) -> str:
    try:
        ZoneInfo(tz)
        return tz
    except Exception:  # noqa: BLE001
        log.warning("неизвестный часовой пояс %r — использую Europe/Moscow", tz)
        return "Europe/Moscow"
INITIATIVE_EVERY_S = 20 * 60


class Jarvis:
    def __init__(self, settings: Settings | None = None, *, client=None, embedder=None, clock=None,
                 workshop: Workshop | None = None, subconscious: StructuredLLM | None = None):
        self.s = settings or Settings.from_env()
        if client is None:
            import anthropic

            client = anthropic.Anthropic(max_retries=4)  # перегрузка/сеть: повторить, а не молчать
        data = Path(self.s.db_path).parent if self.s.db_path != ":memory:" else Path("data")
        # Модели речи можно держать вне папки данных (в образе), чтобы не копировать их в резервную копию.
        self.models_dir = Path(os.environ.get("JARVIS_MODELS_DIR") or data / "models")
        m = self.memory = CognitiveMemory(self.s.db_path, embedder=embedder, clock=clock)
        m.llm = subconscious or AnthropicStructuredLLM(client, model=self.s.subconscious_model,
                                                       effort=self.s.subconscious_effort, usage_sink=m.record_usage)
        m.encoder = EpisodeEncoder(m.ctx, m.llm, m.entities, m.facts, m.episodes, m.retriever)
        m.sleeper = Sleep(m.ctx, m.llm, m.facts, m.core, m.intentions)
        m.add_person(self.s.owner_id, self.s.owner_name, role="owner", timezone=self.s.owner_timezone)
        for pid, (name, role, tz) in self.s.people.items():
            m.add_person(pid, name, role=role, timezone=_valid_tz(tz))

        self.workshop = workshop or workshop_from_env()
        self.skills = SkillBank(m, self.workshop, data / "skills")
        self.keys = KeyRing(m)
        self.devices = DeviceHub()
        self.voice = self._make_voice(self.models_dir)
        self.gateway = Gateway(m, self.devices, port=self.s.devices_port, on_utterance=self._device_utterance,
                               tts=(lambda t: self.voice.speak(t, "wav")[0]) if self.voice else None) \
            if self.s.devices_port else None
        self.vault = Vault(data / "vault.bin")
        self.tools = ToolBox(m, workshop=self.workshop, skills=self.skills, keys=self.keys, devices=self.devices,
                             vault=self.vault, pairing=self.gateway.create_pairing if self.gateway else None,
                             devices_url=self._devices_urls(), domains=[d for d in (self.s.public_domain,
                                                                                     self.s.relay_domain) if d])
        self.brain = Brain(m, self.s, client, self.tools)
        # Органы, которым нужен «мир»: фоновые задачи будят мысль, «tell» говорит людям.
        if hasattr(self.tools, "on_stimulus"):
            self.tools.on_stimulus = self._background_stimulus
        if hasattr(self.tools, "on_tell"):
            self.tools.on_tell = self._tell
        self._notifiers: list[Notifier] = []
        self.initiative = Initiative(m, m.llm, self.brain.handle_stimulus, self._notify)
        self.speakers = self._make_speakers(self.models_dir)
        self.api = None
        self.call = None
        if self.gateway is not None:
            # Сказанное Джарвисом по своей инициативе звучит и на устройствах с динамиком.
            self.on_notify(lambda person, text: self.gateway.say(person, text))
        self._stop = threading.Event()
        self._last_sleep: dict[str, str] = {}
        self._last_initiative = 0.0

    def _make_speakers(self, models: Path):
        if self.voice is None:
            return None
        try:
            import sherpa_onnx  # noqa: F401
        except Exception:  # noqa: BLE001
            return None
        from jarvis.voice.speakers import Speakers

        return Speakers(self.memory, models)

    def enroll_voice(self, person_id: str, pcm: bytes) -> None:
        """Пассивная запись голоса из личного канала (фоном, ошибки не мешают разговору)."""
        if self.speakers is None:
            return

        def job():
            try:
                self.speakers.enroll(person_id, pcm)
            except Exception:  # noqa: BLE001
                log.exception("не удалось записать голосовой отпечаток")

        threading.Thread(target=job, daemon=True).start()

    def who_speaks(self, owner: str, pcm: bytes) -> tuple[str, str | None]:
        """Кто говорит на устройстве владельца owner → (person_id, пометка для контекста)."""
        if self.speakers is None:
            return owner, None
        try:
            m = self.speakers.identify(pcm)
        except Exception:  # noqa: BLE001
            log.exception("узнавание голоса не удалось")
            return owner, None
        if m.person_id and self.memory.person(m.person_id):
            if m.person_id == owner:
                return owner, None
            name = self.memory.person(m.person_id)["name"]
            return m.person_id, f"Говорит {name} (узнан(а) по голосу) с чужого устройства."
        if self.speakers.profiles():
            owner_name = self.memory.person(owner)["name"]
            return owner, (f"Голос не узнан уверенно — возможно, говорит не {owner_name}, а гость. "
                           "Не раскрывай личное, пока не убедишься, кто это.")
        return owner, None

    def _device_utterance(self, owner: str, device_id: str, audio: bytes) -> tuple[str, str]:
        if self.voice is None:
            return "", "Голос на сервере не настроен."
        pcm = self.voice.pcm16k(audio)
        heard = self.voice.transcribe(audio, pcm=pcm)
        if not heard:
            return "", ""
        person, note = self.who_speaks(owner, pcm)
        from jarvis.brain.agent import is_stop

        if is_stop(heard):  # «Джарвис, стоп» — сразу, не дожидаясь текущего хода
            return heard, "Остановил." if self.brain.cancel(person) else "Хорошо."
        return heard, self.brain.handle(person, heard, channel="voice", device=device_id, note=note).text

    def _devices_urls(self) -> str:
        urls = [self.s.devices_url] if self.s.devices_url else []
        if self.s.relay_domain:
            urls.append(f"wss://{self.s.relay_domain}/devices")
        return ",".join(urls)

    @staticmethod
    def _make_voice(models: Path):
        try:
            import onnx_asr  # noqa: F401
            import piper  # noqa: F401
        except Exception:  # noqa: BLE001 — голосовые зависимости не установлены
            return None
        from jarvis.voice import Voice

        return Voice(models)

    def on_notify(self, fn: Notifier) -> None:
        self._notifiers.append(fn)

    def _notify(self, person_id: str, text: str) -> None:
        for fn in self._notifiers:
            try:
                fn(person_id, text)
            except Exception:  # noqa: BLE001
                log.exception("не удалось отправить сообщение")

    def _background_stimulus(self, person_id: str, reason: str) -> None:
        """Фоновая задача закончилась (или другое внутреннее событие органа): подумать и, если нужно, сказать."""
        def job():
            try:
                res = self.brain.handle_stimulus(person_id, reason)
                if res.text and not res.silent:
                    self._notify(person_id, res.text)
            except Exception:  # noqa: BLE001
                log.exception("ошибка обработки фонового события")

        threading.Thread(target=job, name="jarvis-stimulus", daemon=True).start()

    def _tell(self, person_id: str, text: str, device: str | None = None) -> None:
        """Сказать человеку (во все его каналы; на конкретное устройство — если указано)."""
        if device and self.gateway is not None:
            try:
                self.gateway.say(person_id, text, device=device)
                return
            except TypeError:  # старый шлюз без выбора устройства
                pass
        self._notify(person_id, text)

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
        try:
            due = m.intentions.due()
        except Exception:  # noqa: BLE001
            log.exception("не удалось прочитать напоминания")
            due = []
        for it in due:
            # Напоминание проходит через мышление: Джарвис сам решает, как и что сказать (и сделать).
            try:
                if hasattr(m.intentions, "fire"):
                    m.intentions.fire(it.id)  # повторяющееся — переносится на следующий раз
                else:
                    m.intentions.set_status(it.id, "fired", actor="runtime")
            except Exception:  # noqa: BLE001
                log.exception("не удалось отметить напоминание I%s", it.id)
                continue
            verbatim = f"Напоминание: {it.action_text}"
            try:
                res = self.brain.handle_stimulus(it.person_id, f"Наступил срок: {it.action_text} [I{it.id}]")
                if res.over_budget:
                    self._notify(it.person_id, verbatim)  # без «мысли», но напоминание важнее бюджета
                elif res.text and not res.silent:
                    self._notify(it.person_id, res.text)
            except Exception:  # noqa: BLE001 — нет сети/ключа: напомнить хотя бы дословно
                log.exception("мышление недоступно — напоминаю дословно")
                self._notify(it.person_id, verbatim)
        now = m.ctx.clock.now()
        run_initiative = now - self._last_initiative >= INITIATIVE_EVERY_S
        if run_initiative:
            self._last_initiative = now
        for r in m.ctx.db.query("SELECT id, timezone FROM persons"):
            local = datetime.fromtimestamp(now, ZoneInfo(_valid_tz(r["timezone"])))
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
        if self.s.call_port and self.voice is not None and self.call is None:
            from jarvis.channels.call import CallServer

            self.call = CallServer(self, port=self.s.call_port, voice=self.voice, models_dir=self.models_dir)
            self.call.start()
            log.info("живой разговор слушает порт %s", self.call.port)

        def loop():
            while not self._stop.wait(interval_s):
                try:
                    self.pulse()
                except Exception:  # noqa: BLE001 — пульс не должен умирать от одной ошибки
                    log.exception("ошибка пульса")

        t = threading.Thread(target=loop, name="jarvis-pulse", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
