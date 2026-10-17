"""Шлюз записи (по мотивам SSGM, 2026): ИИ только ПРЕДЛАГАЕТ изменения памяти, применяет их код.

Проверки:
  • доказательства — только реплики этого эпизода (выдуманные ID отбрасываются);
  • источник определяется по репликам, а не по словам модели: сказал человек / Джарвис / внешний текст;
  • внешние тексты: уверенность ≤ 0.5, никогда не «защищённые»;
  • заменить можно только видимый и актуальный факт; защищённый — только через подтверждение человека;
  • дубликаты не создаются (подтверждение вместо повтора);
  • запрещённое к хранению (пароли, карты) отбрасывается;
  • всё — в аудит.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from cogmem.consolidate.schemas import EpisodeEncoding, FactProposal
from cogmem.context import Ctx
from cogmem.entities import EntityStore
from cogmem.facts import FactStore
from cogmem.prospective import Intentions
from cogmem.store import to_blob

log = logging.getLogger(__name__)

_SECRET = re.compile(r"(парол|password|pin[- ]?код|cvv|cvc|номер карты|\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b)",
                     re.IGNORECASE)
SELF_WORDS = {"я", "собеседник", "пользователь", "меня", "мне"}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return lo


def parse_local_date(s: str | None, tz: str) -> float | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip()[:16], fmt).replace(tzinfo=ZoneInfo(tz)).timestamp()
        except ValueError:
            continue
    return None


@dataclass
class GateReport:
    facts_added: list[int] = field(default_factory=list)
    facts_confirmed: list[int] = field(default_factory=list)
    facts_superseded: list[int] = field(default_factory=list)
    facts_pending: list[int] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    entities: list[int] = field(default_factory=list)
    intentions: list[int] = field(default_factory=list)


class WriteGate:
    def __init__(self, ctx: Ctx, entities: EntityStore, facts: FactStore, intentions: Intentions):
        self.ctx = ctx
        self.entities = entities
        self.facts = facts
        self.intentions = intentions

    def _person(self, person_id: str):
        return self.ctx.db.one("SELECT * FROM persons WHERE id=?", (person_id,))

    def _subject(self, name: str, person_id: str) -> int:
        p = self._person(person_id)
        if name.strip().lower() in SELF_WORDS or (p and name.strip().lower() == p["name"].lower()):
            return p["entity_id"]
        return self.entities.get_or_create(name, viewer=person_id, reason="субъект факта")

    def apply_encoding(self, episode_id: int, enc: EpisodeEncoding, events: list[dict]) -> GateReport:
        rep = GateReport()
        ep = self.ctx.db.one("SELECT * FROM episodes WHERE id=?", (episode_id,))
        if ep is None:
            return rep
        person_id = ep["person_id"]
        tz = (self._person(person_id) or {"timezone": "Europe/Paris"})["timezone"]
        by_id = {e["id"]: e for e in events}

        with self.ctx.db.tx():
            # 1. Сущности.
            for prop in enc.entities:
                if not prop.name.strip() or _SECRET.search(prop.name):
                    continue
                eid = self.entities.get_or_create(prop.name, viewer=person_id, kind=prop.kind,
                                                  aliases=[a for a in prop.aliases if a.strip()],
                                                  reason=f"эпизод E{episode_id}")
                rep.entities.append(eid)
                self.ctx.db.execute(
                    "INSERT INTO links(src_type, src_id, dst_type, dst_id, kind, weight, updated_at) "
                    "VALUES ('episode',?,'entity',?,'mentions',0.7,?) ON CONFLICT DO UPDATE SET "
                    "weight=MAX(weight, 0.7)", (episode_id, eid, self.ctx.clock.now()))

            # 2. Факты.
            for prop in enc.facts:
                self._apply_fact(prop, episode_id, person_id, tz, by_id, rep)

            # 3. Намерения.
            for it in enc.intentions:
                if not it.action.strip():
                    continue
                due = parse_local_date(it.due, tz)
                iid = self.intentions.add(person_id, it.action, trigger_kind="time" if due else "event",
                                          due_ts=due, trigger_text=it.trigger, actor="subconscious")
                rep.intentions.append(iid)

            # 4. Сам эпизод: суть, оценки, новый вектор.
            text = f"{enc.title}. {enc.gist}"
            vec = self.ctx.embed1(text)
            importance = max(float(ep["importance"]), _clamp(enc.importance))
            self.ctx.db.execute(
                "UPDATE episodes SET title=?, gist=?, importance=?, surprise=?, emotion=?, status='encoded', "
                "embedding=?, updated_at=? WHERE id=?",
                (enc.title.strip()[:120], enc.gist.strip(), importance, _clamp(enc.surprise),
                 _clamp(enc.emotion, -1, 1), to_blob(vec), self.ctx.clock.now(), episode_id))
            self.ctx.fts_add("episode", episode_id, text)
            self.ctx.audit.log("subconscious", "encode", "episode", episode_id,
                               after={"title": enc.title, "facts": rep.facts_added, "superseded": rep.facts_superseded,
                                      "rejected": rep.rejected})
        self.ctx.index.add("episode", episode_id, vec, owner=person_id, visibility=ep["visibility"], ts=ep["start_ts"])
        return rep

    def _apply_fact(self, prop: FactProposal, episode_id: int, person_id: str, tz: str,
                    by_id: dict[int, dict], rep: GateReport) -> None:
        stmt = prop.statement.strip()
        if not stmt or len(stmt) > 500:
            rep.rejected.append(f"пустое/длинное утверждение: {stmt[:60]}")
            return
        if _SECRET.search(stmt) or _SECRET.search(prop.value or ""):
            rep.rejected.append("секретные данные не храним")
            return

        evidence = [i for i in prop.evidence if i in by_id]
        speakers = {by_id[i]["speaker"] for i in evidence}
        kinds = {by_id[i]["source_kind"] for i in evidence}
        confidence = _clamp(prop.confidence)
        if not evidence:
            source_kind, confidence = "inferred", min(confidence, 0.5)
        elif "user" in speakers and "external" not in kinds:
            source_kind = "user_stated"
        elif kinds == {"external"} or "external" in kinds and "user" not in speakers:
            source_kind, confidence = "external", min(confidence, 0.5)
        elif speakers == {"assistant"}:
            source_kind, confidence = "assistant", min(confidence, 0.6)
        else:
            source_kind = "observed"

        target = None
        if prop.replaces_fact_id is not None:
            target = self.facts.get(prop.replaces_fact_id)
            if target is None or not self.facts.visible(target, person_id) or not target.current:
                rep.rejected.append(f"F{prop.replaces_fact_id}: нельзя заменить (нет/не видно/устарел)")
                target = None

        if prop.op == "confirm":
            if target is not None:
                self.facts.add_evidence(target.id, evidence)
                rep.facts_confirmed.append(target.id)
            return

        subject_id = self._subject(prop.subject, person_id)
        object_id = None
        if prop.object and prop.object.strip():
            object_id = self._subject(prop.object, person_id) if prop.object.strip().lower() in SELF_WORDS \
                else self.entities.get_or_create(prop.object, viewer=person_id, reason="объект факта")

        if prop.op == "new":
            dup = self.facts.find_duplicate(subject_id, prop.predicate, object_id, prop.value, stmt, person_id)
            if dup is not None:
                self.facts.add_evidence(dup.id, evidence)
                rep.facts_confirmed.append(dup.id)
                return

        status = "active"
        if prop.op == "update" and target is not None and target.protected:
            status = "pending_review"  # защищённое меняем только с подтверждения человека
        if source_kind == "external" and prop.op == "update":
            status = "pending_review"  # внешний текст не может молча переписать знание

        valid_from = parse_local_date(prop.valid_from, tz)
        fid = self.facts.add(
            subject_id=subject_id, predicate=prop.predicate, statement=stmt, owner=person_id,
            object_id=object_id, value=prop.value, valid_from=valid_from, confidence=confidence,
            importance=_clamp(prop.importance), source_kind=source_kind, source_event_ids=evidence,
            source_episode_id=episode_id, status=status, reason=f"эпизод E{episode_id}",
        )
        self.ctx.db.execute(
            "INSERT OR IGNORE INTO links(src_type, src_id, dst_type, dst_id, kind, weight, updated_at) "
            "VALUES ('fact',?,'episode',?,'derived',0.8,?)", (fid, episode_id, self.ctx.clock.now()))
        if status == "pending_review":
            rep.facts_pending.append(fid)
            return
        rep.facts_added.append(fid)
        if prop.op == "update" and target is not None:
            self.facts.invalidate(target.id, superseded_by=fid, valid_to=valid_from, actor="subconscious",
                                  reason=f"заменён F{fid} (эпизод E{episode_id})")
            rep.facts_superseded.append(target.id)
