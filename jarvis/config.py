"""Настройки Джарвиса из переменных окружения (файл .env не обязателен)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "да", "on"}


@dataclass
class Settings:
    db_path: str = "data/jarvis.db"
    # «Сознание»: разговор, решения, инструменты.
    brain_model: str = "claude-opus-5-5"
    brain_effort: str = "medium"
    # «Подсознание»: фоновая работа памяти.
    subconscious_model: str = "claude-haiku-5-5"
    subconscious_effort: str = "medium"
    max_tokens: int = 16000
    # Возможности API (можно отключить, если аккаунт их не поддерживает).
    use_fallbacks: bool = True       # резервная модель при отказе фильтров
    use_web_search: bool = True
    monthly_budget_usd: float = 40.0
    session_max_tokens: int = 60000  # после — разговор начинается заново (с ядром и памятью)
    sleep_hour_local: int = 3
    owner_id: str = "owner"
    owner_name: str = "Хозяин"
    owner_timezone: str = "Europe/Paris"
    telegram_token: str | None = None
    telegram_users: dict[int, str] = field(default_factory=dict)  # telegram id → person id

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        s = cls()
        e = os.environ
        s.db_path = e.get("JARVIS_DB", s.db_path)
        s.brain_model = e.get("JARVIS_BRAIN_MODEL", s.brain_model)
        s.brain_effort = e.get("JARVIS_BRAIN_EFFORT", s.brain_effort)
        s.subconscious_model = e.get("JARVIS_SUBCONSCIOUS_MODEL", s.subconscious_model)
        s.use_fallbacks = _bool("JARVIS_FALLBACKS", s.use_fallbacks)
        s.use_web_search = _bool("JARVIS_WEB_SEARCH", s.use_web_search)
        s.monthly_budget_usd = float(e.get("JARVIS_MONTHLY_BUDGET_USD", s.monthly_budget_usd))
        s.owner_id = e.get("JARVIS_OWNER_ID", s.owner_id)
        s.owner_name = e.get("JARVIS_OWNER_NAME", s.owner_name)
        s.owner_timezone = e.get("JARVIS_OWNER_TZ", s.owner_timezone)
        s.telegram_token = e.get("TELEGRAM_BOT_TOKEN") or None
        users = e.get("JARVIS_TELEGRAM_USERS", "")  # «123456:owner,789:mama»
        for pair in filter(None, (p.strip() for p in users.split(","))):
            tg, pid = pair.split(":", 1)
            s.telegram_users[int(tg)] = pid.strip()
        return s
