"""HTTP-API: вход для iPhone (Команды Siri, кнопка Action), веб-приложения и автоматизаций.

Авторизация: «Authorization: Bearer <токен>»; токен привязан к человеку (выдаётся командой /token).
  POST /api/ask    {"text": "..."}                    → {"reply": "..."}
  POST /api/voice  тело = аудио (m4a/ogg/wav/webm)   → {"heard": "...", "reply": "..."}
                   ?reply=audio — вместо JSON сразу mp3 с голосом Джарвиса
  POST /api/event  {"text": "Пришёл домой"}           → событие для памяти и инициативы (не команда!)
  GET  /api/health
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cogmem.types import Observation

log = logging.getLogger(__name__)
MAX_BODY = 25 * 1024 * 1024


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def create_token(memory, person_id: str, name: str = "") -> str:
    token = "jv_" + secrets.token_urlsafe(32)
    memory.ctx.db.execute("INSERT INTO api_tokens(token_hash, person_id, name, created_at) VALUES (?,?,?,?)",
                          (_h(token), person_id, name, memory.ctx.clock.now()))
    return token


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

    def start(self) -> None:
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # тише
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, obj: dict) -> None:
                self._send(code, json.dumps(obj, ensure_ascii=False).encode())

            def do_GET(self):  # noqa: N802
                if urlparse(self.path).path == "/api/health":
                    return self._json(200, {"ok": True})
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
                        r = api.j.brain.handle(person, text, channel="api", device=device)
                        return self._json(200, {"reply": r.text})
                    if u.path == "/api/voice":
                        if api.voice is None:
                            return self._json(501, {"error": "голос не настроен на сервере"})
                        heard = api.voice.transcribe(body)
                        if not heard:
                            return self._json(200, {"heard": "", "reply": "Не расслышал, повтори, пожалуйста."})
                        r = api.j.brain.handle(person, heard, channel="voice", device=device)
                        if parse_qs(u.query).get("reply") == ["audio"]:
                            audio, mime = api.voice.speak(r.text, "mp3")
                            return self._send(200, audio, mime)
                        return self._json(200, {"heard": heard, "reply": r.text})
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
                    self._json(500, {"error": f"{type(exc).__name__}"})

        self._srv = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._srv.server_address[1]
        threading.Thread(target=self._srv.serve_forever, name="jarvis-api", daemon=True).start()

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
