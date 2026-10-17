"""«Подсознание»: интерфейс к языковой модели для фоновой работы памяти.

Всегда структурированный вывод (Pydantic) — модель физически не может вернуть «кривой» JSON.
По умолчанию Claude Haiku 5.5 ($0.10 / $0.50 за 1M токенов): кодирование эпизодов, сводки,
сверка фактов стоят доли цента.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# Цены $ за 1M токенов: вход, выход, чтение кэша, запись кэша (5 мин). Источник: документация Claude API, 10.2026.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


_warned: set[str] = set()
WEB_SEARCH_USD = 0.01  # за один запрос поиска (серверный инструмент)


def price_for(model: str) -> tuple[float, float, float, float]:
    """Цена модели; датированные и «альясные» имена (claude-sonnet-5-5-20260901) — по семейству.
    Неизвестная модель считается по самой дорогой цене: лучше переоценить, чем отключить лимиты бюджета."""
    if model in PRICES:
        return PRICES[model]
    for name, p in PRICES.items():
        if model.startswith(name):
            return p
    for fam in ("haiku", "sonnet", "opus"):
        if fam in model:
            return next(p for n, p in PRICES.items() if fam in n)
    if model not in _warned:
        _warned.add(model)
        log.warning("нет цены для модели %s — считаю по самой дорогой", model)
    return max(PRICES.values(), key=lambda p: p[1])


def cost_usd(model: str, usage: Any) -> float:
    if usage is None:
        return 0.0
    p = price_for(model)
    g = lambda o, k: (getattr(o, k, 0) if not isinstance(o, dict) else o.get(k, 0)) or 0  # noqa: E731
    inp, out = g(usage, "input_tokens"), g(usage, "output_tokens")
    cr, cw = g(usage, "cache_read_input_tokens"), g(usage, "cache_creation_input_tokens")
    # Запись в кэш на 1 час стоит 2× входа, на 5 минут — 1.25×.
    detail = getattr(usage, "cache_creation", None) if not isinstance(usage, dict) else usage.get("cache_creation")
    cw_1h = g(detail, "ephemeral_1h_input_tokens") if detail is not None else 0
    cw_1h = min(cw_1h, cw)
    tools = getattr(usage, "server_tool_use", None) if not isinstance(usage, dict) else usage.get("server_tool_use")
    searches = g(tools, "web_search_requests") if tools is not None else 0
    return (inp * p[0] + out * p[1] + cr * p[2] + (cw - cw_1h) * p[3] + cw_1h * p[0] * 2) / 1e6 \
        + searches * WEB_SEARCH_USD


UsageSink = Callable[[str, str, Any], None]  # (model, purpose, usage)


class StructuredLLM(Protocol):
    def parse(self, *, system: str, user: str, schema: type[T], purpose: str, max_tokens: int = 8000) -> T: ...


class AnthropicStructuredLLM:
    """Claude через официальный SDK: messages.parse + Pydantic-схема."""

    def __init__(self, client: Any = None, model: str = "claude-haiku-5-5", effort: str = "medium",
                 usage_sink: UsageSink | None = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.usage_sink = usage_sink

    def parse(self, *, system: str, user: str, schema: type[T], purpose: str, max_tokens: int = 8000) -> T:
        resp = self.client.messages.parse(
            model=self.model,
            max_tokens=max_tokens,
            # Системный промпт неизменен → кэшируется между вызовами одного назначения.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
            output_format=schema,
        )
        if self.usage_sink:
            self.usage_sink(self.model, purpose, resp.usage)
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"модель отказалась ({purpose})")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError(f"ответ обрезан по max_tokens ({purpose})")
        out = resp.parsed_output
        if out is None:
            raise RuntimeError(f"пустой структурированный ответ ({purpose})")
        return out


class ScriptedLLM:
    """Для тестов и стенда: ответы задаёт функция (schema, system, user) -> экземпляр схемы."""

    def __init__(self, fn: Callable[[type[BaseModel], str, str], BaseModel]):
        self.fn = fn
        self.calls: list[tuple[str, str]] = []

    def parse(self, *, system: str, user: str, schema: type[T], purpose: str, max_tokens: int = 8000) -> T:
        self.calls.append((purpose, user))
        out = self.fn(schema, system, user)
        if not isinstance(out, schema):
            raise TypeError(f"ScriptedLLM вернул {type(out)} вместо {schema}")
        return out
