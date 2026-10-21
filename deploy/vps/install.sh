#!/bin/bash
# Установка полного Джарвиса на чистый Ubuntu 22.04/24.04 (от root):
#   curl -fsSL https://raw.githubusercontent.com/lilcryyw/Agent/claude/jarvis-cogmem/deploy/vps/install.sh | bash
# Нужно: 6+ ГБ памяти, 4 ядра, 40+ ГБ диска. Ключи скрипт спрашивает сам и кладёт только в /opt/jarvis/.env.
set -euo pipefail
REPO=${JARVIS_REPO:-https://github.com/lilcryyw/Agent.git}
BRANCH=${JARVIS_BRANCH:-claude/jarvis-cogmem}
ask() { local v; read -r -p "$1: " v </dev/tty; echo "$v"; }

echo "== Установка Джарвиса =="
apt-get update -y && apt-get install -y git curl ca-certificates
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
# Файл подкачки — запас на пики памяти (модели ~5 ГБ).
if [ ! -f /swapfile ] && [ "$(free -m | awk '/Mem:/{print $2}')" -lt 12000 ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
if [ -d /opt/jarvis/.git ]; then git -C /opt/jarvis pull --ff-only; else git clone -b "$BRANCH" "$REPO" /opt/jarvis; fi
cd /opt/jarvis

if [ ! -f .env ]; then
  KEY=$(ask "Ключ ProxyAPI (sk-…) или Anthropic")
  NAME=$(ask "Как Джарвису к тебе обращаться")
  TZ_=$(ask "Часовой пояс [Europe/Paris]"); TZ_=${TZ_:-Europe/Paris}
  BASE=$(ask "Адрес API [https://api.proxyapi.ru] (для ключа Anthropic — оставь пустым и напиши -)")
  [ -z "$BASE" ] && BASE=https://api.proxyapi.ru; [ "$BASE" = "-" ] && BASE=""
  IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
  DOMAIN=$(ask "Домен сервера [$(echo "$IP" | tr . -).sslip.io]"); DOMAIN=${DOMAIN:-$(echo "$IP" | tr . -).sslip.io}
  SITE=$(ask "Адрес веб-приложения на Cloudflare, если есть [пусто]")
  OWNER_TOKEN="jv_$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)"
  umask 077
  cat > .env <<ENV
ANTHROPIC_API_KEY=$KEY
${BASE:+ANTHROPIC_BASE_URL=$BASE}
JARVIS_OWNER_ID=owner
JARVIS_OWNER_NAME="$NAME"
JARVIS_OWNER_TZ=$TZ_
JARVIS_BRAIN_MODEL=claude-sonnet-5-5
JARVIS_SUBCONSCIOUS_MODEL=claude-haiku-5-5
JARVIS_MONTHLY_BUDGET_USD=10
JARVIS_TURN_BUDGET_USD=0.5
JARVIS_DOMAIN=$DOMAIN
JARVIS_WORKSHOP_TOKEN=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)
JARVIS_OWNER_TOKEN=$OWNER_TOKEN
${SITE:+JARVIS_WEBAPP_URL=$SITE}
${SITE:+JARVIS_CORS_ORIGINS=$SITE}
ENV
fi
cd deploy && docker compose --env-file ../.env up -d --build
. ../.env
echo
echo "Готово. Первый запуск 10–20 минут (скачиваются модели). Проверка: https://$JARVIS_DOMAIN/api/health"
echo "Приложение: https://$JARVIS_DOMAIN/app/#t=$JARVIS_OWNER_TOKEN   (ссылка с ключом — никому не давай)"
echo "Журнал: cd /opt/jarvis/deploy && docker compose logs -f jarvis"
