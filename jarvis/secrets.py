"""Сейф секретов: пароли и токены, которыми Джарвис пользуется, но которые не видит.

В коде Джарвис пишет {{secret:имя}} — значение подставляется прямо перед выполнением,
а из вывода вычищается (заменяется на ***). Ни в историю разговора, ни в память значения не попадают.
Сейф зашифрован (Fernet); ключ — JARVIS_VAULT_KEY (или создаётся в data/vault.key с правами 600).
Секреты добавляет только человек — через отдельную команду канала (/secret имя значение), не через разговор.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from cryptography.fernet import Fernet

PLACEHOLDER = re.compile(r"\{\{\s*secret:([A-Za-z0-9_.\-]+)\s*\}\}")


class Vault:
    def __init__(self, path: str | Path = "data/vault.bin", key: str | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        key = key or os.environ.get("JARVIS_VAULT_KEY")
        if not key:
            kf = self.path.with_name("vault.key")
            if not kf.exists():
                kf.write_text(Fernet.generate_key().decode())
                kf.chmod(0o600)
            key = kf.read_text().strip()
        self._f = Fernet(key.encode() if isinstance(key, str) else key)

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self._f.decrypt(self.path.read_bytes()))

    def _save(self, data: dict[str, str]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._f.encrypt(json.dumps(data).encode()))
        tmp.replace(self.path)

    def set(self, name: str, value: str) -> None:
        data = self._load()
        data[name] = value
        self._save(data)

    def delete(self, name: str) -> bool:
        data = self._load()
        ok = data.pop(name, None) is not None
        self._save(data)
        return ok

    def names(self) -> list[str]:
        return sorted(self._load())

    def fill(self, code: str) -> tuple[str, list[str], list[str]]:
        """Подставить секреты. → (код, использованные имена, неизвестные имена)."""
        data = self._load()
        used, missing = [], []

        def sub(m: re.Match) -> str:
            name = m.group(1)
            if name in data:
                used.append(name)
                return data[name]
            missing.append(name)
            return m.group(0)

        return PLACEHOLDER.sub(sub, code), used, missing

    def scrub(self, text: str, names: list[str] | None = None) -> str:
        """Вычистить значения секретов из текста (вывода программ)."""
        data = self._load()
        for name in names if names is not None else data:
            v = data.get(name)
            if v and len(v) >= 3:
                text = text.replace(v, f"***{name}***")
        return text
