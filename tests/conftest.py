import pytest

from cogmem.clock import FakeClock
from cogmem.embed import HashEmbedder
from cogmem.memory import CognitiveMemory


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def mem(clock):
    m = CognitiveMemory(embedder=HashEmbedder(), clock=clock)
    m.add_person("owner", "Владимир", role="owner", aliases=["Вова"])
    m.add_person("mama", "Ольга", role="family", timezone="Europe/Samara")
    return m


def say(mem, clock, person, *texts, speaker="user", gap_min=1.0, **kw):
    from cogmem.types import Observation

    out = []
    for t in texts:
        out.append(mem.observe(Observation(person, t, speaker=speaker, **kw)))
        clock.advance(minutes=gap_min)
    return out
