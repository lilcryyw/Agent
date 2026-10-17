from cogmem.clock import FakeClock
from cogmem.embed import HashEmbedder
from cogmem.memory import CognitiveMemory
from jarvis.brain.agent import Brain, split_used
from jarvis.brain.prompts import SYSTEM_PROMPT
from jarvis.config import Settings
from tests.fake_claude import FakeClaude, response, text_block, tool_block


def setup(script, tmp_path=None):
    import tempfile

    from jarvis.brain.tools import ToolBox
    from jarvis.devices import DeviceHub
    from jarvis.keys import KeyRing
    from jarvis.secrets import Vault
    from jarvis.skills import SkillBank
    from jarvis.workshop import LocalWorkshop

    root = tempfile.mkdtemp()
    clock = FakeClock()
    mem = CognitiveMemory(embedder=HashEmbedder(), clock=clock)
    mem.add_person("owner", "Владимир", role="owner")
    s = Settings(db_path=":memory:", use_web_search=False)
    client = FakeClaude(script)
    ws = LocalWorkshop(f"{root}/ws", skills_dir=f"{root}/skills")
    tools = ToolBox(mem, workshop=ws, skills=SkillBank(mem, ws, f"{root}/skills"), keys=KeyRing(mem),
                    devices=DeviceHub(), vault=Vault(f"{root}/vault.bin"))
    return Brain(mem, s, client, tools), mem, clock, client


def last_user_text(call):
    content = call["messages"][-1]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))


def test_split_used_marker():
    clean, refs = split_used("Мама живёт в Тольятти.\n⟦исп: F2, E7⟧")
    assert clean == "Мама живёт в Тольятти." and refs == ["F2", "E7"]
    assert split_used("Ок ⟦исп: —⟧") == ("Ок", [])


def test_turn_with_tool_and_append_only_history():
    def script(call):
        msgs = call["messages"]
        last = msgs[-1]
        if last["role"] == "user" and isinstance(last["content"], list) and last["content"] and \
                last["content"][0].get("type") == "tool_result":
            return response([text_block("Запомнил! ⟦исп: —⟧")])
        if "Запомни" in last_user_text(call):
            return response([tool_block("note", {"op": "remember", "text": "У мамы аллергия на пенициллин",
                                                "about": "мама", "ref": None, "share_with_family": False})],
                            stop="tool_use")
        return response([text_block("У мамы аллергия на пенициллин. ⟦исп: F1⟧")], cache_read=3000)

    brain, mem, clock, client = setup(script)
    r1 = brain.handle("owner", "Запомни: у мамы аллергия на пенициллин")
    assert r1.text == "Запомнил!" and r1.tool_calls == ["note"]
    assert mem.facts.get(1).statement == "У мамы аллергия на пенициллин"
    clock.advance(minutes=2)
    r2 = brain.handle("owner", "На что у мамы аллергия?")
    assert "⟦" not in r2.text and r2.used == ["F1"]

    # Неизменная «шапка» запроса: системный промпт и инструменты одинаковы во всех вызовах.
    systems = {str(c["system"]) for c in client.calls}
    tools = {str(c["tools"]) for c in client.calls}
    assert len(systems) == 1 and len(tools) == 1
    assert client.calls[0]["system"][0]["text"] == SYSTEM_PROMPT
    assert client.calls[0]["system"][0]["cache_control"]["ttl"] == "1h"
    names = [t["name"] for t in client.calls[0]["tools"]]
    assert names == sorted(names)
    # История только дописывается: каждый следующий запрос начинается с предыдущего.
    for prev, nxt in zip(client.calls, client.calls[1:]):
        assert nxt["messages"][: len(prev["messages"])] == prev["messages"]
    # Факт уже в истории (модель сама его записала) — повторно в <память> не подаётся.
    assert "пенициллин" in str(client.calls[-1]["messages"][:-1])
    assert "[F1]" not in last_user_text(client.calls[-1])


def test_new_session_after_pause_has_profile_and_memory():
    brain, mem, clock, client = setup(lambda call: response([text_block("Ок ⟦исп: —⟧")]))
    mem.remember("owner", "Владимир живёт в Париже", importance=0.9)
    brain.handle("owner", "Привет")
    first = client.calls[-1]["messages"][0]["content"][0]["text"]
    assert "<о_собеседнике>" in first and "Париже" in first
    clock.advance(hours=3)
    r = brain.handle("owner", "Снова привет")
    assert r.new_session and len(client.calls[-1]["messages"]) == 1  # свежая короткая сессия


def test_already_shown_memory_is_not_repeated_in_session():
    brain, mem, clock, client = setup(lambda call: response([text_block("Ок ⟦исп: —⟧")]))
    mem.remember("owner", "Любимый чай Владимира — пуэр", importance=0.4)
    brain.handle("owner", "Какой чай я люблю?")
    clock.advance(minutes=1)
    brain.handle("owner", "А какой чай мне заварить?")
    texts = [b["text"] for m in client.calls[-1]["messages"] if m["role"] == "user" and isinstance(m["content"], list)
             for b in m["content"] if b.get("type") == "text"]
    assert sum(t.count("пуэр") for t in texts) <= 2  # показано один раз (плюс, возможно, в профиле)


def test_budget_cap_stops_calls():
    brain, mem, clock, client = setup(lambda call: response([text_block("Ок")], inp=10_000_000))
    brain.s.monthly_budget_usd = 1.0
    brain.handle("owner", "Привет")          # этот вызов «съест» бюджет ($40 при Opus)
    r = brain.handle("owner", "Ещё вопрос")  # а этот уже не пойдёт в API
    assert "бюджет" in r.text and len(client.calls) == 1


def test_internal_stimulus_can_stay_silent_and_cannot_grant_keys():
    def script(call):
        last = call["messages"][-1]
        if last["role"] == "user" and isinstance(last["content"], list) and last["content"] and \
                last["content"][0].get("type") == "tool_result":
            return response([text_block("⟦молчу⟧")])
        return response([tool_block("key_grant", {"scope": "money", "target": None, "limit_eur": 1000,
                                                  "duration": "forever"})], stop="tool_use")

    brain, mem, clock, client = setup(script)
    r = brain.handle_stimulus("owner", "Подошёл срок цели")
    assert r.silent and r.text == ""
    assert brain.tools.keys.active("owner") == []  # по своей инициативе ключ не выдать
    assert "<внутренний_повод>" in str(client.calls[0]["messages"][-1])
