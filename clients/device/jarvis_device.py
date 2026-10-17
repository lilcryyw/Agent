#!/usr/bin/env python3
"""Клиент Джарвиса для устройства: Windows, macOS, Linux, Android (через Termux).

Один файл. Нужно: Python 3.10+ и `pip install websockets`. По желанию (экран и мышь на ПК):
`pip install mss pillow pyautogui`.

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


def run_code(language: str, code: str, timeout: float) -> tuple[bool, str]:
    if language == "python":
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
        cmd = [sys.executable, f.name]
    elif language == "powershell":
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", code]
    else:
        cmd = [shutil.which("bash") or "sh", "-c", code]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(Path.home()),
                           encoding="utf-8", errors="replace")
        out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
        return p.returncode == 0, f"код выхода {p.returncode}\n{out[-MAX_OUT:]}"
    except subprocess.TimeoutExpired:
        return False, f"превышено время {timeout:.0f} с"
    except FileNotFoundError as e:
        return False, f"не найдено: {e}"


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


def do_input(a: dict) -> tuple[bool, str]:
    import pyautogui

    pyautogui.FAILSAFE = True  # мышь в угол экрана — аварийная остановка
    act = a.get("action")
    x = a.get("x")
    y = a.get("y")
    if x is not None and y is not None:
        x, y = int(x * _scale), int(y * _scale)
    if act in ("click", "double_click", "right_click", "move"):
        fn = {"click": pyautogui.click, "double_click": pyautogui.doubleClick,
              "right_click": pyautogui.rightClick, "move": pyautogui.moveTo}[act]
        fn(x, y)
    elif act == "type":
        pyautogui.write(a.get("text") or "", interval=0.02)
    elif act == "key":
        keys = [k.strip() for k in (a.get("keys") or "").split("+") if k.strip()]
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
            ok, out = await asyncio.to_thread(run_code, a.get("language", "python"), a.get("code", ""), timeout)
        elif msg["action"] == "screenshot":
            ok, out, image = await asyncio.to_thread(screenshot)
        elif msg["action"] == "input":
            ok, out = await asyncio.to_thread(do_input, a)
        else:
            ok, out = False, f"неизвестное действие {msg['action']}"
    except Exception as e:  # noqa: BLE001
        ok, out = False, f"{type(e).__name__}: {e}"
    await ws.send(json.dumps({"type": "result", "id": msg["id"], "ok": ok, "output": out, "image_b64": image}))


# ---------------------------------------------------------------- связь
def load_cfg() -> dict:
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else {}


def save_cfg(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass


async def session(server: str, first: dict, utterances: asyncio.Queue | None = None) -> dict | None:
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

        sender = asyncio.create_task(send_utterances())
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "call":
                    t = asyncio.create_task(handle(ws, msg))
                    tasks.add(t)
                    t.add_done_callback(tasks.discard)
                elif msg.get("type") == "say":
                    print(f"Джарвис: {msg.get('text', '')}")
                    asyncio.create_task(asyncio.to_thread(speak, msg.get("text", ""), msg.get("audio_b64")))
        finally:
            sender.cancel()
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
                                   "name": name, **info}, utterances)
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
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
