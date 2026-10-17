"""Резервная копия памяти для площадок без постоянного диска (бесплатный Hugging Face Space).

Папка данных (память, навыки, сейф) раз в несколько минут упаковывается и кладётся в ПРИВАТНЫЙ датасет
Hugging Face; при запуске — достаётся обратно. Модели речи и смысла не копируются (они в образе).
  JARVIS_BACKUP_REPO = "имя/jarvis-data"   — приватный датасет (создаётся сам)
  HF_TOKEN                                 — токен Hugging Face с правом записи
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import sqlite3
import tarfile
import tempfile
import threading
from pathlib import Path

log = logging.getLogger(__name__)
FILE = "data.tar.gz"
SKIP = {"models", "workshop", "caddy"}  # тяжёлое и временное
EVERY_S = int(os.environ.get("JARVIS_BACKUP_EVERY_S", "300"))


def _api():
    from huggingface_hub import HfApi

    return HfApi(token=os.environ.get("HF_TOKEN"))


def _add(tar: tarfile.TarFile, path: Path, arcname: str) -> None:
    """Добавить файл без меток времени и владельца — одинаковые данные дают одинаковый архив."""
    info = tar.gettarinfo(str(path), arcname=arcname)
    info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
    with open(path, "rb") as f:
        tar.addfile(info, f)


def snapshot(data: Path) -> bytes:
    """Упаковать папку данных. База SQLite копируется через backup API — согласованно, даже во время записи."""
    buf = io.BytesIO()
    import gzip

    gz = gzip.GzipFile(fileobj=buf, mode="wb", mtime=0)
    with tarfile.open(fileobj=gz, mode="w") as tar:
        for p in sorted(data.rglob("*")):
            rel = p.relative_to(data)
            if not p.is_file() or rel.parts[0] in SKIP or p.name.endswith(("-wal", "-shm", "-journal", ".part")):
                continue
            if p.suffix == ".db":
                with tempfile.TemporaryDirectory() as td:
                    tmp = Path(td) / p.name
                    src, dst = sqlite3.connect(p), sqlite3.connect(tmp)
                    with dst:
                        src.backup(dst)
                    src.close()
                    dst.close()
                    _add(tar, tmp, str(rel))
            else:
                _add(tar, p, str(rel))
    gz.close()
    return buf.getvalue()


def restore(data: Path, repo: str) -> bool:
    """Достать последнюю копию в папку данных (если копии ещё нет — начать с чистого листа)."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError, RemoteEntryNotFoundError, RepositoryNotFoundError

    data.mkdir(parents=True, exist_ok=True)
    if any(data.glob("*.db")):
        # Диск сохранился (VPS, перезапуск без потери данных) — локальные данные новее копии, не трогаем.
        log.info("локальная память на месте — восстановление из копии не нужно")
        return False
    api = _api()
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    try:
        path = hf_hub_download(repo, FILE, repo_type="dataset", token=os.environ.get("HF_TOKEN"),
                               local_dir=tempfile.mkdtemp())
    except (EntryNotFoundError, RemoteEntryNotFoundError, RepositoryNotFoundError):
        log.info("резервной копии ещё нет — начинаю с чистой памяти")
        return False
    for leftover in list(data.glob("*.db-wal")) + list(data.glob("*.db-shm")):
        leftover.unlink()  # старый журнал SQLite поверх восстановленной базы её испортит
    with tarfile.open(path, "r:gz") as tar:
        tar.extractall(data, filter="data")
    log.info("память восстановлена из %s", repo)
    return True


class Backup:
    def __init__(self, data: Path, repo: str):
        self.data, self.repo = Path(data), repo
        self._last = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def save(self, reason: str = "по расписанию") -> bool:
        with self._lock:
            blob = snapshot(self.data)
            digest = hashlib.sha256(blob).hexdigest()
            if digest == self._last:
                return False
            _api().upload_file(path_or_fileobj=blob, path_in_repo=FILE, repo_id=self.repo, repo_type="dataset",
                               commit_message=f"Резервная копия ({reason})")
            self._last = digest
            log.info("резервная копия сохранена (%d КБ, %s)", len(blob) // 1024, reason)
            return True

    def start(self) -> None:
        def loop():
            while not self._stop.wait(EVERY_S):
                try:
                    self.save()
                except Exception:  # noqa: BLE001 — сеть мигнула: попробуем в следующий раз
                    log.exception("не удалось сохранить резервную копию")

        threading.Thread(target=loop, name="jarvis-backup", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.save("остановка")
        except Exception:  # noqa: BLE001
            log.exception("не удалось сохранить копию при остановке")
