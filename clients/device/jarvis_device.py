#!/usr/bin/env python3
"""Клиент Джарвиса для устройства: Windows, macOS, Linux, Android (через Termux).

Один файл. Нужно: Python 3.10+ и `pip install websockets`. По желанию (экран и мышь на ПК):
`pip install mss pillow pyautogui pyperclip send2trash` (pyperclip — печать кириллицы на Mac/Linux,
send2trash — удаление в корзину, обратимое).

Первое подключение (код выдаёт Джарвис):
    python jarvis_device.py --server wss://ВАШ-СЕРВЕР/devices --pair ABCD-EFGH --name "Ноутбук" --install
Дальше клиент сам подключается при входе в систему (--install) и переподключается при обрывах.

Что умеет по просьбе Джарвиса: выполнить код (python, powershell/shell), снять экран, нажать/напечатать,
сказать вслух. Голосовой режим (--voice): скажите «Джарвис, …» — фраза уйдёт серверу, ответ прозвучит здесь.
Для голоса: `pip install vosk sounddevice numpy` (модель слова «Джарвис» ~45 МБ скачается сама, работает офлайн).
Токен хранится в ~/.jarvis_device.json (только для вас).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

CONFIG = Path.home() / ".jarvis_device.json"
MAX_OUT = 50_000
SHOT_MAX_W = 1280


# ---------------------------------------------------------------- что это за устройство
def detect_kind() -> str:
    if "com.termux" in os.environ.get("PREFIX", "") or os.environ.get("ANDROID_ROOT"):
        return "android"
    return {"Windows": "windows", "Darwin": "mac"}.get(platform.system(), "linux")


def detect(voice: bool = False) -> dict:
    kind = detect_kind()
    langs = ["python", "powershell" if kind == "windows" else "shell"]
    caps = set()
    try:
        import mss  # noqa: F401
        import PIL  # noqa: F401
        if kind != "android":
            caps.add("screen")
    except Exception:  # noqa: BLE001
        pass
    try:
        import pyautogui  # noqa: F401
        caps.add("input")
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("termux-battery-status"):
        caps.add("termux_api")  # termux-location, termux-sms-send, termux-notification, ...
    try:
        import sounddevice  # noqa: F401
        caps.add("speaker")
    except Exception:  # noqa: BLE001
        if shutil.which("termux-tts-speak") or kind in ("windows", "mac"):
            caps.add("speaker")  # системный голос
    if voice:
        caps.add("microphone")
    return {"kind": kind, "languages": langs, "capabilities": sorted(caps)}


# ---------------------------------------------------------------- голос
VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
MODELS = Path.home() / ".jarvis_models"
_speaking = threading.Event()  # пока Джарвис говорит — не слушаем (чтобы не услышать сам себя)


def _vosk_model_path() -> Path:
    path = MODELS / "vosk-model-small-ru-0.22"
    if not path.exists():
        import urllib.request
        import zipfile

        MODELS.mkdir(parents=True, exist_ok=True)
        z = MODELS / "vosk.zip"
        print("скачиваю модель слова «Джарвис» (~45 МБ)…", file=sys.stderr)
        urllib.request.urlretrieve(VOSK_MODEL_URL, z)
        with zipfile.ZipFile(z) as f:
            f.extractall(MODELS)
        z.unlink()
    return path


def pcm_to_wav(pcm: bytes, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


WAKE_FORMS = ("джарвис", "джервис", "жарвис", "джарвиз")


def voice_listener(loop: asyncio.AbstractEventLoop, out: asyncio.Queue, wake: str = "джарвис") -> None:
    """Поток: офлайн ждём слово «Джарвис», затем пишем фразу до паузы и кладём WAV в очередь.

    Два этапа (проверено на синтезированной речи: 0 ложных срабатываний на похожих словах):
    1) быстрый распознаватель, знающий только слово «Джарвис», даёт кандидата;
    2) полная модель перепроверяет последние 2 секунды — действительно ли сказано «Джарвис».
    """
    import queue as q

    import numpy as np
    import sounddevice as sd
    import vosk

    vosk.SetLogLevel(-1)
    model = vosk.Model(str(_vosk_model_path()))
    spot = vosk.KaldiRecognizer(model, 16000, json.dumps([wake, "[unk]"], ensure_ascii=False))
    chunks: q.Queue = q.Queue()
    block = 4000  # 0.25 с
    noise = [400.0]
    recent = b""

    def rms(d: bytes) -> float:
        a = np.frombuffer(d, np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(a * a))) if a.size else 0.0

    def confirmed(pcm: bytes) -> bool:
        full = vosk.KaldiRecognizer(model, 16000)
        full.SetWords(True)
        full.AcceptWaveform(pcm)
        words = json.loads(full.FinalResult()).get("result", [])
        forms = WAKE_FORMS if wake == "джарвис" else (wake,)
        return any(w.get("word") in forms and w.get("conf", 0) > 0.5 for w in words)

    with sd.RawInputStream(samplerate=16000, blocksize=block, dtype="int16", channels=1,
                           callback=lambda indata, frames, t, status: chunks.put(bytes(indata))):
        print("слушаю: скажите «Джарвис, …»", file=sys.stderr)
        while True:
            data = chunks.get()
            if _speaking.is_set():
                spot.Reset()
                recent = b""
                continue
            recent = (recent + data)[-64000:]  # последние 2 с
            noise.append(rms(data))
            del noise[:-40]
            if spot.AcceptWaveform(data):
                hit = wake in json.loads(spot.Result()).get("text", "")
            else:
                hit = wake in json.loads(spot.PartialResult()).get("partial", "")
            if not hit:
                continue
            spot.Reset()
            if not confirmed(recent):
                continue
            play_beep()
            threshold = max(300.0, sorted(noise)[len(noise) // 2] * 2.5)
            frames, silent, spoke = [recent], 0, True  # начало фразы уже в буфере
            while True:
                d = chunks.get()
                frames.append(d)
                if rms(d) > threshold:
                    silent = 0
                else:
                    silent += 1
                dur = (len(frames) - 1) * 0.25
                if silent >= 5 or dur > 15:
                    break
            recent = b""
            asyncio.run_coroutine_threadsafe(out.put(pcm_to_wav(b"".join(frames))), loop)


def play_beep() -> None:
    try:
        import numpy as np
        import sounddevice as sd

        t = np.linspace(0, 0.12, int(16000 * 0.12), False)
        sd.play((0.2 * np.sin(2 * np.pi * 880 * t)).astype(np.float32), 16000)
    except Exception:  # noqa: BLE001
        pass


def speak(text: str, audio_b64: str | None) -> None:
    """Проиграть ответ: голос Джарвиса с сервера, иначе системный голос устройства."""
    _speaking.set()
    try:
        if audio_b64:
            try:
                import numpy as np
                import sounddevice as sd

                with wave.open(io.BytesIO(base64.b64decode(audio_b64))) as w:
                    pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
                    sd.play(pcm, w.getframerate())
                    sd.wait()
                return
            except Exception:  # noqa: BLE001
                pass
        kind = detect_kind()
        if kind == "windows":
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis."
                            f"SpeechSynthesizer).Speak($args[0])", text], timeout=120)
        elif kind == "mac":
            subprocess.run(["say", text], timeout=120)
        elif shutil.which("termux-tts-speak"):
            subprocess.run(["termux-tts-speak", text], timeout=120)
        else:
            print(f"Джарвис: {text}")
    finally:
        time.sleep(0.3)
        _speaking.clear()


# ---------------------------------------------------------------- действия
_scale = 1.0  # во сколько раз снимок меньше реального экрана


_procs: dict[str, subprocess.Popen] = {}   # выполняющиеся вызовы: id → процесс (для «стоп»)
_cancelled: set[str] = set()


def _kill_tree(p: subprocess.Popen) -> None:
    """Убить процесс со всеми потомками (установщики, браузеры), а не только оболочку."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=20)
        else:
            import signal

            os.killpg(p.pid, signal.SIGKILL)
    except Exception:  # noqa: BLE001
        try:
            p.kill()
        except Exception:  # noqa: BLE001
            pass


def _clip(s: str, limit: int = MAX_OUT) -> str:
    if len(s) <= limit:
        return s
    head = limit // 3
    return s[:head] + f"\n…[обрезано {len(s) - limit} симв.]…\n" + s[-(limit - head):]


PS_UTF8 = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
           "$OutputEncoding=[System.Text.Encoding]::UTF8; ")


def run_code(language: str, code: str, timeout: float, env: dict | None = None,
             call_id: str | None = None) -> tuple[bool, str]:
    penv = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **{str(k): str(v) for k, v in (env or {}).items()}}
    tmp = None
    if language == "python":
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
        tmp = f.name
        cmd = [sys.executable, tmp]
    elif language == "powershell":
        # Русская Windows по умолчанию отдаёт вывод в cp866 — просим UTF-8, иначе кириллица превращается в мусор.
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", PS_UTF8 + code]
    else:
        cmd = [shutil.which("bash") or "sh", "-c", code]
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                             cwd=str(Path.home()), env=penv, **kw)
    except FileNotFoundError as e:
        if tmp:
            os.unlink(tmp)
        return False, f"не найдено: {e}"
    if call_id:
        _procs[call_id] = p
    timed_out = False
    try:
        try:
            out_b, err_b = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(p)
            out_b, err_b = p.communicate()
    finally:
        if call_id:
            _procs.pop(call_id, None)
        if tmp:  # в файле могли быть подставленные секреты — не оставляем его на диске
            try:
                os.unlink(tmp)
            except OSError:
                pass
    out = out_b.decode("utf-8", errors="replace")
    err = err_b.decode("utf-8", errors="replace")
    text = out + (("\n[stderr]\n" + err) if err else "")
    if call_id and call_id in _cancelled:
        _cancelled.discard(call_id)
        return False, "остановлено по просьбе человека\n" + _clip(text)
    if timed_out:
        return False, f"превышено время {timeout:.0f} с (процесс остановлен)\n" + _clip(text)
    return p.returncode == 0, f"код выхода {p.returncode}\n{_clip(text)}"


def cancel_call(call_id: str) -> None:
    p = _procs.get(call_id)
    if p is not None:
        _cancelled.add(call_id)
        _kill_tree(p)


def screenshot() -> tuple[bool, str, str | None]:
    global _scale
    import mss
    from PIL import Image

    with mss.mss() as s:
        mon = s.monitors[1]
        raw = s.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.rgb)
    _scale = max(1.0, img.width / SHOT_MAX_W)
    if _scale > 1:
        img = img.resize((int(img.width / _scale), int(img.height / _scale)))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return True, f"снимок {img.width}x{img.height} (координаты — в пикселях этого снимка)", \
        base64.b64encode(buf.getvalue()).decode()


def _type_unicode_win(text: str) -> None:
    """Печать любого текста (кириллица, эмодзи) в Windows через SendInput с KEYEVENTF_UNICODE."""
    import ctypes
    import struct
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    for ch in text:
        raw = ch.encode("utf-16-le")
        for unit in struct.unpack(f"<{len(raw) // 2}H", raw):
            for flags in (0x4, 0x4 | 0x2):  # KEYEVENTF_UNICODE, + KEYEVENTF_KEYUP
                inp = INPUT(type=1, u=_U(ki=KEYBDINPUT(0, unit, flags, 0, None)))
                ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.01)


def type_text(text: str) -> tuple[bool, str]:
    """pyautogui.write умеет только латиницу (остальное молча пропускает) — для прочего другие пути."""
    import pyautogui

    if text.isascii():
        pyautogui.write(text, interval=0.02)
        return True, "сделано"
    if os.name == "nt":
        _type_unicode_win(text)
        return True, "сделано"
    try:
        import pyperclip

        try:
            old = pyperclip.paste()
        except Exception:  # noqa: BLE001
            old = None
        pyperclip.copy(text)
        pyautogui.hotkey("command" if detect_kind() == "mac" else "ctrl", "v")
        time.sleep(0.3)
        if old is not None:
            pyperclip.copy(old)
        return True, "сделано (через буфер обмена)"
    except ImportError:
        pass
    if shutil.which("xdotool"):
        subprocess.run(["xdotool", "type", "--delay", "20", text], timeout=60)
        return True, "сделано"
    return False, "не могу напечатать не-латиницу: на устройстве нужно pip install pyperclip"


PC_KEYS = {"back": ["alt", "left"], "recents": ["alt", "tab"], "notifications": ["win", "a"]}


def do_input(a: dict) -> tuple[bool, str]:
    import pyautogui

    pyautogui.FAILSAFE = True  # мышь в угол экрана — аварийная остановка
    act = a.get("action")

    def pt(kx: str, ky: str):
        x, y = a.get(kx), a.get(ky)
        return (int(x * _scale), int(y * _scale)) if x is not None and y is not None else (None, None)

    x, y = pt("x", "y")
    if act in ("click", "double_click", "right_click", "move"):
        fn = {"click": pyautogui.click, "double_click": pyautogui.doubleClick,
              "right_click": pyautogui.rightClick, "move": pyautogui.moveTo}[act]
        fn(x, y)
    elif act == "long_press":
        pyautogui.moveTo(x, y)
        pyautogui.mouseDown()
        time.sleep(0.8)
        pyautogui.mouseUp()
    elif act in ("drag", "swipe"):
        x2, y2 = pt("x2", "y2")
        pyautogui.moveTo(x, y)
        pyautogui.dragTo(x2, y2, duration=max(float(a.get("ms") or 400) / 1000, 0.1), button="left")
    elif act == "type":
        return type_text(a.get("text") or "")
    elif act == "key":
        raw = (a.get("keys") or "").strip().lower()
        keys = PC_KEYS.get(raw) or [k.strip() for k in raw.split("+") if k.strip()]
        unknown = [k for k in keys if k not in pyautogui.KEYBOARD_KEYS]
        if unknown or not keys:
            return False, f"неизвестные клавиши: {', '.join(unknown) or raw}"
        pyautogui.hotkey(*keys)
    elif act == "scroll":
        pyautogui.scroll(int(a.get("amount") or -5), x=x, y=y)
    else:
        return False, f"неизвестное действие {act}"
    return True, "сделано"


async def handle(ws, msg: dict) -> None:
    a = msg.get("args") or {}
    timeout = float(msg.get("timeout") or 120)
    image = None
    try:
        if msg["action"] == "run":
            ok, out = await asyncio.to_thread(run_code, a.get("language", "python"), a.get("code", ""), timeout,
                                              a.get("env"), str(msg.get("id")))
        elif msg["action"] == "screenshot":
            ok, out, image = await asyncio.to_thread(screenshot)
        elif msg["action"] == "input":
            ok, out = await asyncio.to_thread(do_input, a)
        else:
            ok, out = False, f"неизвестное действие {msg['action']}"
    except Exception as e:  # noqa: BLE001
        ok, out = False, f"{type(e).__name__}: {e}"
    await ws.send(json.dumps({"type": "result", "id": msg["id"], "ok": ok, "output": out, "image_b64": image}))


# ---------------------------------------------------------------- органы чувств
# Устройство само сообщает Джарвису о важном — это события (данные), а не команды.
_senses_state: dict = {"seen": None, "low_sent": False}


def battery() -> tuple[int | None, bool]:
    """→ (процент заряда или None, заряжается ли)."""
    try:
        if shutil.which("termux-battery-status"):
            d = json.loads(subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=20).stdout)
            return int(d.get("percentage")), d.get("plugged", "UNPLUGGED") != "UNPLUGGED"
        for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
            return int((b / "capacity").read_text()), (b / "status").read_text().strip() in ("Charging", "Full")
        if detect_kind() == "mac":
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout
            import re

            m = re.search(r"(\d+)%;\s*(\w+)", out)
            if m:
                return int(m.group(1)), m.group(2).lower() in ("charging", "charged", "finishing")
        import psutil  # Windows (если установлен)

        b = psutil.sensors_battery()
        if b is not None:
            return int(b.percent), bool(b.power_plugged)
    except Exception:  # noqa: BLE001
        pass
    return None, False


def senses_once() -> list[tuple[str, str]]:
    """Один осмотр: → [(текст события, доверие)]. Уведомления — чужой текст (external)."""
    st = _senses_state
    events: list[tuple[str, str]] = []
    level, charging = battery()
    if level is not None:
        if level <= 20 and not charging and not st["low_sent"]:
            events.append((f"Батарея {level}%, не заряжается", "observed"))
            st["low_sent"] = True
        elif level > 30 or charging:
            st["low_sent"] = False
    if shutil.which("termux-notification-list"):
        try:
            items = json.loads(subprocess.run(["termux-notification-list"], capture_output=True, text=True,
                                              timeout=20).stdout or "[]")
        except Exception:  # noqa: BLE001
            items = []
        keys = {f"{n.get('id')}|{n.get('when')}" for n in items}
        if st["seen"] is not None:  # первый осмотр — только запоминаем, что уже было
            for n in items:
                k = f"{n.get('id')}|{n.get('when')}"
                if k in st["seen"] or n.get("packageName", "").startswith("com.termux"):
                    continue
                text = f"Уведомление ({n.get('packageName', '?')}): {n.get('title', '')} — {n.get('content', '')}"
                events.append((text[:500], "external"))
        st["seen"] = keys
    return events[:5]


# ---------------------------------------------------------------- связь
def load_cfg() -> dict:
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else {}


def save_cfg(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass


async def session(server: str, first: dict, utterances: asyncio.Queue | None = None,
                  senses: bool = True) -> dict | None:
    from websockets.asyncio.client import connect

    local = any(h in server for h in ("localhost", "127.0.0.1"))
    async with connect(server, max_size=16 * 1024 * 1024, proxy=None if local else True) as ws:
        await ws.send(json.dumps(first))
        welcome = json.loads(await ws.recv())
        if welcome.get("type") != "welcome":
            raise PermissionError(welcome.get("error", "отказ сервера"))
        tasks = set()

        async def send_utterances():
            while utterances is not None:
                wav = await utterances.get()
                await ws.send(json.dumps({"type": "utterance", "audio_b64": base64.b64encode(wav).decode()}))

        async def watch():
            while senses:
                for text, trust in await asyncio.to_thread(senses_once):
                    await ws.send(json.dumps({"type": "event", "text": text, "trust": trust}))
                await asyncio.sleep(60)

        sender = asyncio.create_task(send_utterances())
        watcher = asyncio.create_task(watch())
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "call":
                    t = asyncio.create_task(handle(ws, msg))
                    tasks.add(t)
                    t.add_done_callback(tasks.discard)
                elif msg.get("type") == "cancel":
                    cancel_call(str(msg.get("id")))
                elif msg.get("type") == "say":
                    print(f"Джарвис: {msg.get('text', '')}")
                    asyncio.create_task(asyncio.to_thread(speak, msg.get("text", ""), msg.get("audio_b64")))
        finally:
            sender.cancel()
            watcher.cancel()
        return welcome


async def main_async(args) -> None:
    cfg = load_cfg()
    info = detect(voice=args.voice)
    name = args.name or cfg.get("name") or platform.node() or info["kind"]
    server = args.server or cfg.get("server")
    if not server:
        raise SystemExit("Укажите --server")
    if args.pair:
        from websockets.asyncio.client import connect

        first_server = server.split(",")[0].strip()
        local = any(h in first_server for h in ("localhost", "127.0.0.1"))
        async with connect(first_server, max_size=16 * 1024 * 1024, proxy=None if local else True) as ws:
            await ws.send(json.dumps({"type": "pair", "code": args.pair, "name": name, **info}))
            welcome = json.loads(await ws.recv())
        if welcome.get("type") != "welcome":
            raise SystemExit(f"Не удалось подключить: {welcome.get('error')}")
        cfg = {"server": server, "device_id": welcome["device_id"], "token": welcome["token"], "name": name}
        save_cfg(cfg)
        print(f"Подключено как {cfg['device_id']}")
    if args.install:
        print(install_autostart())
    if args.once:
        return
    if args.voice and cfg.get("device_id") and not cfg.get("voice"):
        cfg["voice"] = True  # запомнить: автозапуск тоже будет слушать «Джарвис»
        save_cfg(cfg)
    voice_on = args.voice or bool(cfg.get("voice"))
    info = detect(voice=voice_on)
    utterances: asyncio.Queue = asyncio.Queue()
    if voice_on:
        threading.Thread(target=voice_listener, args=(asyncio.get_running_loop(), utterances, args.wake),
                         daemon=True, name="voice").start()
    servers = [x.strip() for x in server.split(",") if x.strip()]  # основной, затем запасные (ретранслятор)
    delay, i = 2, 0
    while True:
        server = servers[i % len(servers)]
        try:
            await session(server, {"type": "hello", "device_id": cfg["device_id"], "token": cfg["token"],
                                   "name": name, **info}, utterances, not args.no_senses)
            delay = 2
        except PermissionError as e:
            raise SystemExit(f"Сервер отказал: {e}. Подключите устройство заново (--pair).")
        except Exception as e:  # noqa: BLE001 — нет сети: пробуем следующий адрес
            print(f"нет связи с {server} ({type(e).__name__}), повтор через {delay} с", file=sys.stderr)
            i += 1
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


# ---------------------------------------------------------------- автозапуск
def install_autostart() -> str:
    script = Path(__file__).resolve()
    kind = detect_kind()
    if kind == "windows":
        pyw = Path(sys.executable).with_name("pythonw.exe")
        startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/jarvis.cmd"
        startup.write_text(f'@start "" "{pyw if pyw.exists() else sys.executable}" "{script}"\r\n')
        return f"Автозапуск: {startup}"
    if kind == "android":
        boot = Path.home() / ".termux/boot/jarvis.sh"
        boot.parent.mkdir(parents=True, exist_ok=True)
        boot.write_text(f"#!/data/data/com.termux/files/usr/bin/sh\ntermux-wake-lock\npython {script} &\n")
        boot.chmod(0o755)
        return "Автозапуск через Termux:Boot (поставьте приложение Termux:Boot из F-Droid)."
    if kind == "mac":
        plist = Path.home() / "Library/LaunchAgents/ai.jarvis.device.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Label</key><string>ai.jarvis.device</string>
<key>ProgramArguments</key><array><string>{sys.executable}</string><string>{script}</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/></dict></plist>""")
        subprocess.run(["launchctl", "load", str(plist)], check=False)
        return f"Автозапуск: {plist}"
    unit = Path.home() / ".config/systemd/user/jarvis-device.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f"[Unit]\nDescription=Jarvis device\n[Service]\nExecStart={sys.executable} {script}\n"
                    "Restart=always\nRestartSec=5\n[Install]\nWantedBy=default.target\n")
    subprocess.run(["systemctl", "--user", "enable", "--now", "jarvis-device"], check=False)
    return f"Автозапуск: {unit}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Клиент устройства Джарвиса")
    ap.add_argument("--server", help="wss://сервер/devices (можно несколько через запятую: основной,ретранслятор)")
    ap.add_argument("--pair", help="одноразовый код подключения от Джарвиса")
    ap.add_argument("--name", help="как назвать устройство")
    ap.add_argument("--install", action="store_true", help="запускаться автоматически")
    ap.add_argument("--once", action="store_true", help="только подключить и выйти")
    ap.add_argument("--voice", action="store_true", help="слушать слово «Джарвис» и говорить ответы вслух")
    ap.add_argument("--wake", default="джарвис", help="слово пробуждения")
    ap.add_argument("--no-senses", action="store_true", help="не сообщать о заряде и уведомлениях")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
