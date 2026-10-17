"""Живой голосовой разговор: разбивка ответа на фразы, эхо, потоковый ответ «сознания», звонок целиком."""

import json
import struct
import time
from types import SimpleNamespace

import numpy as np
import pytest

from cogmem.clock import FakeClock
from cogmem.embed import HashEmbedder
from cogmem.memory import CognitiveMemory
from jarvis.channels.call import CallServer, SpeechSplitter, is_echo, speakable
from jarvis.channels.http_api import create_token
from jarvis.voice.vad import EnergySegmenter
from tests.fake_claude import response, text_block, tool_block
from tests.test_brain import setup as brain_setup


def test_splitter_streams_sentences_and_hides_markers():
    sp = SpeechSplitter()
    out = []
    for chunk in ["Прив", "ет! Сейчас ", "посмотрю.", " Завтра +18 и солнце", ". ⟦ис", "п: F1, E2⟧"]:
        out += sp.feed(chunk)
    out += sp.flush()
    assert out == ["Привет!", "Сейчас посмотрю.", "Завтра +18 и солнце."]
    sp = SpeechSplitter()
    out = sp.feed("Готово: [") + sp.feed("[ярлык:Фонарик|Включить фонарик]] нажми кнопку.\n") + sp.flush()
    assert out == ["Готово:  нажми кнопку."] and "ярлык" not in "".join(out)
    sp = SpeechSplitter()
    assert sp.feed("⟦молчу⟧") == [] and sp.flush() == []
    long = sp.feed("слово, " * 60)
    assert long and all(len(s) <= 220 for s in long)


def test_speakable_and_echo():
    assert speakable("**Важно**: смотри https://example.com/x") == "Важно : смотри ссылку показал на экране"
    assert speakable("— …") == ""
    spoken = ["Завтра в Париже будет солнечно.", "Около восемнадцати градусов."]
    assert is_echo("в париже будет солнечно", spoken)
    assert not is_echo("стоп подожди", spoken)
    assert not is_echo("", spoken)


def test_brain_streams_text_of_every_step():
    def script(call):
        last = call["messages"][-1]
        if isinstance(last["content"], list) and last["content"][0].get("type") == "tool_result":
            return response([text_block("В Париже солнечно. ⟦исп: —⟧")])
        return response([text_block("Сейчас посмотрю."),
                         tool_block("recall", {"query": "погода", "period": None, "include_outdated": False})],
                        stop="tool_use")

    brain, mem, clock, client = brain_setup(script)
    chunks = []
    r = brain.handle("owner", "Какая погода?", channel="call", on_text=chunks.append, effort="low")
    assert r.text == "В Париже солнечно."
    joined = "".join(chunks)
    assert "Сейчас посмотрю." in joined and "В Париже солнечно." in joined
    assert all(c["output_config"]["effort"] == "low" for c in client.calls)


# ---------------------------------------------------------------- звонок целиком
def tone(seconds, amp=0.3):
    t = np.arange(int(16000 * seconds)) / 16000
    return (np.sin(2 * np.pi * 300 * t) * amp * 32767).astype("<i2").tobytes()


def silence(seconds):
    return b"\0\0" * int(16000 * seconds)


class FakeVoice:
    """Короткая фраза — вопрос, длинная — «перебивание»."""

    def transcribe(self, audio, pcm=None):
        return "Какая завтра погода" if len(pcm) / 32000 < 2.8 else "Стоп, подожди"

    def speak(self, text, fmt):
        return b"MP3" + text.encode(), "audio/mpeg"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr("jarvis.channels.call.make_segmenter", lambda d: EnergySegmenter())
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=FakeClock())
    mem.add_person("owner", "Владимир", role="owner")
    seen = []

    def handle(person, text, **kw):
        seen.append((person, text, kw))
        for chunk in ["Завтра в Париже ", "солнечно. ", "Около восемнадцати ", "градусов. ⟦исп: —⟧"]:
            kw["on_text"](chunk)
            time.sleep(0.05)
        return SimpleNamespace(text="Завтра в Париже солнечно. Около восемнадцати градусов.")

    j = SimpleNamespace(memory=mem, brain=SimpleNamespace(handle=handle), s=SimpleNamespace(call_effort="low"),
                        enroll_voice=lambda p, pcm: None)
    srv = CallServer(j, host="127.0.0.1", port=0, voice=FakeVoice())
    srv.start()
    yield srv, create_token(mem, "owner"), seen
    srv.stop()


def recv_until(ws, kind, timeout=10):
    """Читать сообщения до нужного типа; вернуть все прочитанные (JSON) и двоичные кадры."""
    got, audio = [], []
    end = time.time() + timeout
    while time.time() < end:
        m = ws.recv(timeout=end - time.time())
        if isinstance(m, bytes):
            audio.append(m)
            continue
        m = json.loads(m)
        got.append(m)
        if m["type"] == kind:
            return got, audio
    raise AssertionError(f"не дождался {kind}: {got}")


def stream(ws, pcm):
    for i in range(0, len(pcm), 2048):
        ws.send(pcm[i:i + 2048])


def test_call_rejects_bad_token(server):
    from websockets.sync.client import connect

    srv, token, seen = server
    with connect(f"ws://127.0.0.1:{srv.port}", proxy=None) as ws:
        ws.send(json.dumps({"type": "hello", "token": "jv_wrong"}))
        assert json.loads(ws.recv(timeout=5))["type"] == "error"


def test_call_conversation_and_barge_in(server):
    from websockets.sync.client import connect

    srv, token, seen = server
    with connect(f"ws://127.0.0.1:{srv.port}", proxy=None) as ws:
        ws.send(json.dumps({"type": "hello", "token": token}))
        got, audio = recv_until(ws, "done")  # приветствие
        assert got[0]["type"] == "ready" and audio and audio[0][4:].startswith(b"MP3")
        ws.send(json.dumps({"type": "played", "turn": 1}))
        recv_until(ws, "state")  # слушаю

        # Сказал фразу и замолчал — без всяких кнопок.
        stream(ws, silence(0.5) + tone(1.0) + silence(1.2))
        got, audio = recv_until(ws, "done")
        types = [m["type"] for m in got]
        assert {"type": "heard", "text": "Какая завтра погода"} in got
        assert {"type": "state", "state": "thinking"} in got and types.index("say") < types.index("reply")
        said = [m["text"] for m in got if m["type"] == "say"]
        assert said == ["Завтра в Париже солнечно.", "Около восемнадцати градусов."]  # по предложениям
        assert len(audio) == 2 and struct.unpack(">I", audio[0][:4])[0] == got[-1]["turn"]
        assert seen[-1][0] == "owner" and seen[-1][2]["channel"] == "call" and seen[-1][2]["effort"] == "low"
        ws.send(json.dumps({"type": "played", "turn": got[-1]["turn"]}))
        recv_until(ws, "state")

        # Новый вопрос — и перебиваем Джарвиса, пока он говорит (playback не закончен).
        stream(ws, tone(1.0) + silence(1.2))
        got, _ = recv_until(ws, "done")
        turn = got[-1]["turn"]
        stream(ws, tone(3.0) + silence(1.2))
        got, _ = recv_until(ws, "interrupt")
        assert got[-1]["turn"] == turn
        got, _ = recv_until(ws, "done")  # перебившая фраза стала следующей репликой
        assert seen[-1][1] == "Стоп, подожди"
        assert "перебили" in seen[-1][2]["note"]
