"""Хаб устройств: что подключено и как на нём выполнить код.

Сейчас — интерфейс и реестр; реальные клиенты (Windows, Android, iPhone) подключаются на этапе
«Устройства» через WebSocket и регистрируются здесь же. У каждого устройства есть владелец:
действия на устройствах других членов семьи — под замком (ключ relative_device).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class DeviceResult:
    ok: bool
    output: str


Executor = Callable[[str, str, float], DeviceResult]  # (язык, код, таймаут) → результат


@dataclass
class Device:
    id: str
    owner: str               # id человека
    kind: str                # windows | android | iphone | linux | mac
    name: str
    languages: list[str]     # что умеет выполнять: python, powershell, shell
    executor: Executor
    capabilities: set[str] = field(default_factory=set)  # screen, sms, location, ...


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
            return ("Сейчас ни одно устройство не подключено. Код можно выполнять в мастерской (run_code). "
                    "Клиенты для ПК и телефонов подключаются на этапе «Устройства».")
        lines = []
        for d in self.all():
            whose = "твоё" if d.owner == viewer else f"принадлежит {d.owner} (под замком relative_device)"
            lines.append(f"- {d.id}: {d.name} [{d.kind}], {whose}; языки: {', '.join(d.languages)}"
                         + (f"; умеет: {', '.join(sorted(d.capabilities))}" if d.capabilities else ""))
        return "\n".join(lines)
