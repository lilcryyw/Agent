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

    j = Jarvis()
    if os.environ.get("JARVIS_OWNER_TOKEN"):
        from jarvis.channels.http_api import ensure_token

        ensure_token(j.memory, j.s.owner_id, os.environ["JARVIS_OWNER_TOKEN"])
    j.start_background()
    if os.environ.get("JARVIS_KEEP_AWAKE") == "1" and j.s.public_domain:
        keep_awake(f"https://{j.s.public_domain}/api/health")
    if backup is not None:
        backup.start()

        def on_term(*_):
            logging.info("остановка: сохраняю память")
            j.stop()
            backup.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, on_term)
    if j.s.telegram_token:
        from jarvis.channels.telegram import run

        asyncio.run(run(j))
    else:
        logging.info("Telegram не настроен — работают API, живой разговор и устройства")
        threading.Event().wait()


if __name__ == "__main__":
    main()
