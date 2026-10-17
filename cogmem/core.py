"""Ядро — то, что всегда в контексте (как «знание о себе и близком человеке»).

Профиль человека НЕ пишется языковой моделью свободным текстом (это источник «дрейфа»),
а детерминированно собирается из самых важных и активных актуальных фактов о нём.
Поэтому ядро всегда можно объяснить: каждая строка — факт с ID и источником.
Пересобирается при старте сессии и во время «сна»; меняется — новая версия.
"""

from __future__ import annotations

from cogmem.activation import base_levels, squash
from cogmem.context import Ctx
from cogmem.facts import FactStore
from cogmem.text.ru import estimate_tokens
from cogmem.types import ref


class CoreBlocks:
    def __init__(self, ctx: Ctx, facts: FactStore):
        self.ctx = ctx
        self.facts = facts

    def get(self, person_id: str, kind: str = "profile") -> str:
        r = self.ctx.db.one("SELECT content FROM core_blocks WHERE person_id=? AND kind=?", (person_id, kind))
        return r["content"] if r else ""

    def version(self, person_id: str, kind: str = "profile") -> int:
        return self.ctx.db.scalar(
            "SELECT version FROM core_blocks WHERE person_id=? AND kind=?", (person_id, kind)) or 0

    def _save(self, person_id: str, kind: str, content: str, reason: str) -> bool:
        if self.get(person_id, kind) == content and self.version(person_id, kind) > 0:
            return False
        now = self.ctx.clock.now()
        v = self.version(person_id, kind) + 1
        with self.ctx.db.tx():
            self.ctx.db.execute(
                "INSERT INTO core_blocks(person_id, kind, content, version, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(person_id, kind) DO UPDATE SET content=excluded.content, version=excluded.version, "
                "updated_at=excluded.updated_at", (person_id, kind, content, v, now))
            self.ctx.db.execute(
                "INSERT INTO core_versions(person_id, kind, version, content, ts, reason) VALUES (?,?,?,?,?,?)",
                (person_id, kind, v, content, now, reason))
        return True

    def rebuild_profile(self, person_id: str, reason: str = "") -> str:
        """Собрать профиль из фактов о человеке и его близких (в пределах бюджета токенов)."""
        p = self.ctx.db.one("SELECT name, role, timezone, entity_id FROM persons WHERE id=?", (person_id,))
        if p is None:
            return ""
        header = f"Собеседник: {p['name']} (роль: {p['role']}, часовой пояс: {p['timezone']})."
        lines: list[tuple[float, str]] = []
        rows = self.ctx.db.query(
            "SELECT id, statement, importance, subject_id FROM facts WHERE invalidated_at IS NULL AND status='active' "
            "AND (visibility='family' OR owner_person=?)", (person_id,))
        if rows:
            act = base_levels(self.ctx, [("fact", r["id"]) for r in rows])
            for r in rows:
                about_self = 1.0 if r["subject_id"] == p["entity_id"] else 0.6
                a = squash(act[("fact", r["id"])], self.ctx.cfg.activation_tau)
                score = about_self * (0.65 * r["importance"] + 0.35 * a)
                lines.append((score, f"- [{ref('fact', r['id'])}] {r['statement']}"))
        lines.sort(key=lambda x: -x[0])
        budget = self.ctx.cfg.core_max_tokens - estimate_tokens(header)
        body = []
        for _, line in lines:
            cost = estimate_tokens(line)
            if cost > budget:
                continue
            body.append(line)
            budget -= cost
        content = header + ("\nГлавное о нём и его близких:\n" + "\n".join(body) if body else "")
        self._save(person_id, "profile", content, reason or "пересборка")
        return content
