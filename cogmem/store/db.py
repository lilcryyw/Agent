"""Подключение к SQLite: WAL-журнал, транзакции, миграции.

SQLite выбран вместо Postgres осознанно: у семьи объём памяти — десятки тысяч
записей за годы, а SQLite — один файл, без администрирования, легко бэкапить,
транзакции надёжны. Доступ к данным идёт только через этот модуль и cogmem.store.repo,
поэтому переезд на Postgres позже — замена одного слоя.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import zlib
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any, Iterator

import numpy as np

SCHEMA_VERSION = 7
log = logging.getLogger(__name__)

# Полнотекстовый индекс: rowid = код_типа << 40 | id — удаление по rowid мгновенно
# (DELETE по UNINDEXED-колонкам FTS5 — это полный перебор таблицы при каждой записи).
_FTS_CODES = {"event": 1, "episode": 2, "fact": 3, "entity": 4, "procedure": 5, "intention": 6, "goal": 7,
              "skill": 8}


def fts_rowid(unit_type: str, unit_id: int) -> int:
    code = _FTS_CODES.get(unit_type)
    if code is None:
        code = 100 + zlib.crc32(unit_type.encode()) % 10_000
    return (code << 40) | int(unit_id)


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
        """Новая база — схема целиком. Старая — сначала шаги-миграции (ALTER и правка данных), потом схема
        (CREATE IF NOT EXISTS добавит новые таблицы). Каждый шаг идемпотентен и выполняется один раз."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        sql = resources.files("cogmem.store").joinpath("schema.sql").read_text(encoding="utf-8")
        fresh = version == 0 and not self._table_exists("events")
        if not fresh:
            for v in range(max(version, 1) + 1, SCHEMA_VERSION + 1):
                step = MIGRATIONS.get(v)
                if step is not None:
                    log.info("миграция схемы памяти → %d", v)
                    step(self._conn)
        self._conn.executescript(sql)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _table_exists(self, name: str) -> bool:
        return self._conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None

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


# ---------------------------------------------------------------- шаги миграций
def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    cols = _columns(conn, table)
    if cols and column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _m7(conn: sqlite3.Connection) -> None:
    """v7: время наблюдения факта, предложенная замена, «устаревшие» сводки, FTS по rowid, родственные прозвища."""
    _add_column(conn, "facts", "observed_at", "REAL")
    _add_column(conn, "facts", "replaces_id", "INTEGER")
    _add_column(conn, "episodes", "stale", "INTEGER NOT NULL DEFAULT 0")
    if "observed_at" in _columns(conn, "facts"):
        conn.execute("UPDATE facts SET observed_at=COALESCE(valid_from, recorded_at) WHERE observed_at IS NULL")
    # FTS: переложить строки под детерминированные rowid.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='fts'").fetchone():
        rows = conn.execute("SELECT unit_type, unit_id, text FROM fts").fetchall()
        conn.execute("BEGIN")
        conn.execute("DELETE FROM fts")
        seen = set()
        for r in rows:
            rid = fts_rowid(r[0], int(r[1]))
            if rid in seen:
                continue
            seen.add(rid)
            conn.execute("INSERT INTO fts(rowid, unit_type, unit_id, text) VALUES (?,?,?,?)", (rid, r[0], r[1], r[2]))
        conn.execute("COMMIT")
    # «мама», «жена»… не бывают общими для всей семьи: у каждого своя мама.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='aliases'").fetchone():
        from cogmem.entities import is_kinship_norm

        for alias_norm, eid in conn.execute("SELECT alias_norm, entity_id FROM aliases WHERE person_scope=''").fetchall():
            if not is_kinship_norm(alias_norm):
                continue
            owner = conn.execute("SELECT owner_person FROM entities WHERE id=?", (eid,)).fetchone()
            conn.execute("DELETE FROM aliases WHERE alias_norm=? AND entity_id=? AND person_scope=''", (alias_norm, eid))
            if owner and owner[0]:
                conn.execute("INSERT OR IGNORE INTO aliases(alias_norm, entity_id, person_scope) VALUES (?,?,?)",
                             (alias_norm, eid, owner[0]))


MIGRATIONS = {7: _m7}
