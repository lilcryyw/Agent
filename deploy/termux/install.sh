#!/data/data/com.termux/files/usr/bin/bash
# Джарвис на Android-телефоне (сервер в кармане). Запуск в Termux:
#   curl -fsSL https://jarvis-app-b4p.pages.dev/install.sh | bash
# Нужно: Termux из F-Droid (https://f-droid.org/packages/com.termux/), Wi-Fi, телефон на зарядке.
# Скрипт спросит токен Hugging Face (hf_…): по нему он сам достанет ключи и настройки из твоего приватного хранилища.
set -euo pipefail

echo "== Джарвис: установка на телефон =="
if [ -z "${HF_TOKEN:-}" ]; then
  read -r -p "Токен Hugging Face (hf_…): " HF_TOKEN </dev/tty
fi
pkg update -y
pkg install -y proot-distro curl termux-api || pkg install -y proot-distro curl
proot-distro install debian 2>/dev/null || echo "Debian уже установлен"

# Код и настройки лежат в твоём приватном хранилище Hugging Face (<имя>/jarvis-data).
USER_NAME=$(curl -fsS -H "Authorization: Bearer $HF_TOKEN" https://huggingface.co/api/whoami-v2 \
  | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
[ -n "$USER_NAME" ] || { echo "Токен не подошёл — проверь его на huggingface.co/settings/tokens"; exit 1; }
curl -fL -H "Authorization: Bearer $HF_TOKEN" -o "$HOME/jarvis-code.tar.gz" \
  "https://huggingface.co/datasets/$USER_NAME/jarvis-data/resolve/main/code.tar.gz"
proot-distro login debian --shared-tmp -- env HF_TOKEN="$HF_TOKEN" bash -c \
  'mkdir -p /opt/jarvis && tar xzf /data/data/com.termux/files/home/jarvis-code.tar.gz -C /opt/jarvis \
   && bash /opt/jarvis/deploy/termux/debian-setup.sh'

# Запуск одной командой и автозапуск после перезагрузки телефона (если стоит Termux:Boot).
cat > "$HOME/jarvis-start.sh" <<'START'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null || true   # не даём Android усыпить процессор
exec proot-distro login debian --shared-tmp -- bash /opt/jarvis/deploy/termux/run.sh
START
chmod +x "$HOME/jarvis-start.sh"
mkdir -p "$HOME/.termux/boot"
printf '#!/data/data/com.termux/files/usr/bin/bash\nnohup %s/jarvis-start.sh > %s/jarvis.log 2>&1 &\n' "$HOME" "$HOME" \
  > "$HOME/.termux/boot/start-jarvis"
chmod +x "$HOME/.termux/boot/start-jarvis"

echo
echo "Готово. Запускаю Джарвиса (первый запуск 5–15 минут: скачиваются модели речи и смысла)."
echo "Дальше запуск: ~/jarvis-start.sh   (или сам после перезагрузки — с приложением Termux:Boot)"
exec "$HOME/jarvis-start.sh"
