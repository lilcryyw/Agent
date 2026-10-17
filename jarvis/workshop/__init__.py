"""Мастерская — где Джарвис выполняет свой код (CodeAct): расчёты, запросы к API, файлы, проверка навыков.

Два исполнителя с одним интерфейсом:
  • LocalWorkshop — отдельный процесс Python с лимитами (для тестов и одиночной установки);
  • HttpWorkshop  — отдельный контейнер-сервис (jarvis.workshop.server): там нет базы памяти и ключей API.
Интернет в мастерской есть, библиотеки можно ставить — это часть свободы Джарвиса.

Что живёт между запусками (папка мастерской):
  pkgs/    — библиотеки (pip install кладёт сюда навсегда);
  home/    — домашняя папка процессов (настройки программ, кэш браузеров Playwright и т.п.);
  shared/  — диск Джарвиса ($JARVIS_SHARED): свои файлы, данные, входящие от людей (inbox/),
             результаты запусков (runs/<id>/ — новые файлы из рабочей папки), полные выводы (out/).
Рабочая папка каждого запуска временная и после него стирается.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

MAX_OUTPUT = 20_000          # сколько вывода вообще держим в памяти результата
SUMMARY_LIMIT = 6000         # сколько вывода показываем модели (голова + хвост)
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
             ".webp": "image/webp"}
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 3_500_000
KEEP_FILES = 20              # сколько новых файлов верхнего уровня сохранить в shared/runs/<id>/
KEEP_BYTES = 50_000_000
KEEP_RUNS = 30               # сколько последних папок runs/ хранить
SKIP_DIRS = {".cache", "__pycache__", ".git", "node_modules", ".venv", "site-packages"}


def clip(s: str, limit: int) -> str:
    """Голова и хвост: в начале обычно заголовки/ошибки импорта, в конце — итог."""
    if len(s) <= limit:
        return s
    head = limit // 3
    return s[:head] + f"\n…[обрезано {len(s) - limit} симв.]…\n" + s[-(limit - head):]


@dataclass
class RunResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    files: dict[str, str] = field(default_factory=dict)  # новые картинки (до 3): имя → base64
    saved: list[str] = field(default_factory=list)       # новые файлы, сохранённые в shared (пути от shared)
    saved_total: int = 0                                 # сколько всего новых файлов было
    full_output: str = ""                                # путь (от shared) к полному выводу, если обрезан
    cancelled: bool = False

    def summary(self, limit: int = SUMMARY_LIMIT) -> str:
        parts = [f"код выхода {self.exit_code}, {self.seconds:.1f} с" + (" — остановлено" if self.cancelled else "")]
        if self.stdout:
            parts.append("stdout:\n" + clip(self.stdout, limit))
        if self.stderr:
            parts.append("stderr:\n" + clip(self.stderr, max(limit // 2, 500)))
        if self.full_output:
            parts.append(f"полный вывод: $JARVIS_SHARED/{self.full_output}")
        if self.saved:
            more = self.saved_total - len(self.saved)
            parts.append("новые файлы сохранены в $JARVIS_SHARED: " + ", ".join(self.saved[:KEEP_FILES])
                         + (f" (и ещё {more} не сохранено)" if more > 0 else ""))
        elif self.saved_total:
            parts.append(f"создано файлов: {self.saved_total} (во временной папке, стёрты; "
                         "нужное сохраняй в $JARVIS_SHARED)")
        return "\n".join(parts)

    def images(self) -> list[tuple[str, str, str]]:
        """[(имя, media_type, base64)] — картинки, созданные запуском."""
        out = []
        for name, data in sorted(self.files.items()):
            mt = IMAGE_EXT.get(Path(name).suffix.lower())
            if mt:
                out.append((name, mt, data))
        return out[:MAX_IMAGES]


class Workshop(Protocol):
    shared: Path

    def run(self, code: str, *, files: dict[str, bytes] | None = None, timeout: float = 90.0,
            extra_paths: list[str] | None = None, env: dict[str, str] | None = None,
            cancel: threading.Event | None = None, keep: bool = True) -> RunResult: ...


def _limits(mem_mb: int) -> None:  # выполняется в дочернем процессе
    import resource

    # RLIMIT_DATA, а не RLIMIT_AS: браузеры, Node, JVM резервируют огромное виртуальное пространство
    # (без реальной памяти) и под RLIMIT_AS просто не стартуют.
    lim = mem_mb * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_DATA, (lim, lim))
    except (ValueError, OSError):
        pass
    os.setsid()


def _no_dump() -> None:
    """Сделать текущий процесс «недампируемым»: его /proc/<pid>/environ и память перестают читаться
    процессами того же пользователя (код мастерской не достанет ключи API из окружения сервера).
    Для root это не защита — root видит всё; поэтому в одном контейнере сервер работает не от root."""
    if sys.platform != "linux" or os.environ.get("JARVIS_WORKSHOP_NODUMP") == "0":
        return
    try:
        import ctypes

        ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 4
    except Exception:  # noqa: BLE001
        pass


_BWRAP_OK: bool | None = None


def _bwrap_works() -> bool:
    """Есть ли рабочий bubblewrap (нужны пространства имён; в некоторых контейнерах их нет)."""
    global _BWRAP_OK
    if _BWRAP_OK is None:
        exe = shutil.which("bwrap")
        _BWRAP_OK = False
        if exe and os.environ.get("JARVIS_WORKSHOP_SANDBOX", "auto") != "off":
            try:
                _BWRAP_OK = subprocess.run([exe, "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev",
                                            "--unshare-pid", "true"], capture_output=True, timeout=10).returncode == 0
            except Exception:  # noqa: BLE001
                _BWRAP_OK = False
    return _BWRAP_OK


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # setsid в дочернем: убиваем всю группу (pip, браузеры…)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


class LocalWorkshop:
    """Отдельный процесс: чистое окружение (без ключей API и секретов), временная рабочая папка,
    лимиты памяти и времени. Если есть рабочий bubblewrap — ещё и своя «картина мира»: не видны процессы
    сервера и папки с данными (hide: база памяти, сейф).

    skills_dir — банк навыков (импортируется как обычные пакеты); pkgs/ — библиотеки, которые Джарвис
    сам поставил (pip install --target), сохраняются между запусками; shared/ — постоянный диск.
    """

    def __init__(self, root: str | Path = "data/workshop", *, skills_dir: str | Path = "data/skills",
                 mem_mb: int = 1536, python: str | None = None, hide: list[str | Path] | None = None):
        self.root = Path(root)
        self.pkgs = self.root / "pkgs"
        self.shared = self.root / "shared"
        self.home = self.root / "home"
        self.cache = self.root / "cache"
        self.skills_dir = Path(skills_dir)
        for d in (self.pkgs, self.shared, self.home, self.cache, self.skills_dir, self.shared / "runs",
                  self.shared / "out", self.shared / "inbox"):
            d.mkdir(parents=True, exist_ok=True)
        self.mem_mb = mem_mb
        self.python = python or sys.executable
        if hide is None:
            env_hide = os.environ.get("JARVIS_WORKSHOP_HIDE", "")
            hide = [p for p in env_hide.split(os.pathsep) if p]
            parent = self.root.resolve().parent
            if not hide and any((parent / f).exists() for f in ("jarvis.db", "vault.key", "vault.bin")):
                hide = [parent]  # мастерская лежит в папке данных — саму папку данных прячем
        self.hide = [Path(p).resolve() for p in hide]
        _no_dump()

    @property
    def sandboxed(self) -> bool:
        return _bwrap_works()

    def _cmd(self, work: Path) -> list[str]:
        base = [self.python, "main.py"]
        if not self.sandboxed:
            return base
        cmd = [shutil.which("bwrap") or "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
               "--tmpfs", "/tmp", "--unshare-pid", "--die-with-parent"]
        for h in self.hide:
            cmd += ["--tmpfs", str(h)]
        for d in (self.root.resolve(), work):
            cmd += ["--bind", str(d), str(d)]
        cmd += ["--ro-bind", str(self.skills_dir.resolve()), str(self.skills_dir.resolve()), "--chdir", str(work)]
        return cmd + base

    def run(self, code: str, *, files: dict[str, bytes] | None = None, timeout: float = 90.0,
            extra_paths: list[str] | None = None, env: dict[str, str] | None = None,
            cancel: threading.Event | None = None, keep: bool = True) -> RunResult:
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        work = Path(tempfile.mkdtemp(prefix="run-", dir=self.root)).resolve()
        logs = Path(tempfile.mkdtemp(prefix="log-", dir=self.root)).resolve()
        try:
            for name, data in (files or {}).items():
                p = (work / name).resolve()
                if work not in p.parents:
                    continue  # путь за пределы рабочей папки — игнорируем
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            (work / "main.py").write_text(code, encoding="utf-8")
            before = {p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()}
            paths = [str(p) for p in (extra_paths or [])] + [str(self.skills_dir.resolve()), str(self.pkgs.resolve())]
            penv = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(self.home.resolve()),
                "XDG_CACHE_HOME": str((self.home / ".cache").resolve()),
                "LANG": "C.UTF-8",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "PYTHONPATH": os.pathsep.join(paths),
                "PIP_TARGET": str(self.pkgs.resolve()),  # pip install кладёт библиотеки сюда навсегда
                "PIP_CACHE_DIR": str(self.cache.resolve()),
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "MPLBACKEND": "Agg",
                "JARVIS_SHARED": str(self.shared.resolve()),
            }
            for k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
                      "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
                if k in os.environ:  # сеть через прокси окружения (если есть) — да; ключи API — нет
                    penv[k] = os.environ[k]
            penv.update(env or {})
            out_f, err_f = logs / "out", logs / "err"
            t0 = time.perf_counter()
            cancelled = timed_out = False
            with open(out_f, "wb") as fo, open(err_f, "wb") as fe:
                proc = subprocess.Popen(self._cmd(work), cwd=work, env=penv, stdout=fo, stderr=fe,
                                        stdin=subprocess.DEVNULL, preexec_fn=lambda: _limits(self.mem_mb))
                while True:
                    try:
                        proc.wait(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                    elif time.perf_counter() - t0 > timeout:
                        timed_out = True
                    if cancelled or timed_out:
                        _kill_tree(proc)
                        proc.wait()
                        break
            _kill_tree(proc)  # «внуки», оставшиеся после выхода (фоновые процессы кода), тоже
            out = out_f.read_text(encoding="utf-8", errors="replace")
            err = err_f.read_text(encoding="utf-8", errors="replace")
            code_ = -9 if (cancelled or timed_out) else proc.returncode
            if timed_out:
                err += f"\n[превышено время {timeout:.0f} с — для долгих задач запускай в фоне (wait_s=0)]"
            if cancelled:
                err += "\n[остановлено по просьбе человека]"
            res = RunResult(code_ == 0, code_, out[-MAX_OUTPUT * 5:], err[-MAX_OUTPUT * 2:],
                            time.perf_counter() - t0, cancelled=cancelled)
            if len(out) > SUMMARY_LIMIT or len(err) > SUMMARY_LIMIT // 2:
                full = self.shared / "out" / f"{run_id}.txt"
                full.write_text(out + ("\n--- stderr ---\n" + err if err else ""), encoding="utf-8")
                res.full_output = f"out/{run_id}.txt"
            res.stdout, res.stderr = clip(res.stdout, MAX_OUTPUT), clip(res.stderr, MAX_OUTPUT)
            self._collect(work, before, run_id, res, keep)
            return res
        finally:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(logs, ignore_errors=True)

    def _collect(self, work: Path, before: set[str], run_id: str, res: RunResult, keep: bool) -> None:
        new = []
        for p in work.rglob("*"):
            rel = p.relative_to(work)
            if not p.is_file() or rel.as_posix() in before or any(part in SKIP_DIRS for part in rel.parts[:-1]):
                continue
            new.append((rel, p))
        res.saved_total = len(new)
        imgs = [(r, p) for r, p in new if p.suffix.lower() in IMAGE_EXT and p.stat().st_size <= MAX_IMAGE_BYTES]
        for r, p in sorted(imgs, key=lambda x: (len(x[0].parts), x[0].as_posix()))[:MAX_IMAGES]:
            res.files[r.as_posix()] = base64.b64encode(p.read_bytes()).decode()
        if not keep or not new:
            return
        dst = self.shared / "runs" / run_id
        total = 0
        top = sorted([x for x in new if len(x[0].parts) == 1], key=lambda x: x[0].as_posix())
        for r, p in top[:KEEP_FILES]:
            size = p.stat().st_size
            if total + size > KEEP_BYTES:
                break
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / r.name)
            total += size
            res.saved.append(f"runs/{run_id}/{r.name}")
        runs = sorted((self.shared / "runs").iterdir(), key=lambda d: d.name)
        for old in runs[:-KEEP_RUNS]:
            shutil.rmtree(old, ignore_errors=True)


class HttpWorkshop:
    """Клиент мастерской-контейнера (jarvis.workshop.server)."""

    def __init__(self, url: str, token: str, shared: str | Path | None = None):
        self.url = url.rstrip("/")
        self.token = token
        # Тот же диск, что у контейнера мастерской (общий том): нужен, чтобы отправлять файлы людям.
        self.shared = Path(shared or os.environ.get("JARVIS_WORKSHOP_SHARED", "data/workshop/shared"))

    def _post(self, path: str, obj: dict, timeout: float) -> dict:
        req = urllib.request.Request(self.url + path, data=json.dumps(obj).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")

    def run(self, code: str, *, files: dict[str, bytes] | None = None, timeout: float = 90.0,
            extra_paths: list[str] | None = None, env: dict[str, str] | None = None,
            cancel: threading.Event | None = None, keep: bool = True) -> RunResult:
        run_id = uuid.uuid4().hex
        body = {"code": code, "timeout": timeout, "extra_paths": extra_paths or [], "env": env or {},
                "run_id": run_id, "keep": keep,
                "files": {k: base64.b64encode(v).decode() for k, v in (files or {}).items()}}
        box: dict = {}

        def call():
            try:
                box["res"] = self._post("/run", body, timeout + 30)
            except Exception as exc:  # noqa: BLE001
                box["err"] = exc

        t = threading.Thread(target=call, daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.3)
            if cancel is not None and cancel.is_set():
                try:
                    self._post("/cancel", {"run_id": run_id}, 10)
                except Exception:  # noqa: BLE001
                    pass
                t.join(15)
                break
        if "res" in box:
            return RunResult(**box["res"])
        if "err" in box:
            raise box["err"]
        return RunResult(False, -9, "", "[остановлено по просьбе человека]", 0.0, cancelled=True)


def from_env() -> Workshop:
    url = os.environ.get("JARVIS_WORKSHOP_URL")
    if url:
        return HttpWorkshop(url, os.environ.get("JARVIS_WORKSHOP_TOKEN", ""))
    return LocalWorkshop()


__all__ = ["RunResult", "Workshop", "LocalWorkshop", "HttpWorkshop", "from_env", "asdict", "clip"]
