"""Мастерская как отдельный сервис (запускается в своём контейнере, без базы памяти и ключей API).

POST /run  {"code": "...", "timeout": 90, "files": {"имя": base64}}  →  RunResult (JSON)
Авторизация: заголовок «Authorization: Bearer <JARVIS_WORKSHOP_TOKEN>».
"""

from __future__ import annotations

import base64
import hmac
import json
import os
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jarvis.workshop import LocalWorkshop

TOKEN = os.environ.get("JARVIS_WORKSHOP_TOKEN", "")
WS = LocalWorkshop(os.environ.get("WORKSHOP_ROOT", "/data/workshop"),
                   skills_dir=os.environ.get("WORKSHOP_SKILLS", "/data/skills"))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if self.path != "/run" or not TOKEN or not hmac.compare_digest(
                self.headers.get("Authorization", ""), f"Bearer {TOKEN}"):
            self.send_response(403)
            self.end_headers()
            return
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        files = {k: base64.b64decode(v) for k, v in req.get("files", {}).items()}
        res = WS.run(req["code"], files=files, timeout=float(req.get("timeout", 90)),
                     extra_paths=req.get("extra_paths") or [])
        body = json.dumps(asdict(res)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # тише в логах
        pass


def main() -> None:
    if not TOKEN:
        raise SystemExit("Нужен JARVIS_WORKSHOP_TOKEN")
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("WORKSHOP_PORT", "8700"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
