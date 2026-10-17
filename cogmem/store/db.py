"""Подключение к SQLite: WAL-журнал, транзакции, миграции.

SQLite выбран вместо Postgres осознанно: у семьи объём памяти — десятки тысяч
записей за годы, а SQLite — один файл, без администрирования, легко бэкапить,
транзакции надёжны. Доступ к данным идёт только через этот модуль и cogmem.store.repo,
поэтому переезд на Postgres позже — замена одного слоя.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any, Iterator

import numpy as np

SCHEMA_VERSION = 4


def to_blob(vec: np.ndarray | None) -> bytes | None:
    if vec is None:
        return None
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes | None) -> np.ndarray | None:
    if blob is None:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def dumps(obj: Any) -> str:
    # sort_keys — детерминированный вид (важно и для кэша промптов, и для сравнения).
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


class Database:
    """Потокобезопасная обёртка над одним соединением SQLite."""

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._depth = 0
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.execute("PRAGMA synchronous = NORMAL")
            self._migrate()

    # --- миграции ---
    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        sql = resources.files("cogmem.store").joinpath("schema.sql").read_text(encoding="utf-8")
        self._conn.executescript(sql)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # --- транзакции ---
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Транзакция (вложенные вызовы объединяются в одну внешнюю)."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self._conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self._conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | dict = ()) -> Any:
        row = self.one(sql, params)
        return None if row is None else row[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
