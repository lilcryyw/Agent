"""Поддельный клиент Claude для тестов «сознания» без сети и ключа."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(name, inp, id_="toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=inp, id=id_)


def response(blocks, stop="end_turn", cache_read=0, inp=100, out=20):
    usage = SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_input_tokens=cache_read,
                            cache_creation_input_tokens=0)
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage)


def _plain(obj):
    if isinstance(obj, SimpleNamespace):
        return {k: _plain(v) for k, v in vars(obj).items()}
    if isinstance(obj, list):
        return [_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    return obj


@dataclass
class FakeClaude:
    script: Callable[[dict], SimpleNamespace]
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        snap = _plain(copy.deepcopy(kw))
        self.calls.append(snap)
        return self.script(snap)
