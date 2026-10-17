"""Инструменты «сознания» для работы с памятью.

Все схемы строгие (strict): аргументы всегда валидны. Список инструментов неизменен и
отсортирован по имени — иначе сломается кэш промпта (инструменты стоят в самом начале запроса).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from cogmem.memory import CognitiveMemory
from cogmem.types import parse_ref


def _schema(props: dict[str, Any]) -> dict:
    return {"type": "object", "properties": props, "required": sorted(props), "additionalProperties": False}


_STR = {"type": "string"}
_STR_OR_NULL = {"type": ["string", "null"]}

MEMORY_TOOLS: list[dict] = [
    {
        "name": "intention_add",
        "description": "Поставить напоминание/намерение. due_local — 'YYYY-MM-DDTHH:MM' по времени собеседника, "
                       "если есть срок; иначе null и trigger — условие («когда приду домой»).",
        "input_schema": _schema({"action": _STR, "due_local": _STR_OR_NULL, "trigger": _STR_OR_NULL}),
    },
    {
        "name": "intention_done",
        "description": "Отметить намерение [I..] выполненным или отменённым.",
        "input_schema": _schema({"ref": _STR, "status": {"type": "string", "enum": ["done", "cancelled"]}}),
    },
    {
        "name": "memory_correct",
        "description": "Исправить факт [F..], если человек говорит, что он неверен или изменился. "
                       "Старая версия сохранится в истории как устаревшая.",
        "input_schema": _schema({"ref": _STR, "new_statement": _STR}),
    },
    {
        "name": "memory_explain",
        "description": "Откуда известен факт/эпизод: исходные реплики и история изменений.",
        "input_schema": _schema({"ref": _STR}),
    },
    {
        "name": "memory_forget",
        "description": "Удалить навсегда воспоминание [F../E../M../I..] по прямой просьбе человека "
                       "(только после его подтверждения).",
        "input_schema": _schema({"ref": _STR}),
    },
    {
        "name": "memory_recall",
        "description": "Глубоко поискать в памяти, если в блоке <память> не хватило. period — выражение "
                       "времени по-русски («в прошлом месяце», «в мае», «5 марта») или null. include_outdated — "
                       "показывать ли устаревшие факты (для вопросов «как было раньше»).",
        "input_schema": _schema({"query": _STR, "period": _STR_OR_NULL, "include_outdated": {"type": "boolean"}}),
    },
    {
        "name": "memory_remember",
        "description": "Сразу запомнить то, что человек явно просит запомнить. statement — самодостаточно, "
                       "с именами. about — о ком/чём (null — о самом собеседнике). share_with_family — только "
                       "если человек явно хочет, чтобы это знали все в семье.",
        "input_schema": _schema({"statement": _STR, "about": _STR_OR_NULL, "importance": {"type": "number"},
                                 "share_with_family": {"type": "boolean"}}),
    },
    {
        "name": "memory_timeline",
        "description": "Что происходило в период (сводки и эпизоды по времени). period — по-русски.",
        "input_schema": _schema({"period": _STR}),
    },
]
for t in MEMORY_TOOLS:
    t["strict"] = True
MEMORY_TOOLS.sort(key=lambda t: t["name"])


class ToolBox:
    """Выполнение инструментов от имени конкретного человека (права проверяет память)."""

    def __init__(self, memory: CognitiveMemory):
        self.memory = memory
        self.extra: dict[str, Callable[[str, dict], str]] = {}

    def definitions(self, *, web_search: bool) -> list[dict]:
        defs = list(MEMORY_TOOLS)
        if web_search:
            defs.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 5})
        return defs

    def run(self, person_id: str, name: str, args: dict, *, source_event_id: int | None = None) -> tuple[str, bool]:
        """→ (текст результата, ошибка?)"""
        m = self.memory
        try:
            if name == "memory_recall":
                return m.recall_deep(person_id, args["query"], period=args.get("period"),
                                     include_outdated=bool(args.get("include_outdated"))), False
            if name == "memory_timeline":
                return m.timeline(person_id, args["period"]), False
            if name == "memory_remember":
                fid = m.remember(person_id, args["statement"], about=args.get("about"),
                                 importance=float(args.get("importance", 0.7)),
                                 share_with_family=bool(args.get("share_with_family")),
                                 source_event_id=source_event_id)
                return f"Запомнено как [F{fid}].", False
            if name == "memory_correct":
                new = m.correct(person_id, args["ref"], args["new_statement"])
                return (f"Исправлено: новая версия [F{new}], старая помечена устаревшей." if new
                        else "Не удалось: такого факта нет или он недоступен."), new is None
            if name == "memory_forget":
                ok = m.forget(person_id, args["ref"])
                return ("Удалено навсегда." if ok else "Не удалось удалить (нет такого или это не ваше)."), not ok
            if name == "memory_explain":
                return m.explain(person_id, args["ref"]), False
            if name == "intention_add":
                iid = m.add_intention(person_id, args["action"], due_local=args.get("due_local"),
                                      trigger=args.get("trigger") or "")
                return f"Намерение записано как [I{iid}].", False
            if name == "intention_done":
                u = parse_ref(args["ref"])
                row = m.ctx.db.one("SELECT person_id FROM intentions WHERE id=?", (u[1],)) if u and u[0] == "intention" \
                    else None
                if row is None or row["person_id"] != person_id:
                    return "Нет такого намерения.", True
                m.intentions.set_status(u[1], args["status"])
                return "Готово.", False
            if name in self.extra:
                return self.extra[name](person_id, args), False
            return f"Неизвестный инструмент {name}", True
        except Exception as exc:  # noqa: BLE001 — ошибка инструмента возвращается модели, а не роняет диалог
            return f"Ошибка инструмента: {exc}", True

    @staticmethod
    def dumps(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False)
