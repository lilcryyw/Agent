"""Аудит изменений памяти: кто, что, почему. Основа для «почему ты так решил» и для отката."""

from __future__ import annotations

from typing import Any

from cogmem.clock import Clock
from cogmem.store import Database, dumps


class Audit:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock

    def log(self, actor: str, op: str, unit_type: str, unit_id: int | None, *,
            before: Any = None, after: Any = None, reason: str = "") -> None:
        self.db.execute(
            "INSERT INTO memory_audit(ts, actor, op, unit_type, unit_id, before, after, reason) VALUES (?,?,?,?,?,?,?,?)",
            (self.clock.now(), actor, op, unit_type, unit_id,
             None if before is None else dumps(before),
             None if after is None else dumps(after), reason),
        )

    def history(self, unit_type: str, unit_id: int) -> list[dict]:
        rows = self.db.query(
            "SELECT ts, actor, op, before, after, reason FROM memory_audit WHERE unit_type=? AND unit_id=? ORDER BY id",
            (unit_type, unit_id),
        )
        return [dict(r) for r in rows]
