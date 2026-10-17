"""Шлюз записи (по мотивам SSGM, 2026): ИИ только ПРЕДЛАГАЕТ изменения памяти, применяет их код.

Проверки:
  • доказательства — только реплики этого эпизода (выдуманные ID отбрасываются);
  • источник определяется по репликам, а не по словам модели: сказал человек / Джарвис / внешний текст;
  • внешние тексты: уверенность ≤ 0.5, никогда не «защищённые»;
  • заменить можно только видимый и актуальный факт; защищённый — только через подтверждение человека;
  • дубликаты не создаются (подтверждение вместо повтора);
  • слоты: у «живёт в», «день рождения»… значение одно — новое заменяет старое (решает код, не модель);
  • порядок времени: более старое сведение не заменяет более новое (становится историей);
  • намерения — только по просьбе самого человека (не из внешних текстов), без дублей;
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
from cogmem.entities import is_kinship
from cogmem.facts import Fact, FactStore, is_single_valued, norm_predicate
from cogmem.prospective import Intentions
from cogmem.text import ru
from cogmem.store import to_blob

log = logging.getLogger(__name__)

_SECRET = re.compile(r"(парол|password|pin[- ]?код|cvv|cvc|номер карты|\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b)",
                     re.IGNORECASE)
SELF_WORDS = {"я", "собеседник", "пользователь", "меня", "мне"}
TRUSTED_SOURCES = {"user_stated", "observed"}  # могут сами заменить знание в слоте


def is_secret(*texts: str | None) -> bool:
    return any(t and _SECRET.search(t) for t in texts)


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
    facts_historical: list[int] = field(default_factory=list)  # записаны сразу как «было раньше»
    rejected: list[str] = field(default_factory=list)
    entities: list[int] = field(default_factory=list)
    intentions: list[int] = field(default_factory=list)


def _stem_set(text: str) -> set[str]:
    return set(ru.stems(text))


def similar_text(a: str, b: str, threshold: float = 0.6) -> bool:
    sa, sb = _stem_set(a), _stem_set(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= threshold


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
        n = name.strip().lower()
        if n in SELF_WORDS or (p and n == p["name"].lower() and not is_kinship(n)):
            return p["entity_id"]
        return self.entities.get_or_create(name, viewer=person_id, reason="субъект факта")

    # ------------------------------------------------------------------ эпизод целиком
    def apply_encoding(self, episode_id: int, enc: EpisodeEncoding, events: list[dict]) -> GateReport:
        rep = GateReport()
        ep = self.ctx.db.one("SELECT * FROM episodes WHERE id=?", (episode_id,))
        if ep is None:
            return rep
        person_id = ep["person_id"]
        tz = (self._person(person_id) or {"timezone": "Europe/Paris"})["timezone"]
        by_id = {e["id"]: e for e in events}
        text = f"{enc.title}. {enc.gist}"
        # Векторы — заранее, одним пакетом: внутри транзакции общий замок базы держим только на запись.
        self.ctx.prefetch([text] + [f.statement.strip() for f in enc.facts]
                          + [x.name.strip() for x in enc.entities]
                          + [x for f in enc.facts for x in (f.subject.strip(), (f.object or "").strip()) if x])

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
                self._apply_fact(prop, episode_id, person_id, tz, by_id, rep, default_ts=float(ep["end_ts"]))

            # 3. Намерения: только то, о чём просил/что обещал сам человек; без дублей.
            has_user = any(e["speaker"] == "user" and e["source_kind"] != "external" for e in events)
            has_external = any(e["source_kind"] == "external" for e in events)
            for it in enc.intentions:
                if not it.action.strip() or _SECRET.search(it.action):
                    continue
                ev = [i for i in it.evidence if i in by_id]
                ok = any(by_id[i]["speaker"] == "user" and by_id[i]["source_kind"] != "external" for i in ev) \
                    if ev else (has_user and not has_external)
                if not ok:
                    rep.rejected.append(f"намерение не от человека: {it.action[:60]}")
                    continue
                due = parse_local_date(it.due, tz)
                dup = self.similar_intention(person_id, it.action, due)
                if dup is not None:
                    rep.rejected.append(f"намерение уже есть: I{dup}")
                    continue
                src = next((i for i in ev if by_id[i]["speaker"] == "user"), None)
                iid = self.intentions.add(person_id, it.action, trigger_kind="time" if due else "event",
                                          due_ts=due, trigger_text=it.trigger, source_event_id=src,
                                          actor="subconscious")
                rep.intentions.append(iid)

            # 4. Сам эпизод: суть, оценки, новый вектор.
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

    def mark_encoded_without_llm(self, episode_id: int, reason: str) -> None:
        """Эпизод без содержания (только «ага/спасибо», события устройств, внутренние поводы) — без вызова ИИ."""
        with self.ctx.db.tx():
            self.ctx.db.execute("UPDATE episodes SET status='encoded', updated_at=? WHERE id=? AND status='closed'",
                                (self.ctx.clock.now(), episode_id))
            self.ctx.audit.log("subconscious", "skip", "episode", episode_id, reason=reason)

    def similar_intention(self, person_id: str, action: str, due: float | None) -> int | None:
        """Уже запланированное то же самое (другими словами, плюс-минус 3 часа)?"""
        for r in self.ctx.db.query(
                "SELECT id, action_text, due_ts FROM intentions WHERE person_id=? AND status='pending'", (person_id,)):
            if not similar_text(action, r["action_text"]):
                continue
            if due is None or r["due_ts"] is None or abs(r["due_ts"] - due) <= 3 * 3600:
                return r["id"]
        return None

    # ------------------------------------------------------------------ один факт
    def _apply_fact(self, prop: FactProposal, episode_id: int, person_id: str, tz: str,
                    by_id: dict[int, dict], rep: GateReport, *, default_ts: float) -> None:
        stmt = prop.statement.strip()
        if not stmt or len(stmt) > 500:
            rep.rejected.append(f"пустое/длинное утверждение: {stmt[:60]}")
            return
        if is_secret(stmt, prop.value):
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
        observed_at = max((by_id[i]["ts"] for i in evidence), default=default_ts)

        target = None
        if prop.replaces_fact_id is not None:
            target = self.facts.get(prop.replaces_fact_id)
            if target is None or not self.facts.visible(target, person_id) or not target.current:
                rep.rejected.append(f"F{prop.replaces_fact_id}: нельзя заменить (нет/не видно/устарел) — ищу по слоту")
                target = None

        if prop.op == "confirm" and target is not None:
            self.facts.add_evidence(target.id, evidence)
            rep.facts_confirmed.append(target.id)
            return
        # confirm с неверным номером — не теряем сведение: проверим как новое (дубль найдётся по слоту).
        op = "update" if prop.op == "update" else "new"

        subject_id = self._subject(prop.subject, person_id)
        object_id = None
        if prop.object and prop.object.strip():
            object_id = self._subject(prop.object, person_id) if prop.object.strip().lower() in SELF_WORDS \
                else self.entities.get_or_create(prop.object, viewer=person_id, reason="объект факта")

        self.write_fact(
            person_id=person_id, subject_id=subject_id, predicate=prop.predicate, statement=stmt,
            object_id=object_id, value=prop.value, op=op, target=target, source_kind=source_kind,
            confidence=confidence, importance=_clamp(prop.importance), evidence=evidence, episode_id=episode_id,
            valid_from=parse_local_date(prop.valid_from, tz), observed_at=observed_at,
            reason=f"эпизод E{episode_id}", rep=rep)

    def write_fact(self, *, person_id: str, subject_id: int, predicate: str, statement: str,
                   object_id: int | None = None, value: str | None = None, op: str = "new",
                   target: Fact | None = None, source_kind: str = "user_stated", confidence: float = 0.8,
                   importance: float = 0.5, evidence: list[int] | None = None, episode_id: int | None = None,
                   valid_from: float | None = None, observed_at: float | None = None, visibility: str = "private",
                   actor: str = "subconscious", reason: str = "", rep: GateReport | None = None) -> int:
        """Записать факт по правилам слотов. Возвращает id нового или подтверждённого (дубль) факта."""
        rep = rep if rep is not None else GateReport()
        evidence = evidence or []
        observed_at = observed_at if observed_at is not None else self.ctx.clock.now()
        pred = norm_predicate(predicate)
        world = valid_from or observed_at

        # 1. Дубль — подтверждение вместо повтора.
        dup = self.facts.find_duplicate(subject_id, pred, object_id, value, statement, person_id)
        if dup is not None:
            self.facts.add_evidence(dup.id, evidence)
            rep.facts_confirmed.append(dup.id)
            if op == "update" and target is not None and target.id != dup.id and target.current \
                    and source_kind in TRUSTED_SOURCES and not target.protected:
                self.facts.invalidate(target.id, superseded_by=dup.id, valid_to=world, actor=actor,
                                      reason=f"заменён F{dup.id} ({reason})")
                rep.facts_superseded.append(target.id)
            return dup.id

        # 2. Что заменяем: явную цель и/или своё в том же слоте.
        olds: list[Fact] = [target] if target is not None else []
        slot = [f for f in self.facts.current_for(subject_id, person_id, pred)
                if f.owner_person == person_id and all(f.id != o.id for o in olds)]
        if is_single_valued(pred):
            olds += slot
        elif op == "update" and target is None and len(slot) == 1:
            olds = slot

        status = "active"
        if olds and (any(o.protected for o in olds) or source_kind not in TRUSTED_SOURCES):
            status = "pending_review"  # защищённое и недостоверное меняем только с подтверждения человека
        if source_kind == "external" and op == "update":
            status = "pending_review"  # внешний текст не может молча переписать знание

        fid = self.facts.add(
            subject_id=subject_id, predicate=pred, statement=statement, owner=person_id,
            object_id=object_id, value=value, valid_from=valid_from, confidence=confidence,
            importance=importance, source_kind=source_kind, source_event_ids=evidence,
            source_episode_id=episode_id, status=status, visibility=visibility, actor=actor, reason=reason,
            observed_at=observed_at, replaces_id=olds[0].id if status == "pending_review" and olds else None)
        if episode_id is not None:
            self.ctx.db.execute(
                "INSERT OR IGNORE INTO links(src_type, src_id, dst_type, dst_id, kind, weight, updated_at) "
                "VALUES ('fact',?,'episode',?,'derived',0.8,?)", (fid, episode_id, self.ctx.clock.now()))
        if status == "pending_review":
            rep.facts_pending.append(fid)
            return fid
        rep.facts_added.append(fid)

        # 3. Порядок времени: старое сведение не вытесняет более новое знание — само становится историей.
        newer = [o for o in olds if o.world_time > world]
        if newer:
            head = max(newer, key=lambda o: o.world_time)
            self.facts.invalidate(fid, superseded_by=head.id, valid_to=head.world_time, actor=actor,
                                  reason=f"сведение старее F{head.id}")
            rep.facts_historical.append(fid)
            return fid
        for o in olds:
            self.facts.invalidate(o.id, superseded_by=fid, valid_to=world, actor=actor,
                                  reason=f"заменён F{fid} ({reason})")
            rep.facts_superseded.append(o.id)
        return fid

    def approve(self, fact: Fact, *, actor: str = "user") -> None:
        """Человек подтвердил факт «на проверке»: он становится актуальным и вытесняет заменяемое."""
        world = fact.valid_from or fact.observed_at or fact.recorded_at
        with self.ctx.db.tx():
            self.facts.set_status(fact.id, "active", actor=actor, reason="подтверждено человеком")
            self.facts.set_confidence(fact.id, max(fact.confidence, 0.9), actor=actor, reason="подтверждено")
            olds = []
            if fact.replaces_id:
                t = self.facts.get(fact.replaces_id)
                if t is not None and t.current:
                    olds.append(t)
            if is_single_valued(fact.predicate):
                olds += [f for f in self.facts.current_for(fact.subject_id, fact.owner_person or "", fact.predicate)
                         if f.id != fact.id and f.owner_person == fact.owner_person and all(f.id != o.id for o in olds)]
            for o in olds:
                self.facts.invalidate(o.id, superseded_by=fact.id, valid_to=world, actor=actor,
                                      reason=f"заменён подтверждённым F{fact.id}")
