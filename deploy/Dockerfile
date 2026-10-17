FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/app/data/models

COPY pyproject.toml README.md ./
COPY cogmem ./cogmem
COPY jarvis ./jarvis
COPY evals ./evals
COPY clients ./clients
RUN pip install --no-cache-dir -e '.[embeddings,telegram,devices]'

VOLUME ["/app/data"]
CMD ["python", "-m", "jarvis.channels.telegram"]
