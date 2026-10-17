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
from cogmem.facts import FactStore, scrub_audit
from cogmem.goals import Goals
from cogmem.govern.access import can_see
from cogmem.govern.audit import Audit
from cogmem.govern.write_gate import GateReport, WriteGate, is_secret
from cogmem.jobs import JobDeferred, JobQueue
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


_REEMBED = [
    ("events", "id", "text"),
    ("episodes", "id", "title || '. ' || gist"),
    ("facts", "id", "statement"),
    ("entities", "id", "name || CASE WHEN card != '' THEN '. ' || card ELSE '' END"),
    ("procedures", "id", "name || '. ' || trigger_text"),
]


def _reembed_if_model_changed(db: Database, embedder: Embedder) -> None:
    """Сменилась модель эмбеддингов → пересчитать все векторы (иначе поиск по смыслу тихо сломается)."""
    from cogmem.store import to_blob

    row = db.one("SELECT value FROM meta WHERE key='embed_model'")
    if row is not None and row["value"] == embedder.name:
        return
    total = 0
    try:
        for table, pk, expr in _REEMBED:
            rows = db.query(f"SELECT {pk} AS id, {expr} AS t FROM {table} WHERE embedding IS NOT NULL")
            for start in range(0, len(rows), 64):
                chunk = rows[start : start + 64]
                vecs = embedder.embed([r["t"] or "" for r in chunk])
                with db.tx():
                    if table == "events":  # журнал неизменяем; вектор — не содержимое, временно снимаем защиту
                        db.execute("DROP TRIGGER IF EXISTS events_append_only")
                    for r, v in zip(chunk, vecs):
                        db.execute(f"UPDATE {table} SET embedding=? WHERE {pk}=?", (to_blob(v), r["id"]))
                total += len(chunk)
    finally:
        # Защита журнала возвращается всегда — даже если пересчёт упал на середине.
        db.execute("CREATE TRIGGER IF NOT EXISTS events_append_only BEFORE UPDATE ON events "
                   "BEGIN SELECT RAISE(ABORT, 'events: журнал только для добавления'); END")
    if total:
        log.warning("модель эмбеддингов сменилась на %s — пересчитано %d векторов", embedder.name, total)
    db.execute("INSERT INTO meta(key, value) VALUES ('embed_model', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (embedder.name,))


class CognitiveMemory:
    def __init__(self, db_path: str | Path = ":memory:", *, embedder: Embedder | None = None,
                 clock: Clock | None = None, config: MemoryConfig | None = None, llm: StructuredLLM | None = None):
        db = Database(db_path)
        clock = clock or SystemClock()
        embedder = embedder or default_embedder()
        _reembed_if_model_changed(db, embedder)
        self.ctx = Ctx(db=db, clock=clock, cfg=config or MemoryConfig(), embedder=embedder,
                       index=VectorIndex(db, embedder.dim), audit=Audit(db, clock), jobs=JobQueue(db, clock))
        self.entities = EntityStore(self.ctx)
        self.facts = FactStore(self.ctx)
        self.episodes = EpisodeStream(self.ctx, self.entities)
        self.retriever = Retriever(self.ctx, self.entities)
        self.core = CoreBlocks(self.ctx, self.facts)
        self.intentions = Intentions(self.ctx)
        self.procedures = Procedures(self.ctx)
        self.goals = Goals(self.ctx)
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

    def rename_person(self, person_id: str, name: str) -> bool:
        """Новое имя человека (например, настройка поменялась): имя, схема-сущность, прозвища, профиль."""
        p = self.person(person_id)
        if p is None or not name:
            return False
        if p["name"] == name:
            # Переименование уже было (например, до обновления), а важного факта о нём ещё нет — дописываем.
            row = self.ctx.db.one("SELECT reason FROM memory_audit WHERE op='rename' AND unit_type='person' "
                                  "AND reason LIKE ? ORDER BY id DESC LIMIT 1", (f"% → {name}",))
            mark = f"Обращаться к нему: «{name}»"
            if row and not self.ctx.db.one("SELECT 1 FROM facts WHERE owner_person=? AND statement LIKE ? "
                                           "AND invalidated_at IS NULL", (person_id, mark + "%")):
                old = row["reason"].rsplit(" → ", 1)[0]
                self.remember(person_id, f"{mark}. Имя «{old}» было ошибкой — так не называть.", importance=0.95)
                self.core.rebuild_profile(person_id, reason="новое имя")
            return False
        from cogmem.text import ru

        db = self.ctx.db
        with db.tx():
            db.execute("UPDATE persons SET name=? WHERE id=?", (name, person_id))
            if p["entity_id"]:
                db.execute("UPDATE entities SET name=?, updated_at=? WHERE id=?",
                           (name, self.ctx.clock.now(), p["entity_id"]))
                old = ru.alias_norm(p["name"])
                if old:
                    db.execute("DELETE FROM aliases WHERE entity_id=? AND alias_norm=?", (p["entity_id"], old))
        if p["entity_id"]:
            self.entities.add_alias(p["entity_id"], name)
            self.entities._alias_cache = None
        self.ctx.audit.log("system", "rename", "person", 0, reason=f"{p['name']} → {name}")
        # Как у человека: «меня зовут иначе» — важный факт, который перевешивает старые оговорки в разговоре.
        try:
            self.remember(person_id, f"Обращаться к нему: «{name}». Имя «{p['name']}» было ошибкой — так не называть.",
                          importance=0.95)
        except Exception:  # noqa: BLE001 — профиль всё равно обновится
            log.exception("не удалось записать факт о новом имени")
        self.core.rebuild_profile(person_id, reason="новое имя")
        return True

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
                  procedures=self.procedures.relevant(person_id, cue, k=4), exclude_refs=exclude_refs,
                  goals=self.goals.lines(person_id))
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
        if ep is None or ep.status != "closed":
            return  # идемпотентность: уже закодирован (или удалён)
        # Строго по порядку времени для каждого человека: иначе более старый эпизод, закодированный
        # после сбоя позже, «заменил» бы более новое знание.
        blocker = self.ctx.db.scalar(
            "SELECT e.id FROM episodes e JOIN jobs j ON j.key = 'encode:' || e.id WHERE e.person_id=? "
            "AND e.level='episode' AND e.status='closed' AND e.id!=? AND (e.start_ts<? OR (e.start_ts=? AND e.id<?)) "
            "AND j.status IN ('pending','running') LIMIT 1",
            (ep.person_id, episode_id, ep.start_ts, ep.start_ts, episode_id))
        if blocker is not None:
            raise JobDeferred(f"ждёт более ранний эпизод E{blocker}", delay=30)
        events = self.encoder.events_for_encoding(episode_id)
        why = self.encoder.is_trivial(events) if events else "нет реплик"
        if why:
            self.gate.mark_encoded_without_llm(episode_id, why)
            return
        built = self.encoder.build_prompt(episode_id)  # промпт строится один раз
        if built is None:
            return
        user, events = built
        enc = self.encoder.encode_prompt(user)
        rep: GateReport = self.gate.apply_encoding(episode_id, enc, events)
        # Эпизод мог попасть в уже готовую сводку периода (кодирование после сбоя) — пересобрать её во «сне».
        self.sleeper.mark_stale(ep.person_id, ep.start_ts)
        log.info("эпизод E%s закодирован: +%s фактов, заменено %s, на проверке %s, отклонено %s", episode_id,
                 len(rep.facts_added), len(rep.facts_superseded), len(rep.facts_pending), len(rep.rejected))

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

    def requeue_unencoded(self, person_id: str | None = None) -> int:
        """Вернуть в очередь всё закрытое, но не закодированное (упавшие задачи, потерянные задачи)."""
        rows = self.ctx.db.query(
            "SELECT id FROM episodes WHERE status='closed' AND level='episode'" + (" AND person_id=?" if person_id else ""),
            (person_id,) if person_id else ())
        n = 0
        for r in rows:
            n += self.ctx.jobs.enqueue("encode_episode", f"encode:{r['id']}", {"episode_id": r["id"]}, reset=True)
        return n

    def sleep(self, person_id: str) -> dict:
        self.requeue_unencoded(person_id)
        self.tick(limit=1000)
        return self.sleeper.run(person_id)

    # ------------------------------------------------------------------ явные операции
    def remember(self, person_id: str, statement: str, *, about: str | None = None, importance: float = 0.7,
                 share_with_family: bool = False, source_event_id: int | None = None) -> int:
        """«Запомни…» — прямая запись факта со слов человека (минуя ночную обработку), но через шлюз записи:
        фильтр секретов, дубли, слоты, привязка к эпизоду. Секрет → ValueError (для них есть хранилище)."""
        statement = statement.strip()
        if is_secret(statement):
            raise ValueError("пароли, коды доступа и номера карт в память не записываю — для них есть хранилище секретов")
        p = self.person(person_id)
        subject = p["entity_id"] if not about or about.strip().lower() in {"я", "меня", "мне"} else \
            self.entities.get_or_create(about, viewer=person_id, reason="запомни")
        ev = self.ctx.db.one("SELECT ts, episode_id FROM events WHERE id=? AND person_id=?",
                             (source_event_id, person_id)) if source_event_id else None
        episode_id = ev["episode_id"] if ev else self.current_episode_id(person_id)
        self.ctx.prefetch([statement])
        visibility = "family" if share_with_family else "private"
        fid = self.gate.write_fact(
            person_id=person_id, subject_id=subject, predicate="заметка", statement=statement,
            source_kind="user_stated", confidence=0.95, importance=max(0.0, min(1.0, importance)),
            evidence=[source_event_id] if ev else [], episode_id=episode_id,
            observed_at=ev["ts"] if ev else self.ctx.clock.now(), visibility=visibility, actor="brain",
            reason="просьба запомнить")
        f = self.facts.get(fid)
        if f is not None and share_with_family and f.visibility != "family" and f.owner_person == person_id:
            self.ctx.db.execute("UPDATE facts SET visibility='family' WHERE id=?", (fid,))
            self.ctx.index.set_visibility("fact", fid, "family")
        return fid

    def correct(self, person_id: str, unit_ref: str, new_statement: str) -> int | None:
        """«Нет, не так…» — заменить факт исправленным (старый остаётся в истории).
        Если ссылка на уже устаревшую версию — исправляется её актуальная версия (иначе было бы два «текущих»)."""
        u = parse_ref(unit_ref)
        if not u or u[0] != "fact" or not new_statement.strip():
            return None
        old = self.facts.get(u[1])
        if old is None or not self.facts.visible(old, person_id):
            return None
        head = self.facts.head(old.id)
        if head is not None and head.id != old.id and self.facts.visible(head, person_id) \
                and (head.current or head.status == "pending_review"):
            old = head
        if is_secret(new_statement):
            raise ValueError("секретные данные в память не записываю")
        now = self.ctx.clock.now()
        vec = self.ctx.embed1(new_statement.strip())  # вектор — до транзакции
        with self.ctx.db.tx():
            new_id = self.facts.add(
                subject_id=old.subject_id, predicate=old.predicate, statement=new_statement, owner=old.owner_person,
                object_id=old.object_id, confidence=0.95, importance=old.importance, source_kind="user_stated",
                source_event_ids=old.source_event_ids, source_episode_id=old.source_episode_id,
                visibility=old.visibility, actor="user", reason=f"исправление {unit_ref}", observed_at=now, vec=vec)
            if old.status == "pending_review":
                self.facts.set_status(old.id, "rejected", actor="user", reason=f"исправлено на F{new_id}")
            self.facts.invalidate(old.id, superseded_by=new_id, valid_to=now, actor="user", reason="исправлено человеком")
        return new_id

    def pending_facts(self, person_id: str, limit: int = 10) -> list[str]:
        """Факты «на проверке» (внешний источник, защищённое, не подтвердилось при сверке) — спросить человека."""
        rows = self.ctx.db.query(
            "SELECT id, statement, source_kind, replaces_id FROM facts WHERE status='pending_review' "
            "AND invalidated_at IS NULL AND owner_person=? ORDER BY importance DESC, id DESC LIMIT ?", (person_id, limit))
        out = []
        for r in rows:
            repl = ""
            if r["replaces_id"]:
                old = self.facts.get(r["replaces_id"])
                if old is not None and old.current:
                    repl = f" — заменит [F{old.id}] «{old.statement}»"
            out.append(f"[{ref('fact', r['id'])}] {r['statement']} (источник: {r['source_kind']}){repl}")
        return out

    def review_fact(self, person_id: str, unit_ref: str, approve: bool) -> bool:
        """Человек решил судьбу факта «на проверке»: approve=True — принять (заменит то, что должен),
        False — отклонить. Только свои факты. → удалось ли."""
        u = parse_ref(unit_ref)
        if not u or u[0] != "fact":
            return False
        f = self.facts.get(u[1])
        if f is None or f.owner_person != person_id or f.status != "pending_review" or f.invalidated_at is not None:
            return False
        if approve:
            self.gate.approve(f, actor="user")
        else:
            self.facts.set_status(f.id, "rejected", actor="user", reason="отклонено человеком")
        return True

    def forget(self, person_id: str, unit_ref: str) -> bool:
        """«Забудь…» — настоящее удаление по просьбе (GDPR). Только своё.
        Удаляется и то, что из этого выведено: факты эпизода, содержимое аудита и истории ядра;
        сводки периода стираются и пересобираются во «сне»."""
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
            if t == "fact":
                self.facts.purge(i)
            else:
                ev_ids: list[int] = []
                if t == "episode":
                    ep = self.episodes.get(i)
                    ev_ids = [r["id"] for r in self.ctx.db.query("SELECT id FROM events WHERE episode_id=?", (i,))]
                    for r in self.ctx.db.query("SELECT id FROM facts WHERE source_episode_id=? AND owner_person=?",
                                               (i, person_id)):
                        self.facts.purge(r["id"])
                    self.ctx.db.execute("UPDATE episodes SET parent_id=NULL WHERE parent_id=?", (i,))
                    if ep is not None and ep.level == "episode":
                        self.sleeper.mark_stale(person_id, ep.start_ts, blank=True)
                elif t == "event":
                    ev_ids = [i]
                    ev = self.ctx.db.one("SELECT episode_id, ts FROM events WHERE id=?", (i,))
                    ep = self.episodes.get(ev["episode_id"]) if ev else None
                    if ep is not None and ep.gist:  # суть эпизода могла пересказывать удалённое
                        self.ctx.db.execute("UPDATE episodes SET gist='' WHERE id=?", (ep.id,))
                        self.ctx.fts_add("episode", ep.id, ep.title)
                        scrub_audit(self.ctx, "episode", ep.id)
                        self.sleeper.mark_stale(person_id, ep.start_ts, blank=True)
                if ev_ids:
                    self._purge_facts_from_events(person_id, set(ev_ids))
                    for eid in ev_ids:
                        self.ctx.fts_remove("event", eid)
                        self.ctx.index.remove("event", eid)
                        self.ctx.db.execute("DELETE FROM links WHERE src_type='event' AND src_id=?", (eid,))
                    if t == "episode":
                        self.ctx.db.execute("DELETE FROM events WHERE episode_id=?", (i,))
                self.ctx.db.execute(f"DELETE FROM {table[0]} WHERE id=?", (i,))
                self.ctx.db.execute("DELETE FROM links WHERE (src_type=? AND src_id=?) OR (dst_type=? AND dst_id=?)",
                                    (t, i, t, i))
                self.ctx.db.execute("DELETE FROM access_traces WHERE unit_type=? AND unit_id=?", (t, i))
                self.ctx.fts_remove(t, i)
                scrub_audit(self.ctx, t, i)
            self.ctx.audit.log("user", "forget", t, i, reason="удалено по просьбе (содержимое не сохраняется)")
        if t in ("episode", "event", "procedure"):
            self.ctx.index.remove(t, i)
        self.core.rebuild_profile(person_id, reason="забыто по просьбе")
        return True

    def _purge_facts_from_events(self, person_id: str, ev_ids: set[int]) -> None:
        """Факты, целиком основанные на удаляемых репликах, удаляются; у остальных — убираются ссылки."""
        import json

        for r in self.ctx.db.query("SELECT id, source_event_ids FROM facts WHERE owner_person=? "
                                   "AND source_event_ids != '[]'", (person_id,)):
            ids = set(json.loads(r["source_event_ids"]))
            if not ids & ev_ids:
                continue
            if ids <= ev_ids:
                self.facts.purge(r["id"])
            else:
                self.ctx.db.execute("UPDATE facts SET source_event_ids=? WHERE id=?",
                                    (json.dumps(sorted(ids - ev_ids)), r["id"]))

    def recall_deep(self, person_id: str, query: str, *, period: str | None = None,
                    include_outdated: bool = True, exclude_refs: set[str] | None = None,
                    exclude_episode_id: int | None | str = "current") -> str:
        """Глубокое вспоминание по всему архиву (инструмент для «сознания»).

        exclude_episode_id — какой разговор не искать: по умолчанию текущий («current» — он и так в
        контексте; иначе инструмент возвращал весь нынешний разговор, вплоть до самого вопроса).
        None — не исключать ничего. exclude_refs — уже показанное в этом разговоре: не повторяем
        целиком, а перечисляем одной строкой (оно относится к делу и уже есть в истории).
        """
        tr = parse_time_range(period, self.ctx.clock.now(), self.person(person_id)["timezone"]) if period else None
        if exclude_episode_id == "current":
            exclude_episode_id = self.current_episode_id(person_id)
        big = Budgets(core=0, facts=1200, episodes=2400, procedures=300, intentions=300)
        skip = set(exclude_refs or ())
        wm, res = self.working_memory(person_id, query, deep=True, history=include_outdated, budgets=big,
                                      time_range=tr, exclude_episode_id=exclude_episode_id, exclude_refs=skip)
        again = ", ".join(dict.fromkeys(r.ref for r in res.items[:20] if r.ref in skip))
        if wm.is_empty() and again:
            return f"Нового не нашлось; относящееся к делу уже показано выше в разговоре: {again}"
        out = wm.render()
        return out + (f"\nТакже относится (уже показано выше в разговоре): {again}" if again else "")

    def timeline(self, person_id: str, period: str, *, exclude_refs: set[str] | None = None) -> str:
        """Что было в период: сводки и эпизоды по времени (инструмент для «сознания»).
        Открытый (текущий) разговор не входит; уже показанное (exclude_refs) — одной строкой ссылок."""
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
        skip = set(exclude_refs or ())
        lines = [f"Период: {tr.label}"]
        again: list[str] = []
        for r in rows:
            rf = ref("episode", r["id"])
            if rf in skip:
                again.append(rf)
                continue
            if len(lines) > 40:
                break
            lvl = "" if r["level"] == "episode" else f"[{r['level']}] "
            lines.append(f"- [{rf}] {fmt_date(r['start_ts'], p['timezone'], True)} {lvl}"
                         f"«{r['title']}»" + (f": {r['gist']}" if r["gist"] else ""))
        if again:
            lines.append("Уже показано выше в разговоре: " + ", ".join(again[:40]))
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
