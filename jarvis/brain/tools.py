"""«Органы» Джарвиса — немного универсальных способностей вместо набора узких команд.

  recall / note / schedule / goal — память, напоминания, цели;
  run_code      — Python в мастерской (интернет, любые API и библиотеки, файлы) — главный «орган» (CodeAct);
  device_*      — код и команды на подключённых устройствах;
  skill_*       — найти, прочитать, создать (с тестами), дополнить опытом свои навыки;
  key_*         — ключи от замка;
  web_search / web_fetch — серверные инструменты Claude.
Всё, чего нет, Джарвис строит сам из этих органов и сохраняет как навык.

Замок проверяется здесь, в коде — никакой текст (в т.ч. с сайтов) его не откроет:
действия с деньгами, сообщениями от имени человека, удалением его данных и на устройствах родных
выполняются только при действующем ключе. Ключи выдаёт только сам человек своей репликой.
Схемы строгие; список неизменен и отсортирован (иначе ломается кэш промпта).
"""

from __future__ import annotations

import re
from typing import Any

from cogmem.govern.write_gate import parse_local_date
from cogmem.memory import CognitiveMemory
from cogmem.types import parse_ref
from jarvis.devices import DeviceHub
from jarvis.keys import SCOPES, KeyRing
from jarvis.secrets import Vault
from jarvis.skills import SkillBank
from jarvis.workshop import Workshop


def _schema(props: dict[str, Any]) -> dict:
    return {"type": "object", "properties": props, "required": sorted(props), "additionalProperties": False}


S = {"type": "string"}
SN = {"type": ["string", "null"]}
NN = {"type": ["number", "null"]}
B = {"type": "boolean"}
EFFECTS = {"type": "array", "items": {"type": "string", "enum": ["money", "message", "delete"]},
           "description": "Что из «под замком» делает этот код: money — платит/покупает; message — пишет/звонит "
                          "людям от имени человека; delete — удаляет его личные данные. Пусто — ничего из этого."}

TOOLS: list[dict] = [
    {"name": "device_list", "description": "Какие устройства сейчас подключены и что умеют.",
     "input_schema": _schema({})},
    {"name": "device_run",
     "description": "Выполнить код/команду на подключённом устройстве (ПК, телефон). Обычные действия — свободно: "
                    "открыть, установить, настроить, прочитать. target и amount_eur — для действий под замком.",
     "input_schema": _schema({"device": S, "language": {"type": "string", "enum": ["python", "powershell", "shell"]},
                              "code": S, "purpose": S, "effects": EFFECTS, "target": SN, "amount_eur": NN})},
    {"name": "goal",
     "description": "Цели — то, что ты доводишь до конца за несколько шагов/дней. op: add | update | done | drop. "
                    "next_check_local — когда вернуться к цели ('YYYY-MM-DDTHH:MM' по времени человека).",
     "input_schema": _schema({"op": {"type": "string", "enum": ["add", "update", "done", "drop"]}, "ref": SN,
                              "title": SN, "notes": SN, "next_check_local": SN})},
    {"name": "key_grant",
     "description": "Выдать ключ от замка — ТОЛЬКО когда человек сам ясно разрешил в своей реплике. "
                    "scope: money | message | delete | relative_device. duration: once | today | week | forever.",
     "input_schema": _schema({"scope": {"type": "string", "enum": sorted(SCOPES)}, "target": SN, "limit_eur": NN,
                              "duration": {"type": "string", "enum": ["once", "today", "week", "forever"]}})},
    {"name": "key_list", "description": "Действующие ключи человека.", "input_schema": _schema({})},
    {"name": "key_revoke", "description": "Отозвать ключ [K..] или все ключи области scope.",
     "input_schema": _schema({"ref": SN, "scope": SN})},
    {"name": "note",
     "description": "Работа с памятью явно. op: remember — сохранить сразу (text, about=о ком, null — о собеседнике); "
                    "correct — исправить факт ref на text; forget — удалить навсегда ref (только по желанию человека); "
                    "explain — откуда известно ref.",
     "input_schema": _schema({"op": {"type": "string", "enum": ["remember", "correct", "forget", "explain"]},
                              "ref": SN, "text": SN, "about": SN, "share_with_family": B})},
    {"name": "recall",
     "description": "Вспомнить глубже, чем в блоке <память>. query — как человек мог об этом рассказывать (другими "
                    "словами, синонимы); period — время по-русски («в прошлом месяце», «5 марта») или null; "
                    "без query и с period — что происходило в период. include_outdated — и как было раньше.",
     "input_schema": _schema({"query": SN, "period": SN, "include_outdated": B})},
    {"name": "run_code",
     "description": "Выполнить Python в мастерской: интернет, любые публичные API, расчёты, файлы, pip install. "
                    "Навыки импортируются как модули (import имя_навыка). Секреты — {{secret:имя}} прямо в коде "
                    "(подставятся при запуске, в вывод не попадут). Печатай результат через print.",
     "input_schema": _schema({"code": S, "purpose": S, "effects": EFFECTS, "target": SN, "amount_eur": NN})},
    {"name": "schedule",
     "description": "Напомнить или сделать позже: when_local 'YYYY-MM-DDTHH:MM' по времени человека, или condition "
                    "(«когда придёт домой»). cancel_ref — отменить [I..].",
     "input_schema": _schema({"what": SN, "when_local": SN, "condition": SN, "cancel_ref": SN})},
    {"name": "skill_create",
     "description": "Сохранить умение как навык: name (латиница), description (когда применять), instructions "
                    "(как вызывать), code (__init__.py), tests (функции test_* с assert). Принимается, только если "
                    "тесты прошли; иначе вернётся ошибка — исправь и повтори. locks — замки навыка.",
     "input_schema": _schema({"name": S, "description": S, "instructions": S, "code": S, "tests": S,
                              "locks": {"type": "array", "items": {"type": "string",
                                                                    "enum": ["money", "message", "delete"]}}})},
    {"name": "skill_note", "description": "Записать опыт к навыку (особенности, на чём спотыкался).",
     "input_schema": _schema({"name": S, "text": S})},
    {"name": "skill_read", "description": "Прочитать навык: описание, код, заметки опыта.",
     "input_schema": _schema({"name": S})},
    {"name": "skill_search", "description": "Найти среди своих навыков подходящие для задачи.",
     "input_schema": _schema({"query": S})},
]
for _t in TOOLS:
    _t["strict"] = True
TOOLS.sort(key=lambda t: t["name"])

# Признаки удаления личных данных в командах для устройств (страховка, если effects не указан).
DELETE_RE = re.compile(r"(rm\s+-[a-z]*r|Remove-Item[^\n]*-Recurse|shutil\.rmtree|os\.remove\(|os\.unlink\(|"
                       r"\bdel\s+/[sq]|\brmdir\s+/s|Format-Volume|\bformat\s+[a-z]:)", re.IGNORECASE)


class ToolBox:
    def __init__(self, memory: CognitiveMemory, *, workshop: Workshop, skills: SkillBank, keys: KeyRing,
                 devices: DeviceHub, vault: Vault):
        self.m = memory
        self.ws = workshop
        self.skills = skills
        self.keys = keys
        self.devices = devices
        self.vault = vault

    def definitions(self, *, web: bool) -> list[dict]:
        defs = list(TOOLS)
        if web:
            defs += [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 10},
                     {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}]
        return defs

    # --- замок ---
    def _locks_needed(self, effects: list[str], code: str, *, on_device: bool) -> set[str]:
        needed = set(effects or []) & set(SCOPES)
        for locks in self.skills.locks_in_code(code).values():
            needed |= set(locks)
        if on_device and DELETE_RE.search(code):
            needed.add("delete")
        return needed

    def _unlock(self, person: str, needed: set[str], target: str | None, amount: float | None) -> tuple[list, str | None]:
        keys = []
        for scope in sorted(needed):
            k = self.keys.find(person, scope, target=target or "", amount_eur=amount)
            if k is None:
                extra = " Для денег укажи amount_eur — ключ может быть с лимитом." if scope == "money" and amount is None \
                    else ""
                return [], (f"🔒 Под замком: {SCOPES[scope]}. Ключа нет (или он не подходит по цели/лимиту).{extra} "
                            f"Спроси человека; если он разрешит — key_grant (можно на один раз), затем повтори.")
            keys.append(k)
        return keys, None

    # --- выполнение ---
    def run(self, person: str, name: str, args: dict, *, origin: str = "user",
            source_event_id: int | None = None) -> tuple[str, bool]:
        try:
            return self._run(person, name, args, origin, source_event_id)
        except Exception as exc:  # noqa: BLE001 — ошибка органа возвращается модели, а не роняет разговор
            return f"Ошибка: {type(exc).__name__}: {exc}", True

    def _run(self, person: str, name: str, a: dict, origin: str, ev: int | None) -> tuple[str, bool]:
        m = self.m
        tz = m.person(person)["timezone"]

        if name == "recall":
            if not a.get("query") and a.get("period"):
                return m.timeline(person, a["period"]), False
            return m.recall_deep(person, a.get("query") or a.get("period") or "", period=a.get("period"),
                                 include_outdated=bool(a.get("include_outdated"))), False

        if name == "note":
            op, ref_, text = a["op"], a.get("ref"), a.get("text")
            if op == "remember":
                if not text:
                    return "Нужен text.", True
                fid = m.remember(person, text, about=a.get("about"), share_with_family=bool(a.get("share_with_family")),
                                 source_event_id=ev)
                return f"Запомнено [F{fid}].", False
            if op == "correct":
                new = m.correct(person, ref_ or "", text or "")
                return (f"Исправлено: [F{new}], старое — в истории." if new else "Нет такого факта."), new is None
            if op == "forget":
                if origin != "user":
                    return "Удалять память можно только по просьбе самого человека.", True
                ok = m.forget(person, ref_ or "")
                return ("Удалено навсегда." if ok else "Не удалось (нет такого или это не твоё)."), not ok
            return m.explain(person, ref_ or ""), False

        if name == "schedule":
            if a.get("cancel_ref"):
                u = parse_ref(a["cancel_ref"])
                row = m.ctx.db.one("SELECT person_id FROM intentions WHERE id=?", (u[1],)) if u else None
                if not row or row["person_id"] != person:
                    return "Нет такого напоминания.", True
                m.intentions.set_status(u[1], "cancelled")
                return "Отменено.", False
            if not a.get("what"):
                return "Нужно what.", True
            iid = m.add_intention(person, a["what"], due_local=a.get("when_local"), trigger=a.get("condition") or "")
            return f"Записано [I{iid}].", False

        if name == "goal":
            op = a["op"]
            if op == "add":
                gid = m.goals.add(person, a.get("title") or "цель", a.get("notes") or "",
                                  parse_local_date(a.get("next_check_local"), tz))
                return f"Цель [G{gid}] поставлена.", False
            u = parse_ref(a.get("ref") or "")
            g = m.goals.get(u[1]) if u and u[0] == "goal" else None
            if g is None or g.person_id != person:
                return "Нет такой цели.", True
            status = {"done": "done", "drop": "dropped"}.get(op)
            m.goals.update(g.id, status=status, notes=a.get("notes"), title=a.get("title"),
                           next_check=parse_local_date(a.get("next_check_local"), tz))
            return "Цель обновлена.", False

        if name == "key_grant":
            if origin != "user" or ev is None:
                return "Ключ может выдать только сам человек своей репликой — не по твоей инициативе.", True
            k = self.keys.grant(person, a["scope"], target=a.get("target") or "", limit_eur=a.get("limit_eur"),
                                duration=a["duration"], evidence_event_id=ev)
            return f"Ключ выдан: {k.describe(tz)}", False
        if name == "key_list":
            lines = self.keys.lines(person)
            return "\n".join(lines) if lines else "Ключей нет — всё под замком работает только с разрешения.", False
        if name == "key_revoke":
            u = parse_ref(a.get("ref") or "")
            n = self.keys.revoke(person, key_id=u[1] if u and u[0] == "key" else None, scope=a.get("scope"))
            return f"Отозвано ключей: {n}.", False

        if name == "skill_search":
            return self.skills.search(person, a["query"]), False
        if name == "skill_read":
            return self.skills.read(a["name"]), False
        if name == "skill_note":
            return self.skills.note(a["name"], a["text"]), False
        if name == "skill_create":
            ok, msg = self.skills.create(a["name"], description=a["description"], instructions=a["instructions"],
                                         code=a["code"], tests=a["tests"], locks=a.get("locks"))
            return msg, not ok

        if name == "run_code":
            return self._exec(person, a, device=None)
        if name == "device_list":
            return self.devices.describe(person), False
        if name == "device_run":
            return self._exec(person, a, device=a["device"])
        return f"Нет такого органа: {name}", True

    def _exec(self, person: str, a: dict, *, device: str | None) -> tuple[str, bool]:
        code = a["code"]
        dev = None
        if device is not None:
            dev = self.devices.get(device)
            if dev is None:
                return f"Устройство «{device}» не подключено.\n" + self.devices.describe(person), True
        needed = self._locks_needed(a.get("effects") or [], code, on_device=dev is not None)
        if dev is not None and dev.owner != person:
            needed.add("relative_device")
        target = a.get("target") or (dev.owner if dev is not None and dev.owner != person else None)
        keys, err = self._unlock(person, needed, target, a.get("amount_eur"))
        if err:
            return err, True
        filled, used_secrets, missing = self.vault.fill(code)
        if missing:
            return f"В сейфе нет секретов: {', '.join(missing)}. Попроси человека добавить: /secret имя значение", True
        if dev is None:
            res = self.ws.run(filled)
            ok, out = res.ok, res.summary()
        else:
            dres = dev.executor(a["language"], filled, 120.0)
            ok, out = dres.ok, dres.output
        out = self.vault.scrub(out, used_secrets)
        for k in keys:
            self.keys.use(k, a.get("amount_eur") if k.scope == "money" else None)
        for skill in self.skills.locks_in_code(code):
            self.skills.outcome(skill, ok)
        self.m.ctx.audit.log("brain", "device_run" if dev else "run_code", "action", None,
                             after={"device": device, "purpose": a.get("purpose"), "ok": ok,
                                    "locks": sorted(needed)})
        return out, not ok
