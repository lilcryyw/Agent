"""Проспективная память: намерения «не забыть сделать» (по времени, человеку, месту, событию)."""

from __future__ import annotations

from dataclasses import dataclass

from cogmem.context import Ctx
from cogmem.retrieve.recall import fmt_date
from cogmem.text import ru
from cogmem.types import ref


@dataclass
class Intention:
    id: int
    person_id: str
    trigger_kind: str
    due_ts: float | None
    trigger_text: str
    action_text: str
    recurrence: str | None
    status: str


def _row(r) -> Intention:
    return Intention(r["id"], r["person_id"], r["trigger_kind"], r["due_ts"], r["trigger_text"], r["action_text"],
                     r["recurrence"], r["status"])


class Intentions:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def add(self, person_id: str, action_text: str, *, trigger_kind: str = "time", due_ts: float | None = None,
            trigger_text: str = "", recurrence: str | None = None, source_event_id: int | None = None,
            actor: str = "brain") -> int:
        now = self.ctx.clock.now()
        # Идемпотентность: такое же активное намерение уже есть — не дублируем.
        # С конкретным сроком — дубль в любом статусе (уже сработавшее не повторяем);
        # без срока — только среди ещё не выполненных.
        dup = self.ctx.db.one(
            "SELECT id FROM intentions WHERE person_id=? AND action_text=? AND "
            "((due_ts IS NOT NULL AND due_ts=?) OR (due_ts IS NULL AND ? IS NULL AND status='pending'))",
            (person_id, action_text.strip(), due_ts, due_ts))
        if dup:
            return dup["id"]
        cur = self.ctx.db.execute(
            "INSERT INTO intentions(person_id, trigger_kind, due_ts, trigger_text, action_text, recurrence, "
            "source_event_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (person_id, trigger_kind, due_ts, trigger_text, action_text.strip(), recurrence, source_event_id, now, now))
        iid = cur.lastrowid
        self.ctx.fts_add("intention", iid, f"{trigger_text} {action_text}")
        self.ctx.audit.log(actor, "create", "intention", iid, after={"action": action_text, "due": due_ts})
        return iid

    def set_status(self, intention_id: int, status: str, actor: str = "brain") -> None:
        self.ctx.db.execute("UPDATE intentions SET status=?, updated_at=? WHERE id=?",
                            (status, self.ctx.clock.now(), intention_id))
        self.ctx.audit.log(actor, "status", "intention", intention_id, after=status)

    def due(self, now: float | None = None) -> list[Intention]:
        """Намерения по времени, которым пора сработать (для планировщика)."""
        now = self.ctx.clock.now() if now is None else now
        return [_row(r) for r in self.ctx.db.query(
            "SELECT * FROM intentions WHERE status='pending' AND trigger_kind='time' AND due_ts<=? ORDER BY due_ts",
            (now,))]

    def relevant(self, person_id: str, cue: str, horizon_days: float = 3.0) -> list[str]:
        """Строки для рабочей памяти: близкие по сроку + совпадающие с темой разговора."""
        now = self.ctx.clock.now()
        tz = self.ctx.db.scalar("SELECT timezone FROM persons WHERE id=?", (person_id,)) or "Europe/Paris"
        rows = self.ctx.db.query(
            "SELECT * FROM intentions WHERE person_id=? AND status='pending' AND trigger_kind='time' AND due_ts<=? "
            "ORDER BY due_ts LIMIT 5", (person_id, now + horizon_days * 86400))
        found = {r["id"]: _row(r) for r in rows}
        q = ru.fts_query(cue)
        if q:
            for r in self.ctx.db.query(
                "SELECT i.* FROM fts f JOIN intentions i ON i.id=f.unit_id WHERE f.unit_type='intention' "
                "AND fts MATCH ? AND i.person_id=? AND i.status='pending' LIMIT 5", (q, person_id)):
                found.setdefault(r["id"], _row(r))
        out = []
        for it in found.values():
            when = f"к {fmt_date(it.due_ts, tz, with_time=True)}" if it.due_ts else (it.trigger_text or "при случае")
            overdue = " (ПРОСРОЧЕНО)" if it.due_ts and it.due_ts < now else ""
            out.append(f"[{ref('intention', it.id)}] {when}{overdue}: {it.action_text}")
        return out
