"""Выкладка облегчённого Джарвиса на бесплатный Render (без карты) — одной командой.

    RENDER_API_KEY=rnd_… python deploy/render/deploy.py

Нужно один раз: зарегистрироваться на https://render.com через GitHub и дать Render доступ к репозиторию
(иначе он не увидит закрытый код), затем Account Settings → API Keys → Create API Key.
Скрипт создаёт сервис (Docker, план free, Франкфурт), переносит настройки из .env в переменные сервиса,
ждёт запуска и переключает сайт на Cloudflare на новый адрес. Повторный запуск обновляет настройки.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy" / "hf"))
from deploy import FROM_ENV, _fernet_key, read_kv  # noqa: E402

API = "https://api.render.com/v1"
NAME = os.environ.get("JARVIS_RENDER_NAME", "jarvis")
REPO = "https://github.com/lilcryyw/Agent"
BRANCH = os.environ.get("JARVIS_BRANCH", "claude/jarvis-cogmem")


def call(method: str, path: str, key: str, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit(f"Render {method} {path}: {e.code} {e.read().decode(errors='replace')[:500]}")


def env_vars() -> list[dict]:
    env = read_kv(ROOT / ".env")
    hf = read_kv(ROOT / "deploy" / "hf" / ".secrets")
    cf = read_kv(ROOT / "deploy" / "cloudflare" / ".secrets")
    hf.setdefault("JARVIS_OWNER_TOKEN", "jv_" + secrets.token_urlsafe(32))
    hf.setdefault("JARVIS_VAULT_KEY", env.get("JARVIS_VAULT_KEY") or _fernet_key())
    (ROOT / "deploy" / "hf" / ".secrets").write_text("".join(f"{k}={v}\n" for k, v in hf.items()), encoding="utf-8")
    out = {k: env[k] for k in FROM_ENV if env.get(k)}
    out.update(JARVIS_OWNER_TOKEN=hf["JARVIS_OWNER_TOKEN"], JARVIS_VAULT_KEY=hf["JARVIS_VAULT_KEY"],
               JARVIS_KEEP_AWAKE="1", JARVIS_KEEP_AWAKE_EVERY_S="600")
    # Смысл и распознавание — в Cloudflare Workers AI; модель смысла облегчённого режима задана в образе.
    out.pop("JARVIS_EMBED_MODEL", None)
    for k in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        if cf.get(k):
            out[k] = cf[k]
    if hf.get("HF_TOKEN"):  # память копируется в приватный датасет: у бесплатного Render диск не постоянный
        from huggingface_hub import HfApi

        out["HF_TOKEN"] = hf["HF_TOKEN"]
        out["JARVIS_BACKUP_REPO"] = HfApi(token=hf["HF_TOKEN"]).whoami()["name"] + "/jarvis-data"
    return [{"key": k, "value": v} for k, v in sorted(out.items())]


def main() -> None:
    key = os.environ.get("RENDER_API_KEY") or read_kv(ROOT / "deploy" / "render" / ".secrets").get("RENDER_API_KEY")
    if not key:
        sys.exit("Нужен RENDER_API_KEY (render.com → Account Settings → API Keys)")
    sec = ROOT / "deploy" / "render" / ".secrets"
    sec.write_text(f"RENDER_API_KEY={key}\n", encoding="utf-8")
    sec.chmod(0o600)

    owners = call("GET", "/owners?limit=20", key)
    owner = owners[0]["owner"]["id"]
    existing = [s["service"] for s in call("GET", f"/services?name={NAME}&limit=20", key) or []]
    evs = env_vars()
    if existing:
        svc = existing[0]
        call("PUT", f"/services/{svc['id']}/env-vars", key, evs)
        call("POST", f"/services/{svc['id']}/deploys", key, {"clearCache": "do_not_clear"})
        print(f"Сервис {NAME} обновлён и перезапускается")
    else:
        res = call("POST", "/services", key, {
            "type": "web_service", "name": NAME, "ownerId": owner, "repo": REPO, "branch": BRANCH,
            "autoDeployTrigger": "commit", "envVars": evs,
            "serviceDetails": {"runtime": "docker", "plan": "free", "region": "frankfurt",
                               "healthCheckPath": "/api/health",
                               "envSpecificDetails": {"dockerfilePath": "./deploy/render/Dockerfile",
                                                      "dockerContext": "."}}})
        svc = res["service"]
        print(f"Сервис создан: {svc.get('dashboardUrl', '')}")
    sid = svc["id"]
    url = (svc.get("serviceDetails") or {}).get("url") or call("GET", f"/services/{sid}", key)["serviceDetails"]["url"]

    print("Render собирает сервер (первый раз ~5–10 минут)…")
    status = ""
    for _ in range(120):
        deps = call("GET", f"/services/{sid}/deploys?limit=1", key) or []
        status = deps[0]["deploy"]["status"] if deps else ""
        if status in ("live", "build_failed", "update_failed", "canceled", "deactivated"):
            break
        time.sleep(15)
    print(f"Статус: {status}")
    if status != "live":
        sys.exit("Сборка не удалась — журнал в панели Render.")

    print("Переключаю сайт на Cloudflare на новый сервер…")
    subprocess.run(["bash", str(ROOT / "deploy" / "cloudflare" / "deploy.sh")],
                   env={**os.environ, "JARVIS_API_BASE": url}, check=False)
    token = read_kv(ROOT / "deploy" / "hf" / ".secrets")["JARVIS_OWNER_TOKEN"]
    webapp = read_kv(ROOT / ".env").get("JARVIS_WEBAPP_URL") or f"{url}/app/"
    print(f"\nГотово. Сервер: {url}")
    print(f"Ссылка владельца (никому не пересылай): {webapp.rstrip('/')}/#t={token}")


if __name__ == "__main__":
    main()
