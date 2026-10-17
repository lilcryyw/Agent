"""Быстрый контур («гиппокамп»): запись событий и деление потока на эпизоды.

Вызова ИИ здесь нет: событие записывается дословно, получает вектор и оценку важности,
попадает в текущий эпизод. Граница эпизода — по паузе, смене темы (по смыслу или по
словам-маркерам), смене канала после паузы или по длине (теория сегментации событий).
Закрытый эпизод ставится в очередь на кодирование «подсознанием».
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from cogmem.context import Ctx
from cogmem.entities import EntityStore
from cogmem.store import dumps, from_blob, to_blob
from cogmem.text import ru
from cogmem.types import Observation


@dataclass
class Episode:
    id: int
    person_id: str
    level: str
    period_key: str | None
    start_ts: float
    end_ts: float
    status: str
    title: str
    gist: str
    context: dict
    importance: float
    surprise: float
    emotion: float
    visibility: str
    parent_id: int | None
    event_count: int


def row_to_episode(r) -> Episode:
    return Episode(r["id"], r["person_id"], r["level"], r["period_key"], r["start_ts"], r["end_ts"], r["status"],
                   r["title"], r["gist"], json.loads(r["context"]), r["importance"], r["surprise"], r["emotion"],
                   r["visibility"], r["parent_id"], r["event_count"])


@dataclass
class ObserveResult:
    event_id: int
    episode_id: int
    new_episode: bool
    closed_episode_id: int | None
    importance: float


class EpisodeStream:
    def __init__(self, ctx: Ctx, entities: EntityStore):
        self.ctx = ctx
        self.entities = entities

    # --- эпизоды ---
    def get(self, episode_id: int) -> Episode | None:
        r = self.ctx.db.one("SELECT * FROM episodes WHERE id=?", (episode_id,))
        return None if r is None else row_to_episode(r)

    def open_episode(self, person_id: str) -> Episode | None:
        r = self.ctx.db.one(
            "SELECT * FROM episodes WHERE person_id=? AND level='episode' AND status='open' ORDER BY id DESC LIMIT 1",
            (person_id,),
        )
        return None if r is None else row_to_episode(r)

    def events_of(self, episode_id: int) -> list[dict]:
        return [dict(r) for r in self.ctx.db.query(
            "SELECT id, ts, speaker, channel, device, kind, text, importance, emotion, source_kind "
            "FROM events WHERE episode_id=? ORDER BY ts, id", (episode_id,))]

    def _centroid(self, episode_id: int) -> np.ndarray | None:
        vecs = [from_blob(r["embedding"]) for r in self.ctx.db.query(
            "SELECT embedding FROM events WHERE episode_id=? AND embedding IS NOT NULL ORDER BY id DESC LIMIT 12",
            (episode_id,))]
        vecs = [v for v in vecs if v is not None and v.shape[0] == self.ctx.embedder.dim]
        if not vecs:
            return None
        c = np.mean(np.stack(vecs), axis=0)
        n = np.linalg.norm(c)
        return c / n if n else None

    def _new_episode(self, obs: Observation, ts: float) -> int:
        cur = self.ctx.db.execute(
            "INSERT INTO episodes(person_id, level, start_ts, end_ts, status, context, visibility, created_at, updated_at) "
            "VALUES (?, 'episode', ?, ?, 'open', ?, ?, ?, ?)",
            (obs.person_id, ts, ts, dumps({"channel": obs.channel, "device": obs.device}), obs.visibility, ts, ts),
        )
        return cur.lastrowid

    def close(self, episode_id: int, reason: str = "") -> None:
        """Закрыть эпизод: вектор-центр, предварительный заголовок, задача на кодирование.
        Проверка статуса и закрытие — в одной транзакции (пульс и новая реплика могут закрывать одновременно)."""
        with self.ctx.db.tx():
            ep = self.get(episode_id)
            if ep is None or ep.status != "open":
                return
            events = self.events_of(episode_id)
            now = self.ctx.clock.now()
            if not events:
                self.ctx.db.execute("DELETE FROM episodes WHERE id=? AND status='open'", (episode_id,))
                return
            centroid = self._centroid(episode_id)
            first_user = next((e["text"] for e in events if e["speaker"] == "user"), events[0]["text"])
            title = first_user.strip().replace("\n", " ")[:80]
            importance = max(e["importance"] for e in events)
            emotion = max((e["emotion"] for e in events), key=abs)
            cur = self.ctx.db.execute(
                "UPDATE episodes SET status='closed', end_ts=?, title=?, importance=?, emotion=?, event_count=?, "
                "embedding=?, updated_at=? WHERE id=? AND status='open'",
                (events[-1]["ts"], title, importance, emotion, len(events), to_blob(centroid), now, episode_id),
            )
            if cur.rowcount == 0:
                return
            self.ctx.fts_add("episode", episode_id, title)
            self.ctx.trace("episode", episode_id, "created", events[0]["ts"])
            self.ctx.audit.log("hippocampus", "close", "episode", episode_id, reason=reason)
            self.ctx.jobs.enqueue("encode_episode", f"encode:{episode_id}", {"episode_id": episode_id})
        if centroid is not None:
            self.ctx.index.add("episode", episode_id, centroid, owner=ep.person_id, visibility=ep.visibility,
                               ts=ep.start_ts)

    def close_stale(self) -> list[int]:
        """Закрыть эпизоды, в которых давно тишина (вызывается периодически)."""
        cutoff = self.ctx.clock.now() - self.ctx.cfg.episode_gap_minutes * 60
        ids = [r["id"] for r in self.ctx.db.query(
            "SELECT id FROM episodes WHERE status='open' AND level='episode' AND end_ts < ?", (cutoff,))]
        for eid in ids:
            self.close(eid, reason="пауза")
        return ids

    # --- запись события ---
    def _boundary(self, ep: Episode, obs: Observation, vec: np.ndarray, ts: float) -> str | None:
        cfg = self.ctx.cfg
        gap = ts - ep.end_ts
        if gap > cfg.episode_gap_minutes * 60:
            return "пауза"
        if ep.event_count >= cfg.episode_max_events:
            return "длина"
        # Смена канала делит разговор, только если сменил канал сам человек: события устройств
        # и внутренние поводы идут своим каналом и не должны рвать живой разговор.
        if obs.speaker == "user" and obs.channel != ep.context.get("channel") and gap > 5 * 60:
            return "смена канала"
        if obs.speaker == "user" and ep.event_count >= cfg.topic_shift_min_events:
            if ru.is_topic_shift(obs.text):
                return "смена темы (слова)"
            c = self._centroid(ep.id)
            if c is not None and float(c @ vec) < cfg.topic_shift_threshold and len(ru.words(obs.text)) >= 5:
                return "смена темы (смысл)"
        return None

    def observe(self, obs: Observation) -> ObserveResult:
        ts = self.ctx.clock.now()
        text = obs.text.strip()
        vec = self.ctx.embed1(text)
        source_kind = obs.source_kind or {
            "user": "user_stated", "assistant": "assistant", "device": "observed", "system": "observed"}[obs.speaker]
        mentioned = self.entities.mentions(text, obs.person_id)
        importance = ru.salience(text, speaker=obs.speaker, has_new_entity=False)
        if mentioned:
            importance = min(1.0, importance + 0.05)
        emo = ru.emotion(text)

        closed_id = None
        new = False
        with self.ctx.db.tx():
            ep = self.open_episode(obs.person_id)
            if ep is not None:
                reason = self._boundary(ep, obs, vec, ts)
                if reason:
                    self.close(ep.id, reason=reason)
                    closed_id, ep = ep.id, None
            if ep is None:
                episode_id = self._new_episode(obs, ts)
                new = True
            else:
                episode_id = ep.id
            cur = self.ctx.db.execute(
                "INSERT INTO events(ts, person_id, speaker, channel, device, kind, text, meta, episode_id, importance, "
                "emotion, source_kind, visibility, embedding) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, obs.person_id, obs.speaker, obs.channel, obs.device, obs.kind, text, dumps(obs.meta), episode_id,
                 importance, emo, source_kind, obs.visibility, to_blob(vec)),
            )
            event_id = cur.lastrowid
            self.ctx.db.execute(
                "UPDATE episodes SET end_ts=?, event_count=event_count+1, updated_at=? WHERE id=?",
                (ts, ts, episode_id),
            )
            self.ctx.fts_add("event", event_id, text)
            for eid in mentioned:
                self.ctx.db.execute(
                    "INSERT OR IGNORE INTO links(src_type, src_id, dst_type, dst_id, kind, weight, updated_at) "
                    "VALUES ('event',?,'entity',?,'mentions',0.6,?)", (event_id, eid, ts))
                self.ctx.db.execute(
                    "INSERT INTO links(src_type, src_id, dst_type, dst_id, kind, weight, updated_at) "
                    "VALUES ('episode',?,'entity',?,'mentions',0.6,?) "
                    "ON CONFLICT DO UPDATE SET weight=MIN(1.0, weight+0.05), updated_at=excluded.updated_at",
                    (episode_id, eid, ts))
        self.ctx.index.add("event", event_id, vec, owner=obs.person_id, visibility=obs.visibility, ts=ts)
        return ObserveResult(event_id, episode_id, new, closed_id, importance)
