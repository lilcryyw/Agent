import json
import os
import urllib.request
from types import SimpleNamespace

import pytest

from cogmem.clock import FakeClock
from cogmem.embed import HashEmbedder
from cogmem.memory import CognitiveMemory
from jarvis.brain.tools import ToolBox
from jarvis.channels.http_api import Api, create_token


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr("jarvis.channels.http_api.CORS_ORIGINS", ["https://jarvis-app.pages.dev"])
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=FakeClock())
    mem.add_person("owner", "Владимир", role="owner")
    a = Api(SimpleNamespace(memory=mem, brain=None), host="127.0.0.1", port=0)
    a.start()
    yield a, create_token(mem, "owner")
    a.stop()


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def test_cors_allows_only_listed_origin(api):
    a, token = api
    req = urllib.request.Request(f"http://127.0.0.1:{a.port}/api/health", method="OPTIONS",
                                 headers={"Origin": "https://jarvis-app.pages.dev"})
    with opener().open(req, timeout=10) as r:
        assert r.status == 204
        assert r.headers["Access-Control-Allow-Origin"] == "https://jarvis-app.pages.dev"
        assert "Authorization" in r.headers["Access-Control-Allow-Headers"]
    req = urllib.request.Request(f"http://127.0.0.1:{a.port}/api/health", method="OPTIONS",
                                 headers={"Origin": "https://evil.example"})
    with opener().open(req, timeout=10) as r:
        assert r.headers.get("Access-Control-Allow-Origin") is None


def test_iphone_action_returns_marker_and_rejects_unknown():
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=FakeClock())
    mem.add_person("owner", "Владимир", role="owner")
    tb = ToolBox(mem, workshop=None, skills=None, keys=None, devices=None, vault=None)
    out, err = tb._iphone({"id": "alarm", "input": "07:30"})
    assert not err and out.count("[[ярлык:Джарвис: будильник|") == 1 and "|07:30]]" in out
    out, err = tb._iphone({"id": "fly_to_moon", "input": None})
    assert err


@pytest.mark.skipif(not os.path.exists("/opt/pw-browsers/chromium"), reason="нужен браузер")
def test_webapp_renders_shortcut_button(tmp_path):
    from playwright.sync_api import sync_playwright

    from jarvis.channels.http_api import WEBAPP

    html = (WEBAPP / "index.html").read_text(encoding="utf-8")
    page_file = tmp_path / "index.html"
    page_file.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        pg = b.new_page()
        pg.goto(page_file.as_uri())
        pg.evaluate("""() => { const w = document.createElement('div'); w.id='probe';
            document.body.appendChild(w);
            fill(w, 'Ставлю. [[ярлык:Джарвис: будильник|⏰ Поставить будильник|07:30]] Удачи!'); }""")
        links = pg.eval_on_selector_all("#probe a.btn", "els => els.map(e => [e.textContent, e.href])")
        text = pg.inner_text("#probe")
        b.close()
    assert links and links[0][0] == "⏰ Поставить будильник"
    assert links[0][1].startswith("shortcuts://run-shortcut?name=")
    assert "input=text&text=07%3A30" in links[0][1]
    assert "[[" not in text and "Удачи!" in text
