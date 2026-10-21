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
# local — GigaAM на сервере (лучше для русского, ~1 ГБ памяти); cloudflare — Whisper в Workers AI (без памяти).
STT_BACKEND = os.environ.get("JARVIS_STT", "local")
# piper — голос Джарвиса синтезирует сервер; client — сервер присылает текст, а говорит сам телефон/браузер
# (для слабых бесплатных серверов, где синтез идёт медленнее речи).
TTS_BACKEND = os.environ.get("JARVIS_TTS", "piper")
# Звучание «в стиле JARVIS»: чуть ниже тон, лёгкий металлический отзвук, ровная громкость (off — чистый голос).
TTS_FX = os.environ.get("JARVIS_TTS_FX", "jarvis")
FX = {"jarvis": "asetrate={sr}*0.93,aresample={sr},atempo=1.05,aecho=0.8:0.6:14:0.22,highpass=f=90,"
                "lowpass=f=8500,acompressor=threshold=0.1:ratio=3"}
TTS_VOICE = os.environ.get("JARVIS_TTS_VOICE", "ru_RU-denis-medium")  # ещё: ru_RU-irina-medium, -denis-, -ruslan-
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
        # Отдельные замки: в живом разговоре Джарвис слышит (перебивание), пока говорит.
        self._stt_lock = threading.Lock()
        self._tts_lock = threading.Lock()

    # --- распознавание ---
    def _stt_model(self):
        if self._stt is None:
            import onnx_asr

            log.info("загружаю модель распознавания %s", STT_MODEL)
            # JARVIS_STT_QUANT=int8 — сжатая модель: ~550 МБ памяти вместо ~1 ГБ, точность почти та же.
            quant = os.environ.get("JARVIS_STT_QUANT") or None
            self._stt = onnx_asr.load_model(STT_MODEL, quantization=quant) if quant else onnx_asr.load_model(STT_MODEL)
        return self._stt

    @staticmethod
    def pcm16k(audio: bytes) -> bytes:
        """Любой аудиоформат → PCM 16 кГц моно int16 (для распознавания и узнавания голоса)."""
        return ffmpeg(audio, ["-ar", "16000", "-ac", "1", "-f", "s16le"])

    def transcribe(self, audio: bytes, *, pcm: bytes | None = None) -> str:
        """Любой аудиоформат → текст."""
        # ffmpeg в поток пишет WAV без длины — берём «сырой» звук и собираем WAV сами.
        pcm = pcm if pcm is not None else self.pcm16k(audio)
        if STT_BACKEND == "cloudflare":
            return self._transcribe_cloudflare(pcm)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            with wave.open(f, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(pcm)
        try:
            with self._stt_lock:
                text = self._stt_model().recognize(f.name)
        finally:
            os.unlink(f.name)
        return (text or "").strip()

    @staticmethod
    def _transcribe_cloudflare(pcm: bytes) -> str:
        """Распознавание в Cloudflare Workers AI (Whisper) — для серверов, где модель GigaAM не помещается."""
        import base64
        import json

        if len(pcm) < 16000:  # меньше полсекунды — нечего распознавать
            return ""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm)
        url = (f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
               "/ai/run/@cf/openai/whisper-large-v3-turbo")
        body = json.dumps({"audio": base64.b64encode(buf.getvalue()).decode(), "language": "ru"}).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        return ((data.get("result") or {}).get("text") or "").strip()

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

    @property
    def can_speak(self) -> bool:
        return TTS_BACKEND != "client"

    def speak_wav(self, text: str) -> bytes:
        if not self.can_speak:
            raise RuntimeError("синтез речи на сервере выключен (JARVIS_TTS=client)")
        buf = io.BytesIO()
        with self._tts_lock, wave.open(buf, "wb") as w:
            self._tts_voice().synthesize_wav(text, w)
        return buf.getvalue()

    def speak(self, text: str, fmt: str = "ogg") -> tuple[bytes, str]:
        """→ (аудио, mime). ogg/opus — для Telegram, mp3 — для iPhone и браузера, wav — как есть."""
        wav = self.speak_wav(text)
        fx = FX.get(TTS_FX)
        if fx:
            with wave.open(io.BytesIO(wav)) as w:
                sr = w.getframerate()
            wav = ffmpeg(wav, ["-af", fx.format(sr=sr), "-f", "wav"])
        if fmt == "wav":
            return wav, "audio/wav"
        if fmt == "mp3":
            return ffmpeg(wav, ["-codec:a", "libmp3lame", "-q:a", "4", "-f", "mp3"]), "audio/mpeg"
        return ffmpeg(wav, ["-codec:a", "libopus", "-b:a", "32k", "-f", "ogg"]), "audio/ogg"
