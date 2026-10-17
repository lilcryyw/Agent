"""Цели — долгие задачи, которые Джарвис держит в голове днями («подключить новый телефон»).

В отличие от намерений-напоминаний, цель — это то, что он сам доводит до конца: шаги и заметки,
статус, когда к ней вернуться. Пульс инициативы смотрит на цели с наступившим сроком проверки.
"""

from __future__ import annotations

from dataclasses import dataclass

from cogmem.context import Ctx
from cogmem.retrieve.recall import fmt_date
from cogmem.types import ref


@dataclass
class Goal:
    id: int
    person_id: str
    title: str
    notes: str
    status: str
    next_check: float | None


def _row(r) -> Goal:
    return Goal(r["id"], r["person_id"], r["title"], r["notes"], r["status"], r["next_check"])


class Goals:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def add(self, person_id: str, title: str, notes: str = "", next_check: float | None = None) -> int:
        now = self.ctx.clock.now()
        gid = self.ctx.db.execute(
            "INSERT INTO goals(person_id, title, notes, next_check, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (person_id, title.strip(), notes.strip(), next_check, now, now)).lastrowid
        self.ctx.audit.log("brain", "create", "goal", gid, after={"title": title})
        return gid

    def get(self, goal_id: int) -> Goal | None:
        r = self.ctx.db.one("SELECT * FROM goals WHERE id=?", (goal_id,))
        return None if r is None else _row(r)

    def update(self, goal_id: int, *, status: str | None = None, notes: str | None = None,
               next_check: float | None = None, title: str | None = None) -> None:
        g = self.get(goal_id)
        if g is None:
            return
        self.ctx.db.execute(
            "UPDATE goals SET status=?, notes=?, next_check=?, title=?, updated_at=? WHERE id=?",
            (status or g.status, g.notes if notes is None else notes, next_check if next_check is not None
             else g.next_check, title or g.title, self.ctx.clock.now(), goal_id))
        self.ctx.audit.log("brain", "update", "goal", goal_id, after={"status": status, "notes": notes})

    def active(self, person_id: str) -> list[Goal]:
        return [_row(r) for r in self.ctx.db.query(
            "SELECT * FROM goals WHERE person_id=? AND status IN ('active','blocked') ORDER BY id", (person_id,))]

    def due(self, person_id: str) -> list[Goal]:
        return [_row(r) for r in self.ctx.db.query(
            "SELECT * FROM goals WHERE person_id=? AND status='active' AND next_check IS NOT NULL AND next_check<=? "
            "ORDER BY next_check", (person_id, self.ctx.clock.now()))]

    def lines(self, person_id: str) -> list[str]:
        tz = self.ctx.db.scalar("SELECT timezone FROM persons WHERE id=?", (person_id,)) or "Europe/Paris"
        out = []
        for g in self.active(person_id)[:6]:
            when = f"; вернуться {fmt_date(g.next_check, tz, True)}" if g.next_check else ""
            st = " [ЗАБЛОКИРОВАНА]" if g.status == "blocked" else ""
            out.append(f"[{ref('goal', g.id)}] {g.title}{st}{when}" + (f" — {g.notes[:200]}" if g.notes else ""))
        return out
