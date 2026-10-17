"""Положить настройки (.env + ключ владельца + ключи сайта) и архив кода в приватный датасет Hugging Face <имя>/jarvis-data,
чтобы телефон-сервер забрал их сам при установке. Запуск с компьютера, где лежит настроенный .env:
    python deploy/termux/push_config.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy" / "hf"))
from deploy import _fernet_key, read_kv  # noqa: E402

import secrets  # noqa: E402

from huggingface_hub import HfApi  # noqa: E402

saved = read_kv(ROOT / "deploy" / "hf" / ".secrets")
token = saved.get("HF_TOKEN")
if not token:
    sys.exit("нет HF_TOKEN в deploy/hf/.secrets")
saved.setdefault("JARVIS_OWNER_TOKEN", "jv_" + secrets.token_urlsafe(32))
saved.setdefault("JARVIS_VAULT_KEY", _fernet_key())
(ROOT / "deploy" / "hf" / ".secrets").write_text("".join(f"{k}={v}\n" for k, v in saved.items()), encoding="utf-8")

env = {k: v for k, v in read_kv(ROOT / ".env").items() if k not in {"JARVIS_DOMAIN", "JARVIS_DEVICES_URL", "JARVIS_DB"}}
env["JARVIS_OWNER_TOKEN"] = saved["JARVIS_OWNER_TOKEN"]
env["JARVIS_VAULT_KEY"] = saved["JARVIS_VAULT_KEY"]
env.update({k: v for k, v in read_kv(ROOT / "deploy" / "cloudflare" / ".secrets").items() if k.startswith("CLOUDFLARE_")})


def q(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"' if any(c in v for c in " ;:'\"$&|<>()") else v


body = "".join(f"{k}={q(v)}\n" for k, v in sorted(env.items()))
api = HfApi(token=token)
repo = api.whoami()["name"] + "/jarvis-data"
api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
api.upload_file(path_or_fileobj=body.encode(), path_in_repo="config.env", repo_id=repo, repo_type="dataset",
                commit_message="Настройки Джарвиса для телефона-сервера")
# Код: репозиторий на GitHub закрытый, поэтому телефон берёт архив кода отсюда же (последний коммит).
import subprocess  # noqa: E402

code = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar.gz", "HEAD"], capture_output=True,
                      check=True).stdout
api.upload_file(path_or_fileobj=code, path_in_repo="code.tar.gz", repo_id=repo, repo_type="dataset",
                commit_message="Код Джарвиса для телефона-сервера")
print(f"настройки и код ({len(code) // 1024 // 1024} МБ) загружены в приватный датасет {repo}")
