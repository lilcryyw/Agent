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
    brain_model: str = "claude-sonnet-5-5"
    brain_effort: str = "medium"
    # «Подсознание»: фоновая работа памяти.
    subconscious_model: str = "claude-haiku-5-5"
    subconscious_effort: str = "medium"
    max_tokens: int = 16000
    # Возможности API (можно отключить, если аккаунт их не поддерживает).
    use_fallbacks: bool = True       # резервная модель при отказе фильтров
    use_web_search: bool = True
    monthly_budget_usd: float = 40.0
    turn_budget_usd: float = 1.0     # один ход дороже — остановиться и спросить
    session_max_tokens: int = 60000  # после — разговор начинается заново (с ядром и памятью)
    sleep_hour_local: int = 3
    owner_id: str = "owner"
    owner_name: str = "Хозяин"
    owner_timezone: str = "Europe/Paris"
    telegram_token: str | None = None
    telegram_users: dict[int, str] = field(default_factory=dict)  # telegram id → person id
    # Члены семьи: id → (имя, роль, часовой пояс). Владелец добавляется отдельно.
    people: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    # Шлюз устройств: порт WebSocket и внешний адрес (за Caddy с HTTPS), например wss://jarvis.example.com/devices
    devices_port: int = 8765
    devices_url: str = ""
    relay_domain: str = ""         # ретранслятор в России (например ru.jarvis.example.com)
    public_domain: str = ""        # основной домен
    api_port: int = 8780           # HTTP-API для iPhone/веб (0 — выключено)
    call_port: int = 8790          # живой голосовой разговор (WebSocket, 0 — выключено)
    call_effort: str = "low"       # глубина размышлений в живом разговоре: важнее быстро ответить

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
        s.turn_budget_usd = float(e.get("JARVIS_TURN_BUDGET_USD", s.turn_budget_usd))
        s.owner_id = e.get("JARVIS_OWNER_ID", s.owner_id)
        s.owner_name = e.get("JARVIS_OWNER_NAME", s.owner_name)
        s.owner_timezone = e.get("JARVIS_OWNER_TZ", s.owner_timezone)
        s.telegram_token = e.get("TELEGRAM_BOT_TOKEN") or None
        users = e.get("JARVIS_TELEGRAM_USERS", "")  # «123456:owner,789:mama»
        for pair in filter(None, (p.strip() for p in users.split(","))):
            tg, pid = pair.split(":", 1)
            s.telegram_users[int(tg)] = pid.strip()
        s.devices_port = int(e.get("JARVIS_DEVICES_PORT", s.devices_port))
        s.devices_url = e.get("JARVIS_DEVICES_URL", s.devices_url)
        s.api_port = int(e.get("JARVIS_API_PORT", s.api_port))
        s.call_port = int(e.get("JARVIS_CALL_PORT", s.call_port))
        s.call_effort = e.get("JARVIS_CALL_EFFORT", s.call_effort)
        s.relay_domain = e.get("JARVIS_RELAY_DOMAIN", s.relay_domain)
        s.public_domain = e.get("JARVIS_DOMAIN", s.public_domain)
        people = e.get("JARVIS_PEOPLE", "")  # «mama:Ольга Петровна:family:Europe/Samara;papa:...»
        for item in filter(None, (p.strip() for p in people.split(";"))):
            parts = [x.strip() for x in item.split(":")]
            pid, name = parts[0], parts[1] if len(parts) > 1 else parts[0]
            role = parts[2] if len(parts) > 2 else "family"
            tz = ":".join(parts[3:]) if len(parts) > 3 else "Europe/Moscow"
            s.people[pid] = (name, role, tz)
        return s
