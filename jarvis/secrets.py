"""Сейф секретов: пароли и токены, которыми Джарвис пользуется, но которые не видит.

Два способа (оба — только в момент запуска; в истории разговора и в памяти значений нет):
  • {{secret:имя}} прямо в коде — подставляется перед выполнением (в Python — с экранированием для строки);
  • переменная окружения JARVIS_SECRET_<ИМЯ> (os.environ["JARVIS_SECRET_WIFI"]) — удобно в навыках:
    передаётся в процесс, если код (или импортированный навык) упоминает это имя.
Из вывода значения вычищаются (заменяются на ***имя***).
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


def env_name(name: str) -> str:
    return "JARVIS_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def _py_escape(v: str) -> str:
    """Значение, безопасное внутри любой строки Python ('…', "…", '''…''')."""
    return (v.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r"))


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

    def fill(self, code: str, *, python: bool = False) -> tuple[str, list[str], list[str]]:
        """Подставить секреты. → (код, использованные имена, неизвестные имена).
        python=True — значение экранируется для строкового литерала (кавычки и \\ не ломают код)."""
        data = self._load()
        used, missing = [], []

        def sub(m: re.Match) -> str:
            name = m.group(1)
            if name in data:
                used.append(name)
                return _py_escape(data[name]) if python else data[name]
            missing.append(name)
            return m.group(0)

        return PLACEHOLDER.sub(sub, code), used, missing

    def env_for(self, text: str) -> tuple[dict[str, str], list[str]]:
        """Переменные JARVIS_SECRET_* для секретов, которые text упоминает по имени переменной.
        → (окружение, имена)."""
        data = self._load()
        env, used = {}, []
        for name, value in sorted(data.items()):
            e = env_name(name)
            if e in text:
                env[e] = value
                used.append(name)
        return env, used

    def scrub(self, text: str, names: list[str] | None = None) -> str:
        """Вычистить значения секретов из текста (вывода программ)."""
        data = self._load()
        for name in names if names is not None else data:
            v = data.get(name)
            if v and len(v) >= 3:
                text = text.replace(v, f"***{name}***")
        return text
