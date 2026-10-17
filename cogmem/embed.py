"""Эмбеддинги — «отпечатки смысла» текста для поиска по смыслу.

Основной вариант — локальная мультиязычная модель (fastembed, ONNX, CPU, ~10 мс на фразу).
Это не языковая модель, она ничего не «думает» — только переводит текст в вектор.
Для тестов есть детерминированный HashEmbedder (не требует скачивания модели).
"""

from __future__ import annotations

import hashlib
import threading
from typing import Protocol, Sequence

import numpy as np

from cogmem.text import ru


class Embedder(Protocol):
    dim: int
    name: str
    # Калибровка шкалы косинуса: ниже floor — «не связано», выше ceil — «то же самое».
    # У разных моделей шкалы очень разные (MiniLM: 0.05…0.8, e5-large: 0.72…0.92).
    sim_floor: float
    sim_ceil: float
    # Шкала «запись↔запись» (для отсева похожего в рабочей памяти) — у моделей она выше, чем «запрос↔запись».
    dup_floor: float
    dup_ceil: float

    def embed(self, texts: Sequence[str], *, query: bool = False) -> np.ndarray:
        """Матрица [n, dim], строки нормированы (длина 1). query=True — это поисковый запрос."""


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class HashEmbedder:
    """Детерминированный «мешок основ слов и n-грамм» через хеширование.

    Ловит совпадение слов в разных падежах (через стемминг) и частичное совпадение
    (через символьные триграммы). Смысловых синонимов не знает — для этого FastEmbedder.
    """

    sim_floor = 0.0
    sim_ceil = 0.6
    dup_floor = 0.0
    dup_ceil = 0.6

    def __init__(self, dim: int = 512):
        self.dim = dim
        self.name = f"hash-{dim}"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for s in ru.stems(text):
            h = int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
            padded = f"#{s}#"
            for i in range(len(padded) - 2):
                g = padded[i : i + 3]
                hg = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "little")
                v[hg % self.dim] += 0.3 if (hg >> 63) & 1 else -0.3
        return v

    def embed(self, texts: Sequence[str], *, query: bool = False) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalize(np.stack([self._vec(t) for t in texts]))


# Модель → (префикс запроса, префикс текста, floor, ceil[, dup_floor, dup_ceil]). Калибровка — на русских парах.
# e5-large «запрос↔запись»: постороннее 0.73–0.80, верное 0.80–0.85 (стенд, 2026-10) — поэтому floor 0.77.
# e5-large «запись↔запись»: постороннее 0.84–0.89, близкое по теме ~0.91, перефразировка 0.97–1.0.
MODELS = {
    "intfloat/multilingual-e5-large": ("query: ", "passage: ", 0.75, 0.90, 0.88, 0.98),
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2": ("", "", 0.10, 0.80),
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": ("", "", 0.05, 0.80),
}


class FastEmbedder:
    """Локальная мультиязычная модель через fastembed (ONNX, CPU).

    По умолчанию multilingual-e5-large: лучшая из проверенных на русских перефразировках
    («На чём я езжу?» → «Моя машина — Peugeot»), ~15 мс на фразу, ~2.3 ГБ на диске.
    """

    DEFAULT_MODEL = "intfloat/multilingual-e5-large"

    def __init__(self, model_name: str = DEFAULT_MODEL):
        from fastembed import TextEmbedding  # необязательная зависимость

        self._model = TextEmbedding(model_name)
        self._lock = threading.Lock()
        self.name = model_name
        cal = MODELS.get(model_name, ("", "", 0.05, 0.8))
        self._qp, self._pp, self.sim_floor, self.sim_ceil = cal[:4]
        self.dup_floor, self.dup_ceil = cal[4:6] if len(cal) >= 6 else (self.sim_floor, self.sim_ceil)
        self.dim = int(self.embed(["проверка"]).shape[1])

    def embed(self, texts: Sequence[str], *, query: bool = False) -> np.ndarray:
        if not texts:
            return np.zeros((0, getattr(self, "dim", 384)), dtype=np.float32)
        prefix = self._qp if query else self._pp
        with self._lock:
            vecs = list(self._model.embed([prefix + t for t in texts]))
        return _normalize(np.stack(vecs))


def default_embedder(model_name: str | None = None) -> Embedder:
    import os

    try:
        return FastEmbedder(model_name or os.environ.get("JARVIS_EMBED_MODEL") or FastEmbedder.DEFAULT_MODEL)
    except Exception:  # нет пакета или модели — работаем, но предупреждаем в логах
        import logging

        logging.getLogger(__name__).warning(
            "fastembed недоступен — используется HashEmbedder (поиск по смыслу будет слабее)"
        )
        return HashEmbedder()
