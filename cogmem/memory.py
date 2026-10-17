"""CognitiveMemory — единый вход в когнитивную память.

Онлайн (на каждую реплику, без ИИ):       observe(), working_memory(), feedback()
Подсознание (фоново, дешёвая модель):      tick() → кодирование закрытых эпизодов
Сон (ночью):                                sleep()
Управление человеком и «сознанием»:        remember(), correct(), forget(), timeline(), recall_deep(), add_intention()
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cogmem.clock import Clock, SystemClock
from cogmem.config import Budgets, MemoryConfig
from cogmem.consolidate.encoder import EpisodeEncoder
from cogmem.consolidate.sleep import Sleep
from cogmem.context import Ctx
from cogmem.core import CoreBlocks
from cogmem.embed import Embedder, default_embedder
from cogmem.entities import EntityStore
from cogmem.episodes import EpisodeStream, ObserveResult
from cogmem.facts import FactStore
from cogmem.govern.access import can_see
from cogmem.govern.audit import Audit
from cogmem.govern.write_gate import GateReport, WriteGate
from cogmem.jobs import JobQueue
from cogmem.llm import StructuredLLM, cost_usd
from cogmem.procedural import Procedures
from cogmem.prospective import Intentions
from cogmem.reconsolidate import apply_feedback
from cogmem.retrieve.recall import RecallResult, Retriever, fmt_date
from cogmem.retrieve.workingmem import WorkingMemory, pack
from cogmem.store import Database
from cogmem.text.timeparse import TimeRange, parse_time_range
from cogmem.types import Observation, parse_ref, ref
from cogmem.vectors import VectorIndex

log = logging.getLogger(__name__)


class CognitiveMemory:
    def __init__(self, db_path: str | Path = ":memory:", *, embedder: Embedder | None = None,
                 clock: Clock | None = None, config: MemoryConfig | None = None, llm: StructuredLLM | None = None):
        db = Database(db_path)
        clock = clock or SystemClock()
        embedder = embedder or default_embedder()
        self.ctx = Ctx(db=db, clock=clock, cfg=config or MemoryConfig(), embedder=embedder,
                       index=VectorIndex(db, embedder.dim), audit=Audit(db, clock), jobs=JobQueue(db, clock))
        self.entities = EntityStore(self.ctx)
        self.facts = FactStore(self.ctx)
        self.episodes = EpisodeStream(self.ctx, self.entities)
        self.retriever = Retriever(self.ctx, self.entities)
        self.core = CoreBlocks(self.ctx, self.facts)
        self.intentions = Intentions(self.ctx)
        self.procedures = Procedures(self.ctx)
        self.gate = WriteGate(self.ctx, self.entities, self.facts, self.intentions)
        self.llm = llm
        self.encoder = EpisodeEncoder(self.ctx, llm, self.entities, self.facts, self.episodes, self.retriever) \
            if llm else None
        self.sleeper = Sleep(self.ctx, llm, self.facts, self.core, self.intentions)

    # ------------------------------------------------------------------ люди
    def add_person(self, person_id: str, name: str, *, role: str = "family", timezone: str = "Europe/Paris",
                   aliases: list[str] | None = None) -> None:
        if self.ctx.db.one("SELECT 1 FROM persons WHERE id=?", (person_id,)):
            return
        eid = self.entities.create(name, kind="person", owner=None, visibility="family", aliases=aliases or [],
                                   importance=0.9, actor="system", reason="новый член семьи")
        self.ctx.db.execute(
            "INSERT INTO persons(id, name, role, timezone, entity_id, created_at) VALUES (?,?,?,?,?,?)",
            (person_id, name, role, timezone, eid, self.ctx.clock.now()))
        self.core.rebuild_profile(person_id, reason="создание")

    def person(self, person_id: str) -> dict | None:
        r = self.ctx.db.one("SELECT * FROM persons WHERE id=?", (person_id,))
        return dict(r) if r else None

    def local_now(self, person_id: str) -> datetime:
        p = self.person(person_id)
        return datetime.fromtimestamp(self.ctx.clock.now(), ZoneInfo(p["timezone"] if p else "Europe/Paris"))

    # ------------------------------------------------------------------ онлайн
    def observe(self, obs: Observation) -> ObserveResult:
        return self.episodes.observe(obs)

    def current_episode_id(self, person_id: str) -> int | None:
        ep = self.episodes.open_episode(person_id)
        return ep.id if ep else None

    def recall(self, person_id: str, cue: str, **kw: Any) -> RecallResult:
        return self.retriever.recall(person_id, cue, **kw)

    def working_memory(self, person_id: str, cue: str, *, context: dict | None = None,
                       exclude_episode_id: int | None = None, budgets: Budgets | None = None,
                       deep: bool = False, history: bool = False, time_range: TimeRange | None = None,
                       exclude_refs: set[str] | None = None) -> tuple[WorkingMemory, RecallResult]:
        res = self.retriever.recall(person_id, cue, context=context, exclude_episode_id=exclude_episode_id,
                                    deep=deep, history=history, time_range=time_range)
        wm = pack(self.ctx, res, person_id, budgets=budgets,
                  intentions=self.intentions.relevant(person_id, cue),
                  procedures=self.procedures.relevant(person_id, cue), exclude_refs=exclude_refs)
        return wm, res

    def core_profile(self, person_id: str, *, rebuild: bool = True) -> str:
        return self.core.rebuild_profile(person_id, reason="старт сессии") if rebuild else self.core.get(person_id)

    def feedback(self, shown: list[str], used: list[str]) -> dict:
        return apply_feedback(self.ctx, shown, used)

    # ------------------------------------------------------------------ подсознание
    def _handle_encode(self, payload: dict) -> None:
        if self.encoder is None:
            raise RuntimeError("нет модели для подсознания")
        episode_id = int(payload["episode_id"])
        ep = self.episodes.get(episode_id)
        if ep is None or ep.status == "encoded":
            return  # идемпотентность
        built = self.encoder.build_prompt(episode_id)
        if built is None:
            return
        enc = self.encoder.encode(episode_id)
        if enc is None:
            return
        _, events = built
        rep: GateReport = self.gate.apply_encoding(episode_id, enc, events)
        log.info("эпизод E%s закодирован: +%s фактов, заменено %s, отклонено %s", episode_id,
                 len(rep.facts_added), len(rep.facts_superseded), len(rep.rejected))

    def tick(self, *, encode: bool = True, limit: int = 20) -> dict:
        """Периодический «пульс»: закрыть затихшие эпизоды, закодировать закрытые."""
        closed = self.episodes.close_stale()
        done = 0
        if encode and self.encoder is not None:
            done = self.ctx.jobs.run_pending({"encode_episode": self._handle_encode}, limit=limit,
                                             kinds={"encode_episode"})
        return {"closed": closed, "encoded": done, "pending": self.ctx.jobs.pending()}

    def flush(self, person_id: str | None = None) -> dict:
        """Закрыть открытые эпизоды прямо сейчас и закодировать (для тестов и перед сном)."""
        rows = self.ctx.db.query(
            "SELECT id FROM episodes WHERE status='open' AND level='episode'" + (" AND person_id=?" if person_id else ""),
            (person_id,) if person_id else ())
        for r in rows:
            self.episodes.close(r["id"], reason="принудительно")
        return self.tick(limit=1000)

    def sleep(self, person_id: str) -> dict:
        self.tick(limit=1000)
        return self.sleeper.run(person_id)

    # ------------------------------------------------------------------ явные операции
    def remember(self, person_id: str, statement: str, *, about: str | None = None, importance: float = 0.7,
                 share_with_family: bool = False, source_event_id: int | None = None) -> int:
        """«Запомни…» — прямая запись факта со слов человека (минуя ночную обработку)."""
        p = self.person(person_id)
        subject = p["entity_id"] if not about or about.strip().lower() in {"я", "меня", "мне"} else \
            self.entities.get_or_create(about, viewer=person_id, reason="запомни")
        return self.facts.add(
            subject_id=subject, predicate="заметка", statement=statement, owner=person_id,
            confidence=0.95, importance=max(0.0, min(1.0, importance)), source_kind="user_stated",
            source_event_ids=[source_event_id] if source_event_id else [],
            visibility="family" if share_with_family else "private", actor="brain", reason="просьба запомнить")

    def correct(self, person_id: str, unit_ref: str, new_statement: str) -> int | None:
        """«Нет, не так…» — заменить факт исправленным (старый остаётся в истории)."""
        u = parse_ref(unit_ref)
        if not u or u[0] != "fact":
            return None
        old = self.facts.get(u[1])
        if old is None or not self.facts.visible(old, person_id):
            return None
        new_id = self.facts.add(
            subject_id=old.subject_id, predicate=old.predicate, statement=new_statement, owner=old.owner_person,
            object_id=old.object_id, confidence=0.95, importance=old.importance, source_kind="user_stated",
            source_event_ids=old.source_event_ids, visibility=old.visibility, actor="user",
            reason=f"исправление {unit_ref}")
        self.facts.invalidate(old.id, superseded_by=new_id, actor="user", reason="исправлено человеком")
        return new_id

    def forget(self, person_id: str, unit_ref: str) -> bool:
        """«Забудь…» — настоящее удаление по просьбе (GDPR). Только своё."""
        u = parse_ref(unit_ref)
        if not u:
            return False
        t, i = u
        table = {"fact": ("facts", "owner_person"), "episode": ("episodes", "person_id"),
                 "event": ("events", "person_id"), "intention": ("intentions", "person_id"),
                 "procedure": ("procedures", "person_id")}.get(t)
        if table is None:
            return False
        row = self.ctx.db.one(f"SELECT {table[1]} AS owner FROM {table[0]} WHERE id=?", (i,))
        if row is None or row["owner"] != person_id:
            return False
        with self.ctx.db.tx():
            if t == "episode":
                ev_ids = [r["id"] for r in self.ctx.db.query("SELECT id FROM events WHERE episode_id=?", (i,))]
                for eid in ev_ids:
                    self.ctx.fts_remove("event", eid)
                    self.ctx.index.remove("event", eid)
                self.ctx.db.execute("DELETE FROM events WHERE episode_id=?", (i,))
            self.ctx.db.execute(f"DELETE FROM {table[0]} WHERE id=?", (i,))
            self.ctx.db.execute("DELETE FROM links WHERE (src_type=? AND src_id=?) OR (dst_type=? AND dst_id=?)",
                                (t, i, t, i))
            self.ctx.db.execute("DELETE FROM access_traces WHERE unit_type=? AND unit_id=?", (t, i))
            self.ctx.fts_remove(t, i)
            self.ctx.audit.log("user", "forget", t, i, reason="удалено по просьбе (содержимое не сохраняется)")
        if t in ("fact", "episode", "event", "procedure"):
            self.ctx.index.remove(t, i)
        return True

    def recall_deep(self, person_id: str, query: str, *, period: str | None = None,
                    include_outdated: bool = True) -> str:
        """Глубокое вспоминание по всему архиву (инструмент для «сознания»)."""
        tr = parse_time_range(period, self.ctx.clock.now(), self.person(person_id)["timezone"]) if period else None
        big = Budgets(core=0, facts=1200, episodes=2400, procedures=300, intentions=300)
        wm, _ = self.working_memory(person_id, query, deep=True, history=include_outdated, budgets=big,
                                    time_range=tr)
        return wm.render()

    def timeline(self, person_id: str, period: str) -> str:
        """Что было в период: сводки и эпизоды по времени (инструмент для «сознания»)."""
        p = self.person(person_id)
        tr = parse_time_range(period, self.ctx.clock.now(), p["timezone"])
        if tr is None:
            return f"Не понял период «{period}». Примеры: «вчера», «в прошлом месяце», «в мае 2026», «5 марта»."
        rows = self.ctx.db.query(
            "SELECT id, level, title, gist, start_ts FROM episodes WHERE (person_id=? OR visibility='family') "
            "AND status!='open' AND start_ts<? AND end_ts>=? ORDER BY "
            "CASE level WHEN 'year' THEN 0 WHEN 'month' THEN 1 WHEN 'week' THEN 2 WHEN 'day' THEN 3 ELSE 4 END, start_ts",
            (person_id, tr.end, tr.start))
        if not rows:
            return f"За период «{tr.label}» воспоминаний нет."
        lines = [f"Период: {tr.label}"]
        for r in rows[:40]:
            lvl = "" if r["level"] == "episode" else f"[{r['level']}] "
            lines.append(f"- [{ref('episode', r['id'])}] {fmt_date(r['start_ts'], p['timezone'], True)} {lvl}"
                         f"«{r['title']}»" + (f": {r['gist']}" if r["gist"] else ""))
        return "\n".join(lines)

    def explain(self, person_id: str, unit_ref: str) -> str:
        """«Откуда ты это знаешь?» — источник и история изменений."""
        u = parse_ref(unit_ref)
        if not u:
            return "Неверная ссылка."
        t, i = u
        tz = self.person(person_id)["timezone"]
        if t == "fact":
            f = self.facts.get(i)
            if f is None or not self.facts.visible(f, person_id):
                return "Такого факта нет."
            lines = [f"[{unit_ref}] {f.statement}", f"Источник: {f.source_kind}, уверенность {f.confidence:.2f}, "
                     f"записано {fmt_date(f.recorded_at, tz, True)}" + (" — УСТАРЕЛ" if not f.current else "")]
            if f.source_event_ids:
                evs = self.ctx.db.query(
                    f"SELECT id, ts, speaker, text, person_id, visibility FROM events WHERE id IN "
                    f"({','.join('?' * len(f.source_event_ids))}) ORDER BY ts", tuple(f.source_event_ids))
                for e in evs:
                    if can_see(person_id, e["person_id"], e["visibility"]):
                        lines.append(f"  · [M{e['id']}] {fmt_date(e['ts'], tz, True)} {e['speaker']}: «{e['text']}»")
            for h in self.ctx.audit.history("fact", i):
                lines.append(f"  история: {fmt_date(h['ts'], tz, True)} {h['actor']} {h['op']} {h['reason']}")
            return "\n".join(lines)
        if t == "episode":
            ep = self.episodes.get(i)
            if ep is None or not can_see(person_id, ep.person_id, ep.visibility):
                return "Такого эпизода нет."
            return f"[{unit_ref}] {fmt_date(ep.start_ts, tz, True)} «{ep.title}»: {ep.gist}"
        return "Объяснение доступно для фактов и эпизодов."

    def add_intention(self, person_id: str, action: str, *, due_local: str | None = None,
                      trigger: str = "") -> int:
        from cogmem.govern.write_gate import parse_local_date

        due = parse_local_date(due_local, self.person(person_id)["timezone"]) if due_local else None
        return self.intentions.add(person_id, action, trigger_kind="time" if due else "event", due_ts=due,
                                   trigger_text=trigger, actor="brain")

    # ------------------------------------------------------------------ учёт
    def record_usage(self, model: str, purpose: str, usage: Any) -> None:
        self.ctx.db.execute(
            "INSERT INTO llm_usage(ts, model, purpose, input_tokens, cache_read, cache_write, output_tokens, cost_usd) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.ctx.clock.now(), model, purpose, getattr(usage, "input_tokens", 0) or 0,
             getattr(usage, "cache_read_input_tokens", 0) or 0, getattr(usage, "cache_creation_input_tokens", 0) or 0,
             getattr(usage, "output_tokens", 0) or 0, cost_usd(model, usage)))

    def spend_usd(self, since_ts: float = 0.0) -> float:
        return float(self.ctx.db.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage WHERE ts>=?", (since_ts,)))

    def stats(self) -> dict:
        q = self.ctx.db.scalar
        return {
            "events": q("SELECT COUNT(*) FROM events"),
            "episodes": q("SELECT COUNT(*) FROM episodes WHERE level='episode'"),
            "summaries": q("SELECT COUNT(*) FROM episodes WHERE level!='episode'"),
            "facts_current": q("SELECT COUNT(*) FROM facts WHERE invalidated_at IS NULL AND status='active'"),
            "facts_outdated": q("SELECT COUNT(*) FROM facts WHERE invalidated_at IS NOT NULL"),
            "facts_pending": q("SELECT COUNT(*) FROM facts WHERE status='pending_review'"),
            "entities": q("SELECT COUNT(*) FROM entities WHERE merged_into IS NULL"),
            "intentions_pending": q("SELECT COUNT(*) FROM intentions WHERE status='pending'"),
            "jobs_pending": q("SELECT COUNT(*) FROM jobs WHERE status='pending'"),
            "jobs_failed": q("SELECT COUNT(*) FROM jobs WHERE status='failed'"),
        }
