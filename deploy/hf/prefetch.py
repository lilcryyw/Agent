"""Скачать все модели при сборке образа: смысл (e5-large), распознавание (GigaAM), голос (Piper),
детектор речи (Silero) и узнавание голосов. Тогда после «сна» Space просыпается за минуту, а не за десять."""

import sys
import tempfile
from pathlib import Path

models = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/models")
models.mkdir(parents=True, exist_ok=True)

from cogmem.embed import FastEmbedder  # noqa: E402

FastEmbedder().embed(["проверка"])
print("смысл: ok")

import onnx_asr  # noqa: E402

from jarvis.voice import STT_MODEL, Voice  # noqa: E402

onnx_asr.load_model(STT_MODEL)
v = Voice(models)
wav = v.speak_wav("Проверка голоса.")
print("распознавание и голос: ok,", len(wav), "байт")

from jarvis.voice.vad import silero_model  # noqa: E402

assert silero_model(models) is not None
print("детектор речи: ok")

from cogmem.clock import FakeClock  # noqa: E402
from cogmem.embed import HashEmbedder  # noqa: E402
from cogmem.memory import CognitiveMemory  # noqa: E402
from jarvis.voice.speakers import Speakers  # noqa: E402

Speakers(CognitiveMemory(embedder=HashEmbedder(), clock=FakeClock()), models)._extractor()
print("голоса: ok")
