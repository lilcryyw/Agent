"""Скрипт первого запуска для любого VPS (Hetzner, Oracle, Timeweb…): вставляется в поле «Cloud config /
User data» при создании сервера — и сервер сам ставит Docker, скачивает Джарвиса и запускает его.

    python deploy/vps/make_cloud_init.py > user-data.sh

Настройки берутся из .env. Свой домен не обязателен: без JARVIS_DOMAIN адрес будет <ip>.sslip.io
(бесплатное имя, указывающее на IP сервера), и HTTPS-сертификат Caddy получит сам.
Внутри — ключи из .env: файл не публикуй и не пересылай.
"""

from __future__ import annotations

import secrets
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "https://github.com/lilcryyw/Agent.git"
BRANCH = "claude/jarvis-cogmem"
SKIP = {"JARVIS_DOMAIN", "JARVIS_DEVICES_URL", "JARVIS_DB"}  # адреса и пути сервер определит сам


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def build(env: dict[str, str], domain: str = "") -> str:
    env = {k: v for k, v in env.items() if k not in SKIP and v}
    env.setdefault("JARVIS_WORKSHOP_TOKEN", secrets.token_urlsafe(32))
    if env.get("JARVIS_WORKSHOP_TOKEN", "").startswith("поменяй"):
        env["JARVIS_WORKSHOP_TOKEN"] = secrets.token_urlsafe(32)
    lines = "\n".join(f"{k}={shlex.quote(v)}" for k, v in sorted(env.items()))
    return f"""#!/bin/bash
# Джарвис: установка на новый сервер (cloud-init). Журнал: /var/log/jarvis-install.log
exec > /var/log/jarvis-install.log 2>&1
set -euxo pipefail
command -v docker || curl -fsSL https://get.docker.com | sh
command -v git || (apt-get update && apt-get install -y git)
# Память под модели речи и смысла: если ОЗУ мало — файл подкачки 4 ГБ.
if [ "$(free -g | awk '/Mem:/{{print $2}}')" -lt 8 ] && [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
[ -d /opt/jarvis ] || git clone -b {BRANCH} {REPO} /opt/jarvis
cd /opt/jarvis && git pull --ff-only || true
IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{{print $1}}')
DOMAIN={shlex.quote(domain) if domain else '"$(echo "$IP" | tr . -).sslip.io"'}
umask 077
cat > .env <<'JARVIS_ENV'
{lines}
JARVIS_ENV
echo "JARVIS_DOMAIN=$DOMAIN" >> .env
cd deploy && docker compose --env-file ../.env up -d --build
echo "Джарвис запущен: https://$DOMAIN"
"""


def main() -> None:
    env = read_env(ROOT / ".env")
    # Ключ владельца для веб-приложения (без Telegram) и резервная копия памяти в приватный датасет Hugging Face.
    saved = read_env(ROOT / "deploy" / "hf" / ".secrets") if (ROOT / "deploy" / "hf" / ".secrets").exists() else {}
    env.setdefault("JARVIS_OWNER_TOKEN", saved.get("JARVIS_OWNER_TOKEN") or "jv_" + secrets.token_urlsafe(32))
    if saved.get("JARVIS_VAULT_KEY"):
        env.setdefault("JARVIS_VAULT_KEY", saved["JARVIS_VAULT_KEY"])
    if saved.get("HF_TOKEN"):
        env.setdefault("HF_TOKEN", saved["HF_TOKEN"])
        env.setdefault("JARVIS_BACKUP_REPO", saved.get("JARVIS_BACKUP_REPO") or _hf_repo(saved["HF_TOKEN"]))
    domain = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.stdout.write(build(env, domain))


def _hf_repo(token: str) -> str:
    from huggingface_hub import HfApi

    return HfApi(token=token).whoami()["name"] + "/jarvis-data"


if __name__ == "__main__":
    main()
