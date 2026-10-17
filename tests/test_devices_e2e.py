"""Сквозная проверка: настоящий клиент устройства в отдельном процессе ↔ шлюз ↔ органы."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cogmem.clock import SystemClock
from cogmem.embed import HashEmbedder
from cogmem.memory import CognitiveMemory
from jarvis.devices import DeviceHub
from jarvis.devices.gateway import CLIENT_PATH, Gateway

pytest.importorskip("websockets")


def wait(cond, timeout=15):
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def gw():
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=SystemClock())
    mem.add_person("owner", "Владимир", role="owner")
    hub = DeviceHub()
    g = Gateway(mem, hub, host="127.0.0.1", port=0)
    g.start()
    return g, hub, mem


def client(home, *args):
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    return [sys.executable, str(CLIENT_PATH), *args], env


def test_pair_connect_run_and_reject_bad_code(gw, tmp_path):
    g, hub, mem = gw
    url = f"ws://127.0.0.1:{g.port}/devices"
    cmd, env = client(tmp_path, "--server", url, "--pair", "XXXX-XXXX", "--once")
    bad = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    assert bad.returncode != 0 and "код неверный" in (bad.stdout + bad.stderr)

    code = g.create_pairing("owner", "linux")
    cmd, env = client(tmp_path, "--server", url, "--pair", code, "--name", "Тестовый ноутбук", "--once")
    ok = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    assert ok.returncode == 0, ok.stderr
    assert (tmp_path / ".jarvis_device.json").exists()
    # Код одноразовый.
    cmd, env = client(tmp_path / "other", "--server", url, "--pair", code, "--once")
    (tmp_path / "other").mkdir()
    assert subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30).returncode != 0

    cmd, env = client(tmp_path)
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert wait(lambda: hub.all()), "устройство не подключилось"
        dev = hub.all()[0]
        assert dev.owner == "owner" and "python" in dev.languages
        res = dev.run("python", "print(6 * 7)", 30)
        assert res.ok and "42" in res.output
        res = dev.run("shell", "echo привет", 30)
        assert res.ok and "привет" in res.output
        # Событие о подключении записано в память.
        assert mem.ctx.db.scalar("SELECT COUNT(*) FROM events WHERE speaker='device'") >= 1
        g.forget_device(dev.id)
        assert wait(lambda: not hub.all())
    finally:
        proc.kill()


def test_client_download_endpoint(gw):
    import urllib.request

    g, hub, mem = gw
    body = urllib.request.urlopen(f"http://127.0.0.1:{g.port}/devices/client.py", timeout=10).read().decode()
    assert "Клиент Джарвиса" in body


def test_client_falls_back_to_relay_address(gw, tmp_path):
    g, hub, mem = gw
    good = f"ws://127.0.0.1:{g.port}/devices"
    code = g.create_pairing("owner", "linux")
    cmd, env = client(tmp_path, "--server", good, "--pair", code, "--once")
    assert subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30).returncode == 0
    dead = "ws://127.0.0.1:9/devices"  # «заблокированный» основной адрес
    cmd, env = client(tmp_path, "--server", f"{dead},{good}")
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert wait(lambda: hub.all(), timeout=20), "не переключился на запасной адрес"
    finally:
        proc.kill()


def test_voice_utterance_and_proactive_say(tmp_path):
    """Устройство прислало голос → сервер ответил голосом; инициатива звучит на устройстве с динамиком."""
    import asyncio
    import base64
    import json

    from websockets.asyncio.client import connect

    mem = CognitiveMemory(embedder=HashEmbedder(), clock=SystemClock())
    mem.add_person("owner", "Владимир", role="owner")
    hub = DeviceHub()
    heard = []
    g = Gateway(mem, hub, host="127.0.0.1", port=0,
                on_utterance=lambda owner, dev, audio: (heard.append((owner, audio)), ("привет", "И тебе привет!"))[1],
                tts=lambda text: b"WAV:" + text.encode())
    g.start()
    code = g.create_pairing("owner", "windows")

    async def scenario():
        url = f"ws://127.0.0.1:{g.port}/devices"
        async with connect(url, proxy=None) as ws:
            await ws.send(json.dumps({"type": "pair", "code": code, "name": "ПК", "kind": "windows",
                                      "languages": ["python"], "capabilities": ["speaker", "microphone"]}))
            welcome = json.loads(await ws.recv())
            await ws.send(json.dumps({"type": "utterance", "audio_b64": base64.b64encode(b"RIFF...").decode()}))
            say = json.loads(await asyncio.wait_for(ws.recv(), 10))
            assert say["type"] == "say" and say["text"] == "И тебе привет!"
            assert base64.b64decode(say["audio_b64"]) == "WAV:И тебе привет!".encode()
            assert await asyncio.to_thread(g.say, "owner", "Напоминаю про налоговую")
            say2 = json.loads(await asyncio.wait_for(ws.recv(), 10))
            assert say2["text"] == "Напоминаю про налоговую"
            return welcome

    asyncio.run(scenario())
    assert heard and heard[0][0] == "owner" and heard[0][1] == b"RIFF..."
    assert not g.say("mama", "x")  # у мамы нет устройств — сказать негде
