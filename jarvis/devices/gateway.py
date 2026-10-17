"""Шлюз устройств: WebSocket-сервер, к которому сами подключаются ПК и телефоны.

Устройство само звонит серверу (порты дома открывать не нужно). Протокол — JSON-сообщения:
  устройство → сервер: {"type":"pair","code":"ABCD-EFGH", ...описание}   — первое подключение по коду
                       {"type":"utterance","audio_b64":..}  — человек сказал «Джарвис, …» у этого устройства
                       {"type":"hello","device_id":..,"token":.., ...}  — обычное подключение
                       {"type":"result","id":..,"ok":..,"output":..,"image_b64":..}
                       {"type":"event","text":..,"trust":"observed"|"external"}  — что-то произошло на устройстве
  сервер → устройство: {"type":"welcome","device_id":..,"token":..}
                       {"type":"call","id":..,"action":"run"|"screenshot"|"input","args":{..}}
                       {"type":"say","text":..,"audio_b64":..}  — сказать вслух на устройстве (ответ или инициатива)
Описание: name, kind, languages, capabilities. GET /client.py — скачать клиента (для подключения нового устройства).
Токены хранятся только хешами; код подключения — одноразовый, живёт 15 минут.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
import threading
import uuid
from pathlib import Path
from typing import Any

from cogmem.memory import CognitiveMemory
from cogmem.types import Observation
from jarvis.devices import Device, DeviceHub, DeviceResult

log = logging.getLogger(__name__)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих O/0, I/1
PAIR_TTL = 15 * 60
MAX_MSG = 16 * 1024 * 1024
CLIENT_PATH = Path(__file__).resolve().parents[2] / "clients" / "device" / "jarvis_device.py"


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


_TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                     ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                      "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _slug(s: str) -> str:
    s = "".join(_TRANSLIT.get(ch, ch) for ch in s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:20] or "device"


class Gateway:
    def __init__(self, memory: CognitiveMemory, hub: DeviceHub, *, host: str = "0.0.0.0", port: int = 8765,
                 on_utterance=None, tts=None):
        self.m = memory
        # on_utterance(owner, device_id, audio) → (услышанный текст, ответ); tts(text) → wav
        self.on_utterance = on_utterance
        self.tts = tts
        self.hub = hub
        self.host, self.port = host, port
        self.loop: asyncio.AbstractEventLoop | None = None
        self._conns: dict[str, Any] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._ready = threading.Event()
        self._server = None

    # ------------------------------------------------------------------ коды подключения
    def create_pairing(self, owner: str, kind: str) -> str:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        code = f"{code[:4]}-{code[4:]}"
        self.m.ctx.db.execute("INSERT INTO pairings(code_hash, owner, kind, expires_at) VALUES (?,?,?,?)",
                              (_h(code), owner, kind, self.m.ctx.clock.now() + PAIR_TTL))
        return code

    def _redeem(self, code: str) -> tuple[str, str] | None:
        row = self.m.ctx.db.one("SELECT owner, kind, expires_at, used_at FROM pairings WHERE code_hash=?",
                                (_h(code.strip().upper()),))
        if row is None or row["used_at"] or row["expires_at"] < self.m.ctx.clock.now():
            return None
        self.m.ctx.db.execute("UPDATE pairings SET used_at=? WHERE code_hash=?",
                              (self.m.ctx.clock.now(), _h(code.strip().upper())))
        return row["owner"], row["kind"]

    def forget_device(self, device_id: str) -> None:
        self.m.ctx.db.execute("UPDATE devices SET revoked_at=? WHERE id=?", (self.m.ctx.clock.now(), device_id))
        self.hub.unregister(device_id)
        ws = self._conns.get(device_id)
        if ws is not None and self.loop:
            asyncio.run_coroutine_threadsafe(ws.close(), self.loop)

    # ------------------------------------------------------------------ запуск
    def start(self) -> None:
        t = threading.Thread(target=self._run, name="jarvis-devices", daemon=True)
        t.start()
        if not self._ready.wait(10):
            raise RuntimeError("шлюз устройств не запустился")

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        from websockets.asyncio.server import serve

        async with serve(self._handler, self.host, self.port, max_size=MAX_MSG,
                         process_request=self._http) as server:
            self._server = server
            if self.port == 0:
                self.port = next(iter(server.sockets)).getsockname()[1]
            self._ready.set()
            await asyncio.Future()  # навсегда

    def _http(self, connection, request):
        if request.path.rstrip("/").endswith("/client.py"):
            return connection.respond(200, CLIENT_PATH.read_text(encoding="utf-8"))
        return None

    # ------------------------------------------------------------------ соединение
    async def _handler(self, ws) -> None:
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), 15))
        except Exception:  # noqa: BLE001
            return
        info = None
        if first.get("type") == "pair":
            redeemed = self._redeem(str(first.get("code", "")))
            if redeemed is None:
                await ws.send(json.dumps({"type": "error", "error": "код неверный или устарел"}))
                return
            owner, kind = redeemed
            name = str(first.get("name") or kind)[:60]
            device_id = f"{_slug(first.get('kind') or kind)}-{_slug(name)}-{secrets.token_hex(2)}"
            token = secrets.token_urlsafe(32)
            self.m.ctx.db.execute(
                "INSERT INTO devices(id, owner, kind, name, token_hash, created_at) VALUES (?,?,?,?,?,?)",
                (device_id, owner, first.get("kind") or kind, name, _h(token), self.m.ctx.clock.now()))
            await ws.send(json.dumps({"type": "welcome", "device_id": device_id, "token": token}))
            info = self.m.ctx.db.one("SELECT * FROM devices WHERE id=?", (device_id,))
            self._observe(owner, device_id, f"Подключено новое устройство «{name}» ({device_id}).", "observed")
        elif first.get("type") == "hello":
            row = self.m.ctx.db.one("SELECT * FROM devices WHERE id=? AND revoked_at IS NULL",
                                    (str(first.get("device_id", "")),))
            if row is None or row["token_hash"] != _h(str(first.get("token", ""))):
                await ws.send(json.dumps({"type": "error", "error": "неизвестное устройство"}))
                return
            await ws.send(json.dumps({"type": "welcome", "device_id": row["id"]}))
            info = row
        else:
            return

        device_id = info["id"]
        self.m.ctx.db.execute("UPDATE devices SET last_seen=? WHERE id=?", (self.m.ctx.clock.now(), device_id))
        old = self._conns.get(device_id)
        self._conns[device_id] = ws
        if old is not None and old is not ws:
            await old.close()
        self.hub.register(Device(
            id=device_id, owner=info["owner"], kind=first.get("kind") or info["kind"], name=info["name"],
            languages=[str(x) for x in first.get("languages") or ["python"]],
            call=self._sync_call(device_id), capabilities={str(x) for x in first.get("capabilities") or []}))
        log.info("устройство %s на связи", device_id)
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "result":
                    fut = self._pending.pop(str(msg.get("id")), None)
                    if fut is not None and not fut.done():
                        fut.set_result(DeviceResult(bool(msg.get("ok")), str(msg.get("output", ""))[:50_000],
                                                    msg.get("image_b64")))
                elif msg.get("type") == "utterance" and self.on_utterance is not None:
                    asyncio.create_task(self._utterance(ws, info["owner"], device_id, msg))
                elif msg.get("type") == "event":
                    trust = "external" if msg.get("trust") == "external" else "observed"
                    self._observe(info["owner"], device_id, f"[{info['name']}] {str(msg.get('text', ''))[:2000]}", trust)
        except Exception:  # noqa: BLE001 — обрыв связи — обычное дело
            pass
        finally:
            if self._conns.get(device_id) is ws:
                self._conns.pop(device_id, None)
                self.hub.unregister(device_id)
                log.info("устройство %s отключилось", device_id)

    async def _utterance(self, ws, owner: str, device_id: str, msg: dict) -> None:
        import base64

        try:
            audio = base64.b64decode(msg.get("audio_b64") or "")
            heard, reply = await asyncio.to_thread(self.on_utterance, owner, device_id, audio)
            if reply:
                await self._say_ws(ws, reply)
        except Exception:  # noqa: BLE001
            log.exception("ошибка голосового хода с устройства")
            await self._say_ws(ws, "Что-то пошло не так, повтори, пожалуйста.")

    async def _say_ws(self, ws, text: str) -> None:
        import base64

        audio = None
        if self.tts is not None:
            try:
                audio = base64.b64encode(await asyncio.to_thread(self.tts, text)).decode()
            except Exception:  # noqa: BLE001
                log.exception("синтез речи не удался")
        await ws.send(json.dumps({"type": "say", "text": text, "audio_b64": audio}))

    def say(self, person: str, text: str) -> bool:
        """Сказать вслух на устройствах человека, где есть динамик. → было ли где сказать."""
        targets = [self._conns[d.id] for d in self.hub.all()
                   if d.owner == person and "speaker" in d.capabilities and d.id in self._conns]
        if not targets or self.loop is None:
            return False
        for ws in targets:
            asyncio.run_coroutine_threadsafe(self._say_ws(ws, text), self.loop)
        return True

    def _observe(self, owner: str, device_id: str, text: str, trust: str) -> None:
        try:
            self.m.observe(Observation(owner, text, speaker="device", device=device_id, channel="device",
                                       kind="device_event", source_kind=trust))
        except Exception:  # noqa: BLE001
            log.exception("не удалось записать событие устройства")

    # ------------------------------------------------------------------ вызовы
    async def _call(self, device_id: str, action: str, args: dict, timeout: float) -> DeviceResult:
        ws = self._conns.get(device_id)
        if ws is None:
            return DeviceResult(False, "устройство не на связи")
        call_id = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._pending[call_id] = fut
        await ws.send(json.dumps({"type": "call", "id": call_id, "action": action, "args": args, "timeout": timeout}))
        try:
            return await asyncio.wait_for(fut, timeout + 5)
        except asyncio.TimeoutError:
            self._pending.pop(call_id, None)
            return DeviceResult(False, f"устройство не ответило за {timeout:.0f} с")

    def _sync_call(self, device_id: str):
        def call(action: str, args: dict, timeout: float) -> DeviceResult:
            if self.loop is None:
                return DeviceResult(False, "шлюз не запущен")
            fut = asyncio.run_coroutine_threadsafe(self._call(device_id, action, args, timeout), self.loop)
            return fut.result(timeout + 15)
        return call
