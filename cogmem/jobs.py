"""Очередь фоновых задач памяти (в той же SQLite).

Идемпотентность: у каждой задачи уникальный ключ («encode:42»). Повторная постановка
той же задачи ничего не создаёт (или, с reset=True, возвращает упавшую/выполненную в очередь).

Сбои делятся на два вида:
  • временные (сеть, 429/5xx, перегрузка API) — повтор без ограничения числа попыток,
    пауза растёт до часа: часовой сбой API не должен навсегда потерять эпизод;
  • постоянные (ответ обрезан, отказ модели, кривые данные, ошибка в коде) — после
    PERMANENT_ATTEMPTS попыток задача помечается failed (ночной «сон» вернёт её в очередь).
Отложить задачу без траты попытки — исключение JobDeferred (например, ждём более ранний эпизод).
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Callable

from cogmem.clock import Clock
from cogmem.store import Database, dumps

log = logging.getLogger(__name__)
PERMANENT_ATTEMPTS = 3
MAX_DELAY_S = 3600.0
MAX_ATTEMPTS = PERMANENT_ATTEMPTS  # совместимость со старым именем


class JobDeferred(Exception):
    """Задача не готова к выполнению (это не сбой): отложить на delay секунд, попытку не считать."""

    def __init__(self, reason: str = "", delay: float = 30.0):
        super().__init__(reason)
        self.delay = delay


class PermanentJobError(Exception):
    """Сбой, который повтор не исправит."""


_TRANSIENT_NAMES = {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
                    "OverloadedError", "ServiceUnavailableError", "ConnectError", "ReadTimeout", "ConnectTimeout"}
_PERMANENT_HINTS = ("max_tokens", "отказалась", "refusal", "пустой структурированный")


def is_transient(exc: BaseException) -> bool:
    """Временный ли сбой (стоит повторять бесконечно с растущей паузой)."""
    if isinstance(exc, PermanentJobError):
        return False
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in (408, 409, 425, 429) or status >= 500
    if type(exc).__name__ in _TRANSIENT_NAMES or isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    msg = str(exc).lower()
    if any(h in msg for h in _PERMANENT_HINTS):
        return False
    if isinstance(exc, (TypeError, ValueError, KeyError, AttributeError, IndexError, AssertionError)):
        return False  # ошибка данных/кода (pydantic ValidationError — тоже ValueError)
    return True  # неизвестное — лучше повторять, чем потерять


class JobQueue:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock
        # Процесс мог упасть посреди задачи — вернуть такие задачи в очередь.
        self.db.execute("UPDATE jobs SET status='pending' WHERE status='running'")

    def enqueue(self, kind: str, key: str, payload: dict | None = None, delay: float = 0.0,
                *, reset: bool = False) -> bool:
        """Поставить задачу. reset=True — упавшую или уже выполненную с тем же ключом вернуть в очередь."""
        now = self.clock.now()
        sql = "INSERT INTO jobs(kind, key, payload, run_after, created_at, updated_at) VALUES (?,?,?,?,?,?) "
        if reset:
            sql += ("ON CONFLICT(key) DO UPDATE SET status='pending', attempts=0, last_error=NULL, "
                    "run_after=excluded.run_after, updated_at=excluded.updated_at WHERE status IN ('failed','done')")
        else:
            sql += "ON CONFLICT(key) DO NOTHING"
        cur = self.db.execute(sql, (kind, key, dumps(payload or {}), now + delay, now, now))
        return cur.rowcount > 0

    def requeue_failed(self, kind: str | None = None) -> int:
        now = self.clock.now()
        cur = self.db.execute(
            "UPDATE jobs SET status='pending', attempts=0, run_after=?, updated_at=? WHERE status='failed'"
            + (" AND kind=?" if kind else ""), (now, now, kind) if kind else (now, now))
        return cur.rowcount

    def status(self, key: str) -> str | None:
        return self.db.scalar("SELECT status FROM jobs WHERE key=?", (key,))

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
            except JobDeferred as d:
                t = self.clock.now()
                self.db.execute("UPDATE jobs SET status='pending', attempts=attempts-1, run_after=?, last_error=?, "
                                "updated_at=? WHERE id=?", (t + d.delay, f"отложено: {d}", t, row["id"]))
            except Exception as exc:  # noqa: BLE001 — любая ошибка задачи не должна ронять память
                attempts = row["attempts"] + 1
                transient = is_transient(exc)
                status = "pending" if transient or attempts < PERMANENT_ATTEMPTS else "failed"
                delay = min(MAX_DELAY_S, 30 * (2 ** min(attempts - 1, 12)))
                log.warning("задача %s (попытка %s, %s) упала: %s", row["key"], attempts,
                            "временный сбой" if transient else "постоянный сбой", exc)
                self.db.execute(
                    "UPDATE jobs SET status=?, last_error=?, run_after=?, updated_at=? WHERE id=?",
                    (status, ("" if transient else "[постоянный] ")
                     + "".join(traceback.format_exception_only(exc)).strip(),
                     self.clock.now() + delay, self.clock.now(), row["id"]),
                )
            else:
                self.db.execute("UPDATE jobs SET status='done', updated_at=? WHERE id=?", (self.clock.now(), row["id"]))
                done += 1
        return done
