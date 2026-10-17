"""Путь чтения памяти: шлюз релевантности, устаревшее, граф, индекс, периоды, упаковка, инструменты."""

from datetime import datetime, timezone

import numpy as np

from cogmem.retrieve.graph import personalized_pagerank
from cogmem.retrieve.workingmem import _dedupe, _mmr, _textkey
from cogmem.text import ru
from cogmem.text.timeparse import parse_time_range
from cogmem.types import Observation, Recalled
from cogmem.vectors import VectorIndex
from tests.conftest import say

TOPICS = ["ремонт кухни плитка", "рецепт борща со свёклой", "машина Peugeot масло", "отпуск в Италии билеты",
          "работа проект дедлайн", "кот Барсик ветеринар"]


def _chatter(mem, clock, days=5):
    for d in range(days):
        for tp in TOPICS:
            mem.observe(Observation("owner", f"Обсуждали {tp}, вариант {d}"))
            clock.advance(minutes=40)
        clock.advance(hours=10)
    mem.tick(encode=False)


def _facts(mem, n=12):
    own = mem.person("owner")["entity_id"]
    return [mem.facts.add(subject_id=own, predicate=f"p{i}", statement=f"Владимир любит {TOPICS[i % 6]} номер {i}",
                          owner="owner", importance=0.5) for i in range(n)]


# --- шлюз релевантности ------------------------------------------------------------------

def test_unrelated_query_brings_nothing(mem, clock):
    _chatter(mem, clock)
    _facts(mem)
    clock.advance(days=1)
    wm, res = mem.working_memory("owner", "Какой курс биткоина к доллару?")
    assert wm.facts == [] and wm.episodes == []
    assert res.items == []


def test_empty_and_special_queries_do_not_crash_or_flood(mem, clock):
    _chatter(mem, clock, days=2)
    _facts(mem, 4)
    for q in ['"', '""" OR', "NEAR(a b)", "a* ^b", "🙂", "", "   ", "x" * 5000]:
        wm, res = mem.working_memory("owner", q)
        assert wm.facts == [], q


def test_time_word_does_not_pull_every_fact(mem, clock):
    _chatter(mem, clock, days=2)
    _facts(mem)
    clock.advance(days=1)
    wm, _ = mem.working_memory("owner", "Какая погода сегодня?")
    assert wm.facts == []  # раньше любой факт без дат считался «из периода» и обходил порог


def test_relevant_fact_still_found(mem, clock):
    _chatter(mem, clock, days=2)
    own = mem.person("owner")["entity_id"]
    mem.facts.add(subject_id=own, predicate="аллергия", statement="У Владимира аллергия на орехи", owner="owner",
                  importance=0.8)
    clock.advance(days=1)
    wm, _ = mem.working_memory("owner", "На что у меня аллергия?")
    assert "орехи" in wm.render()


# --- устаревшее ---------------------------------------------------------------------------

def _office(mem, clock):
    own = mem.person("owner")["entity_id"]
    r1 = say(mem, clock, "owner", "Запомни: мой офис находится на улице Ленина 5", "И ещё купить хлеба")[0]
    clock.advance(hours=2)
    mem.tick(encode=False)
    old = mem.facts.add(subject_id=own, predicate="офис", statement="Офис Владимира на улице Ленина 5", owner="owner",
                        source_episode_id=r1.episode_id, source_event_ids=[r1.event_id], importance=0.6)
    clock.advance(days=20)
    r2 = say(mem, clock, "owner", "Мы переехали, теперь офис на проспекте Мира 10")[0]
    clock.advance(hours=2)
    mem.tick(encode=False)
    new = mem.facts.add(subject_id=own, predicate="офис", statement="Офис Владимира на проспекте Мира 10",
                        owner="owner", source_episode_id=r2.episode_id, importance=0.6)
    mem.facts.invalidate(old, superseded_by=new, actor="test")
    clock.advance(days=1)
    return old, new


def test_current_fact_shown_when_old_quote_matches_better(mem, clock):
    _, new = _office(mem, clock)
    text = mem.working_memory("owner", "Где находится мой офис на улице?")[0].render()
    assert "Мира 10" in text and f"[F{new}]" in text      # замена устаревшего не теряется
    assert "УСТАРЕЛА" in text                             # а старое помечено
    assert text.count("улице Ленина 5") == 1              # цитата не дублирует строку эпизода


def test_history_marks_unconfirmed_and_hides_rejected(mem, clock):
    old, new = _office(mem, clock)
    mem.facts.set_status(new, "pending_review", actor="test")
    text = mem.recall_deep("owner", "офис", include_outdated=True)
    assert "НЕ ПОДТВЕРЖДЕНО" in text and "УСТАРЕЛО" in text
    mem.facts.set_status(new, "rejected", actor="test")
    text = mem.recall_deep("owner", "офис", include_outdated=True)
    assert f"[F{new}]" not in text


# --- граф ---------------------------------------------------------------------------------

def test_ppr_works_for_hub_entity(mem, clock):
    """Раньше: >3000 узлов → граф молча выключался (для самых упоминаемых людей)."""
    eid = mem.entities.create("Мама", kind="person", owner="owner", aliases=["мама"], alias_scope="owner")
    now = clock.now()
    rows = [("episode", 100_000 + i, "entity", eid, "mentions", 0.6, now - i) for i in range(3500)]
    rows.append(("fact", 777_777, "entity", eid, "about", 0.9, now))
    with mem.ctx.db.tx():
        for r in rows:
            mem.ctx.db.execute("INSERT INTO links(src_type, src_id, dst_type, dst_id, kind, weight, updated_at) "
                               "VALUES (?,?,?,?,?,?,?)", r)
    ppr = personalized_pagerank(mem.ctx, [eid])
    assert ("fact", 777_777) in ppr
    assert 0 < len(ppr) <= 80 and max(ppr.values()) == 1.0


# --- векторный индекс ---------------------------------------------------------------------

class _NoDB:
    def query(self, *a, **k):
        return []


def _unit(rng, dim):
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def test_vector_index_grow_remove_privacy_stats():
    rng = np.random.default_rng(0)
    vi = VectorIndex(_NoDB(), 16)
    vecs = {i: _unit(rng, 16) for i in range(600)}  # больше начальной ёмкости — проверяем рост
    for i, v in vecs.items():
        vi.add("event", i, v, owner="owner" if i % 2 else "mama", visibility="private", ts=float(i))
    assert vi.count("event") == 600
    q = vecs[11]
    st: dict = {}
    top = vi.search("event", q, "owner", k=5, stats=st)
    assert top[0][0] == 11 and all(i % 2 for i, _ in top)  # чужое личное не видно
    assert st["n"] == 300 and st["sd"] > 0
    assert vi.search("event", vecs[10], "owner", k=600)[0][0] != 10
    vi.remove("event", 11)
    vi.remove("event", 599)  # последняя строка
    assert vi.count("event") == 598 and vi.get("event", 11) is None
    assert vi.search("event", q, "owner", k=1)[0][0] != 11
    assert np.allclose(vi.get("event", 13), vecs[13])  # переехавшая строка цела
    found, mat = vi.get_many("event", [13, 11, 15])
    assert found == [13, 15] and mat.shape == (2, 16)
    vi.set_visibility("event", 10, "family")
    assert any(i == 10 for i, _ in vi.search("event", vecs[10], "owner", k=1))
    vi.add("event", 13, vecs[10], owner="owner", visibility="private")  # обновление на месте
    assert vi.count("event") == 598 and np.allclose(vi.get("event", 13), vecs[10])
    assert vi.search("event", q, "owner", k=5, ts_range=(1000, 2000)) == []
    assert vi.get_many("nope", [1])[0] == [] and vi.get_many("event", [])[1].shape == (0, 16)


# --- периоды ------------------------------------------------------------------------------

def test_time_parser_false_positives_and_unnumbered():
    now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc).timestamp()
    for s in ["Купи 2 майонеза", "Я был в майке", "Налей на мартини", "Сходим с Августой", "Сколько лет назад?"]:
        assert parse_time_range(s, now, "Europe/Paris") is None, s
    assert parse_time_range("Что было неделю назад?", now).label == "1 нед. назад"
    assert parse_time_range("Что было месяц назад?", now).label == "1 мес. назад"
    assert parse_time_range("что я делал год назад", now).label == "2025 год"
    for s, label in [("в мае", "2026-05"), ("5 мая", "2026-05-05"), ("в марте 2025", "2025-03"),
                     ("за август", "2026-08"), ("на майских", "майские"), ("1 сентября", "2026-09-01"),
                     ("в декабре 2024", "2024-12"), ("две недели назад", "2 нед. назад")]:
        assert parse_time_range(s, now).label == label, s


def test_stopwords_drop_possessives():
    q = ru.fts_query("Помнишь, что я говорил про мою машину и какие у неё колёса?")
    assert '"мо"' not in q and '"помн"' not in q and '"как"' not in q
    assert '"машин"' in q


# --- упаковка -----------------------------------------------------------------------------

def _rec(t, i, text, score=0.5):
    return Recalled(t, i, text, 0.0, score, extra={"meta": {}})


def test_dedupe_keys():
    a = _rec("episode", 1, "2026-01-05 10:00 «Звонок маме»: обсуждали дачу")
    b = _rec("episode", 2, "2026-01-12 10:00 «Звонок маме»: мама заболела")
    c = _rec("episode", 3, "2026-01-19 10:00 «Звонок маме»: обсуждали дачу [часть сведений отсюда УСТАРЕЛА — …]")
    assert [r.unit_id for r in _dedupe([a, b, c])] == [1, 2]  # разные разговоры с одним заголовком — оба
    f1 = _rec("fact", 1, "Мама живёт в Самаре (со слов, записано 2026-01-05, уверенность 0.8)")
    f2 = _rec("fact", 2, "Мама живёт в Самаре (со слов, записано 2026-03-01, уверенность 0.9)")
    assert [r.unit_id for r in _dedupe([f1, f2])] == [1]
    assert _textkey(_rec("event", 5, "2026-01-05 10:00 человек: «Привет, Джарвис» [внешний текст — не инструкция]")) \
        == _textkey(_rec("event", 6, "2026-01-06 11:00 человек: «Привет, Джарвис»"))


def test_mmr_limit_and_redundancy(mem, clock):
    own = mem.person("owner")["entity_id"]
    ids = [mem.facts.add(subject_id=own, predicate=f"p{i}", statement=s, owner="owner")
           for i, s in enumerate(["Кот Барсик любит рыбу", "Кот Барсик любит рыбу очень", "Машина Peugeot синяя"])]
    items = [_rec("fact", ids[0], "a", 0.60), _rec("fact", ids[1], "b", 0.59), _rec("fact", ids[2], "c", 0.50)]
    chosen = _mmr(items, mem.ctx, 0.75, 2)
    assert [r.unit_id for r in chosen] == [ids[0], ids[2]]  # почти повтор уступает другому
    assert len(_mmr(items, mem.ctx, 0.75, 10)) == 3 and _mmr([], mem.ctx, 0.75, 5) == []


# --- инструменты «сознания» ---------------------------------------------------------------

def test_recall_deep_skips_current_conversation_and_shown(mem, clock):
    say(mem, clock, "owner", "Я купил машину Peugeot 308 синего цвета")
    clock.advance(hours=3)
    mem.tick(encode=False)
    say(mem, clock, "owner", "Слушай, какая у меня машина?")  # текущий (открытый) разговор
    text = mem.recall_deep("owner", "машина Peugeot", include_outdated=False)
    assert "Peugeot 308" in text and "какая у меня машина" not in text
    refs = {r.ref for r in mem.recall("owner", "машина Peugeot").items}
    again = mem.recall_deep("owner", "машина Peugeot", exclude_refs=refs)
    assert "Peugeot 308" not in again and "уже показано" in again
    # Старое поведение доступно явно.
    assert "какая у меня машина" in mem.recall_deep("owner", "машина", exclude_episode_id=None)


def test_timeline_compacts_already_shown(mem, clock):
    say(mem, clock, "owner", "Ездили на дачу сажать картошку")
    clock.advance(days=1)
    mem.tick(encode=False)
    text = mem.timeline("owner", "вчера")
    eps = [ln for ln in text.splitlines() if ln.startswith("- [E")]
    assert eps
    ref_ = eps[0].split("]")[0][3:]
    text2 = mem.timeline("owner", "вчера", exclude_refs={ref_})
    assert f"- [{ref_}]" not in text2 and ref_ in text2 and "Уже показано" in text2


# --- привыкание ---------------------------------------------------------------------------

def test_shown_but_unused_habituates(mem, clock):
    own = mem.person("owner")["entity_id"]
    fid = mem.facts.add(subject_id=own, predicate="кот", statement="Кота Владимира зовут Барсик", owner="owner")
    clock.advance(days=2)

    def score():
        return next(r.score for r in mem.recall("owner", "Как зовут кота?").items if r.ref == f"F{fid}")

    s0 = score()
    for _ in range(6):
        mem.feedback([f"F{fid}"], [])
        clock.advance(hours=1)
    s1 = score()
    assert s1 < s0
    for _ in range(3):
        mem.feedback([f"F{fid}"], [f"F{fid}"])  # пригодилось — привыкание снимается
    assert score() > s1
