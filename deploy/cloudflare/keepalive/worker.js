// «Будильник» для бесплатного сервера (Hugging Face Space засыпает после 48 ч без посещений):
// раз в 30 минут заглядывает на сервер — Джарвис не спит, напоминания и инициатива срабатывают вовремя.
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(fetch(env.TARGET + "/api/health", { headers: { "User-Agent": "jarvis-keepalive" } }));
  },
};
