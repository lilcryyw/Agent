"""Смысл текста через Cloudflare Workers AI (bge-m3, многоязычная) — для серверов с малой памятью.

Локальная e5-large занимает ~2 ГБ памяти; здесь сервер хранит только векторы, а считает их Cloudflare
(бесплатно до 10 000 «нейронов» в сутки — это миллионы слов). Нужны CLOUDFLARE_ACCOUNT_ID и
CLOUDFLARE_API_TOKEN (право Workers AI). Сеть пропала — повтор с паузой; не вышло — ошибка (событие
всё равно запишется заново при следующей попытке кодирования).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Sequence

import numpy as np

log = logging.getLogger(__name__)
API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
# Шкала сходства bge-m3 (как у e5: связанное ~0.55–0.8, постороннее ~0.3–0.45) — уточнена на стенде.
CALIBRATION = {"@cf/baai/bge-m3": (0.40, 0.80)}


class CloudflareEmbedder:
    def __init__(self, model: str = "@cf/baai/bge-m3", *, account: str | None = None, token: str | None = None,
                 batch: int = 64, timeout: float = 30.0):
        self.model = model
        self.name = model
        self.account = account or os.environ["CLOUDFLARE_ACCOUNT_ID"]
        self.token = token or os.environ["CLOUDFLARE_API_TOKEN"]
        self.batch = batch
        self.timeout = timeout
        self.sim_floor, self.sim_ceil = CALIBRATION.get(model, (0.3, 0.8))
        self._cache: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        self.dim = int(self._request(["проверка"]).shape[1])

    def _request(self, texts: list[str]) -> np.ndarray:
        body = json.dumps({"text": texts}).encode()
        url = API.format(account=self.account, model=self.model)
        delay = 1.0
        for attempt in range(5):
            req = urllib.request.Request(url, data=body, method="POST", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                vecs = np.asarray(data["result"]["data"], dtype=np.float32)
                return vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
                if attempt == 4:
                    raise RuntimeError(f"Workers AI недоступен: {exc}") from exc
                log.warning("Workers AI: %s — повтор через %.0f с", exc, delay)
                time.sleep(delay)
                delay *= 2
        raise AssertionError("недостижимо")

    def embed(self, texts: Sequence[str], *, query: bool = False) -> np.ndarray:
        if not texts:
            return np.zeros((0, getattr(self, "dim", 1024)), dtype=np.float32)
        texts = [t if t.strip() else "—" for t in texts]
        out: list[np.ndarray | None] = [self._cache.get(t) for t in texts]
        todo = [i for i, v in enumerate(out) if v is None]
        for start in range(0, len(todo), self.batch):
            idx = todo[start:start + self.batch]
            vecs = self._request([texts[i][:2000] for i in idx])
            with self._lock:
                for i, v in zip(idx, vecs):
                    out[i] = v
                    if len(self._cache) < 5000:  # частые запросы (имена, короткие реплики) — без повторной оплаты
                        self._cache[texts[i]] = v
        return np.stack(out).astype(np.float32)

    def embed1(self, text: str, *, query: bool = False) -> np.ndarray:
        return self.embed([text], query=query)[0]
