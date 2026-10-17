"""Путь записи памяти: слоты, порядок времени, повторы задач, «забудь», намерения, исправления, прозвища, сон."""

import re
import sqlite3

import pytest

from cogmem.clock import FakeClock
from cogmem.consolidate.schemas import (EntityProposal, EpisodeEncoding, FactProposal, IntentionProposal,
                                        SummaryOut, VerifyOut)
from cogmem.embed import HashEmbedder
from cogmem.llm import ScriptedLLM
from cogmem.memory import CognitiveMemory
from cogmem.types import Observation
from tests.conftest import say


def F(statement, *, subject="я", predicate="живёт в", value=None, obj=None, op="new", replaces=None, evidence=(),
      valid_from=None, imp=0.8):
    return FactProposal(subject=subject, predicate=predicate, object=obj, value=value, statement=statement,
                        valid_from=valid_from, op=op, replaces_fact_id=replaces, evidence=list(evidence),
                        confidence=0.9, importance=imp)


def ENC(facts=(), intentions=(), entities=(), title="t", gist="g"):
    return EpisodeEncoding(title=title, gist=gist, importance=0.5, surprise=0.1, emotion=0, entities=list(entities),
                           facts=list(facts), intentions=list(intentions))


def mids(user):
    """Номера реплик стенограммы (без раздела «что известно»)."""
    return [int(x) for x in re.findall(r"\[M(\d+)\]", user.split("Стенограмма эпизода:")[1])]


class Script:
    """Подсознание для тестов: encode(user) → EpisodeEncoding; остальные схемы — простые ответы."""

    def __init__(self):
        self.encode = lambda user: ENC()
        self.summary_fail = False
        self.verify = lambda user: VerifyOut(verdict="supported", corrected_statement=None, note="ок")
        self.prompts: list[str] = []

    def __call__(self, schema, system, user):
        if schema is EpisodeEncoding:
            self.prompts.append(user)
            return self.encode(user)
        if schema is SummaryOut:
            if self.summary_fail:
                raise RuntimeError("перегрузка API")
            return SummaryOut(title="Сводка", gist="Что было: " + user[-200:], importance=0.5)
        return self.verify(user)


def make(**kw):
    clock = FakeClock()
    script = Script()
    llm = ScriptedLLM(script)
    m = CognitiveMemory(embedder=HashEmbedder(), clock=clock, llm=llm, **kw)
    m.add_person("v", "Владимир", role="owner")
    return m, clock, script, llm


def current(m, like="%"):
    return [r["statement"] for r in m.ctx.db.query(
        "SELECT statement FROM facts WHERE invalidated_at IS NULL AND status='active' AND statement LIKE ? ORDER BY id",
        (like,))]


def episode(m, clock, *texts, person="v"):
    say(m, clock, person, *texts)
    out = m.flush(person)
    clock.advance(hours=2)
    return out


# ---------------------------------------------------------------- 1. слоты
def test_multi_valued_slot_keeps_both_values_without_value_field():
    m, clock, s, _ = make()
    s.encode = lambda u: ENC([F("Владимир любит кофе", predicate="любит", evidence=mids(u))])
    episode(m, clock, "Я люблю кофе по утрам")
    s.encode = lambda u: ENC([F("Владимир любит джаз", predicate="любит", evidence=mids(u))])
    episode(m, clock, "И ещё я очень люблю джаз")
    assert current(m) == ["Владимир любит кофе", "Владимир любит джаз"]


def test_single_valued_slot_new_value_supersedes_even_with_op_new():
    m, clock, s, _ = make()
    s.encode = lambda u: ENC([F("Владимир живёт в Самаре", value="Самара", evidence=mids(u))])
    episode(m, clock, "Я живу в Самаре")
    s.encode = lambda u: ENC([F("Владимир живёт в Москве", value="Москва", evidence=mids(u))])
    episode(m, clock, "Я переехал в Москву")
    assert current(m, "%живёт%") == ["Владимир живёт в Москве"]
    old = m.ctx.db.one("SELECT * FROM facts WHERE statement='Владимир живёт в Самаре'")
    assert old["superseded_by"] is not None and old["invalidated_at"] is not None


def test_update_with_bogus_target_falls_back_to_slot():
    m, clock, s, _ = make()
    s.encode = lambda u: ENC([F("Владимир живёт в Самаре", value="Самара", evidence=mids(u))])
    episode(m, clock, "Я живу в Самаре")
    s.encode = lambda u: ENC([F("Владимир живёт в Казани", value="Казань", op="update", replaces=9999,
                                evidence=mids(u))])
    episode(m, clock, "Нет, я живу в Казани")
    assert current(m, "%живёт%") == ["Владимир живёт в Казани"]


def test_same_value_is_confirmation_not_duplicate():
    m, clock, s, _ = make()
    s.encode = lambda u: ENC([F("Владимир живёт в Самаре", value="Самара", evidence=mids(u))])
    episode(m, clock, "Я живу в Самаре")
    s.encode = lambda u: ENC([F("Владимир по-прежнему живёт в Самаре", value="Самара", evidence=mids(u))])
    episode(m, clock, "Я всё ещё живу в Самаре")
    assert current(m) == ["Владимир живёт в Самаре"]
    assert len(m.facts.get(1).source_event_ids) == 2


def test_confirm_with_wrong_id_is_not_lost():
    m, clock, s, _ = make()
    s.encode = lambda u: ENC([F("У Владимира есть кот Барсик", predicate="питомец", value="кот Барсик", op="confirm",
                                replaces=777, evidence=mids(u))])
    episode(m, clock, "У меня есть кот Барсик")
    assert current(m) == ["У Владимира есть кот Барсик"]


def test_encoder_sees_slot_facts_of_self_and_mentioned_entities():
    m, clock, s, _ = make()
    fid = m.remember("v", "Владимир работает инженером в Airbus")
    m.entities.create("Самара", kind="place", owner="v")
    episode(m, clock, "Сегодня был длинный день, обсуждали отпуск и погоду в Самаре, потом кино")
    assert f"[F{fid}]" in s.prompts[-1]


# ---------------------------------------------------------------- 2. порядок и время
def test_older_episode_encoded_late_does_not_override_newer_fact():
    m, clock, s, _ = make()
    state = {"fail": True}

    def enc(u):
        t = u.split("Стенограмма эпизода:")[1]
        if "Самар" in t:
            if state["fail"]:
                raise RuntimeError("529 overloaded")
            known = re.findall(r"\[F(\d+)\] Владимир живёт в Москве", u)
            return ENC([F("Владимир живёт в Самаре", value="Самара", evidence=mids(u),
                          op="update" if known else "new", replaces=int(known[0]) if known else None)])
        return ENC([F("Владимир живёт в Москве", value="Москва", evidence=mids(u))])

    s.encode = enc
    say(m, clock, "v", "Я живу в Самаре")
    m.flush("v")
    t_moved = clock.now() + 3600
    clock.advance(hours=1)
    say(m, clock, "v", "Я переехал в Москву, теперь живу там")
    m.flush("v")
    # Более поздний эпизод ждёт более ранний — не кодируется раньше него.
    assert m.ctx.db.scalar("SELECT status FROM episodes WHERE id=2") == "closed"
    state["fail"] = False
    for _ in range(5):
        clock.advance(minutes=2)
        m.tick()
    assert current(m, "%живёт%") == ["Владимир живёт в Москве"]
    samara = m.ctx.db.one("SELECT * FROM facts WHERE statement='Владимир живёт в Самаре'")
    # Закрыт временем реплики о переезде, а не временем кодирования.
    assert abs(samara["valid_to"] - t_moved) < 120


def test_late_old_news_becomes_history():
    """Сведение о прошлом, сказанное позже (valid_from раньше), не вытесняет текущее."""
    m, clock, s, _ = make()
    s.encode = lambda u: ENC([F("Владимир живёт в Москве", value="Москва", evidence=mids(u), valid_from="2025-06-01")])
    episode(m, clock, "Я живу в Москве с июня 2025")
    s.encode = lambda u: ENC([F("Владимир жил в Самаре", value="Самара", evidence=mids(u), valid_from="2010-01-01")])
    episode(m, clock, "Кстати, с 2010 года я жил в Самаре")
    assert current(m, "%Москв%") == ["Владимир живёт в Москве"]
    old = m.ctx.db.one("SELECT * FROM facts WHERE statement='Владимир жил в Самаре'")
    assert old["invalidated_at"] is not None and old["superseded_by"] == 1


# ---------------------------------------------------------------- 3. задачи
def test_transient_failures_retry_forever_with_capped_delay():
    m, clock, s, _ = make()

    def boom(u):
        raise ConnectionError("сеть недоступна")

    s.encode = boom
    say(m, clock, "v", "Сегодня был у врача, всё хорошо")
    m.flush("v")
    for _ in range(12):
        clock.advance(hours=1.01)
        m.tick()
    job = m.ctx.db.one("SELECT * FROM jobs")
    assert job["status"] == "pending" and job["attempts"] >= 10
    assert job["run_after"] - clock.now() <= 3600 + 1
    s.encode = lambda u: ENC()
    clock.advance(hours=1.01)
    m.tick()
    assert m.ctx.db.scalar("SELECT status FROM episodes WHERE id=1") == "encoded"


def test_permanent_failure_marks_failed_and_sleep_requeues():
    m, clock, s, _ = make()

    def cut(u):
        raise RuntimeError("ответ обрезан по max_tokens (encode_episode)")

    s.encode = cut
    say(m, clock, "v", "Сегодня был у врача, всё хорошо")
    m.flush("v")
    for _ in range(5):
        clock.advance(minutes=10)
        m.tick()
    job = m.ctx.db.one("SELECT * FROM jobs")
    assert job["status"] == "failed" and job["attempts"] == 3
    s.encode = lambda u: ENC(title="Врач")
    clock.advance(days=1)
    m.sleep("v")
    assert m.ctx.db.scalar("SELECT status FROM episodes WHERE id=1") == "encoded"


def test_trivial_episode_skips_llm_and_prompt_built_once(monkeypatch):
    m, clock, s, llm = make()
    episode(m, clock, "Спасибо")
    assert llm.calls == []
    assert m.ctx.db.scalar("SELECT status FROM episodes WHERE id=1") == "encoded"
    m.observe(Observation("v", "Подключено новое устройство", speaker="device"))
    m.flush("v")
    assert llm.calls == []
    calls = []
    orig = m.encoder.build_prompt
    monkeypatch.setattr(m.encoder, "build_prompt", lambda eid: calls.append(eid) or orig(eid))
    episode(m, clock, "Я сегодня впервые попробовал устрицы")
    assert len(calls) == 1 and len(llm.calls) == 1


# ---------------------------------------------------------------- 4. «забудь»
def test_forget_fact_scrubs_audit_and_core_history():
    m, clock, _, _ = make()
    fid = m.remember("v", "У Владимира диабет второго типа", importance=0.95)
    m.core_profile("v")
    assert "диабет" in m.core.get("v")
    assert m.forget("v", f"F{fid}")
    db = m.ctx.db
    assert db.scalar("SELECT COUNT(*) FROM memory_audit WHERE after LIKE '%диабет%' OR before LIKE '%диабет%'") == 0
    assert db.scalar("SELECT COUNT(*) FROM core_versions WHERE content LIKE '%диабет%'") == 0
    assert "диабет" not in m.core.get("v")


def test_forget_episode_cascades_derived_facts_and_summaries():
    m, clock, s, _ = make()
    s.encode = lambda u: ENC([F("У Владимира диабет", predicate="болезнь", value="диабет", evidence=mids(u))],
                             title="Здоровье", gist="Владимир рассказал про диабет")
    say(m, clock, "v", "У меня диабет, только никому")
    ev = m.observe(Observation("v", "Запомни это"))
    fid = m.remember("v", "Владимир просил держать диабет в тайне", source_event_id=ev.event_id)
    m.flush("v")
    clock.advance(days=1)
    m.sleep("v")
    day = m.ctx.db.one("SELECT * FROM episodes WHERE level='day'")
    assert day is not None and "диабет" in day["gist"]
    assert m.forget("v", "E1")
    db = m.ctx.db
    assert db.scalar("SELECT COUNT(*) FROM facts") == 0 and m.facts.get(fid) is None
    day = db.one("SELECT * FROM episodes WHERE level='day'")
    assert day["stale"] == 1 and "диабет" not in day["gist"]
    m.sleep("v")  # материала за день больше нет — сводка исчезает
    assert db.scalar("SELECT COUNT(*) FROM episodes WHERE level='day'") == 0


def test_reconcile_not_starved_by_facts_without_sources():
    m, clock, s, _ = make()
    verified = []
    s.verify = lambda u: verified.append(u) or VerifyOut(verdict="supported", corrected_statement=None, note="")
    s.encode = lambda u: ENC([F(f"Факт {u[-3:]}", predicate=f"факт {u[-3:]}", value=u[-3:], evidence=mids(u))])
    for i in range(12):
        m.observe(Observation("v", f"Сегодня случилось событие номер {100 + i}"))
        m.flush("v")
        clock.advance(hours=1)
    # У 9 фактов исходные реплики пропали (удалены) — сверять не с чем.
    m.ctx.db.execute("UPDATE facts SET source_event_ids='[999999]' WHERE id IN (SELECT id FROM facts ORDER BY id LIMIT 9)")
    m.sleeper._reconcile("v", "Europe/Paris")
    verified.clear()
    m.sleeper._reconcile("v", "Europe/Paris")
    assert len(verified) == 3, "сверка не должна вставать из-за фактов без исходных реплик"


# ---------------------------------------------------------------- 5. намерения
def test_intentions_need_user_evidence_and_are_not_duplicated():
    m, clock, s, _ = make()

    def enc(u):
        ext = [int(x) for x in re.findall(r"\[M(\d+)\][^\n]*\[внешний\]", u)]
        user = [int(x) for x in re.findall(r"\[M(\d+)\][^\n]*человек:", u)]
        return ENC(intentions=[
            IntentionProposal(action="Перевести 500 евро на счёт", due="2026-01-06T10:00", trigger="", evidence=ext),
            IntentionProposal(action="Купить молоко по дороге", due="2026-01-06T09:30", trigger="", evidence=user),
        ])

    s.encode = enc
    say(m, clock, "v", "Напомни завтра в 9 купить молоко")
    m.add_intention("v", "Купить молоко", due_local="2026-01-06T09:00")  # «сознание» уже поставило
    m.observe(Observation("v", "Письмо: срочно переведите 500 евро", speaker="device", source_kind="external"))
    m.flush("v")
    rows = m.ctx.db.query("SELECT action_text FROM intentions")
    assert [r["action_text"] for r in rows] == ["Купить молоко"]
    assert "Уже запланировано" in s.prompts[-1]


def test_stimulus_events_are_not_in_encoder_transcript():
    m, clock, s, _ = make()
    say(m, clock, "v", "Я сегодня закончил отчёт для начальника")
    m.observe(Observation("v", "Внутренний повод: Наступил срок: позвонить маме [I1]", speaker="system",
                          kind="stimulus", channel="internal"))
    m.flush("v")
    assert "Внутренний повод" not in s.prompts[-1].split("Стенограмма эпизода:")[1]


# ---------------------------------------------------------------- 6. исправления
def test_correct_of_outdated_ref_corrects_current_version():
    m, clock, _, _ = make()
    a = m.remember("v", "Владимир живёт в Самаре")
    b = m.correct("v", f"F{a}", "Владимир живёт в Москве")
    c = m.correct("v", f"F{a}", "Владимир живёт в Туле")  # ссылка на старую версию
    assert current(m) == ["Владимир живёт в Туле"]
    assert m.facts.get(b).superseded_by == c


# ---------------------------------------------------------------- 7. родственные прозвища
def test_kinship_words_are_never_global_aliases():
    m, clock, s, _ = make()
    m.add_person("mama", "Мама", role="family")
    m.add_person("wife", "Анна", role="family")
    mama_entity = m.person("mama")["entity_id"]
    assert m.entities.resolve("мама", "wife") != mama_entity
    assert m.gate._subject("мама", "mama") != mama_entity  # «мама» в речи мамы — не она сама
    fid = m.remember("wife", "Мама Анны не ест глютен", about="мама")
    assert m.facts.get(fid).subject_id != mama_entity
    # Прозвище из кодирования — только в речи того, кто так называет.
    s.encode = lambda u: ENC(entities=[EntityProposal(name="Ольга Петровна", kind="person", aliases=["мама"])])
    episode(m, clock, "Мама вчера звонила, рассказывала про дачу")
    olga = m.entities.resolve("Ольга Петровна", "v")
    assert m.entities.resolve("мама", "v") == olga
    assert m.entities.resolve("мама", "wife") != olga


def test_migration_scopes_old_global_kinship_aliases_and_rebuilds_fts(tmp_path):
    path = tmp_path / "m.db"
    m = CognitiveMemory(path, embedder=HashEmbedder(), clock=FakeClock())
    m.add_person("v", "Владимир")
    eid = m.entities.create("Ольга", owner="v", kind="person")
    m.ctx.db.execute("INSERT INTO aliases(alias_norm, entity_id, person_scope) VALUES ('мам', ?, '')", (eid,))
    m.ctx.db.execute("INSERT INTO fts(rowid, unit_type, unit_id, text) VALUES (5, 'fact', 42, 'стар')")
    m.ctx.db.execute("PRAGMA user_version = 6")
    m.ctx.db.close()
    m2 = CognitiveMemory(path, embedder=HashEmbedder(), clock=FakeClock())
    assert m2.ctx.db.scalar("PRAGMA user_version") == 7
    assert m2.ctx.db.one("SELECT person_scope FROM aliases WHERE alias_norm='мам'")["person_scope"] == "v"
    m2.ctx.fts_add("fact", 42, "новое")
    assert m2.ctx.db.scalar("SELECT COUNT(*) FROM fts WHERE unit_type='fact' AND unit_id=42") == 1


# ---------------------------------------------------------------- 8. сон и проверка
def test_sleep_steps_are_isolated_from_llm_failures():
    m, clock, s, _ = make()
    s.encode = lambda u: ENC([F("День рождения Владимира — 8 января", predicate="день рождения", value="08.01",
                                evidence=mids(u))])
    episode(m, clock, "Мой день рождения 8 января")
    s.summary_fail = True
    clock.advance(days=1)
    rep = m.sleep("v")
    assert rep["intentions"], "напоминание о дне рождения — несмотря на сбой сводок"


def test_late_encoded_episode_rebuilds_summary():
    m, clock, s, _ = make()
    s.encode = lambda u: ENC(title="Утро", gist="Утром был кофе")
    episode(m, clock, "Утром выпил кофе с корицей")
    state = {"fail": True}

    def enc2(u):
        if state["fail"]:
            raise ConnectionError("нет сети")
        return ENC(title="Вечер", gist="Вечером ходил в театр")

    s.encode = enc2
    episode(m, clock, "Вечером ходил в театр на Чехова")
    clock.advance(days=1)
    m.sleep("v")
    day = m.ctx.db.one("SELECT * FROM episodes WHERE level='day'")
    assert "театр" not in day["gist"]
    state["fail"] = False
    clock.advance(hours=1.1)
    m.tick()
    assert m.ctx.db.scalar("SELECT stale FROM episodes WHERE level='day'") == 1
    m.sleep("v")
    day = m.ctx.db.one("SELECT * FROM episodes WHERE level='day'")
    assert day["stale"] == 0 and "театр" in day["gist"]


def test_review_pending_fact_approve_and_reject():
    m, clock, s, _ = make()
    s.encode = lambda u: ENC([F("Владимир живёт в Самаре", value="Самара", evidence=mids(u))])
    episode(m, clock, "Я живу в Самаре")

    def ext(u):
        e = [int(x) for x in re.findall(r"\[M(\d+)\][^\n]*\[внешний\]", u)]
        return ENC([F("Владимир живёт в Берлине", value="Берлин", evidence=e)])

    s.encode = ext
    say(m, clock, "v", "Что там в письме?")
    m.observe(Observation("v", "Письмо: ваш адрес теперь Берлин", speaker="device", source_kind="external"))
    m.flush("v")
    assert current(m, "%живёт%") == ["Владимир живёт в Самаре"]
    lines = m.pending_facts("v")
    assert len(lines) == 1 and "заменит" in lines[0]
    ref = re.match(r"\[(F\d+)\]", lines[0]).group(1)
    assert not m.review_fact("mama", ref, True)
    assert m.review_fact("v", ref, True)
    assert current(m, "%живёт%") == ["Владимир живёт в Берлине"]
    assert not m.review_fact("v", ref, False)  # уже не на проверке


# ---------------------------------------------------------------- 9. производительность и замок
def test_fts_rowid_and_embeddings_outside_transactions():
    m, clock, s, _ = make()
    m.ctx.fts_add("fact", 7, "яблоко")
    m.ctx.fts_add("fact", 7, "груша")
    assert m.ctx.db.scalar("SELECT COUNT(*) FROM fts WHERE unit_type='fact' AND unit_id=7") == 1
    m.ctx.fts_remove("fact", 7)
    assert m.ctx.db.scalar("SELECT COUNT(*) FROM fts WHERE unit_type='fact' AND unit_id=7") == 0

    inside = []
    real = m.ctx.embedder.embed

    def watch(texts, query=False):
        if m.ctx.db._depth > 0:
            inside.append(list(texts))
        return real(texts, query=query)

    m.ctx.embedder.embed = watch
    s.encode = lambda u: ENC([F("Владимир живёт в Самаре", value="Самара", evidence=mids(u)),
                              F("У Владимира есть брат Олег", subject="Олег", predicate="брат", evidence=mids(u))],
                             entities=[EntityProposal(name="Олег", kind="person", aliases=["брат"])])
    episode(m, clock, "Я живу в Самаре, а мой брат Олег — в Питере")
    m.remember("v", "Владимир любит рыбалку")
    assert inside == []


# ---------------------------------------------------------------- 10. «запомни» через шлюз
def test_remember_goes_through_gate():
    m, clock, _, _ = make()
    with pytest.raises(ValueError):
        m.remember("v", "Пароль от почты qwerty123")
    ev = m.observe(Observation("v", "Запомни: я не ем свинину"))
    a = m.remember("v", "Владимир не ест свинину", source_event_id=ev.event_id)
    b = m.remember("v", "Владимир не ест свинину")
    assert a == b
    f = m.facts.get(a)
    assert f.source_episode_id == ev.episode_id and f.observed_at == m.ctx.db.scalar(
        "SELECT ts FROM events WHERE id=?", (ev.event_id,))


# ---------------------------------------------------------------- мелочи
def test_device_event_does_not_split_live_conversation():
    m, clock, _, _ = make()
    a = m.observe(Observation("v", "Давай обсудим поездку"))
    clock.advance(minutes=6)
    b = m.observe(Observation("v", "[ПК] открыт браузер", speaker="device", channel="device"))
    clock.advance(minutes=1)
    c = m.observe(Observation("v", "Так вот, про поездку"))
    assert a.episode_id == b.episode_id == c.episode_id


def test_double_close_is_harmless():
    m, clock, _, _ = make()
    r = m.observe(Observation("v", "Привет, как дела у тебя"))
    m.episodes.close(r.episode_id)
    m.episodes.close(r.episode_id)
    assert m.ctx.db.scalar("SELECT COUNT(*) FROM memory_audit WHERE op='close'") == 1


def test_reembed_failure_keeps_event_log_protected(tmp_path):
    path = tmp_path / "m.db"
    m = CognitiveMemory(path, embedder=HashEmbedder(), clock=FakeClock())
    m.add_person("v", "Владимир")
    m.observe(Observation("v", "Первая реплика"))
    m.ctx.db.close()

    class Broken(HashEmbedder):
        def __init__(self):
            super().__init__()
            self.name = "broken"

        def embed(self, texts, *, query=False):
            raise RuntimeError("модель не загрузилась")

    with pytest.raises(RuntimeError):
        CognitiveMemory(path, embedder=Broken(), clock=FakeClock())
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='events_append_only'").fetchone()
