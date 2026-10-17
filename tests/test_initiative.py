from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from cogmem.clock import FakeClock
from cogmem.embed import HashEmbedder
from cogmem.llm import ScriptedLLM
from cogmem.memory import CognitiveMemory
from jarvis.mind.initiative import Initiative, WakeDecision


def make(decision):
    clock = FakeClock()
    clock.set(datetime(2026, 3, 10, 14, 0, tzinfo=ZoneInfo("Europe/Paris")))
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=clock)
    mem.add_person("owner", "Владимир", role="owner")
    llm = ScriptedLLM(lambda schema, s, u: decision)
    stim, sent = [], []
    ini = Initiative(mem, llm, lambda p, r: (stim.append(r), SimpleNamespace(text="Пора позвонить в банк", silent=False))[1],
                     lambda p, t: sent.append(t))
    return ini, mem, clock, llm, stim, sent


def test_no_reasons_no_llm_call():
    ini, mem, clock, llm, stim, sent = make(WakeDecision(wake=True, urgent=False, focus="x"))
    assert ini.check("owner") is None and not llm.calls and not stim


def test_due_goal_wakes_mind_and_notifies():
    ini, mem, clock, llm, stim, sent = make(WakeDecision(wake=True, urgent=False, focus="Вернуться к цели"))
    gid = mem.goals.add("owner", "Закрыть старый счёт в банке", next_check=clock.now() - 60)
    assert ini.check("owner") == "Пора позвонить в банк" and sent and stim
    assert mem.goals.get(gid).next_check > clock.now()  # не дёргает повторно сразу


def test_quiet_hours_postpone_non_urgent():
    ini, mem, clock, llm, stim, sent = make(WakeDecision(wake=True, urgent=False, focus="мелочь"))
    clock.set(datetime(2026, 3, 10, 23, 30, tzinfo=ZoneInfo("Europe/Paris")))
    mem.goals.add("owner", "Подобрать фильм", next_check=clock.now() - 60)
    assert ini.check("owner") is None and not stim


def test_same_device_event_does_not_wake_twice():
    from cogmem.types import Observation

    ini, mem, clock, llm, stim, sent = make(WakeDecision(wake=True, urgent=False, focus="Мама написала"))
    mem.observe(Observation("owner", "Уведомление: Мама — позвони мне", speaker="device", source_kind="external"))
    clock.advance(minutes=1)
    assert ini.check("owner") and len(llm.calls) == 1
    clock.advance(minutes=20)
    assert ini.check("owner") is None and len(llm.calls) == 1  # то же событие повторно не будит
