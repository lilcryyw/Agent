#!/usr/bin/env bash
# Публикует веб-приложение Джарвиса на Cloudflare Pages (бесплатно, HTTPS из коробки).
#
# Нужно (один раз, в консоли Cloudflare):
#   CLOUDFLARE_API_TOKEN  — токен с правом «Cloudflare Pages: Edit»
#   CLOUDFLARE_ACCOUNT_ID — ID аккаунта (видно на главной странице dash.cloudflare.com)
#   JARVIS_API_BASE       — адрес сервера Джарвиса, например https://jarvis.example.com
# Необязательно:
#   CLOUDFLARE_PROJECT    — имя проекта (по умолчанию jarvis-app)
#
# Запуск:  CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… JARVIS_API_BASE=https://… bash deploy/cloudflare/deploy.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# Секреты можно положить в файл deploy/cloudflare/.secrets (он не попадает в git).
if [ -f "$HERE/.secrets" ]; then set -a; . "$HERE/.secrets"; set +a; fi
: "${CLOUDFLARE_API_TOKEN:?нужен CLOUDFLARE_API_TOKEN}"
: "${CLOUDFLARE_ACCOUNT_ID:?нужен CLOUDFLARE_ACCOUNT_ID}"
if [ -z "${JARVIS_API_BASE:-}" ]; then
  echo "ВНИМАНИЕ: JARVIS_API_BASE не задан — приложение опубликуется, но разговаривать не сможет,"
  echo "пока сервер Джарвиса не будет на домене. Потом перезапусти скрипт с адресом сервера."
fi
JARVIS_API_BASE="${JARVIS_API_BASE:-}"
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID
PROJECT="${CLOUDFLARE_PROJECT:-jarvis-app}"
SRC="$HERE/../../jarvis/channels/webapp"
OUT="$(mktemp -d)"
cp -r "$SRC"/. "$OUT"/
# Адрес сервера — в отдельный файл, чтобы его можно было менять без пересборки.
printf 'window.JARVIS_API_BASE = "%s";\n' "${JARVIS_API_BASE%/}" > "$OUT/config.js"

# Проект создаётся один раз; повторный вызов безвреден.
npx --yes wrangler@3 pages project create "$PROJECT" --production-branch main >/dev/null 2>&1 || true
npx --yes wrangler@3 pages deploy "$OUT" --project-name "$PROJECT" --branch main --commit-dirty=true

# Реальный адрес берём у Cloudflare: если короткое имя занято, он добавляет суффикс (jarvis-app-xxxx.pages.dev).
URL="$(curl -sS -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/$PROJECT" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["result"]; print("https://"+d["subdomain"])')"
echo
echo "Готово. Адрес приложения: $URL"
echo "На сервере Джарвиса добавь в .env:"
echo "  JARVIS_CORS_ORIGINS=$URL"
echo "  JARVIS_WEBAPP_URL=$URL"
echo "и перезапусти сервер: docker compose --env-file ../.env up -d"
