"""Семантическая память: факты с двухвременной моделью и «слотами».

Факт никогда не стирается при изменении мира — он «закрывается» (valid_to, invalidated_at)
и получает ссылку на заменивший его факт. Так Джарвис знает и «как сейчас», и «как было».
Стереть факт можно только по прямой просьбе человека («забудь»).

Слот — (о ком, отношение). У одних отношений значение одно («живёт в», «день рождения», «работает»):
новое значение заменяет старое. У других — много («любит», «аллергия»): новое добавляется.
Решает это код (is_single_valued), а не языковая модель.

Время: valid_from/valid_to — когда верно в мире; observed_at — когда это было сказано (время реплик);
recorded_at/invalidated_at — когда Джарвис узнал и когда перестал считать актуальным.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from cogmem.context import Ctx
from cogmem.govern.access import can_see, sql_visible
from cogmem.store import to_blob
from cogmem.text import ru


@dataclass
class Fact:
    id: int
    subject_id: int
    predicate: str
    object_id: int | None
    value: str | None
    statement: str
    valid_from: float | None
    valid_to: float | None
    recorded_at: float
    invalidated_at: float | None
    superseded_by: int | None
    confidence: float
    importance: float
    protected: bool
    status: str
    source_kind: str
    source_event_ids: list[int]
    source_episode_id: int | None
    owner_person: str | None
    visibility: str
    observed_at: float | None = None
    replaces_id: int | None = None

    @property
    def current(self) -> bool:
        return self.invalidated_at is None and self.status == "active"

    @property
    def world_time(self) -> float:
        """Когда это стало верным (или хотя бы когда об этом сказали)."""
        return self.valid_from or self.observed_at or self.recorded_at


def _row_to_fact(r) -> Fact:
    keys = r.keys()
    return Fact(
        r["id"], r["subject_id"], r["predicate"], r["object_id"], r["value"], r["statement"], r["valid_from"],
        r["valid_to"], r["recorded_at"], r["invalidated_at"], r["superseded_by"], r["confidence"], r["importance"],
        bool(r["protected"]), r["status"], r["source_kind"], json.loads(r["source_event_ids"]),
        r["source_episode_id"], r["owner_person"], r["visibility"],
        r["observed_at"] if "observed_at" in keys else None, r["replaces_id"] if "replaces_id" in keys else None,
    )


def norm_predicate(p: str) -> str:
    return " ".join(ru.words(p))[:80] or "заметка"


# Отношения с единственным значением в каждый момент времени (по основам слов отношения).
_SINGLE_PHRASES = [
    "живёт в", "живет", "проживает", "живёт", "город", "адрес", "переехал в", "место жительства",
    "работает", "работает в", "место работы", "должность", "профессия", "работодатель",
    "день рождения", "дата рождения", "родился", "родилась", "год рождения", "возраст",
    "телефон", "номер телефона", "email", "почта", "электронная почта",
    "семейное положение", "женат на", "замужем за", "супруг", "супруга", "жена", "муж",
    "зовут", "имя", "фамилия", "отчество", "полное имя",
    "рост", "вес", "размер обуви", "размер одежды", "группа крови", "часовой пояс", "гражданство",
    "учится в", "школа", "класс", "университет",
    "любимый цвет", "любимое блюдо", "любимый напиток", "любимая еда", "любимый фильм",
    "машина", "автомобиль",
]
_SINGLE = {" ".join(ru.stem(w) for w in ru.words(p)) for p in _SINGLE_PHRASES}
_MULTI_HINT = {ru.stem(w) for w in ("любит", "не", "аллергия", "хобби", "увлекается", "дети", "друг", "интересуется",
                                    "боится", "умеет", "знает", "был", "была", "посетил", "заметка")}


def is_single_valued(predicate: str) -> bool:
    """У слота одно значение (новое заменяет старое)?"""
    stems = [ru.stem(w) for w in ru.words(predicate)]
    if not stems:
        return False
    key = " ".join(stems)
    if key in _SINGLE:
        return True
    if set(stems) & _MULTI_HINT:
        return False
    return any(key.startswith(s + " ") for s in _SINGLE)


def _norm_val(v: str | None) -> str:
    return ru.fts_text(v or "")


class FactStore:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def get(self, fact_id: int) -> Fact | None:
        r = self.ctx.db.one("SELECT * FROM facts WHERE id=?", (fact_id,))
        return None if r is None else _row_to_fact(r)

    def head(self, fact_id: int) -> Fact | None:
        """Последняя версия факта (по цепочке «заменён на»)."""
        f = self.get(fact_id)
        for _ in range(50):
            if f is None or f.superseded_by is None or f.current:
                return f
            nxt = self.get(f.superseded_by)
            if nxt is None:
                return f
            f = nxt
        return f

    def visible(self, fact: Fact, viewer: str) -> bool:
        return can_see(viewer, fact.owner_person, fact.visibility)

    def current_for(self, subject_id: int, viewer: str, predicate: str | None = None) -> list[Fact]:
        sql = ("SELECT * FROM facts WHERE subject_id=? AND invalidated_at IS NULL AND status='active' AND "
               + sql_visible("owner_person"))
        params: list = [subject_id, viewer]
        if predicate:
            sql += " AND predicate=?"
            params.append(norm_predicate(predicate))
        return [_row_to_fact(r) for r in self.ctx.db.query(sql + " ORDER BY importance DESC, id", tuple(params))]

    def history(self, subject_id: int, viewer: str) -> list[Fact]:
        rows = self.ctx.db.query(
            "SELECT * FROM facts WHERE subject_id=? AND " + sql_visible("owner_person") + " ORDER BY recorded_at, id",
            (subject_id, viewer),
        )
        return [_row_to_fact(r) for r in rows]

    def find_duplicate(self, subject_id: int, predicate: str, object_id: int | None, value: str | None,
                       statement: str, viewer: str) -> Fact | None:
        """Тот же факт уже есть и актуален? Дубль — только при совпадении значения/объекта в том же слоте
        или дословно того же утверждения (пустые значения у обоих — НЕ дубль: «любит кофе» ≠ «любит джаз»)."""
        pred = norm_predicate(predicate)
        stmt_norm = ru.fts_text(statement)
        val = _norm_val(value)
        for f in self.current_for(subject_id, viewer):
            if stmt_norm and ru.fts_text(f.statement) == stmt_norm:
                return f
            if f.predicate != pred:
                continue
            if object_id is not None and f.object_id == object_id and (not val or _norm_val(f.value) in ("", val)):
                return f
            if val and _norm_val(f.value) == val and (object_id is None or f.object_id in (None, object_id)):
                return f
        return None

    def add(self, *, subject_id: int, predicate: str, statement: str, owner: str | None,
            object_id: int | None = None, value: str | None = None, valid_from: float | None = None,
            valid_to: float | None = None, confidence: float = 0.8, importance: float = 0.4,
            source_kind: str = "user_stated", source_event_ids: list[int] | None = None,
            source_episode_id: int | None = None, visibility: str = "private", protected: bool = False,
            status: str = "active", actor: str = "subconscious", reason: str = "",
            observed_at: float | None = None, replaces_id: int | None = None,
            vec: np.ndarray | None = None) -> int:
        now = self.ctx.clock.now()
        statement = statement.strip()
        if vec is None:
            vec = self.ctx.embed1(statement)
        with self.ctx.db.tx():
            cur = self.ctx.db.execute(
                "INSERT INTO facts(subject_id, predicate, object_id, value, statement, valid_from, valid_to, recorded_at, "
                "confidence, importance, protected, status, source_kind, source_event_ids, source_episode_id, "
                "owner_person, visibility, observed_at, replaces_id, embedding) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (subject_id, norm_predicate(predicate), object_id, value, statement, valid_from, valid_to, now,
                 confidence, importance, int(protected), status, source_kind,
                 json.dumps(sorted(set(source_event_ids or []))), source_episode_id, owner, visibility,
                 observed_at if observed_at is not None else now, replaces_id, to_blob(vec)),
            )
            fid = cur.lastrowid
            self.ctx.fts_add("fact", fid, statement)
            self.ctx.trace("fact", fid, "created", now)
            self.ctx.db.execute(
                "INSERT OR IGNORE INTO links(src_type, src_id, dst_type, dst_id, kind, weight, updated_at) "
                "VALUES ('fact',?,'entity',?,'about',0.9,?)", (fid, subject_id, now))
            if object_id:
                self.ctx.db.execute(
                    "INSERT OR IGNORE INTO links(src_type, src_id, dst_type, dst_id, kind, weight, updated_at) "
                    "VALUES ('fact',?,'entity',?,'mentions',0.7,?)", (fid, object_id, now))
            self.ctx.audit.log(actor, "create", "fact", fid,
                               after={"statement": statement, "source": source_kind, "status": status}, reason=reason)
        self.ctx.index.add("fact", fid, vec, owner=owner, visibility=visibility,
                           active=(status == "active"), ts=now)
        return fid

    def invalidate(self, fact_id: int, *, superseded_by: int | None = None, valid_to: float | None = None,
                   actor: str, reason: str = "") -> None:
        """Закрыть факт (мир изменился или факт оказался неверным). Не удаляет."""
        f = self.get(fact_id)
        if f is None or f.invalidated_at is not None:
            return
        now = self.ctx.clock.now()
        with self.ctx.db.tx():
            self.ctx.db.execute(
                "UPDATE facts SET invalidated_at=?, superseded_by=?, valid_to=COALESCE(valid_to, ?) WHERE id=?",
                (now, superseded_by, valid_to if valid_to is not None else now, fact_id),
            )
            self.ctx.audit.log(actor, "invalidate", "fact", fact_id, before={"statement": f.statement},
                               after={"superseded_by": superseded_by}, reason=reason)
        self.ctx.index.set_active("fact", fact_id, False)

    def set_status(self, fact_id: int, status: str, *, actor: str, reason: str = "") -> None:
        f = self.get(fact_id)
        if f is None or f.status == status:
            return
        with self.ctx.db.tx():
            self.ctx.db.execute("UPDATE facts SET status=? WHERE id=?", (status, fact_id))
            self.ctx.audit.log(actor, "status", "fact", fact_id, before=f.status, after=status, reason=reason)
        self.ctx.index.set_active("fact", fact_id, status == "active" and f.invalidated_at is None)

    def set_confidence(self, fact_id: int, confidence: float, *, actor: str, reason: str = "") -> None:
        f = self.get(fact_id)
        if f is None:
            return
        with self.ctx.db.tx():
            self.ctx.db.execute("UPDATE facts SET confidence=? WHERE id=?", (confidence, fact_id))
            self.ctx.audit.log(actor, "confidence", "fact", fact_id, before=f.confidence, after=confidence,
                               reason=reason)

    def add_evidence(self, fact_id: int, event_ids: list[int]) -> None:
        f = self.get(fact_id)
        if f is None:
            return
        merged = sorted(set(f.source_event_ids) | set(event_ids))
        self.ctx.db.execute("UPDATE facts SET source_event_ids=? WHERE id=?", (json.dumps(merged), fact_id))
        self.ctx.trace("fact", fact_id, "retrieved")

    def purge(self, fact_id: int) -> str | None:
        """Настоящее удаление («забудь»): сам факт, его связи, следы, индекс, содержимое аудита,
        строки в истории ядра. Возвращает владельца (чтобы пересобрать его профиль) или None."""
        f = self.get(fact_id)
        if f is None:
            return None
        tag = f"[F{fact_id}]"
        with self.ctx.db.tx():
            self.ctx.db.execute("DELETE FROM facts WHERE id=?", (fact_id,))
            self.ctx.db.execute("DELETE FROM links WHERE (src_type='fact' AND src_id=?) OR (dst_type='fact' AND dst_id=?)",
                                (fact_id, fact_id))
            self.ctx.db.execute("DELETE FROM access_traces WHERE unit_type='fact' AND unit_id=?", (fact_id,))
            self.ctx.db.execute("UPDATE facts SET superseded_by=NULL WHERE superseded_by=?", (fact_id,))
            self.ctx.db.execute("UPDATE facts SET replaces_id=NULL WHERE replaces_id=?", (fact_id,))
            self.ctx.fts_remove("fact", fact_id)
            scrub_audit(self.ctx, "fact", fact_id)
            for r in self.ctx.db.query("SELECT person_id, kind, version, content FROM core_versions WHERE content LIKE ?",
                                       (f"%{tag}%",)):
                cleaned = "\n".join(ln for ln in r["content"].split("\n") if tag not in ln)
                self.ctx.db.execute("UPDATE core_versions SET content=? WHERE person_id=? AND kind=? AND version=?",
                                    (cleaned, r["person_id"], r["kind"], r["version"]))
            for r in self.ctx.db.query("SELECT person_id, kind, content FROM core_blocks WHERE content LIKE ?",
                                       (f"%{tag}%",)):
                cleaned = "\n".join(ln for ln in r["content"].split("\n") if tag not in ln)
                self.ctx.db.execute("UPDATE core_blocks SET content=? WHERE person_id=? AND kind=?",
                                    (cleaned, r["person_id"], r["kind"]))
        self.ctx.index.remove("fact", fact_id)
        return f.owner_person


def scrub_audit(ctx: Ctx, unit_type: str, unit_id: int) -> None:
    """Стереть содержимое из аудита единицы (сами записи «кто/когда/что сделал» остаются)."""
    ctx.db.execute("UPDATE memory_audit SET before=NULL, after=NULL, reason='[удалено по просьбе]' "
                   "WHERE unit_type=? AND unit_id=?", (unit_type, unit_id))
