"""Разбор русских выражений времени в запросах → период для фильтра памяти.

«вчера», «в прошлом месяце», «на прошлой неделе», «в мае», «в марте 2025», «3 дня назад»,
«позавчера», «сегодня утром», «в прошлом году», «на выходных», «недавно», «давно».
Работает детерминированно (без ИИ) — это часть «быстрого» пути вспоминания.
Время человека (часовой пояс) учитывается.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
# Только настоящие падежные формы месяцев: «\w*» ловил «майонез», «майку», «мартини», «Августу».
_MONTH_RE = (r"((?:январ|феврал|апрел|июн|июл|сентябр|октябр|ноябр|декабр)(?:ь|я|е|ем|ю)\b"
             r"|(?:март|август)(?:а|е|ом|у)?\b|ма(?:й|я|е|ем|ю)\b)")
_NUM_WORDS = {
    "один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "пару": 2, "несколько": 3,
}
WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3, "пятниц": 4, "суббот": 5, "воскресень": 6,
}


@dataclass(frozen=True)
class TimeRange:
    start: float  # Unix, включительно
    end: float    # Unix, исключительно
    label: str

    def contains(self, ts: float) -> bool:
        return self.start <= ts < self.end


def _month_num(word: str) -> int | None:
    w = word.lower().replace("ё", "е")
    for prefix, n in MONTHS.items():
        if prefix == "ма":
            if re.match(r"ма[йяе]", w):
                return 5
            continue
        if w.startswith(prefix):
            return n
    return None


def _day_range(d: date, tz: ZoneInfo, label: str, days: int = 1) -> TimeRange:
    start = datetime.combine(d, time.min, tzinfo=tz)
    return TimeRange(start.timestamp(), (start + timedelta(days=days)).timestamp(), label)


def _month_range(year: int, month: int, tz: ZoneInfo, label: str) -> TimeRange:
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    return TimeRange(start.timestamp(), end.timestamp(), label)


def _num(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUM_WORDS.get(token)


def parse_time_range(text: str, now_ts: float, tz_name: str = "Europe/Paris") -> TimeRange | None:
    """Найти в тексте первое понятное выражение времени. None — если его нет."""
    tz = ZoneInfo(tz_name)
    now = datetime.fromtimestamp(now_ts, tz)
    today = now.date()
    t = text.lower().replace("ё", "е")

    if re.search(r"\bпозавчера\b", t):
        return _day_range(today - timedelta(days=2), tz, "позавчера")
    if re.search(r"\bвчера\b", t):
        return _day_range(today - timedelta(days=1), tz, "вчера")
    if re.search(r"\bсегодня\b", t):
        return _day_range(today, tz, "сегодня")

    m = re.search(r"\b(\d+|" + "|".join(_NUM_WORDS) + r")\s+(дн\w*|день|недел\w*|месяц\w*|год\w*|лет)\s+назад", t)
    if m is None:
        # «неделю назад», «месяц назад», «год назад», «день назад» — без числа значит «один».
        # («лет назад»/«дней назад» без числа — «много», это не период.)
        m = re.search(r"\b()(день|неделю|месяц|год)\s+назад", t)
    if m:
        n = _num(m.group(1)) or 1
        unit = m.group(2)
        if unit.startswith(("дн", "день")):
            d = today - timedelta(days=n)
            return _day_range(d, tz, f"{n} дн. назад")
        if unit.startswith("недел"):
            start = today - timedelta(days=7 * n + today.weekday())
            return _day_range(start, tz, f"{n} нед. назад", days=7)
        if unit.startswith("месяц"):
            y, mo = now.year, now.month - n
            while mo <= 0:
                mo += 12
                y -= 1
            return _month_range(y, mo, tz, f"{n} мес. назад")
        y = now.year - n
        return TimeRange(datetime(y, 1, 1, tzinfo=tz).timestamp(), datetime(y + 1, 1, 1, tzinfo=tz).timestamp(), f"{y} год")

    if re.search(r"\b(на|в)\s+прошлой\s+неделе\b", t):
        start = today - timedelta(days=today.weekday() + 7)
        return _day_range(start, tz, "прошлая неделя", days=7)
    if re.search(r"\b(на|в)\s+этой\s+неделе\b", t):
        start = today - timedelta(days=today.weekday())
        return _day_range(start, tz, "эта неделя", days=7)
    if re.search(r"\bна\s+(прошлых\s+)?выходных\b", t):
        last_sat = today - timedelta(days=(today.weekday() - 5) % 7 or 7)
        return _day_range(last_sat, tz, "выходные", days=2)
    if re.search(r"\bв\s+прошлом\s+месяце\b", t):
        y, mo = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        return _month_range(y, mo, tz, "прошлый месяц")
    if re.search(r"\bв\s+этом\s+месяце\b", t):
        return _month_range(now.year, now.month, tz, "этот месяц")
    if re.search(r"\bв\s+прошлом\s+году\b", t):
        y = now.year - 1
        return TimeRange(datetime(y, 1, 1, tzinfo=tz).timestamp(), datetime(y + 1, 1, 1, tzinfo=tz).timestamp(), f"{y} год")
    if re.search(r"\bв\s+этом\s+году\b", t):
        y = now.year
        return TimeRange(datetime(y, 1, 1, tzinfo=tz).timestamp(), datetime(y + 1, 1, 1, tzinfo=tz).timestamp(), f"{y} год")

    # «5 марта», «5 марта 2025»
    m = re.search(r"\b(\d{1,2})\s+" + _MONTH_RE + r"(?:\s+(\d{4}))?", t)
    if m:
        day, mon = int(m.group(1)), _month_num(m.group(2))
        if mon and 1 <= day <= 31:
            year = int(m.group(3)) if m.group(3) else now.year
            try:
                d = date(year, mon, day)
            except ValueError:
                d = None
            if d:
                if not m.group(3) and d > today:
                    d = date(year - 1, mon, day)
                return _day_range(d, tz, d.isoformat())

    # «в мае», «в марте 2025», «на майских»
    m = re.search(r"\b(в|на|за)\s+" + _MONTH_RE + r"(?:\s+(\d{4}))?", t)
    if m:
        mon = _month_num(m.group(2))
        if mon:
            year = int(m.group(3)) if m.group(3) else now.year
            if not m.group(3) and (year, mon) > (now.year, now.month):
                year -= 1
            return _month_range(year, mon, tz, f"{year}-{mon:02d}")
    if re.search(r"\bна\s+майских\b", t):
        year = now.year if now.month >= 5 else now.year - 1
        return TimeRange(datetime(year, 5, 1, tzinfo=tz).timestamp(), datetime(year, 5, 12, tzinfo=tz).timestamp(), "майские")

    # «в понедельник», «в прошлую пятницу»
    m = re.search(r"\bв\s+(прошл\w+\s+)?(понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\b", t)
    if m:
        wd = next(v for k, v in WEEKDAYS.items() if m.group(2).startswith(k))
        delta = (today.weekday() - wd) % 7 or 7
        if m.group(1):
            delta = delta if delta >= 1 else 7
        return _day_range(today - timedelta(days=delta), tz, m.group(2))

    # «в 2024 году»
    m = re.search(r"\b(в|за)\s+(19\d\d|20\d\d)(\s+год\w*)?\b", t)
    if m:
        y = int(m.group(2))
        return TimeRange(datetime(y, 1, 1, tzinfo=tz).timestamp(), datetime(y + 1, 1, 1, tzinfo=tz).timestamp(), f"{y} год")

    if re.search(r"\bнедавно\b", t):
        return TimeRange((now - timedelta(days=14)).timestamp(), now_ts + 1, "недавно")
    return None
