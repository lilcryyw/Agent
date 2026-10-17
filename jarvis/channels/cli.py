"""Консольный канал: разговор с Джарвисом в терминале (для отладки и проверки памяти).

Запуск:  jarvis            (или python -m jarvis.channels.cli)
Команды: /память — статистика   /профиль — ядро   /почему F12 — источник факта
         /сон — ночная обработка сейчас   /сброс — закрыть эпизод и закодировать   /выход
"""

from __future__ import annotations

import argparse
import logging
import sys

from jarvis.runtime import Jarvis


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Джарвис в терминале")
    ap.add_argument("--person", default=None, help="id собеседника (по умолчанию — владелец)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    j = Jarvis()
    person = args.person or j.s.owner_id
    j.on_notify(lambda pid, text: print(f"\n🔔 [{pid}] {text}") if pid == person else None)
    j.start_background()
    m = j.memory
    print("Джарвис на связи. /выход — завершить.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in {"/выход", "/exit", "/quit"}:
            break
        if line == "/память":
            print(m.stats(), f"расход: ${m.spend_usd():.4f}")
            continue
        if line == "/профиль":
            print(m.core_profile(person))
            continue
        if line.startswith("/почему"):
            print(m.explain(person, line.split(maxsplit=1)[1] if " " in line else ""))
            continue
        if line == "/сон":
            print(m.sleep(person))
            continue
        if line == "/сброс":
            print(m.flush(person))
            continue
        r = j.brain.handle(person, line, channel="cli")
        print(r.text)
        if args.verbose:
            print(f"   [использовано: {', '.join(r.used) or '—'}; инструменты: {', '.join(r.tool_calls) or '—'}; "
                  f"${r.cost_usd:.4f}; кэш: {r.usage.get('cache_read_input_tokens', 0)}]")
    j.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
