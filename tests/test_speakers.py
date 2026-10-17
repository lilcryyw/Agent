import os
from types import SimpleNamespace

import numpy as np
import pytest

from cogmem.clock import FakeClock
from cogmem.embed import HashEmbedder
from cogmem.memory import CognitiveMemory
from jarvis.runtime import Jarvis
from jarvis.voice.speakers import Match


def runtime_stub(match, profiles=True):
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=FakeClock())
    mem.add_person("owner", "Владимир", role="owner")
    mem.add_person("mama", "Ольга", role="family")
    j = Jarvis.__new__(Jarvis)
    j.memory = mem
    j.speakers = SimpleNamespace(identify=lambda pcm: match, profiles=lambda: {"owner": 1} if profiles else {})
    return j


def test_recognized_family_member_on_owner_device():
    person, note = Jarvis.who_speaks(runtime_stub(Match("mama", 0.9, 0.3)), "owner", b"")
    assert person == "mama" and "Ольга" in note


def test_unsure_voice_stays_owner_but_cautious():
    person, note = Jarvis.who_speaks(runtime_stub(Match(None, 0.8, 0.02)), "owner", b"")
    assert person == "owner" and "Не раскрывай личное" in note


def test_no_profiles_yet_no_note():
    assert Jarvis.who_speaks(runtime_stub(Match(None, 0, 0), profiles=False), "owner", b"") == ("owner", None)


@pytest.mark.skipif(not os.environ.get("JARVIS_TEST_VOICE"), reason="тяжёлые модели: JARVIS_TEST_VOICE=1")
def test_real_speaker_identification():
    import io
    import wave

    from piper import PiperVoice

    from jarvis.voice import ffmpeg
    from jarvis.voice.speakers import Speakers

    models = os.environ["JARVIS_TEST_MODELS"]
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=FakeClock())
    sp = Speakers(mem, models)
    voices = {n: PiperVoice.load(f"{models}/piper/ru_RU-{n}-medium.onnx") for n in ("dmitri", "irina", "denis")}

    def pcm(voice, text):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            voices[voice].synthesize_wav(text, w)
        return ffmpeg(buf.getvalue(), ["-ar", "16000", "-ac", "1", "-f", "s16le"])

    for t in ("Привет, Джарвис, как у тебя дела сегодня?", "Напомни мне завтра купить хлеб и молоко"):
        assert sp.enroll("owner", pcm("dmitri", t))
        assert sp.enroll("mama", pcm("irina", t))
    assert sp.identify(pcm("dmitri", "Какая погода будет на выходных в Париже?")).person_id == "owner"
    assert sp.identify(pcm("irina", "Позвони, пожалуйста, моему сыну вечером")).person_id == "mama"
    assert sp.identify(pcm("denis", "Добрый день, я сосед, можно спросить?")).person_id is None  # чужой
    assert not sp.enroll("owner", pcm("dmitri", "Да"))  # слишком коротко
