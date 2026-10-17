import json
import os
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from cogmem.clock import FakeClock
from cogmem.embed import HashEmbedder
from cogmem.memory import CognitiveMemory
from jarvis.channels.http_api import Api, create_token


class FakeVoice:
    def transcribe(self, audio):
        return audio.decode()

    def speak(self, text, fmt):
        return b"MP3" + text.encode(), "audio/mpeg"


@pytest.fixture
def api():
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=FakeClock())
    mem.add_person("owner", "Владимир", role="owner")
    seen = []
    brain = SimpleNamespace(handle=lambda p, t, **kw: (seen.append((p, t, kw)), SimpleNamespace(text=f"ответ: {t}"))[1])
    a = Api(SimpleNamespace(memory=mem, brain=brain), host="127.0.0.1", port=0, voice=FakeVoice())
    a.start()
    yield a, mem, seen, create_token(mem, "owner", "iphone")
    a.stop()


def post(api, path, body, token=None, ctype="application/json"):
    req = urllib.request.Request(f"http://127.0.0.1:{api.port}{path}", data=body, method="POST",
                                 headers={"Content-Type": ctype, **({"Authorization": f"Bearer {token}"} if token else {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=10) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def test_auth_required(api):
    a, mem, seen, token = api
    with pytest.raises(urllib.error.HTTPError) as e:
        post(a, "/api/ask", json.dumps({"text": "привет"}).encode(), "jv_wrong")
    assert e.value.code == 401 and not seen


def test_ask_voice_and_event(api):
    a, mem, seen, token = api
    _, _, body = post(a, "/api/ask", json.dumps({"text": "Привет"}).encode(), token)
    assert json.loads(body)["reply"] == "ответ: Привет" and seen[-1][0] == "owner"
    _, _, body = post(a, "/api/voice", "Сколько времени".encode(), token, "audio/m4a")
    assert json.loads(body) == {"heard": "Сколько времени", "reply": "ответ: Сколько времени"}
    _, ctype, body = post(a, "/api/voice?reply=audio", "Скажи голосом".encode(), token, "audio/m4a")
    assert ctype == "audio/mpeg" and body.startswith(b"MP3")
    post(a, "/api/event", json.dumps({"text": "Пришёл домой"}).encode(), token)
    row = mem.ctx.db.one("SELECT speaker, text FROM events ORDER BY id DESC LIMIT 1")
    assert row["speaker"] == "device" and "Пришёл домой" in row["text"]


@pytest.mark.skipif(not os.environ.get("JARVIS_TEST_VOICE"), reason="тяжёлые модели: JARVIS_TEST_VOICE=1")
def test_real_voice_round_trip(tmp_path):
    from jarvis.voice import Voice

    v = Voice(os.environ.get("JARVIS_TEST_MODELS", tmp_path))
    audio, mime = v.speak("Напомни завтра позвонить маме", "ogg")
    assert mime == "audio/ogg" and len(audio) > 1000
    heard = v.transcribe(audio).lower()
    assert "напомни" in heard and "маме" in heard
