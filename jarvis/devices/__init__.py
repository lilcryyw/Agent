"""Хаб устройств: что подключено и как с ним работать.

Устройство умеет действия (call): run — выполнить код/команду; screenshot — снимок экрана;
input — мышь и клавиатура. Реальные устройства подключаются через шлюз (jarvis.devices.gateway),
в тестах — напрямую функцией. У каждого устройства есть владелец: устройства других членов семьи —
под замком (ключ relative_device).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class DeviceResult:
    ok: bool
    output: str
    image_b64: str | None = None  # PNG снимка экрана


Call = Callable[[str, dict, float], DeviceResult]  # (действие, аргументы, таймаут) → результат


@dataclass
class Device:
    id: str
    owner: str               # id человека
    kind: str                # windows | android | linux | mac | iphone
    name: str
    languages: list[str]     # что умеет выполнять: python, powershell, shell
    call: Call
    capabilities: set[str] = field(default_factory=set)  # screen, input, termux_api, ...

    def run(self, language: str, code: str, timeout: float = 120.0) -> DeviceResult:
        return self.call("run", {"language": language, "code": code}, timeout)


class DeviceHub:
    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}
        self._lock = threading.Lock()

    def register(self, d: Device) -> None:
        with self._lock:
            self._devices[d.id] = d

    def unregister(self, device_id: str) -> None:
        with self._lock:
            self._devices.pop(device_id, None)

    def get(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    def all(self) -> list[Device]:
        return list(self._devices.values())

    def describe(self, viewer: str) -> str:
        if not self._devices:
            return ("Сейчас ни одно устройство не подключено. Чтобы подключить — device_pair: он выдаст код и "
                    "инструкцию. Код без устройства можно выполнять в мастерской (run_code).")
        lines = []
        for d in self.all():
            whose = "твоё" if d.owner == viewer else f"принадлежит {d.owner} (под замком relative_device)"
            lines.append(f"- {d.id}: {d.name} [{d.kind}], {whose}; языки: {', '.join(d.languages)}"
                         + (f"; умеет: {', '.join(sorted(d.capabilities))}" if d.capabilities else ""))
        return "\n".join(lines)
