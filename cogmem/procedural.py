"""Процедурная память: рецепты действий (по мотивам Memp, 2025).

Удачная цепочка действий сохраняется как рецепт. В следующий раз Джарвис выполняет её
по шагам, не рассуждая заново и не «разглядывая» экран — быстрее и дешевле.
Рецепт со счётчиком успехов/провалов; после серии провалов помечается сломанным.
"""

from __future__ import annotations

import json

from cogmem.context import Ctx
from cogmem.store import to_blob
from cogmem.types import ref

BROKEN_AFTER_FAILURES = 3


class Procedures:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def save(self, person_id: str | None, name: str, trigger_text: str, steps: list[dict | str], *,
             visibility: str = "private", status: str = "active", actor: str = "brain") -> int:
        now = self.ctx.clock.now()
        vec = self.ctx.embed1(f"{name}. {trigger_text}")
        existing = self.ctx.db.one("SELECT id, version FROM procedures WHERE name=? AND COALESCE(person_id,'')=?",
                                   (name, person_id or ""))
        with self.ctx.db.tx():
            if existing:
                pid = existing["id"]
                self.ctx.db.execute(
                    "UPDATE procedures SET trigger_text=?, steps=?, version=version+1, status=?, embedding=?, "
                    "failures=0, updated_at=? WHERE id=?",
                    (trigger_text, json.dumps(steps, ensure_ascii=False), status, to_blob(vec), now, pid))
            else:
                pid = self.ctx.db.execute(
                    "INSERT INTO procedures(person_id, name, trigger_text, steps, status, visibility, embedding, "
                    "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (person_id, name, trigger_text, json.dumps(steps, ensure_ascii=False), status, visibility,
                     to_blob(vec), now, now)).lastrowid
            self.ctx.fts_add("procedure", pid, f"{name} {trigger_text}")
            self.ctx.audit.log(actor, "save", "procedure", pid, after={"name": name, "steps": steps})
        self.ctx.index.add("procedure", pid, vec, owner=person_id, visibility=visibility, ts=now)
        return pid

    def outcome(self, procedure_id: int, success: bool) -> None:
        col = "successes" if success else "failures"
        now = self.ctx.clock.now()
        self.ctx.db.execute(f"UPDATE procedures SET {col}={col}+1, last_used=?, updated_at=? WHERE id=?",
                            (now, now, procedure_id))
        r = self.ctx.db.one("SELECT failures, status FROM procedures WHERE id=?", (procedure_id,))
        if r and not success and r["failures"] >= BROKEN_AFTER_FAILURES and r["status"] == "active":
            self.ctx.db.execute("UPDATE procedures SET status='broken' WHERE id=?", (procedure_id,))
            self.ctx.audit.log("brain", "broken", "procedure", procedure_id, reason="серия провалов")
            self.ctx.index.set_active("procedure", procedure_id, False)
        self.ctx.trace("procedure", procedure_id, "used")

    def relevant(self, viewer: str, cue: str, k: int = 2, min_sim: float = 0.45) -> list[str]:
        qv = self.ctx.embed1(cue)
        out = []
        for pid, sim in self.ctx.index.search("procedure", qv, viewer, k=k):
            if sim < min_sim:
                continue
            r = self.ctx.db.one("SELECT name, steps, successes, failures FROM procedures WHERE id=?", (pid,))
            steps = json.loads(r["steps"])
            short = "; ".join(s if isinstance(s, str) else json.dumps(s, ensure_ascii=False) for s in steps)[:300]
            out.append(f"[{ref('procedure', pid)}] {r['name']} (успехов {r['successes']}, провалов {r['failures']}): "
                       f"{short}")
        return out
