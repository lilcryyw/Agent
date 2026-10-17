# Облегчённый Джарвис для бесплатного Render (512 МБ памяти, 0.1 ядра):
# смысл текста и распознавание речи — в Cloudflare Workers AI, голос — на телефоне (браузер),
# на сервере только детектор речи (Silero, 2 МБ). Наружу один порт $PORT (Caddy).
FROM python:3.12-slim
ARG CADDY=2.10.2
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY}/caddy_${CADDY}_linux_amd64.tar.gz" \
       | tar xz -C /usr/local/bin caddy
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 JARVIS_MODELS_DIR=/opt/models \
    JARVIS_EMBED_MODEL=@cf/baai/bge-m3 JARVIS_STT=cloudflare JARVIS_TTS=client \
    JARVIS_DB=/app/data/jarvis.db MALLOC_ARENA_MAX=2
COPY pyproject.toml README.md ./
COPY cogmem ./cogmem
COPY jarvis ./jarvis
COPY clients ./clients
COPY deploy/hf/Caddyfile deploy/hf/start.sh ./deploy/hf/
RUN pip install --no-cache-dir -e '.[devices,telegram,backup]' 'sherpa-onnx>=1.10' \
    && python -c "from jarvis.voice.vad import silero_model; assert silero_model('/opt/models')"
CMD ["bash", "deploy/hf/start.sh"]
