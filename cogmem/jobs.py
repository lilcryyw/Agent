"""Очередь фоновых задач памяти (в той же SQLite).

Идемпотентность: у каждой задачи уникальный ключ («encode:42»). Повторная постановка
той же задачи ничего не создаёт. Сбой → повтор с нарастающей паузой, после 5 попыток — failed.
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Callable

from cogmem.clock import Clock
from cogmem.store import Database, dumps

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


class JobQueue:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock
        # Процесс мог упасть посреди задачи — вернуть такие задачи в очередь.
        self.db.execute("UPDATE jobs SET status='pending' WHERE status='running'")

    def enqueue(self, kind: str, key: str, payload: dict | None = None, delay: float = 0.0) -> bool:
        now = self.clock.now()
        cur = self.db.execute(
            "INSERT OR IGNORE INTO jobs(kind, key, payload, run_after, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (kind, key, dumps(payload or {}), now + delay, now, now),
        )
        return cur.rowcount > 0

    def pending(self, kind: str | None = None) -> int:
        if kind:
            return self.db.scalar("SELECT COUNT(*) FROM jobs WHERE status='pending' AND kind=?", (kind,))
        return self.db.scalar("SELECT COUNT(*) FROM jobs WHERE status='pending'")

    def run_pending(self, handlers: dict[str, Callable[[dict], None]], *, limit: int = 100,
                    kinds: set[str] | None = None) -> int:
        """Выполнить готовые задачи. Возвращает число успешно выполненных."""
        done = 0
        for _ in range(limit):
            now = self.clock.now()
            with self.db.tx():
                row = self.db.one(
                    "SELECT * FROM jobs WHERE status='pending' AND run_after<=? "
                    + ("AND kind IN (%s) " % ",".join("?" * len(kinds)) if kinds else "")
                    + "ORDER BY run_after, id LIMIT 1",
                    (now, *sorted(kinds)) if kinds else (now,),
                )
                if row is None:
                    break
                if row["kind"] not in handlers:
                    # Нет обработчика в этом процессе — отложим, чтобы не крутиться.
                    self.db.execute("UPDATE jobs SET run_after=?, updated_at=? WHERE id=?", (now + 60, now, row["id"]))
                    continue
                self.db.execute(
                    "UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=?", (now, row["id"])
                )
            try:
                handlers[row["kind"]](json.loads(row["payload"]))
            except Exception as exc:  # noqa: BLE001 — любая ошибка задачи не должна ронять память
                attempts = row["attempts"] + 1
                status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
                delay = 30 * (2 ** (attempts - 1))
                log.warning("задача %s (%s) упала: %s", row["key"], attempts, exc)
                self.db.execute(
                    "UPDATE jobs SET status=?, last_error=?, run_after=?, updated_at=? WHERE id=?",
                    (status, "".join(traceback.format_exception_only(exc)).strip(),
                     self.clock.now() + delay, self.clock.now(), row["id"]),
                )
            else:
                self.db.execute("UPDATE jobs SET status='done', updated_at=? WHERE id=?", (self.clock.now(), row["id"]))
                done += 1
        return done
