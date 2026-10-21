"""HTTP-API: вход для iPhone (Команды Siri, кнопка Action), веб-приложения и автоматизаций.

Авторизация: «Authorization: Bearer <токен>»; токен привязан к человеку (выдаётся командой /token).
  POST /api/ask    {"text": "..."}                    → {"reply": "..."}
  POST /api/voice  тело = аудио (m4a/ogg/wav/webm)   → {"heard": "...", "reply": "..."}
                   ?reply=audio — вместо JSON сразу mp3 с голосом Джарвиса
  POST /api/event  {"text": "Пришёл домой"}           → событие для памяти и инициативы (не команда!)
  POST /api/speak  {"text": "..."}                    → mp3 голосом Джарвиса
  POST /api/inbox                                      → {"messages": [...]} — что Джарвис сказал сам (инициатива)
  GET  /app/                                           → веб-приложение с голосом (ставится на экран телефона)
  GET  /api/health
"""

from __future__ import annotations

import hashlib
import json
import os
import logging
import secrets
import threading
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cogmem.types import Observation
from jarvis.brain.agent import is_stop

log = logging.getLogger(__name__)
MAX_BODY = 25 * 1024 * 1024
WEBAPP = Path(__file__).with_name("webapp")
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("JARVIS_CORS_ORIGINS", "").split(",") if o.strip()]
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json",
        ".svg": "image/svg+xml"}


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def create_token(memory, person_id: str, name: str = "") -> str:
    token = "jv_" + secrets.token_urlsafe(32)
    memory.ctx.db.execute("INSERT INTO api_tokens(token_hash, person_id, name, created_at) VALUES (?,?,?,?)",
                          (_h(token), person_id, name, memory.ctx.clock.now()))
    return token


def ensure_token(memory, person_id: str, token: str, name: str = "владелец") -> None:
    """Заранее известный ключ (например, из секретов площадки) — чтобы войти без Telegram."""
    if token and person_for_token(memory, token) is None:
        memory.ctx.db.execute("INSERT INTO api_tokens(token_hash, person_id, name, created_at) VALUES (?,?,?,?)",
                              (_h(token), person_id, name, memory.ctx.clock.now()))


def person_for_token(memory, token: str) -> str | None:
    row = memory.ctx.db.one("SELECT person_id FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL",
                            (_h(token),))
    return row["person_id"] if row else None


class Api:
    def __init__(self, jarvis, *, host: str = "0.0.0.0", port: int = 8780, voice=None):
        self.j = jarvis
        self.voice = voice
        self.host, self.port = host, port
        self._srv: ThreadingHTTPServer | None = None
        self._outbox: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        if hasattr(jarvis, "on_notify"):
            jarvis.on_notify(lambda person, text: self._outbox[person].append(text))

    def _stop(self, person: str, text: str) -> str | None:
        """«Стоп» — сразу, без очереди: прерываем текущий ход, если он идёт."""
        if not is_stop(text):
            return None
        brain = self.j.brain
        return "Остановил." if getattr(brain, "cancel", None) and brain.cancel(person) else "Хорошо, ничего не делаю."

    def start(self) -> None:
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # тише
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)

            def _cors(self) -> None:
                """Веб-приложение может быть на другом домене (Cloudflare Pages): разрешаем только свои адреса."""
                origin = (self.headers.get("Origin") or "").rstrip("/")
                if origin and origin in CORS_ORIGINS:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Device")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Max-Age", "600")

            def do_OPTIONS(self):  # noqa: N802 — предварительный запрос браузера
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _json(self, code: int, obj: dict) -> None:
                self._send(code, json.dumps(obj, ensure_ascii=False).encode())

            def do_GET(self):  # noqa: N802
                path = urlparse(self.path).path
                if path == "/api/health":
                    return self._json(200, {"ok": True})
                if path in ("/app", "/app/") or path.startswith("/app/"):
                    name = path[len("/app/"):] or "index.html"
                    f = (WEBAPP / name).resolve()
                    if WEBAPP.resolve() in f.parents and f.is_file():
                        return self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
                    if path == "/app":
                        self.send_response(301)
                        self.send_header("Location", "/app/")
                        self.end_headers()
                        return None
                self._json(404, {"error": "нет такого адреса"})

            def do_POST(self):  # noqa: N802
                u = urlparse(self.path)
                auth = self.headers.get("Authorization", "")
                person = person_for_token(api.j.memory, auth[7:]) if auth.startswith("Bearer ") else None
                if person is None:
                    return self._json(401, {"error": "нужен токен (/token в Telegram)"})
                n = int(self.headers.get("Content-Length", "0"))
                if n > MAX_BODY:
                    return self._json(413, {"error": "слишком большой запрос"})
                body = self.rfile.read(n)
                device = self.headers.get("X-Device") or "iphone"
                try:
                    if u.path == "/api/ask":
                        text = json.loads(body or b"{}").get("text", "").strip()
                        if not text:
                            return self._json(400, {"error": "пустой текст"})
                        if stopped := api._stop(person, text):
                            return self._json(200, {"reply": stopped})
                        r = api.j.brain.handle(person, text, channel="api", device=device)
                        return self._json(200, {"reply": r.text, "silent": bool(getattr(r, "silent", False))})
                    if u.path == "/api/voice":
                        if api.voice is None:
                            return self._json(501, {"error": "голос не настроен на сервере"})
                        pcm = api.voice.pcm16k(body)
                        heard = api.voice.transcribe(body, pcm=pcm)
                        if heard and hasattr(api.j, "enroll_voice"):
                            api.j.enroll_voice(person, pcm)  # личный канал: голос точно этого человека
                        if not heard:
                            return self._json(200, {"heard": "", "reply": "Не расслышал, повтори, пожалуйста."})
                        reply = api._stop(person, heard) or \
                            api.j.brain.handle(person, heard, channel="voice", device=device).text
                        if parse_qs(u.query).get("reply") == ["audio"] and getattr(api.voice, "can_speak", True):
                            audio, mime = api.voice.speak(reply, "mp3")
                            return self._send(200, audio, mime)
                        return self._json(200, {"heard": heard, "reply": reply})
                    if u.path == "/api/speak":
                        if api.voice is None or not getattr(api.voice, "can_speak", True):
                            return self._json(501, {"error": "голос не настроен на сервере"})
                        text = json.loads(body or b"{}").get("text", "").strip()[:2000]
                        audio, mime = api.voice.speak(text or "…", "mp3")
                        return self._send(200, audio, mime)
                    if u.path == "/api/inbox":
                        q = api._outbox[person]
                        msgs = [q.popleft() for _ in range(len(q))]
                        return self._json(200, {"messages": msgs})
                    if u.path == "/api/event":
                        text = json.loads(body or b"{}").get("text", "").strip()
                        if text:
                            # Событие — это данные для памяти и инициативы, а не команда.
                            api.j.memory.observe(Observation(person, f"[{device}] {text}", speaker="device",
                                                             device=device, channel="device", kind="device_event",
                                                             source_kind="observed"))
                        return self._json(200, {"ok": True})
                    self._json(404, {"error": "нет такого адреса"})
                except Exception as exc:  # noqa: BLE001
                    log.exception("ошибка API")
                    # Команды Siri и веб-приложение показывают reply — пусть человек увидит понятный ответ.
                    self._json(503, {"error": f"{type(exc).__name__}",
                                     "reply": "Что-то пошло не так у меня внутри. Попробуй ещё раз через минуту."})

        self._srv = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._srv.server_address[1]
        threading.Thread(target=self._srv.serve_forever, name="jarvis-api", daemon=True).start()

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
