# Образ для бесплатного Hugging Face Space (Docker, 2 ядра, 16 ГБ памяти). Снаружи открыт один порт 7860:
# Caddy внутри раздаёт /app, /api, /call и /devices по процессам Джарвиса.
FROM python:3.12-slim
ARG CADDY=2.10.2
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates bubblewrap \
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
# Мастерская здесь — в том же контейнере, что и Джарвис. Её код не должен видеть базу памяти и сейф:
#  • bubblewrap (если платформа разрешает пространства имён) — своя «картина мира» без /app/data;
#  • иначе Landlock (ядро 5.13+, без root) — /app/data закрыта на чтение, писать можно только в мастерскую;
#  • процесс сервера «недампируемый» — /proc/<pid>/environ с ключами API не читается.
# Сервер работает не от root (USER user) — иначе последние две защиты не действуют.
ENV JARVIS_DB=/app/data/jarvis.db PORT=7860 JARVIS_WORKSHOP_HIDE=/app/data
EXPOSE 7860
CMD ["bash", "deploy/hf/start.sh"]
