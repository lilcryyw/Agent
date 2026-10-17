# Веб-приложение на Cloudflare Pages

Приложение — статические файлы (`jarvis/channels/webapp`). Cloudflare отдаёт их по HTTPS бесплатно.
Сам «мозг» остаётся на вашем сервере: приложение обращается к нему по `JARVIS_API_BASE`.

## 1. Токен и ID аккаунта
1. dash.cloudflare.com → **My Profile → API Tokens → Create Token** → шаблон «Edit Cloudflare Pages»
   (или право Pages: Edit). Скопируй токен.
2. ID аккаунта — на главной странице dash.cloudflare.com (справа, «Account ID»).

## 2. Публикация
```
CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… JARVIS_API_BASE=https://jarvis.твой-домен \
  bash deploy/cloudflare/deploy.sh
```
Адрес появится в конце: `https://jarvis-app.pages.dev`.

## 3. Разрешить приложению говорить с сервером
В `.env` на сервере Джарвиса:
```
JARVIS_CORS_ORIGINS=https://jarvis-app.pages.dev
JARVIS_WEBAPP_URL=https://jarvis-app.pages.dev
```
и `docker compose --env-file ../.env up -d`. Без `JARVIS_CORS_ORIGINS` браузер не пустит запросы с другого домена.

## Важно
- Пока сервер Джарвиса не развёрнут на домене, приложение откроется, но разговаривать не сможет.
- Ссылки для родных (`app_link`) будут вести на Cloudflare, если задан `JARVIS_WEBAPP_URL`.
