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
        self.messages = SimpleNamespace(create=self._create, stream=self._stream)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create, stream=self._stream))

    def _create(self, **kw):
        snap = _plain(copy.deepcopy(kw))
        self.calls.append(snap)
        return self.script(snap)

    def _stream(self, **kw):
        return _Stream(self._create(**kw))


class _Stream:
    """Как MessageStream из SDK: text_stream отдаёт текст кусочками, get_final_message() — весь ответ."""

    def __init__(self, resp):
        self.resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        for b in self.resp.content:
            if getattr(b, "type", "") == "text":
                for i in range(0, len(b.text), 7):
                    yield b.text[i:i + 7]

    def get_final_message(self):
        return self.resp
