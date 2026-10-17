"""Векторный индекс в памяти процесса (точный поиск по косинусу).

Для семейного масштаба (до сотен тысяч записей) точный перебор numpy быстрее и надёжнее
любого приближённого индекса: ~25 мс на 50 тыс. векторов × 1024. Источник истины — SQLite;
индекс загружается при старте и обновляется при каждой записи.
Шлюз чтения встроен: маска видимости применяется ДО ранжирования.

Колонки хранятся предвыделенными массивами numpy (растут удвоением): запись не требует
пересборки матрицы. Раньше векторы лежали списком и склеивались заново на первый поиск
после каждой записи — а запись идёт на каждой реплике (≈100 мс лишних на ход при 50 тыс.).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

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
    dim: int
    n: int = 0
    ids: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    mat: np.ndarray | None = None
    owner_code: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int32))
    family: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    active: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    ts: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    pos: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mat is None:
            self.mat = np.zeros((0, self.dim), dtype=np.float32)

    def grow(self, need: int) -> None:
        cap = self.mat.shape[0]
        if need <= cap:
            return
        new = max(need, cap * 2, 256)

        def ext(a: np.ndarray) -> np.ndarray:
            b = np.zeros((new,) + a.shape[1:], dtype=a.dtype)
            b[: self.n] = a[: self.n]
            return b

        self.mat, self.ids, self.owner_code = ext(self.mat), ext(self.ids), ext(self.owner_code)
        self.family, self.active, self.ts = ext(self.family), ext(self.active), ext(self.ts)


class VectorIndex:
    def __init__(self, db: Database, dim: int):
        self.db = db
        self.dim = dim
        self._lock = threading.RLock()
        self._t: dict[str, _Table] = {}
        self._owners: dict[str, int] = {"": 0}  # владелец → код (сравнение чисел, а не строк)
        for unit_type in _LOADERS:
            self._load(unit_type)

    def _code(self, owner: str | None) -> int:
        return self._owners.setdefault(owner or "", len(self._owners))

    def _put(self, t: _Table, unit_id: int, vec: np.ndarray, owner: str | None, visibility: str,
             active: bool, ts: float) -> None:
        i = t.pos.get(unit_id)
        if i is None:
            t.grow(t.n + 1)
            i = t.n
            t.n += 1
            t.pos[unit_id] = i
            t.ids[i] = unit_id
        t.mat[i] = vec
        t.owner_code[i] = self._code(owner)
        t.family[i] = visibility == "family"
        t.active[i] = active
        t.ts[i] = ts or 0.0

    def _load(self, unit_type: str) -> None:
        t = _Table(self.dim)
        for r in self.db.query(_LOADERS[unit_type]):
            v = from_blob(r["embedding"])
            if v is None or v.shape[0] != self.dim:
                continue  # вектор от другой модели — переиндексируем позже
            self._put(t, r["id"], v, r["owner"], r["visibility"], bool(r["active"]), r["ts"] or 0.0)
        self._t[unit_type] = t

    def add(self, unit_type: str, unit_id: int, vec: np.ndarray, *, owner: str | None,
            visibility: str, active: bool = True, ts: float = 0.0) -> None:
        with self._lock:
            self._put(self._t[unit_type], unit_id, vec.astype(np.float32), owner, visibility, active, ts)

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
        """Удаление (редко — «забудь»): последняя строка переезжает на место удалённой."""
        with self._lock:
            t = self._t[unit_type]
            i = t.pos.pop(unit_id, None)
            if i is None:
                return
            last = t.n - 1
            if i != last:
                for a in (t.mat, t.ids, t.owner_code, t.family, t.active, t.ts):
                    a[i] = a[last]
                t.pos[int(t.ids[i])] = i
            t.mat[last] = 0.0
            t.n = last

    def get(self, unit_type: str, unit_id: int) -> np.ndarray | None:
        t = self._t[unit_type]
        i = t.pos.get(unit_id)
        return None if i is None else t.mat[i].copy()

    def get_many(self, unit_type: str, unit_ids: list[int]) -> tuple[list[int], np.ndarray]:
        """Векторы набора записей одной матрицей: (какие нашлись, матрица [m, dim])."""
        t = self._t.get(unit_type)
        if t is None:
            return [], np.zeros((0, self.dim), dtype=np.float32)
        found = [(u, t.pos[u]) for u in unit_ids if u in t.pos]
        if not found:
            return [], np.zeros((0, self.dim), dtype=np.float32)
        return [u for u, _ in found], t.mat[[i for _, i in found]]

    def search(self, unit_type: str, query: np.ndarray, viewer: str, *, k: int = 40,
               include_inactive: bool = False, ts_range: tuple[float, float] | None = None,
               stats: dict | None = None) -> list[tuple[int, float]]:
        """Топ-k (id, косинус) среди видимых viewer записей.
        stats — если передан словарь, в него кладутся mu/sd/n косинусов по всем видимым записям."""
        with self._lock:
            t = self._t[unit_type]
            n = t.n
            if not n or k <= 0:
                return []
            mask = t.family[:n] | (t.owner_code[:n] == self._owners.get(viewer, -1))
            if not include_inactive:
                mask &= t.active[:n]
            if ts_range is not None:
                ts = t.ts[:n]
                mask &= (ts >= ts_range[0]) & (ts < ts_range[1])
            m = int(mask.sum())
            if not m:
                return []
            raw = t.mat[:n] @ query.astype(np.float32)
            if stats is not None:
                vis = raw[mask]
                stats.update(mu=float(vis.mean()), sd=float(vis.std()), n=int(vis.size))
            sims = np.where(mask, raw, -np.inf)
            k = min(k, m)
            top = np.argpartition(-sims, k - 1)[:k]
            top = top[np.argsort(-sims[top])]
            return [(int(t.ids[i]), float(sims[i])) for i in top]

    def count(self, unit_type: str) -> int:
        return self._t[unit_type].n
