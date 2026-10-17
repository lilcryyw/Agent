// Адрес сервера Джарвиса. Пусто — приложение работает с тем же сервером, с которого открыто.
// Для публикации на Cloudflare Pages скрипт deploy/cloudflare/deploy.sh перезапишет этот файл.
window.JARVIS_API_BASE = "";
// Адрес живого разговора (WebSocket). Пусто — тот же сервер, путь /call (так настроен Caddy).
window.JARVIS_CALL_URL = window.JARVIS_CALL_URL || "";
