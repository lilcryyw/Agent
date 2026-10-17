"""Голос: распознавание (GigaAM v3, Сбер — лучшее для русского) и синтез (Piper), всё локально на сервере.

Без PyTorch: модели в формате ONNX. Распознавание фразы ~0.5 с, синтез ~0.3 с на обычном CPU.
Любой входной формат (ogg из Telegram, m4a с iPhone, webm из браузера) приводится к wav через ffmpeg.
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import tempfile
import threading
import urllib.request
import wave
from pathlib import Path

log = logging.getLogger(__name__)

STT_MODEL = os.environ.get("JARVIS_STT_MODEL", "gigaam-v3-e2e-ctc")  # с пунктуацией и цифрами
TTS_VOICE = os.environ.get("JARVIS_TTS_VOICE", "ru_RU-dmitri-medium")  # ещё: ru_RU-irina-medium, -denis-, -ruslan-
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def ffmpeg(data: bytes, out_args: list[str], in_fmt: str | None = None) -> bytes:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"] + (["-f", in_fmt] if in_fmt else []) + \
        ["-i", "pipe:0", *out_args, "pipe:1"]
    p = subprocess.run(cmd, input=data, capture_output=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg: " + p.stderr.decode(errors="replace")[-500:])
    return p.stdout


class Voice:
    def __init__(self, models_dir: str | Path = "data/models"):
        self.dir = Path(models_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._stt = None
        self._tts = None
        self._lock = threading.Lock()

    # --- распознавание ---
    def _stt_model(self):
        if self._stt is None:
            import onnx_asr

            log.info("загружаю модель распознавания %s", STT_MODEL)
            self._stt = onnx_asr.load_model(STT_MODEL)
        return self._stt

    def transcribe(self, audio: bytes) -> str:
        """Любой аудиоформат → текст."""
        # ffmpeg в поток пишет WAV без длины — берём «сырой» звук и собираем WAV сами.
        pcm = ffmpeg(audio, ["-ar", "16000", "-ac", "1", "-f", "s16le"])
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            with wave.open(f, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(pcm)
        try:
            with self._lock:
                text = self._stt_model().recognize(f.name)
        finally:
            os.unlink(f.name)
        return (text or "").strip()

    # --- синтез ---
    def _tts_voice(self):
        if self._tts is None:
            from piper import PiperVoice

            lang, region_name, quality = TTS_VOICE.split("-")[0], TTS_VOICE.split("-")[1], TTS_VOICE.split("-")[2]
            path = self.dir / "piper" / f"{TTS_VOICE}.onnx"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                lang_short = lang.split("_")[0]
                for suffix in (".onnx", ".onnx.json"):
                    url = f"{PIPER_BASE}/{lang_short}/{lang}/{region_name}/{quality}/{TTS_VOICE}{suffix}"
                    log.info("скачиваю голос %s", url)
                    urllib.request.urlretrieve(url, str(path) + suffix[len(".onnx"):])
            self._tts = PiperVoice.load(str(path))
        return self._tts

    def speak_wav(self, text: str) -> bytes:
        buf = io.BytesIO()
        with self._lock, wave.open(buf, "wb") as w:
            self._tts_voice().synthesize_wav(text, w)
        return buf.getvalue()

    def speak(self, text: str, fmt: str = "ogg") -> tuple[bytes, str]:
        """→ (аудио, mime). ogg/opus — для Telegram, mp3 — для iPhone и браузера, wav — как есть."""
        wav = self.speak_wav(text)
        if fmt == "wav":
            return wav, "audio/wav"
        if fmt == "mp3":
            return ffmpeg(wav, ["-codec:a", "libmp3lame", "-q:a", "4", "-f", "mp3"]), "audio/mpeg"
        return ffmpeg(wav, ["-codec:a", "libopus", "-b:a", "32k", "-f", "ogg"]), "audio/ogg"
