"""Органы и замок: свобода по умолчанию, замок — только с ключом от человека."""

import pytest

from cogmem.clock import FakeClock
from cogmem.embed import HashEmbedder
from cogmem.memory import CognitiveMemory
from cogmem.types import Observation
from jarvis.brain.tools import ToolBox
from jarvis.devices import Device, DeviceHub, DeviceResult
from jarvis.keys import KeyRing
from jarvis.secrets import Vault
from jarvis.skills import SkillBank
from jarvis.workshop import LocalWorkshop


@pytest.fixture
def box(tmp_path):
    clock = FakeClock()
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=clock)
    mem.add_person("owner", "Владимир", role="owner")
    mem.add_person("mama", "Ольга", role="family", timezone="Europe/Samara")
    ws = LocalWorkshop(tmp_path / "ws", skills_dir=tmp_path / "skills")
    hub = DeviceHub()
    calls = []

    def exe(action, args, timeout):
        calls.append(args.get("code", action))
        if action == "screenshot":
            return DeviceResult(True, "снимок 100x50", "iVBORw0KGgo=")
        return DeviceResult(True, f"выполнено: {str(args)[:60]}")

    hub.register(Device("pc", "owner", "windows", "ПК Владимира", ["powershell", "python"], exe, {"screen", "input"}))
    hub.register(Device("mama-phone", "mama", "android", "Телефон мамы", ["shell"], exe))
    tb = ToolBox(mem, workshop=ws, skills=SkillBank(mem, ws, tmp_path / "skills"), keys=KeyRing(mem),
                 devices=hub, vault=Vault(tmp_path / "vault.bin"))
    ev = mem.observe(Observation("owner", "Разрешаю")).event_id
    return tb, mem, calls, ev


def code_args(code, effects=(), target=None, amount=None):
    return {"code": code, "purpose": "тест", "effects": list(effects), "target": target, "amount_eur": amount}


def test_free_by_default(box):
    tb, mem, calls, ev = box
    out, err = tb.run("owner", "run_code", code_args("print(2 + 2)"))
    assert not err and "4" in out
    out, err = tb.run("owner", "device_run", {**code_args("winget install VLC"), "device": "pc", "language": "powershell"})
    assert not err and calls  # своё устройство — без вопросов


def test_money_needs_key_with_limit(box):
    tb, mem, calls, ev = box
    out, err = tb.run("owner", "run_code", code_args("print('покупка')", ["money"], "продукты", 30))
    assert err and "🔒" in out
    out, err = tb.run("owner", "key_grant", {"scope": "money", "target": "продукты", "limit_eur": 50,
                                             "duration": "forever"}, source_event_id=ev)
    assert not err
    assert not tb.run("owner", "run_code", code_args("print('ok')", ["money"], "продукты", 30))[1]
    out, err = tb.run("owner", "run_code", code_args("print('ok')", ["money"], "продукты", 30))
    assert err and "🔒" in out  # 30 + 30 > 50 — лимит


def test_key_only_from_human(box):
    tb, mem, calls, ev = box
    out, err = tb.run("owner", "key_grant", {"scope": "message", "target": None, "limit_eur": None,
                                             "duration": "forever"}, origin="internal")
    assert err and not tb.keys.active("owner")


def test_once_key_and_revoke(box):
    tb, mem, calls, ev = box
    tb.run("owner", "key_grant", {"scope": "message", "target": "мама", "limit_eur": None, "duration": "once"},
           source_event_id=ev)
    assert not tb.run("owner", "run_code", code_args("print('пишу маме')", ["message"], "мама"))[1]
    assert tb.run("owner", "run_code", code_args("print('ещё раз')", ["message"], "мама"))[1]  # ключ на раз
    tb.run("owner", "key_grant", {"scope": "message", "target": None, "limit_eur": None, "duration": "forever"},
           source_event_id=ev)
    tb.run("owner", "key_revoke", {"ref": None, "scope": "message"})
    assert tb.run("owner", "run_code", code_args("print('x')", ["message"]))[1]


def test_relatives_device_and_delete_are_locked(box):
    tb, mem, calls, ev = box
    out, err = tb.run("owner", "device_run", {**code_args("ls"), "device": "mama-phone", "language": "shell"})
    assert err and "🔒" in out
    out, err = tb.run("owner", "device_run", {**code_args("Remove-Item C:\\Users\\V\\Photos -Recurse"),
                                              "device": "pc", "language": "powershell"})
    assert err and "удаление" in out  # не указал effects — замок всё равно сработал


def test_skill_gated_by_tests_and_usable(box):
    tb, mem, calls, ev = box
    bad = {"name": "add_two", "description": "Сложить два числа", "instructions": "add(a, b)",
           "code": "def add(a, b):\n    return a - b\n", "tests": "from add_two import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
           "locks": []}
    out, err = tb.run("owner", "skill_create", bad)
    assert err and "не прошли" in out and tb.skills.get("add_two") is None
    good = {**bad, "code": "def add(a, b):\n    return a + b\n"}
    out, err = tb.run("owner", "skill_create", good)
    assert not err and tb.skills.get("add_two") is not None
    out, err = tb.run("owner", "run_code", code_args("from add_two import add\nprint(add(20, 22))"))
    assert not err and "42" in out
    assert "add_two" in tb.run("owner", "skill_search", {"query": "сложить числа"})[0]
    assert mem.ctx.db.scalar("SELECT successes FROM procedures WHERE name='add_two'") == 1


def test_skill_locks_apply_when_imported(box):
    tb, mem, calls, ev = box
    sk = {"name": "pay_shop", "description": "Оплатить заказ", "instructions": "pay()", "locks": ["money"],
          "code": "def pay():\n    return 'paid'\n", "tests": "from pay_shop import pay\n\ndef test_pay():\n    assert pay() == 'paid'\n"}
    assert not tb.run("owner", "skill_create", sk)[1]
    out, err = tb.run("owner", "run_code", code_args("from pay_shop import pay\nprint(pay())"))
    assert err and "🔒" in out


def test_secrets_are_filled_and_scrubbed(box):
    tb, mem, calls, ev = box
    tb.vault.set("wifi", "S3cretPass")
    out, err = tb.run("owner", "run_code", code_args("pw = '{{secret:wifi}}'\nprint(len(pw), pw)"))
    assert not err and "10" in out and "S3cretPass" not in out
    out, err = tb.run("owner", "run_code", code_args("print('{{secret:nope}}')"))
    assert err and "нет секретов" in out


def test_workshop_has_no_api_keys(box, monkeypatch):
    tb, mem, calls, ev = box
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    out, err = tb.run("owner", "run_code", code_args("import os\nprint('ANTHROPIC_API_KEY' in os.environ)"))
    assert "False" in out
