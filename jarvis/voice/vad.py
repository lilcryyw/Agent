"""Детектор речи для живого разговора: режет непрерывный поток звука на фразы.

Основной — Silero VAD (нейросеть, ~2 МБ, через sherpa-onnx): отличает речь от шума, музыки и дыхания.
Запасной — по громкости, если модели нет (хуже в шуме, но работает без зависимостей).

Вход — PCM16 моно 16 кГц кусками любой длины. feed() возвращает законченные фразы (PCM16);
in_speech / speech_ms / current() — что происходит прямо сейчас (для перебивания).
"""

from __future__ import annotations

import logging
import urllib.request
from collections import deque
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

RATE = 16000
SILERO_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
PREROLL_S = 0.3   # сколько звука до начала речи держать (начало слова детектор слышит с опозданием)
MAX_PHRASE_S = 30  # дольше — режем принудительно


def _to_f32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def _to_pcm(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class Segmenter:
    """Общая часть: учёт текущей речи и «предзвука»."""

    def __init__(self, min_silence_s: float):
        self.min_silence_s = min_silence_s
        self.in_speech = False
        self._cur: list[np.ndarray] = []
        self._cur_n = 0
        self._pre: deque[np.ndarray] = deque()
        self._pre_n = 0

    @property
    def speech_ms(self) -> int:
        return int(self._cur_n * 1000 / RATE) if self.in_speech else 0

    def current(self) -> bytes:
        """Звук текущей (ещё не законченной) фразы."""
        return _to_pcm(np.concatenate(self._cur)) if self._cur else b""

    def _track(self, x: np.ndarray, speaking: bool) -> None:
        if speaking and not self.in_speech:
            self.in_speech = True
            self._cur, self._cur_n = list(self._pre), self._pre_n
        if self.in_speech:
            self._cur.append(x)
            self._cur_n += len(x)
        self._pre.append(x)
        self._pre_n += len(x)
        while self._pre and self._pre_n - len(self._pre[0]) >= PREROLL_S * RATE:
            self._pre_n -= len(self._pre.popleft())

    def _end(self) -> None:
        self.in_speech = False
        self._cur, self._cur_n = [], 0

    def reset(self) -> None:
        self._end()
        self._pre.clear()
        self._pre_n = 0


class SileroSegmenter(Segmenter):
    WINDOW = 512  # Silero принимает окна по 32 мс

    def __init__(self, model_path: str | Path, *, min_silence_s: float = 0.7, threshold: float = 0.5):
        super().__init__(min_silence_s)
        import sherpa_onnx

        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(model_path)
        cfg.silero_vad.min_silence_duration = min_silence_s
        cfg.silero_vad.min_speech_duration = 0.25
        cfg.silero_vad.threshold = threshold
        cfg.silero_vad.max_speech_duration = MAX_PHRASE_S
        cfg.sample_rate = RATE
        cfg.num_threads = 1
        self._vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=MAX_PHRASE_S * 2)
        self._rest = np.zeros(0, dtype=np.float32)

    def feed(self, pcm: bytes) -> list[bytes]:
        x = np.concatenate([self._rest, _to_f32(pcm)])
        out: list[bytes] = []
        n = len(x) // self.WINDOW * self.WINDOW
        for i in range(0, n, self.WINDOW):
            w = x[i:i + self.WINDOW]
            self._vad.accept_waveform(w)
            self._track(w, self._vad.is_speech_detected())
            while not self._vad.empty():
                out.append(_to_pcm(np.asarray(self._vad.front.samples, dtype=np.float32)))
                self._vad.pop()
                self._end()
        self._rest = x[n:]
        return out

    def reset(self) -> None:
        super().reset()
        self._vad.reset()
        self._rest = np.zeros(0, dtype=np.float32)


class EnergySegmenter(Segmenter):
    """Запасной детектор по громкости с подстройкой под фоновый шум."""

    FRAME = 480  # 30 мс

    def __init__(self, *, min_silence_s: float = 0.7, min_speech_s: float = 0.25):
        super().__init__(min_silence_s)
        self.min_speech_s = min_speech_s
        self._floor = 0.003
        self._loud = 0      # подряд громких кадров
        self._quiet = 0     # подряд тихих кадров во время речи
        self._rest = np.zeros(0, dtype=np.float32)

    def feed(self, pcm: bytes) -> list[bytes]:
        x = np.concatenate([self._rest, _to_f32(pcm)])
        out: list[bytes] = []
        n = len(x) // self.FRAME * self.FRAME
        for i in range(0, n, self.FRAME):
            f = x[i:i + self.FRAME]
            rms = float(np.sqrt(np.mean(f * f)) + 1e-9)
            loud = rms > max(0.01, self._floor * 3.5)
            if not loud:  # уровень шума — медленно следим за тишиной
                self._floor = 0.95 * self._floor + 0.05 * rms
            self._loud = self._loud + 1 if loud else 0
            started = self.in_speech or self._loud >= 3
            self._track(f, started)
            if not self.in_speech:
                continue
            self._quiet = 0 if loud else self._quiet + 1
            dur = self._cur_n / RATE
            if self._quiet * self.FRAME / RATE >= self.min_silence_s or dur >= MAX_PHRASE_S:
                if dur - self._quiet * self.FRAME / RATE >= self.min_speech_s:
                    out.append(self.current())
                self._end()
                self._quiet = 0
        self._rest = x[n:]
        return out


def silero_model(models_dir: str | Path) -> Path | None:
    """Путь к модели Silero (скачивается один раз, ~2 МБ); None — если не удалось."""
    path = Path(models_dir) / "vad" / "silero_vad.onnx"
    if path.exists():
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        log.info("скачиваю детектор речи %s", SILERO_URL)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(SILERO_URL, tmp)
        tmp.rename(path)
        return path
    except Exception:  # noqa: BLE001
        log.exception("не удалось скачать Silero VAD — будет детектор по громкости")
        return None


def make_segmenter(models_dir: str | Path | None, *, min_silence_s: float = 0.7) -> Segmenter:
    if models_dir is not None:
        try:
            import sherpa_onnx  # noqa: F401

            path = silero_model(models_dir)
            if path is not None:
                return SileroSegmenter(path, min_silence_s=min_silence_s)
        except Exception:  # noqa: BLE001
            log.exception("Silero VAD недоступен — детектор по громкости")
    return EnergySegmenter(min_silence_s=min_silence_s)
