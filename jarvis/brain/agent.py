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

from cogmem.llm import cost_usd
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
    effort: str = "medium"  # постоянна в сессии: смена глубины размышлений сбрасывает кэш истории


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
    over_budget: bool = False


class TurnCancelled(Exception):
    """Ход прерван человеком («стоп», перебивание в звонке)."""


STOP_RE = re.compile(r"^\W*(джарвис\W*)?(стоп|хватит|отмена|остановись|прекрати)(\W+(всё|все|это))?\W*$", re.I)


def is_stop(text: str) -> bool:
    """«Джарвис, стоп» — остановить текущую работу (проверяется до очереди к «сознанию»)."""
    return bool(STOP_RE.match(text.strip()))


def human_now(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]}, {dt.day} {MONTHS_GEN[dt.month - 1]} {dt.year}, {dt:%H:%M}"


INNER_RE = re.compile(r"⟦\s*внутри\s*:([^⟧]*)⟧")


def split_inner(text: str) -> tuple[str, str | None]:
    """Отделить внутреннюю заметку ⟦внутри: …⟧ (что думаю, чувствую, чего жду) — её человек не видит."""
    notes = [m.group(1).strip() for m in INNER_RE.finditer(text)]
    return INNER_RE.sub("", text).strip(), (notes[-1] if notes else None)


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
        self._cancels: dict[str, threading.Event] = {}

    # ------------------------------------------------------------------ API
    def _call(self, messages: list[dict], on_text: Callable[[str], None] | None = None,
              effort: str | None = None, cancel: threading.Event | None = None) -> Any:
        """Один запрос к Claude. on_text — получать текст по мере генерации (живой голосовой разговор).
        cancel — прервать генерацию (человек перебил или сказал «стоп») → TurnCancelled."""
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
                if on_text is None and cancel is None:
                    return api.create(**kwargs, **more, extra_body=extra)
                with api.stream(**kwargs, **more, extra_body=extra) as stream:
                    for chunk in stream.text_stream:
                        if cancel is not None and cancel.is_set():
                            raise TurnCancelled()
                        if on_text:
                            on_text(chunk)
                    final = stream.get_final_message()
                if on_text:
                    on_text("\n")  # конец шага: недосказанное предложение можно произносить
                return final
            except TurnCancelled:
                raise
            except Exception as exc:
                import anthropic

                if not isinstance(exc, anthropic.BadRequestError):
                    raise
                text = str(exc).lower()
                # Отключаем возможность, только если ошибка явно про неё (а не, например, «превышен контекст»).
                if self._fallbacks_ok and ("fallbacks" in text or FALLBACK_BETA in text):
                    self._fallbacks_ok = False
                elif self._ctx_edit_ok and ("context_management" in text or "clear_tool" in text
                                            or CONTEXT_BETA in text):
                    self._ctx_edit_ok = False
                else:
                    raise
                log.warning("возможность API недоступна (%s) — отключаю и повторяю", exc)

    # ------------------------------------------------------------------ ход
    def _lock(self, person_id: str) -> threading.Lock:
        return self._locks.setdefault(person_id, threading.Lock())

    def cancel(self, person_id: str) -> bool:
        """«Джарвис, стоп»: прервать текущий ход человека (генерацию и долгие инструменты). True — было что прерывать."""
        stopped = 0
        if hasattr(self.tools, "cancel_all"):
            stopped = self.tools.cancel_all(person_id) or 0  # фоновые задачи тоже
        ev = self._cancels.get(person_id)
        if ev is not None:
            ev.set()
        return ev is not None or bool(stopped)

    def busy(self, person_id: str) -> bool:
        return self._lock(person_id).locked()

    def handle(self, person_id: str, text: str, *, channel: str = "text", device: str | None = None,
               note: str | None = None, on_text: Callable[[str], None] | None = None,
               effort: str | None = None, cancel: threading.Event | None = None) -> TurnResult:
        """Реплика человека. note — служебная пометка для контекста (например, «голос не узнан уверенно»).
        on_text — получать ответ кусочками по мере генерации (включая служебные пометки ⟦…⟧ — их убирает
        получатель). effort — глубина размышлений для новой сессии (в живом разговоре важнее скорость).
        cancel — событие отмены хода (иначе создаётся своё; прервать можно через cancel(person_id))."""
        with self._lock(person_id):
            return self._turn(person_id, text, origin="user", channel=channel, device=device, note=note,
                              on_text=on_text, effort=effort, cancel=cancel)

    def handle_stimulus(self, person_id: str, reason: str, *, channel: str = "internal", device: str | None = None,
                        on_text: Callable[[str], None] | None = None, cancel: threading.Event | None = None,
                        effort: str | None = None) -> TurnResult:
        """Внутренний повод (цель, срок, событие, пауза в разговоре): Джарвис сам решает, действовать ли
        и говорить ли. channel="call" — повод внутри живого разговора (ответ звучит сразу)."""
        with self._lock(person_id):
            return self._turn(person_id, reason, origin="internal", channel=channel, device=device,
                              on_text=on_text, cancel=cancel, effort=effort)

    def inner_state(self, person_id: str) -> str:
        row = self.memory.ctx.db.one("SELECT value FROM meta WHERE key=?", (f"inner:{person_id}",))
        return row["value"] if row else ""

    def set_inner_state(self, person_id: str, text: str) -> None:
        self.memory.ctx.db.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"inner:{person_id}", text[:600]))

    def _over_budget(self) -> bool:
        now = self.memory.local_now(self.s.owner_id) if self.memory.person(self.s.owner_id) else datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        return self.memory.spend_usd(month_start) >= self.s.monthly_budget_usd

    def _recent_lines(self, episode_ids: list[int], skip_event: int | None) -> list[str]:
        events: list[dict] = []
        for eid in episode_ids:
            events += [e for e in self.memory.episodes.events_of(eid) if e["id"] != skip_event]
        events = [e for e in events if e.get("kind") != "stimulus"][-14:]
        who = {"user": "человек", "assistant": "Джарвис"}
        return [f"{who.get(e['speaker'], e['speaker'])}: {e['text'][:600]}" for e in events]

    def _turn(self, person_id: str, text: str, *, origin: str, channel: str, device: str | None,
              note: str | None = None, on_text: Callable[[str], None] | None = None,
              effort: str | None = None, cancel: threading.Event | None = None) -> TurnResult:
        cancel = cancel or threading.Event()
        self._cancels[person_id] = cancel
        try:
            return self._turn_inner(person_id, text, origin=origin, channel=channel, device=device, note=note,
                                    on_text=on_text, effort=effort, cancel=cancel)
        finally:
            if self._cancels.get(person_id) is cancel:
                self._cancels.pop(person_id, None)

    def _turn_inner(self, person_id: str, text: str, *, origin: str, channel: str, device: str | None,
                    note: str | None, on_text: Callable[[str], None] | None, effort: str | None,
                    cancel: threading.Event) -> TurnResult:
        mem = self.memory
        if origin == "user":
            obs = mem.observe(Observation(person_id, text, speaker="user", channel=channel, device=device))
        else:
            obs = mem.observe(Observation(person_id, f"Внутренний повод: {text}", speaker="system", kind="stimulus",
                                          channel=channel))
        sess = self.sessions.get(person_id)
        new_session = sess is None or sess.episode_id != obs.episode_id or \
            sess.context_tokens > self.s.session_max_tokens
        recent_from: list[int] = []
        if new_session:
            # Разговор продолжается, а истории в «сознании» нет (перезапуск сервера, длинная беседа,
            # смена эпизода без паузы) — подаём недавние реплики, чтобы не потерять нить.
            if not obs.new_episode:
                recent_from = [obs.episode_id]
            elif obs.closed_episode_id is not None:
                recent_from = [obs.closed_episode_id, obs.episode_id]
            sess = Session(person_id, obs.episode_id, effort=effort or self.s.brain_effort)
            self.sessions[person_id] = sess

        if self._over_budget():
            if origin != "user":
                return TurnResult("", [], [], [], 0.0, {}, new_session, True, over_budget=True)
            msg = (f"Месячный бюджет на ИИ (${self.s.monthly_budget_usd:.0f}) исчерпан. "
                   "Увеличь JARVIS_MONTHLY_BUDGET_USD, если нужно продолжить.")
            if on_text:
                on_text(msg)
            mem.observe(Observation(person_id, msg, speaker="assistant", channel=channel, device=device))
            return TurnResult(msg, [], [], [], 0.0, {}, new_session, over_budget=True)

        # Профиль собеседника — в начале сессии; его факты не дублируем в <память>.
        profile = mem.core_profile(person_id) if new_session else ""
        core_refs = REF_RE.findall(profile)
        # Рабочая память под эту реплику. Текущий разговор и так в истории (или в <недавний_разговор>) —
        # его не ищем, иначе свежая реплика человека вернётся к нему же как «воспоминание».
        ctx = {"channel": channel, "device": device}
        wm, res = mem.working_memory(person_id, text, context=ctx, exclude_episode_id=obs.episode_id,
                                     exclude_refs=sess.shown | set(core_refs))
        shown_now = core_refs + wm.shown_refs() + REF_RE.findall("\n".join(wm.intentions + wm.procedures))
        now = mem.local_now(person_id)
        blocks: list[dict] = []
        if new_session:
            blocks.append({"type": "text", "text": f"<о_собеседнике>\n{profile}\n</о_собеседнике>"})
            lines = self._recent_lines(recent_from, obs.event_id) if recent_from else []
            if lines:
                blocks.append({"type": "text", "text": "<недавний_разговор>\n" + "\n".join(lines)
                               + "\n</недавний_разговор>"})
        where = f"Канал: {channel}." + (f" Устройство: {device}." if device else "")
        keys = self.tools.keys.lines(person_id)
        trust = self.tools.keys.trust_suggestions(person_id)
        state = ("Ключи от замка: " + ("; ".join(keys) if keys else "нет") + "."
                 + (" Доверие: " + "; ".join(trust) + "." if trust else ""))
        if hasattr(self.tools, "context_lines"):
            extra_lines = self.tools.context_lines(person_id)
            if extra_lines:
                state += " " + " ".join(extra_lines)
        if origin == "user" and hasattr(mem, "pending_facts"):
            pending = mem.pending_facts(person_id, limit=3)
            if pending:  # то, что пришло из сомнительного источника, — спросить при случае, не навязываясь
                state += " Ждут подтверждения человека (note approve/reject): " + "; ".join(pending) + "."
        if note:
            state += f" {note}"
        inner = self.inner_state(person_id)
        if inner:  # непрерывность разума: что я думал и чего ждал в прошлый раз
            state += f"\n<моё_состояние>{inner}</моё_состояние>"
        blocks.append({"type": "text", "text": f"<контекст>Сейчас: {human_now(now)} ({now.tzinfo}). {where} {state}"
                                              f"</контекст>\n<память>\n{wm.render()}\n</память>"})
        blocks.append({"type": "text", "text": text if origin == "user"
                       else f"<внутренний_повод>{text}</внутренний_повод>"})
        turn_start = len(sess.messages)
        user_msg = {"role": "user", "content": blocks}
        sess.messages.append(user_msg)
        sess.shown.update(shown_now)
        if isinstance(getattr(self.tools, "shown", None), dict):
            self.tools.shown[person_id] = sess.shown  # тот же набор: инструмент видит актуальное
        if hasattr(self.tools, "begin_turn"):
            self.tools.begin_turn(person_id, origin=origin, unverified_speaker=bool(note and "не узнан" in note),
                                  cancel=cancel)

        tool_calls: list[str] = []
        total: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                                 "cache_creation_input_tokens": 0}
        turn_cost = 0.0
        final_text = ""
        reset_once = False

        def close_with(text_: str) -> None:
            """Завершить ход ответом-текстом, сохранив историю корректной (после user — ответ ассистента)."""
            if sess.messages and sess.messages[-1]["role"] == "user":
                sess.messages.append({"role": "assistant", "content": [{"type": "text", "text": text_}]})

        step = 0
        while step < MAX_STEPS:
            step += 1
            if cancel.is_set():
                final_text = final_text or "Хорошо, остановился."
                close_with(final_text)
                break
            try:
                resp = self._call(sess.messages, on_text, sess.effort, cancel)
            except TurnCancelled:
                final_text = "Хорошо, остановился."
                close_with("(Меня прервали — ответ не закончен.)")
                break
            except Exception as exc:  # noqa: BLE001
                import anthropic

                bad_history = isinstance(exc, anthropic.BadRequestError) and \
                    any(w in str(exc) for w in ("tool_use", "tool_result", "messages."))
                if bad_history and not reset_once:
                    # Страховка: история испорчена — начинаем сессию заново с этой реплики.
                    log.warning("история разговора отклонена API (%s) — начинаю сессию заново", exc)
                    reset_once = True
                    sess.messages = [user_msg]
                    step -= 1
                    continue
                log.exception("мозг недоступен")
                final_text = ("Не могу сейчас связаться со своим «мозгом» — сеть или сервис перегружены. "
                              "Попробуй через минуту.")
                if on_text:
                    on_text(final_text)
                close_with(final_text)
                break
            model = getattr(resp, "model", None) or self.s.brain_model
            if not isinstance(model, str):
                model = self.s.brain_model
            mem.record_usage(model, "brain", resp.usage)
            turn_cost += cost_usd(model, resp.usage)
            for k in total:
                total[k] += getattr(resp.usage, k, 0) or 0
            sess.context_tokens = sum(getattr(resp.usage, k, 0) or 0 for k in
                                      ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            content = list(resp.content or [])
            stop = resp.stop_reason
            if hasattr(self.tools, "observe_response"):
                # Серверные инструменты (поиск, чтение сайтов) приносят чужой текст — отмечаем это для замка.
                self.tools.observe_response(person_id, content)
            if stop == "refusal":
                # Отказ: его содержимое не оставляем в истории (иначе сломаются следующие ходы).
                final_text = "Извини, с этим я помочь не могу."
                if on_text:
                    on_text(final_text)
                sess.messages[turn_start:] = [user_msg]
                close_with(final_text)
                break
            if content:
                sess.messages.append({"role": "assistant", "content": content})
            final_text = "".join(b.text for b in content if getattr(b, "type", "") == "text")
            tool_uses = [b for b in content if getattr(b, "type", "") == "tool_use"]
            if stop in ("max_tokens", "model_context_window_exceeded"):
                if tool_uses:  # оборвался вызов инструмента — закрываем его ошибкой, чтобы история была цельной
                    sess.messages.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                         "content": "Ответ оборвался по длине — инструмент не выполнен. Сделай короче или по частям."}
                        for b in tool_uses]})
                    if stop == "max_tokens":
                        continue
                if stop == "model_context_window_exceeded":
                    sess.context_tokens = 10 ** 9  # следующий ход — свежая сессия
                note_ = "\n(Ответ получился слишком длинным и оборвался — спроси, если нужно продолжение.)"
                final_text = (final_text + note_) if final_text else note_.strip()
                close_with(final_text)
                break
            if stop == "tool_use" and turn_cost > self.s.turn_budget_usd:
                # Защита от «увлёкся»: дальше без разрешения человека не тратим.
                final_text = (f"Я потратил на эту задачу уже больше ${self.s.turn_budget_usd:.2f} и ещё не закончил. "
                              "Продолжать?")
                if on_text:
                    on_text(final_text)
                sess.messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b.id, "content": "Остановлено: лимит стоимости хода.",
                     "is_error": True} for b in tool_uses]})
                close_with(final_text)
                break
            if stop == "tool_use":
                results = []
                for b in tool_uses:
                    if cancel.is_set():
                        results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                        "content": "Не выполнено: человек попросил остановиться."})
                        continue
                    tool_calls.append(b.name)
                    out, is_err = self.tools.run(person_id, b.name, dict(b.input), origin=origin,
                                                 source_event_id=obs.event_id if origin == "user" else None)
                    # Показанное инструментом уже в истории — в <память> не повторяем. (Сервер вычищает старые
                    # результаты только после ~100k токенов, а сессия перезапускается раньше — на session_max_tokens.)
                    refs = REF_RE.findall(out) if isinstance(out, str) else []
                    sess.shown.update(refs)
                    shown_now += refs
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": is_err})
                sess.messages.append({"role": "user", "content": results})
                continue
            if stop == "pause_turn":
                continue  # серверный инструмент (поиск) попросил продолжить
            break
        else:
            # Шаги кончились посреди работы: история заканчивается результатами инструментов — закрываем ответом.
            final_text = final_text or "Я сделал много шагов и ещё не закончил. Продолжать?"
            close_with(final_text)

        final_text, inner_note = split_inner(final_text)
        if inner_note:
            self.set_inner_state(person_id, inner_note)
        clean, used = split_used(final_text)
        # «Использовал» засчитываем и за показанное в прошлых репликах этой сессии.
        mem.feedback(list(dict.fromkeys(shown_now + [u for u in used if u in sess.shown])), used)
        silent = not clean or SILENCE in clean and not clean.replace(SILENCE, "").strip()
        if silent:  # решил промолчать (в том числе в ответ на «помолчи») — это действие, а не сбой
            return TurnResult("", used, shown_now, tool_calls, turn_cost, total, new_session, True)
        clean = clean.replace(SILENCE, "").strip()
        mem.observe(Observation(person_id, clean, speaker="assistant", channel=channel, device=device))
        return TurnResult(clean, used, shown_now, tool_calls, turn_cost, total, new_session)
