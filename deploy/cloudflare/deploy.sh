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
: "${CLOUDFLARE_API_TOKEN:?нужен CLOUDFLARE_API_TOKEN}"
: "${CLOUDFLARE_ACCOUNT_ID:?нужен CLOUDFLARE_ACCOUNT_ID}"
: "${JARVIS_API_BASE:?нужен JARVIS_API_BASE, например https://jarvis.example.com}"
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID
PROJECT="${CLOUDFLARE_PROJECT:-jarvis-app}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../../jarvis/channels/webapp"
OUT="$(mktemp -d)"
cp -r "$SRC"/. "$OUT"/
# Адрес сервера — в отдельный файл, чтобы его можно было менять без пересборки.
printf 'window.JARVIS_API_BASE = "%s";\n' "${JARVIS_API_BASE%/}" > "$OUT/config.js"

# Проект создаётся один раз; повторный вызов безвреден.
npx --yes wrangler@3 pages project create "$PROJECT" --production-branch main >/dev/null 2>&1 || true
npx --yes wrangler@3 pages deploy "$OUT" --project-name "$PROJECT" --branch main --commit-dirty=true

echo
echo "Готово. Адрес приложения: https://$PROJECT.pages.dev"
echo "На сервере Джарвиса добавь в .env:"
echo "  JARVIS_CORS_ORIGINS=https://$PROJECT.pages.dev"
echo "  JARVIS_WEBAPP_URL=https://$PROJECT.pages.dev"
echo "и перезапусти сервер: docker compose --env-file ../.env up -d"
