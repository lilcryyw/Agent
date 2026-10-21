"""Telegram-канал (вспомогательный: для отладки и текстового общения).

Доступ — только по белому списку: JARVIS_TELEGRAM_USERS="123456789:owner,987654321:mama".
Все остальные сообщения игнорируются. Напоминания приходят сюда же.
Фото и документы сохраняются на диск Джарвиса (shared/inbox/<человек>/) — он их видит (file view);
файлы от Джарвиса (file send) приходят сюда же. «Стоп» останавливает текущую работу сразу.

Запуск:  python -m jarvis.channels.telegram
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

from jarvis.runtime import Jarvis

log = logging.getLogger(__name__)
TG_LIMIT = 4096
MARK = re.compile(r"\[\[ярлык:([^|\]]+)\|([^|\]]+)(?:\|([^\]]*))?\]\]")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def split_message(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Длинный ответ — на части по абзацам/строкам/словам (у Telegram предел 4096 символов)."""
    text = text or "…"
    parts = []
    while len(text) > limit:
        cut = max(text.rfind("\n\n", 0, limit), text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    parts.append(text)
    return [p for p in parts if p]


def readable(text: str) -> str:
    """Кнопки Команд iPhone ([[ярлык:…]]) Telegram не откроет — показываем их понятным текстом."""
    return MARK.sub(lambda m: f"«{m.group(2)}» (Команда iPhone «{m.group(1)}»"
                              + (f", ввод: {m.group(3)}" if m.group(3) else "") + ")", text)


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w.\-]+", "_", name or "file", flags=re.UNICODE).strip("._") or "file"
    return name[:80]


STATUS: dict = {"running": False, "bot": "", "error": ""}  # для органа telegram (видно Джарвису)


def _links(j) -> dict[int, str]:
    db = j.memory.ctx.db
    db.execute("CREATE TABLE IF NOT EXISTS telegram_links (tg_id INTEGER PRIMARY KEY, person_id TEXT NOT NULL)")
    return {r["tg_id"]: r["person_id"] for r in db.query("SELECT tg_id, person_id FROM telegram_links")}


async def run(j: Jarvis | None = None, *, token: str | None = None, standalone: bool = True) -> None:
    import os

    from aiogram import Bot, Dispatcher, F
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer
    from aiogram.filters import Command, CommandStart
    from aiogram.types import BufferedInputFile, Message

    j = j or Jarvis()
    token = token or j.s.telegram_token
    if not token:
        raise SystemExit("Нужен TELEGRAM_BOT_TOKEN")
    # Из России api.telegram.org бывает недоступен: можно указать прокси или свой адрес Bot API.
    session = AiohttpSession(proxy=os.environ["TELEGRAM_PROXY"]) if os.environ.get("TELEGRAM_PROXY") else AiohttpSession()
    if os.environ.get("TELEGRAM_API_BASE"):
        session.api = TelegramAPIServer.from_base(os.environ["TELEGRAM_API_BASE"])
    bot = Bot(token, session=session)
    me = await bot.get_me()  # таймаут/ошибка здесь — значит Telegram недоступен с сервера
    STATUS.update(running=True, bot=me.username or "", error="")
    dp = Dispatcher()
    users = dict(j.s.telegram_users)
    users.update(_links(j))
    tg_of = {pid: tg for tg, pid in users.items()}
    loop = asyncio.get_running_loop()

    async def send_text(chat_id: int, text: str) -> None:
        for part in split_message(readable(text)):
            await bot.send_message(chat_id, part)

    def notify(person_id: str, text: str) -> None:
        tg = tg_of.get(person_id)
        if not tg:
            return
        fut = asyncio.run_coroutine_threadsafe(send_text(tg, "🔔 " + text), loop)

        def done(f):  # напоминание не должно потеряться молча
            exc = f.exception()
            if exc is not None:
                log.error("не удалось доставить напоминание %s в Telegram: %s — повторяю", person_id, exc)
                asyncio.run_coroutine_threadsafe(_retry(tg, "🔔 " + text), loop)

        fut.add_done_callback(done)

    async def _retry(chat_id: int, text: str) -> None:
        for delay in (5, 30, 120):
            await asyncio.sleep(delay)
            try:
                await send_text(chat_id, text)
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("повтор доставки не удался: %s", exc)
        log.error("напоминание так и не доставлено: %s", text[:200])

    def send_file(person_id: str, path: Path, caption: str) -> bool:
        """Файл от Джарвиса (орган file send) — в личный чат человека."""
        from aiogram.types import FSInputFile

        tg = tg_of.get(person_id)
        if not tg:
            return False
        cap = (caption or "")[:1000] or None
        if path.suffix.lower() in IMAGE_EXT and path.stat().st_size < 10_000_000:
            coro = bot.send_photo(tg, FSInputFile(path), caption=cap)
        else:
            coro = bot.send_document(tg, FSInputFile(path), caption=cap)
        asyncio.run_coroutine_threadsafe(coro, loop).result(120)
        return True

    j.on_notify(notify)
    if hasattr(j.tools, "file_senders"):
        j.tools.file_senders.append(send_file)
    j.start_background()  # повторный вызов безопасен: шлюз и API запускаются один раз

    def person_of(msg: Message) -> str | None:
        return users.get(msg.from_user.id) if msg.from_user else None

    @dp.message(CommandStart())
    async def start(msg: Message) -> None:
        """Привязка: ссылка t.me/<бот>?start=<код> от Джарвиса → этот Telegram становится каналом человека."""
        from jarvis.channels.http_api import person_for_token

        code = (msg.text or "").split(maxsplit=1)[1].strip() if len((msg.text or "").split()) > 1 else ""
        pid = person_for_token(j.memory, code) if code else None
        if pid is None:
            if person_of(msg):
                await msg.answer("Я на связи. Пиши или присылай голосовые.")
            return  # чужим — молчим
        j.memory.ctx.db.execute("INSERT OR REPLACE INTO telegram_links(tg_id, person_id) VALUES (?,?)",
                                (msg.from_user.id, pid))
        users[msg.from_user.id] = pid
        tg_of[pid] = msg.from_user.id
        name = (j.memory.person(pid) or {}).get("name", "")
        await msg.answer(f"Готово{', ' + name if name else ''}! Теперь пиши мне здесь или присылай голосовые.")

    def stop_reply(pid: str, text: str) -> str | None:
        """«Стоп» — сразу, без очереди к «сознанию»: прервать ход и фоновые задачи."""
        from jarvis.brain.agent import is_stop

        if not is_stop(text):
            return None
        stopped = bool(getattr(j.brain, "cancel", None) and j.brain.cancel(pid))
        if hasattr(j.tools, "cancel_all"):
            stopped = j.tools.cancel_all(pid) > 0 or stopped
        return "Остановил." if stopped else "Хорошо, ничего не делаю."

    async def reply(msg: Message, text: str) -> None:
        if not (text or "").strip():
            return  # Джарвис решил промолчать
        for part in split_message(readable(text)):
            await msg.answer(part)

    def inbox_dir(pid: str) -> tuple[Path, Path]:
        shared = Path(getattr(j.workshop, "shared", "data/workshop/shared"))
        d = shared / "inbox" / pid
        d.mkdir(parents=True, exist_ok=True)
        return shared, d

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
            stop = stop_reply(pid, heard)
            if stop:
                await msg.answer(stop)
                return
            r = await asyncio.to_thread(j.brain.handle, pid, heard, channel="voice")
            audio, _ = await asyncio.to_thread(j.voice.speak, r.text, "ogg")
            await msg.answer_voice(BufferedInputFile(audio, "jarvis.ogg"), caption=readable(r.text)[:1000])
            if len(r.text) > 1000:
                await reply(msg, r.text)
        except Exception:  # noqa: BLE001
            log.exception("ошибка голосового хода")
            await msg.answer("Не получилось обработать голосовое, попробуй ещё раз.")

    @dp.message(F.text)
    async def text(msg: Message) -> None:
        pid = person_of(msg)
        if pid is None:
            log.warning("сообщение от незнакомого telegram id %s — игнорирую", msg.from_user and msg.from_user.id)
            return
        stop = stop_reply(pid, msg.text or "")
        if stop:
            await msg.answer(stop)
            return
        await bot.send_chat_action(msg.chat.id, "typing")
        try:
            r = await asyncio.to_thread(j.brain.handle, pid, msg.text, channel="telegram")
            await reply(msg, r.text)
        except Exception:  # noqa: BLE001
            log.exception("ошибка хода")
            await msg.answer("Что-то пошло не так, попробуй ещё раз через минуту.")

    @dp.message(F.photo | F.document)
    async def incoming_file(msg: Message) -> None:
        """Фото и документы: на диск Джарвиса (inbox), а ему — что пришло и где лежит."""
        pid = person_of(msg)
        if not pid:
            return
        if msg.photo:
            item, name = msg.photo[-1], f"photo-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        else:
            item = msg.document
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_name(msg.document.file_name or 'file')}"
        if getattr(item, "file_size", 0) and item.file_size > 20_000_000:
            await msg.answer("Файл больше 20 МБ — Telegram не даёт боту его скачать. Пришли поменьше или ссылкой.")
            return
        await bot.send_chat_action(msg.chat.id, "typing")
        try:
            shared, d = inbox_dir(pid)
            f = await bot.get_file(item.file_id)
            data = (await bot.download_file(f.file_path)).read()
            (d / name).write_bytes(data)
            rel = (d / name).relative_to(shared).as_posix()
            kind = "фото" if msg.photo else "файл"
            text = (msg.caption or "").strip()
            note = (f"[Человек прислал {kind}: {rel} ({len(data) // 1024} КБ). Посмотреть — file view; "
                    f"в коде — $JARVIS_SHARED/{rel}.]")
            r = await asyncio.to_thread(j.brain.handle, pid, (text + "\n" + note).strip(), channel="telegram")
            await reply(msg, r.text)
        except Exception:  # noqa: BLE001
            log.exception("ошибка приёма файла")
            await msg.answer("Не получилось принять файл, попробуй ещё раз.")

    try:
        await dp.start_polling(bot, handle_signals=standalone)
    finally:
        STATUS["running"] = False
        if standalone:
            j.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
