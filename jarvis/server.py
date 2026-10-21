"""Главный запуск Джарвиса на сервере: память, инициатива, шлюз устройств, HTTP-API, живой разговор
и (если задан) Telegram.

    python -m jarvis.server

На площадке без постоянного диска (Hugging Face Space) задай JARVIS_BACKUP_REPO и HF_TOKEN:
память восстанавливается при запуске и сохраняется каждые несколько минут (jarvis/persist.py).
JARVIS_OWNER_TOKEN — ключ владельца для веб-приложения (если нет Telegram, чтобы выдать его командой /token).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from jarvis.runtime import Jarvis


def keep_awake(url: str, every_s: int = 20 * 60) -> None:
    """Бесплатный Space засыпает без посещений — заходим на свой публичный адрес, как посетитель."""
    import urllib.request

    def loop():
        while True:
            threading.Event().wait(every_s)
            try:
                urllib.request.urlopen(url, timeout=30).read()
            except Exception as exc:  # noqa: BLE001
                logging.warning("будильник: %s", exc)

    threading.Thread(target=loop, name="jarvis-keepawake", daemon=True).start()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    backup = None
    repo = os.environ.get("JARVIS_BACKUP_REPO")
    if repo:
        from jarvis.persist import Backup, restore

        data = Path(os.environ.get("JARVIS_DB", "data/jarvis.db")).parent
        restore(data, repo)
        backup = Backup(data, repo)

    # Площадка сама сообщает свой адрес (Render) — подставляем, если домен не задан явно.
    host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if host and not os.environ.get("JARVIS_DOMAIN"):
        os.environ["JARVIS_DOMAIN"] = host
        os.environ.setdefault("JARVIS_DEVICES_URL", f"wss://{host}/devices")
    j = Jarvis()
    if os.environ.get("JARVIS_OWNER_TOKEN"):
        from jarvis.channels.http_api import ensure_token

        ensure_token(j.memory, j.s.owner_id, os.environ["JARVIS_OWNER_TOKEN"])
    j.start_background()
    if os.environ.get("JARVIS_KEEP_AWAKE") == "1" and j.s.public_domain:
        # Render усыпляет через 15 минут тишины, Hugging Face — через 48 часов.
        keep_awake(f"https://{j.s.public_domain}/api/health",
                   int(os.environ.get("JARVIS_KEEP_AWAKE_EVERY_S", "600")))
    if backup is not None:
        backup.start()

        def on_term(*_):
            logging.info("остановка: сохраняю память")
            j.stop()
            backup.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, on_term)
    try:
        # Telegram (если есть токен в .env или в сейфе) запускается в фоне из start_background.
        threading.Event().wait()
    finally:
        if backup is not None:
            j.stop()
            backup.stop()


if __name__ == "__main__":
    main()
