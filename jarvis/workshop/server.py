"""Мастерская как отдельный сервис (запускается в своём контейнере, без базы памяти и ключей API).

POST /run     {"code": "...", "timeout": 90, "files": {"имя": base64}, "env": {..}, "run_id": "..", "keep": true}
              →  RunResult (JSON)
POST /cancel  {"run_id": ".."}  — остановить запуск («Джарвис, стоп»)
Авторизация: заголовок «Authorization: Bearer <JARVIS_WORKSHOP_TOKEN>».
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jarvis.workshop import LocalWorkshop

TOKEN = os.environ.get("JARVIS_WORKSHOP_TOKEN", "")
WS = LocalWorkshop(os.environ.get("WORKSHOP_ROOT", "/data/workshop"),
                   skills_dir=os.environ.get("WORKSHOP_SKILLS", "/data/skills"))
_running: dict[str, threading.Event] = {}


class Handler(BaseHTTPRequestHandler):
    def _reply(self, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if self.path not in ("/run", "/cancel") or not TOKEN or not hmac.compare_digest(
                self.headers.get("Authorization", ""), f"Bearer {TOKEN}"):
            self.send_response(403)
            self.end_headers()
            return
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if self.path == "/cancel":
            ev = _running.get(str(req.get("run_id", "")))
            if ev is not None:
                ev.set()
            self._reply({"ok": ev is not None})
            return
        files = {k: base64.b64decode(v) for k, v in req.get("files", {}).items()}
        run_id = str(req.get("run_id") or "")
        cancel = threading.Event()
        if run_id:
            _running[run_id] = cancel
        try:
            res = WS.run(req["code"], files=files, timeout=float(req.get("timeout", 90)),
                         extra_paths=req.get("extra_paths") or [], env={str(k): str(v) for k, v in
                                                                         (req.get("env") or {}).items()},
                         cancel=cancel, keep=bool(req.get("keep", True)))
        finally:
            _running.pop(run_id, None)
        self._reply(asdict(res))

    def log_message(self, *args):  # тише в логах
        pass


def main() -> None:
    if not TOKEN:
        raise SystemExit("Нужен JARVIS_WORKSHOP_TOKEN")
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("WORKSHOP_PORT", "8700"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
