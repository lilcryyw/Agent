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

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Матрица [n, dim], строки нормированы (длина 1)."""


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class HashEmbedder:
    """Детерминированный «мешок основ слов и n-грамм» через хеширование.

    Ловит совпадение слов в разных падежах (через стемминг) и частичное совпадение
    (через символьные триграммы). Смысловых синонимов не знает — для этого FastEmbedder.
    """

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

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalize(np.stack([self._vec(t) for t in texts]))


class FastEmbedder:
    """Локальная мультиязычная модель (по умолчанию paraphrase-multilingual-MiniLM-L12-v2, 384 изм.)."""

    DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, model_name: str = DEFAULT_MODEL):
        from fastembed import TextEmbedding  # необязательная зависимость

        self._model = TextEmbedding(model_name)
        self._lock = threading.Lock()
        self.name = model_name
        self.dim = int(self.embed(["проверка"]).shape[1])

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, getattr(self, "dim", 384)), dtype=np.float32)
        with self._lock:
            vecs = list(self._model.embed(list(texts)))
        return _normalize(np.stack(vecs))


def default_embedder() -> Embedder:
    try:
        return FastEmbedder()
    except Exception:  # нет пакета или модели — работаем, но предупреждаем в логах
        import logging

        logging.getLogger(__name__).warning(
            "fastembed недоступен — используется HashEmbedder (поиск по смыслу будет слабее)"
        )
        return HashEmbedder()
