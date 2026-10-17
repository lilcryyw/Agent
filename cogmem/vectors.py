"""Векторный индекс в памяти процесса (точный поиск по косинусу).

Для семейного масштаба (до сотен тысяч записей) точный перебор numpy быстрее и надёжнее
любого приближённого индекса: ~1 мс на 50 тыс. векторов. Источник истины — SQLite;
индекс загружается при старте и обновляется при каждой записи.
Шлюз чтения встроен: маска видимости применяется ДО ранжирования.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from cogmem.store import Database, from_blob

# Как загрузить каждую таблицу: (SQL, есть ли «активность»).
_LOADERS = {
    "event": "SELECT id, embedding, person_id AS owner, visibility, 1 AS active, ts FROM events WHERE embedding IS NOT NULL",
    "episode": "SELECT id, embedding, person_id AS owner, visibility, 1 AS active, start_ts AS ts FROM episodes "
               "WHERE embedding IS NOT NULL",
    "fact": "SELECT id, embedding, owner_person AS owner, visibility, "
            "(invalidated_at IS NULL AND status='active') AS active, recorded_at AS ts FROM facts WHERE embedding IS NOT NULL",
    "entity": "SELECT id, embedding, owner_person AS owner, visibility, (merged_into IS NULL) AS active, "
              "created_at AS ts FROM entities WHERE embedding IS NOT NULL",
    "procedure": "SELECT id, embedding, person_id AS owner, visibility, (status IN ('active','candidate')) AS active, "
                 "created_at AS ts FROM procedures WHERE embedding IS NOT NULL",
}


@dataclass
class _Table:
    ids: list[int]
    vecs: list[np.ndarray]
    owners: list[str]
    family: list[bool]
    active: list[bool]
    ts: list[float]
    pos: dict[int, int]
    matrix: np.ndarray | None = None  # кэш склеенной матрицы


class VectorIndex:
    def __init__(self, db: Database, dim: int):
        self.db = db
        self.dim = dim
        self._lock = threading.RLock()
        self._t: dict[str, _Table] = {}
        for unit_type in _LOADERS:
            self._load(unit_type)

    def _load(self, unit_type: str) -> None:
        t = _Table([], [], [], [], [], [], {})
        for r in self.db.query(_LOADERS[unit_type]):
            v = from_blob(r["embedding"])
            if v is None or v.shape[0] != self.dim:
                continue  # вектор от другой модели — переиндексируем позже
            t.pos[r["id"]] = len(t.ids)
            t.ids.append(r["id"])
            t.vecs.append(v)
            t.owners.append(r["owner"] or "")
            t.family.append(r["visibility"] == "family")
            t.active.append(bool(r["active"]))
            t.ts.append(r["ts"] or 0.0)
        self._t[unit_type] = t

    def add(self, unit_type: str, unit_id: int, vec: np.ndarray, *, owner: str | None,
            visibility: str, active: bool = True, ts: float = 0.0) -> None:
        with self._lock:
            t = self._t[unit_type]
            if unit_id in t.pos:
                i = t.pos[unit_id]
                t.vecs[i] = vec.astype(np.float32)
                t.owners[i] = owner or ""
                t.family[i] = visibility == "family"
                t.active[i] = active
                t.ts[i] = ts
            else:
                t.pos[unit_id] = len(t.ids)
                t.ids.append(unit_id)
                t.vecs.append(vec.astype(np.float32))
                t.owners.append(owner or "")
                t.family.append(visibility == "family")
                t.active.append(active)
                t.ts.append(ts)
            t.matrix = None

    def set_active(self, unit_type: str, unit_id: int, active: bool) -> None:
        with self._lock:
            t = self._t[unit_type]
            if unit_id in t.pos:
                t.active[t.pos[unit_id]] = active

    def set_visibility(self, unit_type: str, unit_id: int, visibility: str) -> None:
        with self._lock:
            t = self._t[unit_type]
            if unit_id in t.pos:
                t.family[t.pos[unit_id]] = visibility == "family"

    def remove(self, unit_type: str, unit_id: int) -> None:
        with self._lock:
            t = self._t[unit_type]
            if unit_id not in t.pos:
                return
            i = t.pos.pop(unit_id)
            for lst in (t.ids, t.vecs, t.owners, t.family, t.active, t.ts):
                lst.pop(i)
            t.pos = {uid: j for j, uid in enumerate(t.ids)}
            t.matrix = None

    def get(self, unit_type: str, unit_id: int) -> np.ndarray | None:
        t = self._t[unit_type]
        i = t.pos.get(unit_id)
        return None if i is None else t.vecs[i]

    def search(self, unit_type: str, query: np.ndarray, viewer: str, *, k: int = 40,
               include_inactive: bool = False, ts_range: tuple[float, float] | None = None,
               ) -> list[tuple[int, float]]:
        """Топ-k (id, косинус) среди видимых viewer записей."""
        with self._lock:
            t = self._t[unit_type]
            if not t.ids:
                return []
            if t.matrix is None:
                t.matrix = np.stack(t.vecs)
            owners = np.array(t.owners, dtype=object)
            mask = np.array(t.family) | (owners == viewer)
            if not include_inactive:
                mask &= np.array(t.active)
            if ts_range is not None:
                ts = np.array(t.ts)
                mask &= (ts >= ts_range[0]) & (ts < ts_range[1])
            if not mask.any():
                return []
            sims = t.matrix @ query.astype(np.float32)
            sims = np.where(mask, sims, -np.inf)
            k = min(k, int(mask.sum()))
            top = np.argpartition(-sims, k - 1)[:k]
            top = top[np.argsort(-sims[top])]
            return [(t.ids[i], float(sims[i])) for i in top]

    def count(self, unit_type: str) -> int:
        return len(self._t[unit_type].ids)
