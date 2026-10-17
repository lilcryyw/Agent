FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/app/data/models

COPY pyproject.toml README.md ./
COPY cogmem ./cogmem
COPY jarvis ./jarvis
COPY evals ./evals
COPY clients ./clients
RUN pip install --no-cache-dir -e '.[embeddings,telegram,devices,voice,backup]'

VOLUME ["/app/data"]
ENV HF_HOME=/app/data/models/hf
CMD ["python", "-m", "jarvis.server"]
