"""Общие типы памяти."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

UnitType = Literal["event", "episode", "fact", "entity", "procedure", "intention"]

# Короткие префиксы ID для цитирования моделью: [F12], [E7], [M345]...
PREFIX: dict[str, str] = {
    "fact": "F",
    "episode": "E",
    "event": "M",
    "entity": "N",
    "procedure": "P",
    "intention": "I",
    "goal": "G",
    "key": "K",
}
PREFIX_TO_TYPE = {v: k for k, v in PREFIX.items()}

TABLE: dict[str, str] = {
    "event": "events",
    "episode": "episodes",
    "fact": "facts",
    "entity": "entities",
    "procedure": "procedures",
    "intention": "intentions",
    "goal": "goals",
    "key": "keys",
}


def ref(unit_type: str, unit_id: int) -> str:
    return f"{PREFIX[unit_type]}{unit_id}"


def parse_ref(token: str) -> tuple[str, int] | None:
    token = token.strip().strip("[]").upper()
    if len(token) < 2 or token[0] not in PREFIX_TO_TYPE or not token[1:].isdigit():
        return None
    return PREFIX_TO_TYPE[token[0]], int(token[1:])


@dataclass
class Observation:
    """То, что «услышала» память: реплика или событие устройства."""

    person_id: str
    text: str
    speaker: Literal["user", "assistant", "device", "system"] = "user"
    channel: str = "text"
    device: str | None = None
    kind: str = "utterance"
    source_kind: Literal["user_stated", "assistant", "observed", "external"] | None = None
    visibility: Literal["private", "family"] = "private"
    meta: dict = field(default_factory=dict)


@dataclass
class Recalled:
    """Одно найденное воспоминание с оценками (для упаковки и объяснения «почему вспомнил»)."""

    unit_type: str
    unit_id: int
    text: str
    ts: float
    score: float = 0.0
    relevance: float = 0.0
    activation: float = 0.0
    importance: float = 0.0
    graph: float = 0.0
    context: float = 0.0
    episode_id: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return ref(self.unit_type, self.unit_id)
