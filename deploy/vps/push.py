"""Положить код и установщик в приватный датасет Hugging Face; печатает одну команду для нового VPS."""
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy" / "vps"))
from make_cloud_init import read_env, build, main as _m  # noqa: E402,F401
import io, contextlib  # noqa: E402
from huggingface_hub import HfApi  # noqa: E402

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    _m()
script = buf.getvalue()
hf = read_env(ROOT / "deploy" / "hf" / ".secrets")
api = HfApi(token=hf["HF_TOKEN"])
repo = api.whoami()["name"] + "/jarvis-data"
code = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar.gz", "HEAD"], capture_output=True, check=True).stdout
api.upload_file(path_or_fileobj=code, path_in_repo="code.tar.gz", repo_id=repo, repo_type="dataset", commit_message="код")
api.upload_file(path_or_fileobj=script.encode(), path_in_repo="install.sh", repo_id=repo, repo_type="dataset", commit_message="установщик")
print(f'curl -fsSL -H "Authorization: Bearer {hf["HF_TOKEN"]}" https://huggingface.co/datasets/{repo}/resolve/main/install.sh | sudo bash')
