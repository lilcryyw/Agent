#!/bin/bash
# Внутри Debian (proot): зависимости, код, ключи из приватного хранилища Hugging Face.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
BRANCH="${BRANCH:-claude/jarvis-cogmem}"
apt-get update
apt-get install -y --no-install-recommends python3 python3-venv python3-pip git curl ca-certificates ffmpeg \
  nodejs npm
ARCH=$(uname -m); case "$ARCH" in aarch64|arm64) A=arm64;; x86_64) A=amd64;; armv7l) A=arm;; *) A=$ARCH;; esac

if [ -d /opt/jarvis/.git ]; then git -C /opt/jarvis pull --ff-only || true
else git clone -b "$BRANCH" --depth 1 https://github.com/lilcryyw/Agent.git /opt/jarvis; fi
cd /opt/jarvis
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[embeddings,devices,voice,backup]'

mkdir -p bin
[ -x bin/caddy ] || curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v2.10.2/caddy_2.10.2_linux_${A}.tar.gz" \
  | tar xz -C bin caddy
[ -x bin/cloudflared ] || { curl -fsSL -o bin/cloudflared \
  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${A}" && chmod +x bin/cloudflared; }

# Ключи и настройки: из приватного датасета <имя>/jarvis-data (туда их положил Джарвис при подготовке).
HF_TOKEN="$HF_TOKEN" .venv/bin/python deploy/termux/fetch_config.py
echo "Установка в Debian завершена."
