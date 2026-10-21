"""Живой голосовой разговор (как голосовой режим ChatGPT/Claude): говоришь — Джарвис слышит, отвечает голосом,
его можно перебить. Ничего нажимать не нужно: конец фразы сервер определяет сам по паузе (Silero VAD).

WebSocket (за Caddy: wss://ДОМЕН/call). Протокол:
  клиент → сервер: {"type":"hello","token":"jv_…","device":"web"}       — первым сообщением
                   двоичные кадры: PCM16 моно 16 кГц (little-endian)     — микрофон, непрерывно
                   {"type":"played","turn":N}                           — клиент доиграл ответ N
                   {"type":"interrupt"}                                 — человек нажал «хватит»
                   {"type":"mute","on":true|false}
  сервер → клиент: {"type":"ready"} | {"type":"error","text":..}
                   {"type":"state","state":"listening"|"thinking"|"speaking"}
                   {"type":"heard","text":..}                            — что распознано
                   {"type":"say","turn":N,"text":..} + двоичный кадр: 4 байта N (big-endian) + mp3
                   {"type":"reply","turn":N,"text":..}                    — весь ответ (для чата, с кнопками)
                   {"type":"done","turn":N}                              — по ходу N всё отправлено
                   {"type":"interrupt","turn":N}                         — немедленно замолчать

Скорость: ответ произносится по предложениям, пока Claude ещё пишет следующие. Эхо (свой голос из динамика)
не считается перебиванием: браузер вычитает его сам, а сервер ещё сверяет услышанное со сказанным.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import struct
import threading
import time

from jarvis.channels.http_api import person_for_token
from jarvis.voice.vad import RATE, make_segmenter

log = logging.getLogger(__name__)
PROACTIVE_AFTER_S = (25, 60)  # пауза человека, после которой Джарвис может заговорить сам (1-й и 2-й раз)
SPEAK_SYSTEM = """Ты — внутренний голос Джарвиса в живом голосовом разговоре. Человек молчит.
Решай, как решает человек, есть ли у Джарвиса мысль, которую стоит сказать СЕЙЧАС (по работе Inner Thoughts):
- уместность: мысль про то, о чём говорили, а не случайная;
- пробел: человек этого не знает, а ему нужно;
- польза: сказанное заметно поможет или порадует;
- срочность: позже будет поздно;
- связность и баланс: не повтор, не болтовня, не перебивает чужое молчание-раздумье.
Если в состоянии Джарвиса записано, что его просили помолчать/не перебивать, — молчать.
Если разговор естественно закончен или человек занят — молчать."""
BARGE_MS = 450          # столько речи поверх ответа — повод проверить, не перебивают ли
MIN_PHRASE_S = 0.35     # короче — шум, кашель
ENROLL_EVERY_S = 60
GREETING = "Слушаю."
HIDDEN = (("⟦", "⟧"), ("[[", "]]"))  # служебные пометки и кнопки — не произносятся
SENT_END = re.compile(r"[.!?…]+[»\")\]]*\s+|\n+")
URL = re.compile(r"https?://\S+")
WORD = re.compile(r"[а-яёa-z0-9]+")


class SpeechSplitter:
    """Поток текста от модели → готовые к произнесению предложения (без служебных пометок)."""

    def __init__(self, first_min: int = 2, max_len: int = 220):
        self.raw = ""        # ещё не разобранное (может начинаться с незакрытой пометки)
        self.visible = ""    # видимый текст, ждущий конца предложения
        self.first_min = first_min
        self.max_len = max_len

    def _strip(self) -> None:
        while self.raw:
            starts = [(self.raw.find(o), o, c) for o, c in HIDDEN if o in self.raw]
            if not starts:
                # «[» или «⟦» в самом конце может оказаться началом пометки — подождём следующий кусок
                keep = 1 if self.raw.endswith("[") else 0
                self.visible += self.raw[:len(self.raw) - keep]
                self.raw = self.raw[len(self.raw) - keep:]
                return
            pos, o, c = min(starts)
            self.visible += self.raw[:pos]
            end = self.raw.find(c, pos + len(o))
            if end < 0:
                self.raw = self.raw[pos:]
                return
            self.raw = self.raw[end + len(c):]

    def feed(self, chunk: str) -> list[str]:
        self.raw += chunk
        self._strip()
        out = []
        while True:
            m = SENT_END.search(self.visible)
            if m and m.end() >= self.first_min:
                sent, self.visible = self.visible[:m.end()], self.visible[m.end():]
            elif len(self.visible) > self.max_len:  # очень длинное без точки — режем по запятой/пробелу
                cut = max(self.visible.rfind(", ", 0, self.max_len), self.visible.rfind(" ", 0, self.max_len))
                cut = cut + 1 if cut > 40 else self.max_len
                sent, self.visible = self.visible[:cut], self.visible[cut:]
            else:
                break
            if speakable(sent):
                out.append(sent.strip())
        return out

    def flush(self) -> list[str]:
        rest, self.visible, self.raw = self.visible, "", ""
        return [rest.strip()] if speakable(rest) else []


def speakable(text: str) -> str:
    """Текст для синтеза: без разметки и ссылок."""
    t = URL.sub("ссылку показал на экране", text)
    t = re.sub(r"[*_#`>|~]+", " ", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t).strip()
    return t if WORD.search(t.lower()) else ""


def words(text: str) -> list[str]:
    return WORD.findall(text.lower().replace("ё", "е"))


def is_echo(heard: str, spoken: list[str]) -> bool:
    """Услышанное — это, скорее всего, собственный голос Джарвиса из динамика."""
    h = words(heard)
    if not h or not spoken:
        return False
    s = set(words(" ".join(spoken[-4:])))
    return sum(w in s for w in h) / len(h) >= 0.6


class CallServer:
    def __init__(self, jarvis, *, host: str = "0.0.0.0", port: int = 8790, voice=None, models_dir=None):
        self.j = jarvis
        self.active: dict[str, set] = {}  # person → идущие звонки (сюда же звучат слова Джарвиса «по своей инициативе»)
        if hasattr(jarvis, "on_notify"):
            jarvis.on_notify(self._notify)
        self.voice = voice
        self.models_dir = models_dir
        self.host, self.port = host, port
        self.loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._server = None
        self.effort = getattr(getattr(jarvis, "s", None), "call_effort", None)

    def start(self) -> None:
        def run():
            self.loop = asyncio.new_event_loop()
            self.loop.run_until_complete(self._serve())

        threading.Thread(target=run, name="jarvis-call", daemon=True).start()
        threading.Thread(target=self._warm_up, name="jarvis-call-warmup", daemon=True).start()
        self._ready.wait(10)

    def _warm_up(self) -> None:
        """Загрузить модели речи заранее: первый звонок не должен ждать их 5–10 секунд."""
        try:
            make_segmenter(self.models_dir)
            if self.voice is not None and hasattr(self.voice, "speak_wav"):
                self.voice.transcribe(b"", pcm=b"\0\0" * (RATE // 2))
                if getattr(self.voice, "can_speak", True):
                    self.voice.speak_wav("Готов.")
        except Exception:  # noqa: BLE001
            log.exception("прогрев моделей речи не удался")

    async def _serve(self) -> None:
        from websockets.asyncio.server import serve

        async with serve(self._handler, self.host, self.port, max_size=1 << 20) as server:
            self._server = server
            self.port = next(iter(server.sockets)).getsockname()[1]
            self._ready.set()
            await server.serve_forever()

    def _notify(self, person: str, text: str) -> None:
        """Джарвис сам решил сказать (напоминание, инициатива) — если человек на звонке, говорит сразу голосом."""
        for call in list(self.active.get(person, ())):
            if self.loop:
                asyncio.run_coroutine_threadsafe(call.announce(text), self.loop)

    def stop(self) -> None:
        if self._server and self.loop:
            self.loop.call_soon_threadsafe(self._server.close)

    async def _handler(self, ws) -> None:
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 15))
        except Exception:  # noqa: BLE001
            return
        person = person_for_token(self.j.memory, str(hello.get("token", "")))
        if person is None:
            await ws.send(json.dumps({"type": "error", "text": "Нужен ключ доступа"}, ensure_ascii=False))
            return
        if self.voice is None:
            await ws.send(json.dumps({"type": "error", "text": "Голос на сервере не настроен"}, ensure_ascii=False))
            return
        device = re.sub(r"[^\w-]", "", str(hello.get("device") or "web"))[:24] or "web"
        call = Call(self, ws, person, device)
        log.info("звонок: %s (%s)", person, device)
        self.active.setdefault(person, set()).add(call)
        try:
            await call.run()
        finally:
            self.active.get(person, set()).discard(call)
            log.info("звонок завершён: %s", person)


class Call:
    def __init__(self, server: CallServer, ws, person: str, device: str):
        self.srv, self.ws, self.person, self.device = server, ws, person, device
        self.j, self.voice = server.j, server.voice
        self.seg = make_segmenter(server.models_dir)
        self.loop = asyncio.get_running_loop()
        self.phrases: asyncio.Queue[bytes] = asyncio.Queue()
        self.texts: asyncio.Queue[str] = asyncio.Queue()
        self.turn = 0
        self.thinking = False          # «сознание» работает над ходом self.turn
        self.playing: int | None = None  # ход, чей голос сейчас звучит у человека
        self.cancelled: set[int] = set()
        self.spoken: list[str] = []    # что уже отправлено голосом в текущем ходе
        self.note: str | None = None   # пометка для следующего хода (например, «тебя перебили»)
        self.muted = False
        self._barge_check = False
        self._last_enroll = 0.0
        self._state = ""
        self._quiet_since = 0.0        # когда Джарвис замолчал (хвост эха ещё может прийти)
        self._cancel = threading.Event()  # отмена текущего хода «сознания» (перебили)
        self._tasks: set[asyncio.Task] = set()
        self._turn_lock = asyncio.Lock()   # ход по реплике и ход по своей инициативе не пересекаются
        self._activity = time.time()       # последняя речь человека или конец речи Джарвиса
        self._proactive_n = 0              # сколько раз подряд Джарвис заговорил сам (сброс — когда говорит человек)

    # --- отправка ---
    async def send(self, obj: dict) -> None:
        await self.ws.send(json.dumps(obj, ensure_ascii=False))

    async def state(self, st: str) -> None:
        if st != self._state:
            self._state = st
            await self.send({"type": "state", "state": st})

    async def _say(self, turn: int, text: str) -> bool:
        """Синтез и отправка одного предложения; False — ход отменён или звука нет (текст всё равно уходит)."""
        if not getattr(self.voice, "can_speak", True):
            # Слабый сервер: произносит сам браузер (speak=true), сервер шлёт только текст.
            if turn in self.cancelled:
                return False
            self.playing = turn
            await self.state("speaking")
            await self.send({"type": "say", "turn": turn, "text": text, "speak": True})
            self.spoken.append(text)
            return True
        try:
            audio, _ = await self.loop.run_in_executor(None, self.voice.speak, speakable(text), "mp3")
        except Exception:  # noqa: BLE001 — голос сломался: хотя бы текстом
            log.exception("синтез речи не удался")
            audio = None
        if turn in self.cancelled:
            return False
        await self.send({"type": "say", "turn": turn, "text": text})
        if audio is None:
            return False
        self.playing = turn
        await self.state("speaking")
        await self.ws.send(struct.pack(">I", turn) + audio)
        self.spoken.append(text)
        return True

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # --- главный цикл ---
    async def run(self) -> None:
        await self.send({"type": "ready"})
        workers = [asyncio.create_task(self._hearing()), asyncio.create_task(self._thinking()),
                   asyncio.create_task(self._initiative())]
        for w in workers:  # упавший «орган» звонка — не тихая глухота, а закрытое соединение
            w.add_done_callback(lambda t: t.cancelled() or t.exception() is None or
                                self._spawn(self.ws.close(1011, "внутренняя ошибка")))
        try:
            self.turn = 1
            await self._say(self.turn, GREETING)
            await self.send({"type": "done", "turn": self.turn})
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    self._audio(raw)
                else:
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(msg, dict):
                        await self._control(msg)
        except Exception as exc:  # noqa: BLE001 — обрыв связи и т.п.
            log.info("звонок прервался: %s", type(exc).__name__)
        finally:
            self._cancel.set()
            for w in workers + list(self._tasks):
                w.cancel()

    def _audio(self, pcm: bytes) -> None:
        if self.muted:
            return
        for phrase in self.seg.feed(pcm):
            self._barge_check = False
            self.phrases.put_nowait(phrase)
        if self.seg.in_speech and self.seg.speech_ms >= BARGE_MS and not self._barge_check and self._busy():
            self._barge_check = True
            self._spawn(self._maybe_barge(self.seg.current()))

    def _busy(self) -> bool:
        return (self.thinking or self.playing is not None) and self.turn not in self.cancelled

    async def _control(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "played" and msg.get("turn") == self.playing:
            self.playing = None
            self._quiet_since = time.time()
            self._activity = time.time()
            if not self.thinking:
                await self.state("listening")
        elif t == "interrupt":
            await self.interrupt()
        elif t == "mute":
            self.muted = bool(msg.get("on"))
            self.seg.reset()

    async def _maybe_barge(self, pcm: bytes) -> None:
        """Речь поверх ответа: если это не эхо — замолчать и слушать."""
        try:
            heard = await self.loop.run_in_executor(None, lambda: self.voice.transcribe(b"", pcm=pcm))
        except Exception:  # noqa: BLE001
            log.exception("распознавание (перебивание) не удалось")
            return
        if heard and not is_echo(heard, self.spoken) and self._busy():
            await self.interrupt()

    async def interrupt(self) -> None:
        t = self.turn
        if t in self.cancelled:
            return
        self.cancelled.add(t)
        self._cancel.set()  # останавливаем и мысль, и инструменты — не только голос
        if self.spoken:
            said = " ".join(self.spoken)[-300:]
            self.note = f"Тебя перебили: человек заговорил, когда ты успел сказать только «{said}»."
        elif self.thinking:
            self.note = "Человек заговорил снова, пока ты думал над ответом, — тот ответ он не услышал."
        self.playing = None
        self._quiet_since = 0.0
        await self.send({"type": "interrupt", "turn": t})
        await self.state("listening")

    # --- слух: фраза → текст ---
    async def _hearing(self) -> None:
        while True:
            pcm = await self.phrases.get()
            try:
                await self._hear(pcm)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — одна неудачная фраза не должна оглушить звонок
                log.exception("ошибка распознавания фразы")

    async def _hear(self, pcm: bytes) -> None:
        if len(pcm) / 2 / RATE < MIN_PHRASE_S:
            return
        heard = await self.loop.run_in_executor(None, lambda: self.voice.transcribe(b"", pcm=pcm))
        if not heard:
            return
        busy = self._busy()
        echo_window = busy or time.time() - self._quiet_since < 4
        if echo_window and is_echo(heard, self.spoken):
            return
        await self.send({"type": "heard", "text": heard})
        if busy:
            await self.interrupt()
        elif len(pcm) / 2 / RATE >= 1.5 and time.time() - self._last_enroll > ENROLL_EVERY_S \
                and hasattr(self.j, "enroll_voice"):
            self._last_enroll = time.time()  # личный канал: голос точно этого человека
            self.j.enroll_voice(self.person, pcm)
        self._activity = time.time()
        self._proactive_n = 0
        self.texts.put_nowait(heard)

    # --- мысль: текст → ответ голосом ---
    async def _thinking(self) -> None:
        while True:
            text = await self.texts.get()
            while not self.texts.empty():  # сказал несколько фраз подряд — это одна реплика
                text += " " + self.texts.get_nowait()
            try:
                async with self._turn_lock:
                    await self._turn(text)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("ошибка хода в звонке")
            finally:
                self.thinking = False

    # --- инициатива: Джарвис говорит, когда сам считает нужным ---
    async def _initiative(self) -> None:
        while True:
            await asyncio.sleep(2)
            try:
                if self._proactive_n >= len(PROACTIVE_AFTER_S) or self.muted or self.thinking \
                        or self.playing is not None or not self.texts.empty() or self.seg.in_speech:
                    continue
                if time.time() - self._activity < PROACTIVE_AFTER_S[self._proactive_n]:
                    continue
                self._proactive_n += 1
                self._activity = time.time()
                if not await self.loop.run_in_executor(None, self._worth_speaking):
                    continue
                async with self._turn_lock:
                    if self.texts.empty() and not self.thinking:
                        await self._turn("В разговоре пауза: человек молчит. Если есть что сказать по делу — "
                                         "скажи коротко (продолжи мысль, спроси, предложи). Нечего — ⟦молчу⟧.",
                                         stimulus=True)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("ошибка инициативы в звонке")

    def _worth_speaking(self) -> bool:
        """Дешёвая проверка (Haiku): есть ли смысл заговорить самому. Без модели — молчим (экономия)."""
        llm = getattr(self.j.memory, "llm", None)
        if llm is None:
            return False
        from pydantic import BaseModel, Field

        class SpeakDecision(BaseModel):
            speak: bool = Field(description="Заговорить ли Джарвису сейчас самому.")
            why: str = Field(description="Коротко почему.")

        ep = self.j.memory.current_episode_id(self.person)
        lines = [f"{'человек' if e['speaker'] == 'user' else 'Джарвис'}: {e['text'][:300]}"
                 for e in (self.j.memory.episodes.events_of(ep)[-10:] if ep else []) if e.get("kind") != "stimulus"]
        if not lines:
            return False
        inner = self.j.brain.inner_state(self.person) if hasattr(self.j.brain, "inner_state") else ""
        d = llm.parse(system=SPEAK_SYSTEM, user=(f"Состояние Джарвиса: {inner or '—'}\n" if inner else "")
                      + "Последние реплики:\n" + "\n".join(lines), schema=SpeakDecision,
                      purpose="call_initiative", max_tokens=300)
        return bool(d.speak)

    async def announce(self, text: str) -> None:
        """Сказать в звонке то, что Джарвис решил сам (напоминание, инициатива) — без нового хода «сознания»."""
        async with self._turn_lock:
            self.turn += 1
            self.spoken = []
            sent = False
            for s in SpeechSplitter().feed(text + "\n"):
                sent = await self._say(self.turn, s) or sent
            await self.send({"type": "reply", "turn": self.turn, "text": text})
            await self.send({"type": "done", "turn": self.turn})
            if not sent:
                await self.state("listening")

    async def _turn(self, text: str, *, stimulus: bool = False) -> None:
        self.turn += 1
        turn = self.turn
        self.spoken = []
        self.thinking = True
        self._cancel = cancel = threading.Event()
        note, self.note = self.note, None
        await self.state("thinking")
        sentences: asyncio.Queue[str | None] = asyncio.Queue()
        splitter = SpeechSplitter()

        def put(items):
            for s in items:
                self.loop.call_soon_threadsafe(sentences.put_nowait, s)

        def work():
            try:
                if stimulus:
                    return self.j.brain.handle_stimulus(self.person, text, channel="call", device=self.device,
                                                        on_text=lambda chunk: put(splitter.feed(chunk)),
                                                        cancel=cancel, effort=self.srv.effort)
                return self.j.brain.handle(self.person, text, channel="call", device=self.device, note=note,
                                           on_text=lambda chunk: put(splitter.feed(chunk)), effort=self.srv.effort,
                                           cancel=cancel)
            finally:
                put(splitter.flush())
                put([None])

        fut = self.loop.run_in_executor(None, work)
        sent_any = False
        while (s := await sentences.get()) is not None:
            if turn not in self.cancelled:
                sent_any = await self._say(turn, s) or sent_any
        try:
            r = await fut
        except Exception:  # noqa: BLE001
            log.exception("ошибка хода в звонке")
            r = None
        self.thinking = False
        if turn in self.cancelled:
            if r is not None and self.spoken:  # в чат — то, что успел сказать (остальное он не слышал)
                await self.send({"type": "reply", "turn": turn, "text": " ".join(self.spoken)})
            return
        if r is None:
            if not stimulus:
                sent_any = await self._say(turn, "Что-то пошло не так, повтори, пожалуйста.")
        elif getattr(r, "silent", False):
            pass  # решил промолчать
        else:
            if not sent_any and r.text:
                sent_any = await self._say(turn, r.text)
            await self.send({"type": "reply", "turn": turn, "text": r.text})
        await self.send({"type": "done", "turn": turn})
        if not sent_any or self.playing is None:
            await self.state("listening")
