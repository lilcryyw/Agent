"""Общий контекст подсистем памяти (одна база, одни часы, один индекс)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from cogmem.clock import Clock
from cogmem.config import MemoryConfig
from cogmem.embed import Embedder
from cogmem.govern.audit import Audit
from cogmem.jobs import JobQueue
from cogmem.store import Database, fts_rowid
from cogmem.text import ru
from cogmem.vectors import VectorIndex

_CACHE_MAX = 1024


@dataclass
class Ctx:
    db: Database
    clock: Clock
    cfg: MemoryConfig
    embedder: Embedder
    index: VectorIndex
    audit: Audit
    jobs: JobQueue
    # Векторы, посчитанные заранее (prefetch) — чтобы не считать их внутри транзакции под общим замком базы.
    _emb_cache: dict = field(default_factory=dict, repr=False)
    _emb_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def embed1(self, text: str, *, query: bool = False) -> np.ndarray:
        key = (text, query)
        with self._emb_lock:
            v = self._emb_cache.pop(key, None)
        if v is not None:
            return v
        return self.embedder.embed([text], query=query)[0]

    def prefetch(self, texts: Iterable[str], *, query: bool = False) -> None:
        """Посчитать векторы одним пакетом ДО транзакции; embed1 внутри неё возьмёт готовые."""
        todo = list(dict.fromkeys(t for t in texts if t is not None))
        if not todo:
            return
        vecs = self.embedder.embed(todo, query=query)
        with self._emb_lock:
            if len(self._emb_cache) + len(todo) > _CACHE_MAX:
                self._emb_cache.clear()
            for t, v in zip(todo, vecs):
                self._emb_cache[(t, query)] = v

    def sim01(self, cos: float) -> float:
        """Косинус → 0..1 по калибровке модели эмбеддингов."""
        lo, hi = self.embedder.sim_floor, self.embedder.sim_ceil
        return max(0.0, min(1.0, (cos - lo) / (hi - lo)))

    # --- полнотекстовый индекс (rowid детерминирован: удаление без перебора таблицы) ---
    def fts_add(self, unit_type: str, unit_id: int, text: str) -> None:
        rid = fts_rowid(unit_type, unit_id)
        self.db.execute("DELETE FROM fts WHERE rowid=?", (rid,))
        body = ru.fts_text(text)
        if body:
            self.db.execute("INSERT INTO fts(rowid, unit_type, unit_id, text) VALUES (?,?,?,?)",
                            (rid, unit_type, unit_id, body))

    def fts_remove(self, unit_type: str, unit_id: int) -> None:
        self.db.execute("DELETE FROM fts WHERE rowid=?", (fts_rowid(unit_type, unit_id),))

    def trace(self, unit_type: str, unit_id: int, kind: str = "used", ts: float | None = None) -> None:
        self.db.execute(
            "INSERT INTO access_traces(unit_type, unit_id, ts, kind) VALUES (?,?,?,?)",
            (unit_type, unit_id, self.clock.now() if ts is None else ts, kind),
        )
