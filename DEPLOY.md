# Установка Джарвиса на сервер (полная версия)

Всё работает на самом сервере: смысл текста (e5-large), распознавание речи (GigaAM), голос (Piper), память.
Нужен сервер: **Ubuntu 22.04/24.04, 4 ядра, 6+ ГБ памяти, 40+ ГБ диска**. Свой домен не обязателен.

## Одной командой (на сервере, от root)
```bash
curl -fsSL https://raw.githubusercontent.com/lilcryyw/Agent/claude/jarvis-cogmem/deploy/vps/install.sh | bash
```
Скрипт ставит Docker, файл подкачки, скачивает код и спрашивает:
- ключ ProxyAPI (`sk-…`, https://console.proxyapi.ru) — или ключ Anthropic;
- как обращаться к владельцу, часовой пояс;
- домен (Enter — бесплатный `<ip>.sslip.io` с HTTPS);
- адрес веб-приложения на Cloudflare Pages, если есть (например `https://jarvis-app-b4p.pages.dev`).

В конце печатает ссылку владельца `https://<домен>/app/#t=jv_…`. Первый запуск 10–20 минут: качаются модели (~4 ГБ).

## Проверка
- `curl https://<домен>/api/health` → `{"ok": true}`
- открыть ссылку владельца на телефоне → 📞 → сказать фразу → Джарвис отвечает голосом.
- журнал: `cd /opt/jarvis/deploy && docker compose logs -f jarvis`

## Важно
- Ключи хранятся только в `/opt/jarvis/.env` на сервере (в git их нет и быть не должно).
- Порты 80 и 443 должны быть открыты (HTTPS выдаёт Caddy сам).
- Обновление: `cd /opt/jarvis && git pull && cd deploy && docker compose --env-file ../.env up -d --build`.
- Память — в `/opt/jarvis/data` (бэкапить). Подробнее: `docs/setup.md`, `docs/status.md`.
- Веб-приложение на Cloudflare переключить на сервер:
  `JARVIS_API_BASE=https://<домен> bash deploy/cloudflare/deploy.sh` (нужны ключи Cloudflare в `deploy/cloudflare/.secrets`).
