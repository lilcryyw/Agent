"""Главный запуск Джарвиса на сервере: память, инициатива, шлюз устройств, HTTP-API и (если задан) Telegram.

    python -m jarvis.server
"""

from __future__ import annotations

import asyncio
import logging
import threading

from jarvis.runtime import Jarvis


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    j = Jarvis()
    j.start_background()
    if j.s.telegram_token:
        from jarvis.channels.telegram import run

        asyncio.run(run(j))
    else:
        logging.info("Telegram не настроен — работают API и устройства")
        threading.Event().wait()


if __name__ == "__main__":
    main()
