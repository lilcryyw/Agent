"""«Сознание» Джарвиса: один ход разговора с Claude поверх когнитивной памяти.

Порядок частей запроса подобран под кэш (кэш = совпадение начала запроса байт в байт):
  [инструменты — неизменны] [системный промпт — неизменен, кэш 1 ч] [история сессии — только дописывается]
  [новый ход: <о_собеседнике> (в начале сессии) + <контекст> + <память> + реплика]
История никогда не редактируется задним числом — иначе ломаются кэш и «мышление» модели.
Память кладётся в ход человека (а не в системные сообщения): это данные без прав оператора
и они сохраняются при цепочке вызовов инструментов. Повторно показанное не дублируется.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from cogmem.memory import CognitiveMemory
from cogmem.types import Observation
from jarvis.brain.prompts import SILENCE, SYSTEM_PROMPT
from jarvis.brain.tools import ToolBox
from jarvis.config import Settings

log = logging.getLogger(__name__)

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]
USED_RE = re.compile(r"⟦\s*исп\s*:([^⟧]*)⟧")
REF_RE = re.compile(r"\[([FEMNPIGK]\d+)\]")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CONTEXT_BETA = "context-management-2025-06-27"
MAX_STEPS = 30  # свобода искать способ: попытки, код, навыки — но не бесконечно


@dataclass
class Session:
    person_id: str
    episode_id: int
    messages: list[dict] = field(default_factory=list)
    shown: set[str] = field(default_factory=set)
    context_tokens: int = 0


@dataclass
class TurnResult:
    text: str
    used: list[str]
    shown: list[str]
    tool_calls: list[str]
    cost_usd: float
    usage: dict[str, int]
    new_session: bool
    silent: bool = False  # внутренний повод: Джарвис решил не беспокоить


def human_now(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]}, {dt.day} {MONTHS_GEN[dt.month - 1]} {dt.year}, {dt:%H:%M}"


def split_used(text: str) -> tuple[str, list[str]]:
    """Отделить служебную строку ⟦исп: …⟧ от ответа."""
    refs: list[str] = []
    for m in USED_RE.finditer(text):
        refs += [r.strip().upper() for r in m.group(1).split(",") if r.strip() and r.strip() not in {"—", "-"}]
    clean = USED_RE.sub("", text).rstrip()
    return clean, refs


class Brain:
    def __init__(self, memory: CognitiveMemory, settings: Settings, client: Any, tools: ToolBox):
        self.memory = memory
        self.s = settings
        self.client = client
        self.tools = tools
        self.sessions: dict[str, Session] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._fallbacks_ok = settings.use_fallbacks
        self._ctx_edit_ok = True

    # ------------------------------------------------------------------ API
    def _call(self, messages: list[dict], on_text: Callable[[str], None] | None = None,
              effort: str | None = None) -> Any:
        """Один запрос к Claude. on_text — получать текст по мере генерации (живой голосовой разговор)."""
        kwargs: dict[str, Any] = dict(
            model=self.s.brain_model,
            max_tokens=self.s.max_tokens,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            tools=self.tools.definitions(web=self.s.use_web_search),
            messages=messages,
            output_config={"effort": effort or self.s.brain_effort},
        )
        # Необязательные возможности API: если аккаунт/платформа их не поддерживает — отключаем по одной.
        while True:
            extra: dict[str, Any] = {"cache_control": {"type": "ephemeral"}}  # автокэш хвоста разговора
            betas = []
            if self._fallbacks_ok:
                extra["fallbacks"] = "default"  # отказ фильтров → повтор на подходящей модели
                betas.append(FALLBACK_BETA)
            if self._ctx_edit_ok:
                # Старые результаты инструментов (снимки экрана, длинные выводы) убираются сервером.
                extra["context_management"] = {"edits": [{"type": "clear_tool_uses_20250919"}]}
                betas.append(CONTEXT_BETA)
            api = self.client.beta.messages if betas else self.client.messages
            more: dict[str, Any] = {"betas": betas} if betas else {}
            try:
                if on_text is None:
                    return api.create(**kwargs, **more, extra_body=extra)
                with api.stream(**kwargs, **more, extra_body=extra) as stream:
                    for chunk in stream.text_stream:
                        on_text(chunk)
                    final = stream.get_final_message()
                on_text("\n")  # конец шага: недосказанное предложение можно произносить
                return final
            except Exception as exc:
                import anthropic

                if not isinstance(exc, anthropic.BadRequestError):
                    raise
                text = str(exc).lower()
                if self._fallbacks_ok and "fallback" in text:
                    self._fallbacks_ok = False
                elif self._ctx_edit_ok and ("context" in text or "clear_tool" in text):
                    self._ctx_edit_ok = False
                else:
                    raise
                log.warning("возможность API недоступна (%s) — отключаю и повторяю", exc)

    # ------------------------------------------------------------------ ход
    def _lock(self, person_id: str) -> threading.Lock:
        return self._locks.setdefault(person_id, threading.Lock())

    def handle(self, person_id: str, text: str, *, channel: str = "text", device: str | None = None,
               note: str | None = None, on_text: Callable[[str], None] | None = None,
               effort: str | None = None) -> TurnResult:
        """Реплика человека. note — служебная пометка для контекста (например, «голос не узнан уверенно»).
        on_text — получать ответ кусочками по мере генерации (включая служебные пометки ⟦…⟧ — их убирает
        получатель). effort — своя глубина размышлений для хода (в живом разговоре важнее скорость)."""
        with self._lock(person_id):
            return self._turn(person_id, text, origin="user", channel=channel, device=device, note=note,
                              on_text=on_text, effort=effort)

    def handle_stimulus(self, person_id: str, reason: str) -> TurnResult:
        """Внутренний повод (цель, срок, событие): Джарвис сам решает, действовать ли и говорить ли."""
        with self._lock(person_id):
            return self._turn(person_id, reason, origin="internal", channel="internal", device=None)

    def _over_budget(self) -> bool:
        now = self.memory.local_now(self.s.owner_id) if self.memory.person(self.s.owner_id) else datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        return self.memory.spend_usd(month_start) >= self.s.monthly_budget_usd

    def _turn(self, person_id: str, text: str, *, origin: str, channel: str, device: str | None,
              note: str | None = None, on_text: Callable[[str], None] | None = None,
              effort: str | None = None) -> TurnResult:
        mem = self.memory
        if origin == "user":
            obs = mem.observe(Observation(person_id, text, speaker="user", channel=channel, device=device))
        else:
            obs = mem.observe(Observation(person_id, f"Внутренний повод: {text}", speaker="system", kind="stimulus",
                                          channel=channel))
        sess = self.sessions.get(person_id)
        restarted_mid_episode = False
        new_session = sess is None or sess.episode_id != obs.episode_id or \
            sess.context_tokens > self.s.session_max_tokens
        if new_session:
            restarted_mid_episode = sess is not None and sess.episode_id == obs.episode_id
            sess = Session(person_id, obs.episode_id)
            self.sessions[person_id] = sess

        if self._over_budget():
            if origin != "user":
                return TurnResult("", [], [], [], 0.0, {}, new_session, True)
            msg = (f"Месячный бюджет на ИИ (${self.s.monthly_budget_usd:.0f}) исчерпан. "
                   "Увеличь JARVIS_MONTHLY_BUDGET_USD, если нужно продолжить.")
            if on_text:
                on_text(msg)
            mem.observe(Observation(person_id, msg, speaker="assistant", channel=channel, device=device))
            return TurnResult(msg, [], [], [], 0.0, {}, new_session)

        # Рабочая память под эту реплику (текущий разговор и так в истории — его не ищем).
        ctx = {"channel": channel, "device": device}
        wm, res = mem.working_memory(person_id, text, context=ctx,
                                     exclude_episode_id=None if restarted_mid_episode else obs.episode_id,
                                     exclude_refs=sess.shown)
        shown_now = wm.shown_refs() + [r for r in REF_RE.findall("\n".join(wm.intentions + wm.procedures))]
        now = mem.local_now(person_id)
        blocks: list[dict] = []
        if new_session:
            blocks.append({"type": "text", "text": f"<о_собеседнике>\n{mem.core_profile(person_id)}\n</о_собеседнике>"})
            shown_now += REF_RE.findall(mem.core.get(person_id))
            if restarted_mid_episode:
                recent = mem.episodes.events_of(obs.episode_id)[-12:-1]
                if recent:
                    lines = [f"{'человек' if e['speaker'] == 'user' else 'Джарвис'}: {e['text']}" for e in recent]
                    blocks.append({"type": "text", "text": "<недавний_разговор>\n" + "\n".join(lines)
                                   + "\n</недавний_разговор>"})
        where = f"Канал: {channel}." + (f" Устройство: {device}." if device else "")
        keys = self.tools.keys.lines(person_id)
        trust = self.tools.keys.trust_suggestions(person_id)
        state = ("Ключи от замка: " + ("; ".join(keys) if keys else "нет") + "."
                 + (" Доверие: " + "; ".join(trust) + "." if trust else ""))
        if note:
            state += f" {note}"
        blocks.append({"type": "text", "text": f"<контекст>Сейчас: {human_now(now)} ({now.tzinfo}). {where} {state}"
                                              f"</контекст>\n<память>\n{wm.render()}\n</память>"})
        blocks.append({"type": "text", "text": text if origin == "user"
                       else f"<внутренний_повод>{text}</внутренний_повод>"})
        sess.messages.append({"role": "user", "content": blocks})
        sess.shown.update(shown_now)

        tool_calls: list[str] = []
        total: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                                 "cache_creation_input_tokens": 0}
        cost_before = mem.spend_usd()
        final_text = ""
        for _ in range(MAX_STEPS):
            resp = self._call(sess.messages, on_text, effort)
            mem.record_usage(self.s.brain_model, "brain", resp.usage)
            for k in total:
                total[k] += getattr(resp.usage, k, 0) or 0
            sess.context_tokens = sum(getattr(resp.usage, k, 0) or 0 for k in
                                      ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            sess.messages.append({"role": "assistant", "content": resp.content})
            final_text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            if resp.stop_reason == "tool_use" and mem.spend_usd() - cost_before > self.s.turn_budget_usd:
                # Защита от «увлёкся»: дальше без разрешения человека не тратим.
                final_text = (f"Я потратил на эту задачу уже больше ${self.s.turn_budget_usd:.2f} и ещё не закончил. "
                              "Продолжать?")
                if on_text:
                    on_text(final_text)
                sess.messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b.id, "content": "Остановлено: лимит стоимости хода.",
                     "is_error": True} for b in resp.content if getattr(b, "type", "") == "tool_use"]})
                break
            if resp.stop_reason == "tool_use":
                results = []
                for b in resp.content:
                    if getattr(b, "type", "") != "tool_use":
                        continue
                    tool_calls.append(b.name)
                    out, is_err = self.tools.run(person_id, b.name, dict(b.input), origin=origin,
                                                 source_event_id=obs.event_id if origin == "user" else None)
                    refs = REF_RE.findall(out) if isinstance(out, str) else []
                    sess.shown.update(refs)
                    shown_now += refs
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": is_err})
                sess.messages.append({"role": "user", "content": results})
                continue
            if resp.stop_reason == "pause_turn":
                continue  # серверный инструмент (поиск) попросил продолжить
            if resp.stop_reason == "refusal":
                final_text = "Извини, с этим я помочь не могу."
                if on_text:
                    on_text(final_text)
            break

        clean, used = split_used(final_text)
        mem.feedback(shown_now, used)
        silent = origin == "internal" and (not clean or SILENCE in clean)
        if silent:
            return TurnResult("", used, shown_now, tool_calls, mem.spend_usd() - cost_before, total, new_session, True)
        clean = clean.replace(SILENCE, "").strip() or "Готово."
        mem.observe(Observation(person_id, clean, speaker="assistant", channel=channel, device=device))
        return TurnResult(clean, used, shown_now, tool_calls, mem.spend_usd() - cost_before, total, new_session)
