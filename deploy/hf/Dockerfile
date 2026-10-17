# Образ для бесплатного Hugging Face Space (Docker, 2 ядра, 16 ГБ памяти). Снаружи открыт один порт 7860:
# Caddy внутри раздаёт /app, /api, /call и /devices по процессам Джарвиса.
FROM python:3.12-slim
ARG CADDY=2.10.2
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY}/caddy_${CADDY}_linux_amd64.tar.gz" \
       | tar xz -C /usr/local/bin caddy && caddy version
# Hugging Face запускает контейнер от пользователя с uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/user \
    FASTEMBED_CACHE_PATH=/opt/models/fastembed HF_HOME=/opt/models/hf JARVIS_MODELS_DIR=/opt/models

COPY pyproject.toml README.md ./
COPY cogmem ./cogmem
COPY jarvis ./jarvis
COPY clients ./clients
COPY deploy/hf ./deploy/hf
RUN pip install --no-cache-dir -e '.[embeddings,telegram,devices,voice]' 'huggingface_hub>=0.30'
RUN python deploy/hf/prefetch.py /opt/models && chown -R user:user /app /opt/models

USER user
ENV JARVIS_DB=/app/data/jarvis.db PORT=7860
EXPOSE 7860
CMD ["bash", "deploy/hf/start.sh"]
