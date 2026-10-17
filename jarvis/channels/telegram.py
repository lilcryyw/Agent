"""Telegram-канал (вспомогательный: для отладки и текстового общения).

Доступ — только по белому списку: JARVIS_TELEGRAM_USERS="123456789:owner,987654321:mama".
Все остальные сообщения игнорируются. Напоминания приходят сюда же.

Запуск:  python -m jarvis.channels.telegram
"""

from __future__ import annotations

import asyncio
import logging

from jarvis.runtime import Jarvis

log = logging.getLogger(__name__)


async def run(j: Jarvis | None = None) -> None:
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import Command
    from aiogram.types import BufferedInputFile, Message

    j = j or Jarvis()
    if not j.s.telegram_token:
        raise SystemExit("Нужен TELEGRAM_BOT_TOKEN")
    if not j.s.telegram_users:
        raise SystemExit("Нужен JARVIS_TELEGRAM_USERS (кто может говорить с Джарвисом)")
    bot = Bot(j.s.telegram_token)
    dp = Dispatcher()
    tg_of = {pid: tg for tg, pid in j.s.telegram_users.items()}
    loop = asyncio.get_running_loop()

    def notify(person_id: str, text: str) -> None:
        tg = tg_of.get(person_id)
        if tg:
            asyncio.run_coroutine_threadsafe(bot.send_message(tg, "🔔 " + text), loop)

    j.on_notify(notify)
    j.start_background()  # повторный вызов безопасен: шлюз и API запускаются один раз

    def person_of(msg: Message) -> str | None:
        return j.s.telegram_users.get(msg.from_user.id) if msg.from_user else None

    @dp.message(Command("memory"))
    async def stats(msg: Message) -> None:
        if person_of(msg):
            await msg.answer(f"{j.memory.stats()}\nрасход: ${j.memory.spend_usd():.3f}")

    @dp.message(Command("profile"))
    async def profile(msg: Message) -> None:
        pid = person_of(msg)
        if pid:
            await msg.answer(j.memory.core_profile(pid))

    @dp.message(Command("secret"))
    async def secret(msg: Message) -> None:
        """/secret имя значение — положить в сейф; сообщение с секретом сразу удаляется из чата."""
        if not person_of(msg):
            return
        parts = (msg.text or "").split(maxsplit=2)
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001 — нет прав удалить: всё равно сохраняем
            pass
        if len(parts) < 3:
            await bot.send_message(msg.chat.id, "Формат: /secret имя значение")
            return
        j.vault.set(parts[1], parts[2])
        await bot.send_message(msg.chat.id, f"🔐 Секрет «{parts[1]}» в сейфе. Сообщение с ним удалено.")

    @dp.message(Command("keys"))
    async def keys(msg: Message) -> None:
        pid = person_of(msg)
        if pid:
            await msg.answer("\n".join(j.keys.lines(pid)) or "Ключей нет.")

    @dp.message(Command("token"))
    async def token(msg: Message) -> None:
        """Токен для iPhone (Команды Siri) и веб-приложения."""
        pid = person_of(msg)
        if pid:
            from jarvis.channels.http_api import create_token

            t = create_token(j.memory, pid, "telegram")
            await msg.answer(f"Токен для iPhone: {t}\nВставь его в Команду «Джарвис» (см. docs/iphone.md). "
                             "Никому не показывай.")

    @dp.message(F.voice | F.audio)
    async def voice(msg: Message) -> None:
        pid = person_of(msg)
        if not pid:
            return
        if j.voice is None:
            await msg.answer("Голос на сервере не настроен (pip install '.[voice]' и ffmpeg). Напиши текстом 🙏")
            return
        await bot.send_chat_action(msg.chat.id, "record_voice")
        f = await bot.get_file((msg.voice or msg.audio).file_id)
        data = (await bot.download_file(f.file_path)).read()
        try:
            pcm = await asyncio.to_thread(j.voice.pcm16k, data)
            heard = await asyncio.to_thread(j.voice.transcribe, data, pcm=pcm)
            if heard:
                j.enroll_voice(pid, pcm)  # личный Telegram: голос точно этого человека
            if not heard:
                await msg.answer("Не расслышал, повтори, пожалуйста.")
                return
            r = await asyncio.to_thread(j.brain.handle, pid, heard, channel="voice")
            audio, _ = await asyncio.to_thread(j.voice.speak, r.text, "ogg")
            await msg.answer_voice(BufferedInputFile(audio, "jarvis.ogg"), caption=r.text[:1000])
        except Exception:  # noqa: BLE001
            log.exception("ошибка голосового хода")
            await msg.answer("Не получилось обработать голосовое, попробуй ещё раз.")

    @dp.message(F.text)
    async def text(msg: Message) -> None:
        pid = person_of(msg)
        if pid is None:
            log.warning("сообщение от незнакомого telegram id %s — игнорирую", msg.from_user and msg.from_user.id)
            return
        await bot.send_chat_action(msg.chat.id, "typing")
        try:
            r = await asyncio.to_thread(j.brain.handle, pid, msg.text, channel="telegram")
            await msg.answer(r.text)
        except Exception:  # noqa: BLE001
            log.exception("ошибка хода")
            await msg.answer("Что-то пошло не так, попробуй ещё раз через минуту.")

    try:
        await dp.start_polling(bot)
    finally:
        j.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
