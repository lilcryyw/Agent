#!/bin/bash
# Работа сервера на телефоне: входная дверь (Caddy) + туннель Cloudflare + Джарвис. Всё перезапускается само.
cd /opt/jarvis
set -a; . ./.env; set +a
export JARVIS_DB=/opt/jarvis/data/jarvis.db PORT=7860
mkdir -p data logs
URL_FILE=data/public_url

caddy_loop() { while true; do bin/caddy run --config deploy/hf/Caddyfile --adapter caddyfile >> logs/caddy.log 2>&1; sleep 3; done; }

tunnel_loop() {
  while true; do
    : > logs/tunnel.log
    bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:7860 >> logs/tunnel.log 2>&1 &
    pid=$!
    url=""
    for _ in $(seq 60); do
      url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' logs/tunnel.log | head -1 || true)
      [ -n "$url" ] && break; sleep 1
    done
    if [ -n "$url" ]; then
      echo "$url" > "$URL_FILE"
      echo "$(date) новый адрес: $url"
      # Сайт на Cloudflare узнаёт новый адрес телефона.
      JARVIS_API_BASE="$url" bash deploy/cloudflare/deploy.sh >> logs/site.log 2>&1 || echo "не удалось обновить сайт"
    fi
    wait $pid; sleep 5
  done
}

caddy_loop &
tunnel_loop &
for _ in $(seq 90); do [ -s "$URL_FILE" ] && break; sleep 1; done
export JARVIS_DOMAIN="$(sed 's#https://##' "$URL_FILE" 2>/dev/null)"
export JARVIS_DEVICES_URL="wss://$JARVIS_DOMAIN/devices"
echo "Ссылка для владельца: ${JARVIS_WEBAPP_URL:-$(cat $URL_FILE)/app/}#t=${JARVIS_OWNER_TOKEN}"
while true; do
  .venv/bin/python -m jarvis.server >> logs/jarvis.log 2>&1
  echo "$(date) Джарвис остановился — перезапуск через 5 с"; sleep 5
done
