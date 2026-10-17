"""Мастерская — где Джарвис выполняет свой код (CodeAct): расчёты, запросы к API, файлы, проверка навыков.

Два исполнителя с одним интерфейсом:
  • LocalWorkshop — отдельный процесс Python с лимитами (для тестов и одиночной установки);
  • HttpWorkshop  — отдельный контейнер-сервис (jarvis.workshop.server): там нет базы памяти и ключей API.
Интернет в мастерской есть, библиотеки можно ставить — это часть свободы Джарвиса.
"""

from __future__ import annotations

import base64
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

MAX_OUTPUT = 20_000


@dataclass
class RunResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    files: dict[str, str] = field(default_factory=dict)  # новые файлы в рабочей папке: имя → base64

    def summary(self, limit: int = 6000) -> str:
        out = self.stdout[-limit:] if self.stdout else ""
        err = self.stderr[-limit // 2:] if self.stderr else ""
        parts = [f"код выхода {self.exit_code}, {self.seconds:.1f} с"]
        if out:
            parts.append("stdout:\n" + out)
        if err:
            parts.append("stderr:\n" + err)
        if self.files:
            parts.append("созданы файлы: " + ", ".join(sorted(self.files)))
        return "\n".join(parts)


class Workshop(Protocol):
    def run(self, code: str, *, files: dict[str, bytes] | None = None, timeout: float = 90.0,
            extra_paths: list[str] | None = None) -> RunResult: ...


def _limits(mem_mb: int) -> None:  # выполняется в дочернем процессе
    resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
    os.setsid()


def _clip(s: str) -> str:
    return s if len(s) <= MAX_OUTPUT else s[:MAX_OUTPUT // 2] + "\n…[обрезано]…\n" + s[-MAX_OUTPUT // 2:]


class LocalWorkshop:
    """Отдельный процесс: чистое окружение (без ключей API и секретов), временная папка, лимит памяти и времени.

    skills_dir — банк навыков (импортируется как обычные пакеты); pkgs_dir — библиотеки, которые Джарвис
    сам поставил (pip install --target), сохраняются между запусками; shared_dir — постоянная папка для файлов.
    """

    def __init__(self, root: str | Path = "data/workshop", *, skills_dir: str | Path = "data/skills",
                 mem_mb: int = 1024, python: str | None = None):
        self.root = Path(root)
        self.pkgs = self.root / "pkgs"
        self.shared = self.root / "shared"
        self.skills_dir = Path(skills_dir)
        for d in (self.pkgs, self.shared, self.skills_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.mem_mb = mem_mb
        self.python = python or sys.executable

    def run(self, code: str, *, files: dict[str, bytes] | None = None, timeout: float = 90.0,
            extra_paths: list[str] | None = None) -> RunResult:
        work = Path(tempfile.mkdtemp(prefix="run-", dir=self.root))
        try:
            for name, data in (files or {}).items():
                p = (work / name).resolve()
                if work.resolve() not in p.parents:
                    continue  # путь за пределы рабочей папки — игнорируем
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            (work / "main.py").write_text(code, encoding="utf-8")
            before = {p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()}
            paths = [str(p) for p in (extra_paths or [])] + [str(self.skills_dir.resolve()), str(self.pkgs.resolve())]
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(work),
                "LANG": "C.UTF-8",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": os.pathsep.join(paths),
                "PIP_TARGET": str(self.pkgs.resolve()),  # pip install кладёт библиотеки сюда навсегда
                "JARVIS_SHARED": str(self.shared.resolve()),
            }
            for k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
                if k in os.environ:  # сеть через прокси окружения (если есть) — да; ключи API — нет
                    env[k] = os.environ[k]
            t0 = time.perf_counter()
            try:
                proc = subprocess.run([self.python, "main.py"], cwd=work, env=env, capture_output=True, text=True,
                                      timeout=timeout, preexec_fn=lambda: _limits(self.mem_mb))
                code_, out, err = proc.returncode, proc.stdout, proc.stderr
            except subprocess.TimeoutExpired as e:
                code_ = -9
                out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
                err = ((e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or "")) + \
                    f"\n[превышено время {timeout:.0f} с]"
            new_files = {}
            for p in work.rglob("*"):
                rel = p.relative_to(work).as_posix()
                if p.is_file() and rel not in before and p.stat().st_size <= 5_000_000:
                    new_files[rel] = base64.b64encode(p.read_bytes()).decode()
            return RunResult(code_ == 0, code_, _clip(out), _clip(err), time.perf_counter() - t0, new_files)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class HttpWorkshop:
    """Клиент мастерской-контейнера (jarvis.workshop.server)."""

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token

    def run(self, code: str, *, files: dict[str, bytes] | None = None, timeout: float = 90.0,
            extra_paths: list[str] | None = None) -> RunResult:
        body = json.dumps({"code": code, "timeout": timeout, "extra_paths": extra_paths or [],
                           "files": {k: base64.b64encode(v).decode() for k, v in (files or {}).items()}}).encode()
        req = urllib.request.Request(self.url + "/run", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=timeout + 30) as r:
            return RunResult(**json.loads(r.read()))


def from_env() -> Workshop:
    url = os.environ.get("JARVIS_WORKSHOP_URL")
    if url:
        return HttpWorkshop(url, os.environ.get("JARVIS_WORKSHOP_TOKEN", ""))
    return LocalWorkshop()


__all__ = ["RunResult", "Workshop", "LocalWorkshop", "HttpWorkshop", "from_env", "asdict"]
