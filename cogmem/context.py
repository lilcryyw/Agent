"""Общий контекст подсистем памяти (одна база, одни часы, один индекс)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cogmem.clock import Clock
from cogmem.config import MemoryConfig
from cogmem.embed import Embedder
from cogmem.govern.audit import Audit
from cogmem.jobs import JobQueue
from cogmem.store import Database
from cogmem.text import ru
from cogmem.vectors import VectorIndex


@dataclass
class Ctx:
    db: Database
    clock: Clock
    cfg: MemoryConfig
    embedder: Embedder
    index: VectorIndex
    audit: Audit
    jobs: JobQueue

    def embed1(self, text: str) -> np.ndarray:
        return self.embedder.embed([text])[0]

    # --- полнотекстовый индекс ---
    def fts_add(self, unit_type: str, unit_id: int, text: str) -> None:
        self.db.execute("DELETE FROM fts WHERE unit_type=? AND unit_id=?", (unit_type, unit_id))
        body = ru.fts_text(text)
        if body:
            self.db.execute("INSERT INTO fts(unit_type, unit_id, text) VALUES (?,?,?)", (unit_type, unit_id, body))

    def fts_remove(self, unit_type: str, unit_id: int) -> None:
        self.db.execute("DELETE FROM fts WHERE unit_type=? AND unit_id=?", (unit_type, unit_id))

    def trace(self, unit_type: str, unit_id: int, kind: str = "used", ts: float | None = None) -> None:
        self.db.execute(
            "INSERT INTO access_traces(unit_type, unit_id, ts, kind) VALUES (?,?,?,?)",
            (unit_type, unit_id, self.clock.now() if ts is None else ts, kind),
        )
