"""Замок и ключи.

По умолчанию Джарвис свободен. Под замком только то, что нельзя отменить и что касается денег или
других людей:
  money           — оплата и покупки;
  message         — сообщения и звонки от имени человека;
  delete          — удаление его личных данных;
  relative_device — действия на устройствах других членов семьи.
Ключи выдаёт сам человек (только своей репликой — не из текста сайтов и не по инициативе Джарвиса):
на раз, на сегодня, на неделю или навсегда; для денег — с лимитом. Отзываются одной фразой.
Проверка ключей — в коде «органов», а не просьбой в промпте.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from cogmem.memory import CognitiveMemory
from cogmem.retrieve.recall import fmt_date

SCOPES = {
    "money": "оплата и покупки",
    "message": "сообщения и звонки от твоего имени",
    "delete": "удаление личных данных",
    "relative_device": "устройства других членов семьи",
}
DURATIONS = {"once", "today", "week", "forever"}
TRUST_SUGGEST_AFTER = 20


@dataclass
class Key:
    id: int
    person_id: str
    scope: str
    target: str
    limit_eur: float | None
    spent_eur: float
    uses: int
    once: bool
    expires_at: float | None

    def describe(self, tz: str) -> str:
        bits = [SCOPES[self.scope]]
        if self.target:
            bits.append(f"для «{self.target}»")
        if self.limit_eur is not None:
            bits.append(f"лимит {self.limit_eur:g} € (потрачено {self.spent_eur:g} €)")
        if self.once:
            bits.append("на один раз")
        elif self.expires_at:
            bits.append(f"до {fmt_date(self.expires_at, tz, True)}")
        else:
            bits.append("навсегда")
        return f"[K{self.id}] " + ", ".join(bits)


def _row(r) -> Key:
    return Key(r["id"], r["person_id"], r["scope"], r["target"], r["limit_eur"], r["spent_eur"], r["uses"],
               bool(r["once"]), r["expires_at"])


class KeyRing:
    def __init__(self, memory: CognitiveMemory):
        self.m = memory

    def _tz(self, person_id: str) -> str:
        p = self.m.person(person_id)
        return p["timezone"] if p else "Europe/Paris"

    def grant(self, person_id: str, scope: str, *, target: str = "", limit_eur: float | None = None,
              duration: str = "forever", evidence_event_id: int | None = None) -> Key:
        if scope not in SCOPES:
            raise ValueError(f"неизвестная область {scope}")
        duration = duration if duration in DURATIONS else "once"
        now = self.m.ctx.clock.now()
        tz = ZoneInfo(self._tz(person_id))
        expires = None
        if duration == "today":
            local = datetime.fromtimestamp(now, tz)
            expires = datetime.combine(local.date() + timedelta(days=1), dtime.min, tzinfo=tz).timestamp()
        elif duration == "week":
            expires = now + 7 * 86400
        kid = self.m.ctx.db.execute(
            "INSERT INTO keys(person_id, scope, target, limit_eur, once, expires_at, granted_at, evidence_event_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (person_id, scope, (target or "").strip().lower(), limit_eur, int(duration == "once"), expires, now,
             evidence_event_id)).lastrowid
        self.m.ctx.audit.log("user", "grant", "key", kid, after={"scope": scope, "target": target,
                                                                  "limit": limit_eur, "duration": duration})
        return self.get(kid)

    def get(self, key_id: int) -> Key | None:
        r = self.m.ctx.db.one("SELECT * FROM keys WHERE id=?", (key_id,))
        return None if r is None else _row(r)

    def revoke(self, person_id: str, key_id: int | None = None, scope: str | None = None) -> int:
        now = self.m.ctx.clock.now()
        if key_id is not None:
            cur = self.m.ctx.db.execute("UPDATE keys SET revoked_at=? WHERE id=? AND person_id=? AND revoked_at IS NULL",
                                        (now, key_id, person_id))
        else:
            cur = self.m.ctx.db.execute(
                "UPDATE keys SET revoked_at=? WHERE person_id=? AND revoked_at IS NULL" + (" AND scope=?" if scope else ""),
                (now, person_id, scope) if scope else (now, person_id))
        self.m.ctx.audit.log("user", "revoke", "key", key_id, after={"scope": scope, "count": cur.rowcount})
        return cur.rowcount

    def active(self, person_id: str) -> list[Key]:
        now = self.m.ctx.clock.now()
        return [_row(r) for r in self.m.ctx.db.query(
            "SELECT * FROM keys WHERE person_id=? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?) "
            "AND NOT (once=1 AND uses>0) ORDER BY id", (person_id, now))]

    def find(self, person_id: str, scope: str, *, target: str = "", amount_eur: float | None = None) -> Key | None:
        """Подходящий действующий ключ или None."""
        t = (target or "").strip().lower()
        for k in self.active(person_id):
            if k.scope != scope:
                continue
            if k.target and k.target not in t and t not in k.target:
                continue
            if k.limit_eur is not None:
                if amount_eur is None or k.spent_eur + amount_eur > k.limit_eur + 1e-9:
                    continue
            return k
        return None

    def use(self, key: Key, amount_eur: float | None = None) -> None:
        self.m.ctx.db.execute("UPDATE keys SET uses=uses+1, spent_eur=spent_eur+? WHERE id=?",
                              (amount_eur or 0.0, key.id))
        self.m.ctx.audit.log("brain", "use", "key", key.id, after={"amount": amount_eur})

    def lines(self, person_id: str) -> list[str]:
        tz = self._tz(person_id)
        return [k.describe(tz) for k in self.active(person_id)]

    def trust_suggestions(self, person_id: str) -> list[str]:
        """Где Джарвис уже заслужил больше доверия (много успешных использований, ни одного отзыва)."""
        out = []
        for r in self.m.ctx.db.query(
            "SELECT scope, SUM(uses) AS u, SUM(revoked_at IS NOT NULL AND uses=0) AS bad FROM keys "
            "WHERE person_id=? GROUP BY scope", (person_id,)):
            if (r["u"] or 0) >= TRUST_SUGGEST_AFTER and not r["bad"]:
                out.append(f"{SCOPES[r['scope']]}: {r['u']} успешных действий без отмен — можно предложить "
                           f"расширить ключ")
        return out
