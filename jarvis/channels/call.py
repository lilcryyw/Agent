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
                self.voice.transcribe(b"", pcm=b"\0\0" * RATE // 2)
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
        try:
            await call.run()
        finally:
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

    # --- отправка ---
    async def send(self, obj: dict) -> None:
        await self.ws.send(json.dumps(obj, ensure_ascii=False))

    async def state(self, st: str) -> None:
        if st != self._state:
            self._state = st
            await self.send({"type": "state", "state": st})

    async def _say(self, turn: int, text: str) -> bool:
        """Синтез и отправка одного предложения; False — ход отменён."""
        audio, _ = await self.loop.run_in_executor(None, self.voice.speak, speakable(text), "mp3")
        if turn in self.cancelled:
            return False
        self.playing = turn
        await self.state("speaking")
        await self.send({"type": "say", "turn": turn, "text": text})
        await self.ws.send(struct.pack(">I", turn) + audio)
        self.spoken.append(text)
        return True

    # --- главный цикл ---
    async def run(self) -> None:
        await self.send({"type": "ready"})
        workers = [asyncio.create_task(self._hearing()), asyncio.create_task(self._thinking())]
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
            for w in workers:
                w.cancel()

    def _audio(self, pcm: bytes) -> None:
        if self.muted:
            return
        for phrase in self.seg.feed(pcm):
            self._barge_check = False
            self.phrases.put_nowait(phrase)
        if self.seg.in_speech and self.seg.speech_ms >= BARGE_MS and not self._barge_check and self._busy():
            self._barge_check = True
            asyncio.create_task(self._maybe_barge(self.seg.current()))

    def _busy(self) -> bool:
        return (self.thinking or self.playing is not None) and self.turn not in self.cancelled

    async def _control(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "played" and msg.get("turn") == self.playing:
            self.playing = None
            self._quiet_since = time.time()
            if not self.thinking:
                await self.state("listening")
        elif t == "interrupt":
            await self.interrupt()
        elif t == "mute":
            self.muted = bool(msg.get("on"))
            self.seg.reset()

    async def _maybe_barge(self, pcm: bytes) -> None:
        """Речь поверх ответа: если это не эхо — замолчать и слушать."""
        heard = await self.loop.run_in_executor(None, lambda: self.voice.transcribe(b"", pcm=pcm))
        if heard and not is_echo(heard, self.spoken) and self._busy():
            await self.interrupt()

    async def interrupt(self) -> None:
        t = self.turn
        if t in self.cancelled:
            return
        self.cancelled.add(t)
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
            if len(pcm) / 2 / RATE < MIN_PHRASE_S:
                continue
            heard = await self.loop.run_in_executor(None, lambda: self.voice.transcribe(b"", pcm=pcm))
            if not heard:
                continue
            busy = self._busy()
            echo_window = busy or time.time() - self._quiet_since < 4
            if echo_window and is_echo(heard, self.spoken):
                continue
            await self.send({"type": "heard", "text": heard})
            if busy:
                await self.interrupt()
            elif len(pcm) / 2 / RATE >= 1.5 and time.time() - self._last_enroll > ENROLL_EVERY_S \
                    and hasattr(self.j, "enroll_voice"):
                self._last_enroll = time.time()  # личный канал: голос точно этого человека
                self.j.enroll_voice(self.person, pcm)
            self.texts.put_nowait(heard)

    # --- мысль: текст → ответ голосом ---
    async def _thinking(self) -> None:
        while True:
            text = await self.texts.get()
            while not self.texts.empty():  # сказал несколько фраз подряд — это одна реплика
                text += " " + self.texts.get_nowait()
            await self._turn(text)

    async def _turn(self, text: str) -> None:
        self.turn += 1
        turn = self.turn
        self.spoken = []
        self.thinking = True
        note, self.note = self.note, None
        await self.state("thinking")
        sentences: asyncio.Queue[str | None] = asyncio.Queue()
        splitter = SpeechSplitter()

        def put(items):
            for s in items:
                self.loop.call_soon_threadsafe(sentences.put_nowait, s)

        def work():
            try:
                return self.j.brain.handle(self.person, text, channel="call", device=self.device, note=note,
                                           on_text=lambda chunk: put(splitter.feed(chunk)), effort=self.srv.effort)
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
            if r is not None:
                await self.send({"type": "reply", "turn": turn, "text": r.text})
            return
        if r is None:
            sent_any = await self._say(turn, "Что-то пошло не так, повтори, пожалуйста.")
        else:
            if not sent_any and r.text:
                sent_any = await self._say(turn, r.text)
            await self.send({"type": "reply", "turn": turn, "text": r.text})
        await self.send({"type": "done", "turn": turn})
        if not sent_any or self.playing is None:
            await self.state("listening")
