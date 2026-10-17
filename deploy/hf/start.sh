#!/usr/bin/env bash
# Запуск в Space: входная дверь (Caddy) + Джарвис. Если Джарвис упал — контейнер перезапустится целиком.
set -e
mkdir -p /app/data
caddy run --config /app/deploy/hf/Caddyfile --adapter caddyfile &
exec python -m jarvis.server
