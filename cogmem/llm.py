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


def cost_usd(model: str, usage: Any) -> float:
    p = PRICES.get(model)
    if p is None or usage is None:
        return 0.0
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (inp * p[0] + out * p[1] + cr * p[2] + cw * p[3]) / 1e6


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
