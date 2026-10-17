"""Достать настройки (config.env) из приватного датасета Hugging Face и разложить по местам."""

import os
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

token = os.environ["HF_TOKEN"]
user = HfApi(token=token).whoami()["name"]
repo = f"{user}/jarvis-data"
path = hf_hub_download(repo, "config.env", repo_type="dataset", token=token, local_dir="/tmp/jarvis-config")
text = Path(path).read_text(encoding="utf-8")
root = Path("/opt/jarvis")
env = root / ".env"
# Ключи Cloudflare нужны только для обновления сайта — в общие настройки Джарвиса их не кладём.
plain = "\n".join(line for line in text.splitlines() if not line.startswith("CLOUDFLARE_"))
env.write_text(plain + f"\nHF_TOKEN={token}\nJARVIS_BACKUP_REPO={repo}\n", encoding="utf-8")
env.chmod(0o600)
cf = {k: v for k, v in (line.split("=", 1) for line in text.splitlines() if line.startswith("CLOUDFLARE_"))}
if cf:
    sec = root / "deploy" / "cloudflare" / ".secrets"
    sec.write_text("".join(f"{k}={v}\n" for k, v in cf.items()), encoding="utf-8")
    sec.chmod(0o600)
Path(path).unlink()
print(f"настройки получены из {repo}")
