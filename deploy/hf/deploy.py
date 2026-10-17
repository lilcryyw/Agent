"""Выкладка сервера Джарвиса на бесплатный Hugging Face Space — одной командой.

    HF_TOKEN=hf_… python deploy/hf/deploy.py

Что делает:
  1. создаёт Space «<имя>/jarvis» (Docker, бесплатное железо) и приватный датасет «<имя>/jarvis-data» для памяти;
  2. переносит настройки из .env в секреты Space (ключ Claude/ProxyAPI, бюджет, семья, Telegram…);
  3. загружает код — Hugging Face сам собирает образ (~10–15 минут в первый раз);
  4. печатает адрес сервера и ссылку на веб-приложение с ключом владельца.
Токен: https://huggingface.co/settings/tokens → Create new token → тип «Write».
Секреты для повторных запусков хранятся в deploy/hf/.secrets (не попадает в git).
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SECRETS = HERE / ".secrets"
# Что переносим из .env в секреты Space (адреса и пути площадки задаются ниже сами).
FROM_ENV = ["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "JARVIS_BRAIN_MODEL", "JARVIS_BRAIN_EFFORT",
            "JARVIS_SUBCONSCIOUS_MODEL", "JARVIS_EMBED_MODEL", "JARVIS_MONTHLY_BUDGET_USD", "JARVIS_TURN_BUDGET_USD",
            "JARVIS_CALL_EFFORT", "JARVIS_OWNER_ID", "JARVIS_OWNER_NAME", "JARVIS_OWNER_TZ", "JARVIS_PEOPLE",
            "TELEGRAM_BOT_TOKEN", "JARVIS_TELEGRAM_USERS", "JARVIS_WEBAPP_URL", "JARVIS_CORS_ORIGINS",
            "JARVIS_RELAY_DOMAIN", "JARVIS_FALLBACKS", "JARVIS_WEB_SEARCH"]
INCLUDE = ["pyproject.toml", "cogmem", "jarvis", "clients/device", "clients/android/jarvis.apk", "deploy/hf"]
SPACE_CARD = """---
title: Jarvis
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Семейный ИИ-помощник с когнитивной памятью
---

# Джарвис

Сервер семейного помощника. Веб-приложение — по адресу `/app/`. Исходный код и инструкции:
https://github.com/lilcryyw/Agent
"""


def read_kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def host_for(space_id: str) -> str:
    """«Ivan_Petrov/jarvis» → ivan-petrov-jarvis.hf.space (так Hugging Face строит адрес)."""
    return re.sub(r"[^a-z0-9]+", "-", space_id.lower().replace("/", "-")).strip("-") + ".hf.space"


def stage() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-space-"))
    for item in INCLUDE:
        src = ROOT / item
        if not src.exists():
            continue
        dst = tmp / item
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".secrets", "build",
                                                                    ".gradle"))
        else:
            shutil.copy2(src, dst)
    shutil.copy2(HERE / "Dockerfile", tmp / "Dockerfile")
    (tmp / "README.md").write_text(SPACE_CARD, encoding="utf-8")
    return tmp


def main() -> None:
    from huggingface_hub import HfApi

    saved = read_kv(SECRETS)
    token = os.environ.get("HF_TOKEN") or saved.get("HF_TOKEN")
    if not token:
        sys.exit("Нужен HF_TOKEN (https://huggingface.co/settings/tokens, тип Write)")
    api = HfApi(token=token)
    user = api.whoami()["name"]
    space = os.environ.get("JARVIS_SPACE") or f"{user}/jarvis"
    data_repo = f"{user}/jarvis-data"
    host = host_for(space)
    print(f"Hugging Face: {user} → Space {space} (https://{host})")

    env = read_kv(ROOT / ".env")
    # Ключи, которые создаются один раз и потом не меняются (иначе сейф и ссылка владельца перестанут работать).
    saved.setdefault("JARVIS_VAULT_KEY", env.get("JARVIS_VAULT_KEY") or _fernet_key())
    saved.setdefault("JARVIS_OWNER_TOKEN", "jv_" + secrets.token_urlsafe(32))
    saved["HF_TOKEN"] = token
    SECRETS.write_text("".join(f"{k}={v}\n" for k, v in saved.items()), encoding="utf-8")
    SECRETS.chmod(0o600)

    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    api.create_repo(data_repo, repo_type="dataset", private=True, exist_ok=True)

    secret_vals = {k: env[k] for k in FROM_ENV if env.get(k)}
    secret_vals.update(JARVIS_VAULT_KEY=saved["JARVIS_VAULT_KEY"], JARVIS_OWNER_TOKEN=saved["JARVIS_OWNER_TOKEN"],
                       HF_TOKEN=token)
    for k, v in secret_vals.items():
        api.add_space_secret(space, k, v)
    variables = {"JARVIS_DOMAIN": host, "JARVIS_DEVICES_URL": f"wss://{host}/devices",
                 "JARVIS_BACKUP_REPO": data_repo, "JARVIS_KEEP_AWAKE": "1"}
    for k, v in variables.items():
        api.add_space_variable(space, k, v)
    print(f"секретов: {len(secret_vals)}, переменных: {len(variables)}")

    folder = stage()
    try:
        api.upload_folder(repo_id=space, repo_type="space", folder_path=str(folder),
                          commit_message="Джарвис: обновление сервера", delete_patterns=["*"])
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    webapp = env.get("JARVIS_WEBAPP_URL") or f"https://{host}/app/"
    print()
    print(f"Готово. Hugging Face собирает сервер (первый раз 10–15 минут): https://huggingface.co/spaces/{space}")
    print(f"Адрес сервера: https://{host}")
    print(f"Веб-приложение владельца (ссылка с ключом, никому не пересылай): {webapp.rstrip('/')}/#t="
          f"{saved['JARVIS_OWNER_TOKEN']}")
    cf = ROOT / "deploy" / "cloudflare"
    if (cf / ".secrets").exists() or os.environ.get("CLOUDFLARE_API_TOKEN"):
        import subprocess

        print("Обновляю сайт на Cloudflare, чтобы он говорил с этим сервером…")
        subprocess.run(["bash", str(cf / "deploy.sh")], env={**os.environ, "JARVIS_API_BASE": f"https://{host}"},
                       check=False)
    else:
        print(f"Обнови сайт на Cloudflare: JARVIS_API_BASE=https://{host} bash deploy/cloudflare/deploy.sh")


def _fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


if __name__ == "__main__":
    main()
