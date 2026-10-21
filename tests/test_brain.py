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


def test_turn_budget_stops_runaway_loops():
    brain, mem, clock, client = setup(lambda call: response(
        [tool_block("recall", {"query": "что-то", "period": None, "include_outdated": False})], stop="tool_use",
        inp=400_000))  # каждый шаг дороже лимита хода при любой модели (проверка не зависит от цены модели)
    r = brain.handle("owner", "Найди всё обо всём")
    assert "Продолжать?" in r.text and len(client.calls) == 2
    # История осталась корректной: на каждый tool_use есть tool_result.
    msgs = brain.sessions["owner"].messages
    assert msgs[-2]["role"] == "user" and msgs[-2]["content"][0]["type"] == "tool_result"
    assert msgs[-1]["role"] == "assistant"  # ход закрыт ответом — следующий начнётся с чистой реплики


def assert_history_valid(messages):
    """Правила API: роли чередуются (подряд user допустимо), на каждый tool_use — tool_result, нет пустых ответов."""
    pending = set()
    for m in messages:
        content = m["content"]
        if m["role"] == "assistant":
            assert content, "пустой ответ ассистента в истории"
            assert not pending, f"tool_use без tool_result: {pending}"
            pending = {b.id for b in content if getattr(b, "type", "") == "tool_use"}
        else:
            if isinstance(content, list):
                ids = {b["tool_use_id"] for b in content if isinstance(b, dict) and b.get("type") == "tool_result"}
                assert pending <= ids or not pending, f"нет результатов для {pending - ids}"
            pending = set()
    assert not pending


def test_history_survives_cutoff_refusal_and_empty_answers():
    calls = {"n": 0}

    def script(call):
        calls["n"] += 1
        n = calls["n"]
        if n == 1:  # обрыв по длине посреди вызова инструмента
            return response([text_block("Сейчас"), tool_block("recall", {"query": "x", "period": None,
                                                                         "include_outdated": False})],
                            stop="max_tokens")
        if n == 2:
            return response([text_block("Готов ответ. ⟦исп: —⟧")])
        if n == 3:  # отказ
            return response([], stop="refusal")
        if n == 4:  # пустой ответ
            return response([], stop="end_turn")
        return response([text_block("Ок ⟦исп: —⟧")])

    brain, mem, clock, client = setup(script)
    assert brain.handle("owner", "Вопрос один").text == "Готов ответ."
    assert "не могу" in brain.handle("owner", "Вопрос два").text
    assert brain.handle("owner", "Вопрос три").silent  # пустой ответ — это молчание, а не «Готово.»
    assert brain.handle("owner", "Вопрос четыре").text == "Ок"
    assert_history_valid(brain.sessions["owner"].messages)


def test_api_failure_gives_friendly_answer_and_valid_history():
    import anthropic
    import httpx

    def script(call):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))

    brain, mem, clock, client = setup(script)
    r = brain.handle("owner", "Привет")
    assert "Попробуй через минуту" in r.text
    assert brain.sessions["owner"].messages[-1]["role"] == "assistant"


def test_restart_keeps_thread_of_conversation():
    brain, mem, clock, client = setup(lambda call: response([text_block("Ок ⟦исп: —⟧")]))
    brain.handle("owner", "Завтра встреча с Петровым в десять")
    clock.advance(minutes=2)
    brain.sessions.clear()  # как после перезапуска сервера
    brain.handle("owner", "Напомни, с кем встреча?")
    first = str(client.calls[-1]["messages"][0])
    assert "<недавний_разговор>" in first and "Петровым" in first


def test_cancel_stops_tool_loop():
    import threading

    ev = threading.Event()

    def script(call):
        ev.set()  # человек сказал «стоп», пока модель думала
        return response([tool_block("recall", {"query": "x", "period": None, "include_outdated": False})],
                        stop="tool_use")

    brain, mem, clock, client = setup(script)
    r = brain.handle("owner", "Найди всё", cancel=ev)
    assert "остановил" in r.text and len(client.calls) == 1
    assert_history_valid(brain.sessions["owner"].messages)


def test_jarvis_can_stay_silent_and_remembers_why():
    """«Сейчас скажу, а ты молчи» → тишина; договорённость живёт во внутреннем состоянии."""
    def script(call):
        last = str(call["messages"][-1])
        if "молчи" in last:
            return response([text_block("⟦молчу⟧\n⟦внутри: просил помолчать, пока не позовёт; слушаю⟧\n⟦исп: —⟧")])
        assert "просил помолчать" in last  # видит своё состояние в следующей реплике
        return response([text_block("⟦молчу⟧ ⟦внутри: всё ещё молчу — меня не звали⟧")])

    brain, mem, clock, client = setup(script)
    r = brain.handle("owner", "Сейчас я кое-что скажу, а ты молчи")
    assert r.silent and r.text == ""
    r = brain.handle("owner", "Раз, два, три")
    assert r.silent and "меня не звали" in brain.inner_state("owner")
