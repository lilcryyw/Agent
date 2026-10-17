#!/usr/bin/env bash
# Ставит на Cloudflare (бесплатно) Worker-«будильник», который раз в 30 минут будит сервер Джарвиса.
#   JARVIS_API_BASE=https://имя-jarvis.hf.space bash deploy/cloudflare/keepalive.sh
# Запасной вариант (сервер и сам себя будит). Нужны CLOUDFLARE_API_TOKEN (права Workers Scripts: Edit) и CLOUDFLARE_ACCOUNT_ID — как для deploy.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/.secrets" ]; then set -a; . "$HERE/.secrets"; set +a; fi
: "${CLOUDFLARE_API_TOKEN:?нужен CLOUDFLARE_API_TOKEN}"
: "${CLOUDFLARE_ACCOUNT_ID:?нужен CLOUDFLARE_ACCOUNT_ID}"
: "${JARVIS_API_BASE:?нужен JARVIS_API_BASE — адрес сервера}"
API="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/workers/scripts/jarvis-keepalive"
META=$(printf '{"main_module":"worker.js","compatibility_date":"2025-01-01","bindings":[{"type":"plain_text","name":"TARGET","text":"%s"}]}' "${JARVIS_API_BASE%/}")
curl -fsS -X PUT "$API" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -F "metadata=$META;type=application/json" \
  -F "worker.js=@$HERE/keepalive/worker.js;type=application/javascript+module" >/dev/null
curl -fsS -X PUT "$API/schedules" -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" --data '[{"cron":"*/30 * * * *"}]' >/dev/null
echo "Будильник поставлен: каждые 30 минут → ${JARVIS_API_BASE%/}/api/health"
