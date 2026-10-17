"""Кто говорит: узнавание членов семьи по голосу (WeSpeaker ResNet34, ONNX, локально).

Отпечатки копятся сами («пассивная запись»): когда человек говорит из своего личного канала
(свой Telegram, своё приложение по личной ссылке), его голос известен — образец добавляется.
На общем устройстве голос сравнивается с отпечатками. Решение строгое: нужно и высокое сходство,
и явный отрыв от второго кандидата — иначе «не узнан» (проверено: чужой мужской голос похож на
владельца на 0.80, свой — 0.83–0.91, поэтому одного порога мало).
"""

from __future__ import annotations

import logging
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cogmem.memory import CognitiveMemory
from cogmem.store import from_blob, to_blob

log = logging.getLogger(__name__)
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
             "wespeaker_en_voxceleb_resnet34.onnx")
ACCEPT = 0.82        # минимальное сходство с профилем
MARGIN = 0.12        # отрыв от второго кандидата
MAX_SAMPLES = 12     # образцов на человека (старые вытесняются)
MIN_SECONDS = 1.5    # слишком короткие фразы не годятся ни для записи, ни для узнавания


@dataclass
class Match:
    person_id: str | None   # None — не узнан уверенно
    score: float
    margin: float


class Speakers:
    def __init__(self, memory: CognitiveMemory, models_dir: str | Path):
        self.m = memory
        self.path = Path(models_dir) / "speaker" / "wespeaker_resnet34.onnx"
        self._ex = None
        self._lock = threading.Lock()

    def _extractor(self):
        if self._ex is None:
            import sherpa_onnx

            if not self.path.exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                log.info("скачиваю модель голосов")
                urllib.request.urlretrieve(MODEL_URL, self.path)
            self._ex = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self.path), num_threads=2))
        return self._ex

    def embed(self, pcm16k: bytes) -> np.ndarray | None:
        """PCM 16 кГц моно int16 → нормированный вектор голоса (или None, если фраза слишком короткая)."""
        a = np.frombuffer(pcm16k, np.int16).astype(np.float32) / 32768.0
        if a.size < MIN_SECONDS * 16000:
            return None
        with self._lock:
            ex = self._extractor()
            s = ex.create_stream()
            s.accept_waveform(16000, a)
            s.input_finished()
            v = np.array(ex.compute(s), dtype=np.float32)
        n = np.linalg.norm(v)
        return v / n if n else None

    def enroll(self, person_id: str, pcm16k: bytes) -> bool:
        v = self.embed(pcm16k)
        if v is None:
            return False
        db = self.m.ctx.db
        db.execute("INSERT INTO voiceprints(person_id, embedding, created_at) VALUES (?,?,?)",
                   (person_id, to_blob(v), self.m.ctx.clock.now()))
        db.execute("DELETE FROM voiceprints WHERE person_id=? AND id NOT IN (SELECT id FROM voiceprints "
                   "WHERE person_id=? ORDER BY id DESC LIMIT ?)", (person_id, person_id, MAX_SAMPLES))
        return True

    def profiles(self) -> dict[str, np.ndarray]:
        groups: dict[str, list[np.ndarray]] = {}
        for r in self.m.ctx.db.query("SELECT person_id, embedding FROM voiceprints"):
            groups.setdefault(r["person_id"], []).append(from_blob(r["embedding"]))
        out = {}
        for p, vs in groups.items():
            c = np.mean(np.stack(vs), axis=0)
            out[p] = c / np.linalg.norm(c)
        return out

    def identify(self, pcm16k: bytes) -> Match:
        v = self.embed(pcm16k)
        profs = self.profiles()
        if v is None or not profs:
            return Match(None, 0.0, 0.0)
        sims = sorted(((float(v @ c), p) for p, c in profs.items()), reverse=True)
        best, who = sims[0]
        second = sims[1][0] if len(sims) > 1 else 0.0
        margin = best - second
        ok = best >= ACCEPT and (len(sims) == 1 or margin >= MARGIN)
        return Match(who if ok else None, best, margin)
