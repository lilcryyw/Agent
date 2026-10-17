"""Фоновые задачи: долгий код (до 2 ч) идёт сам, а разговор продолжается.

Задача [J..] — поток с собственным событием отмены. Когда она заканчивается, вызывается on_done:
органы будят мысль Джарвиса внутренним поводом («Фоновая задача J3 завершилась: …»).
Список живёт в памяти процесса (после перезапуска сервера незавершённые задачи теряются).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

MAX_PER_PERSON = 3
MAX_SECONDS = 2 * 3600


@dataclass
class Job:
    id: int
    person_id: str
    title: str
    started: float
    cancel: threading.Event = field(default_factory=threading.Event)
    status: str = "running"          # running | done | failed | cancelled
    result: str = ""
    finished: float | None = None

    def line(self, now: float) -> str:
        took = (self.finished or now) - self.started
        mins = f"{took / 60:.0f} мин" if took >= 60 else f"{took:.0f} с"
        state = {"running": "идёт", "done": "готово", "failed": "ошибка", "cancelled": "остановлена"}[self.status]
        return f"[J{self.id}] «{self.title[:60]}» — {state}, {mins}"


class JobBoard:
    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self._jobs: dict[int, Job] = {}
        self._next = 1
        self._lock = threading.Lock()

    def start(self, person_id: str, title: str, fn: Callable[[threading.Event], tuple[str, bool]],
              on_done: Callable[[Job], None] | None = None) -> Job | str:
        """fn(cancel) → (вывод, ошибка?). → Job или текст отказа."""
        with self._lock:
            if len(self.running(person_id)) >= MAX_PER_PERSON:
                return f"Уже идут {MAX_PER_PERSON} фоновые задачи — дождись или останови одну (job cancel)."
            job = Job(self._next, person_id, title or "задача", self.clock())
            self._next += 1
            self._jobs[job.id] = job

        def body():
            try:
                out, is_err = fn(job.cancel)
                job.status = "cancelled" if job.cancel.is_set() else ("failed" if is_err else "done")
                job.result = out
            except Exception as exc:  # noqa: BLE001
                job.status, job.result = "failed", f"{type(exc).__name__}: {exc}"
            job.finished = self.clock()
            if on_done is not None and job.status != "cancelled":
                try:
                    on_done(job)
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=body, name=f"jarvis-job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def of(self, person_id: str) -> list[Job]:
        return [j for j in self._jobs.values() if j.person_id == person_id]

    def running(self, person_id: str) -> list[Job]:
        return [j for j in self.of(person_id) if j.status == "running"]

    def cancel(self, person_id: str, job_id: int | None = None) -> int:
        n = 0
        for j in self.running(person_id):
            if job_id is None or j.id == job_id:
                j.cancel.set()
                n += 1
        return n

    def wait(self, job_id: int, timeout: float = 30.0) -> Job | None:
        """Для тестов: дождаться окончания задачи."""
        t0 = time.time()
        j = self.get(job_id)
        while j is not None and j.status == "running" and time.time() - t0 < timeout:
            time.sleep(0.05)
        return j
