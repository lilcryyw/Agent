from cogmem.types import Observation
from tests.conftest import say


def test_gap_starts_new_episode(mem, clock):
    a = say(mem, clock, "owner", "Привет", "Как дела?")
    clock.advance(hours=2)
    b = say(mem, clock, "owner", "Снова я")
    assert a[0].episode_id == a[1].episode_id
    assert b[0].new_episode and b[0].closed_episode_id == a[0].episode_id
    assert mem.ctx.jobs.pending("encode_episode") == 1


def test_topic_shift_word_starts_new_episode(mem, clock):
    rs = say(mem, clock, "owner", *[f"Обсуждаем ремонт кухни, пункт {i}" for i in range(6)])
    r = say(mem, clock, "owner", "Кстати, другой вопрос — что подарить маме?")[0]
    assert r.new_episode and r.closed_episode_id == rs[0].episode_id


def test_recall_finds_fact_in_other_case_forms(mem, clock):
    say(mem, clock, "owner", "Моя мама живёт в Самаре", "Ещё я люблю кофе без сахара")
    clock.advance(hours=3)
    mem.tick(encode=False)
    wm, res = mem.working_memory("owner", "Где живёт мама?")
    assert "Самаре" in wm.render()
    assert res.latency_ms < 500


def test_privacy_private_memory_is_invisible_to_others(mem, clock):
    say(mem, clock, "mama", "Только между нами: я коплю деньги Вове на подарок, сюрприз — велосипед")
    clock.advance(hours=3)
    mem.tick(encode=False)
    wm_owner, _ = mem.working_memory("owner", "подарок велосипед сюрприз")
    wm_mama, _ = mem.working_memory("mama", "подарок велосипед сюрприз")
    assert "велосипед" not in wm_owner.render()
    assert "велосипед" in wm_mama.render()


def test_family_memory_is_shared(mem, clock):
    mem.observe(Observation("mama", "Семейный ужин в субботу в 19:00 у нас дома", visibility="family"))
    clock.advance(hours=3)
    mem.tick(encode=False)
    wm, _ = mem.working_memory("owner", "когда семейный ужин?")
    assert "ужин" in wm.render()


def test_remember_and_correct_keep_history(mem, clock):
    fid = mem.remember("owner", "Мама живёт в Самаре", about="мама")
    clock.advance(days=30)
    new_id = mem.correct("owner", f"F{fid}", "Мама переехала в Тольятти")
    assert new_id
    old, new = mem.facts.get(fid), mem.facts.get(new_id)
    assert not old.current and old.superseded_by == new_id and new.current
    wm, _ = mem.working_memory("owner", "где живёт мама")
    text = wm.render()
    assert "Тольятти" in text and "Самаре" not in text  # устаревшее не мешает обычному вопросу
    wm_hist, _ = mem.working_memory("owner", "где раньше жила мама", history=True)
    assert "УСТАРЕЛО" in wm_hist.render()


def test_forget_really_deletes_only_own(mem, clock):
    fid = mem.remember("owner", "Код от домофона 1234", about=None)
    assert not mem.forget("mama", f"F{fid}")
    assert mem.forget("owner", f"F{fid}")
    assert mem.facts.get(fid) is None
    wm, _ = mem.working_memory("owner", "код от домофона")
    assert "1234" not in wm.render()


def test_feedback_strengthens_activation_and_links(mem, clock):
    f1 = mem.remember("owner", "Владимир любит кофе без сахара")
    f2 = mem.remember("owner", "Владимир пьёт кофе по утрам в 8:00")
    clock.advance(days=10)
    from cogmem.activation import base_levels

    before = base_levels(mem.ctx, [("fact", f1)])[("fact", f1)]
    mem.feedback([f"F{f1}", f"F{f2}"], [f"F{f1}", f"F{f2}", "F99999"])
    after = base_levels(mem.ctx, [("fact", f1)])[("fact", f1)]
    assert after > before
    link = mem.ctx.db.one("SELECT weight FROM links WHERE kind='co'")
    assert link is not None and 0 < link["weight"] <= 1


def test_working_memory_respects_budget(mem, clock):
    for i in range(80):
        mem.remember("owner", f"Владимир купил книгу номер {i} про историю кофе")
    wm, _ = mem.working_memory("owner", "книги про кофе")
    assert wm.tokens <= sum(vars(mem.ctx.cfg.budgets).values()) + 50
    assert 0 < len(wm.facts) < 80


def test_core_profile_is_deterministic_and_bounded(mem, clock):
    for i in range(50):
        mem.remember("owner", f"Важный факт номер {i} о Владимире и его делах", importance=0.5 + i / 200)
    a = mem.core_profile("owner")
    b = mem.core_profile("owner")
    assert a == b
    from cogmem.text.ru import estimate_tokens

    assert estimate_tokens(a) <= mem.ctx.cfg.core_max_tokens + 5
    assert mem.core.version("owner") >= 2  # пересобрано при изменениях, но не при каждом вызове
