import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cogmem.text import ru
from cogmem.text.timeparse import parse_time_range
from tests.conftest import say


def test_events_are_append_only(mem, clock):
    say(mem, clock, "owner", "Моя мама живёт в Самаре")
    with pytest.raises(sqlite3.IntegrityError):
        mem.ctx.db.execute("UPDATE events SET text='подмена' WHERE id=1")


def test_stems_handle_russian_cases():
    assert ru.stems("маму") == ru.stems("мамой") == ru.stems("мама")
    assert ru.alias_norm("Самаре") == ru.alias_norm("Самара")


def test_salience_signals():
    low = ru.salience("ага", speaker="user")
    high = ru.salience("Запомни: у мамы аллергия на пенициллин", speaker="user")
    corr = ru.salience("Нет, не так, она живёт в Тольятти", speaker="user")
    assert high > 0.6 > low
    assert corr > 0.4


@pytest.mark.parametrize("text,label_part", [
    ("что было вчера", "вчера"),
    ("что я говорил в прошлом месяце", "прошлый месяц"),
    ("в мае", "-05"),
    ("5 марта", "-03-05"),
    ("3 дня назад", "3 дн"),
    ("на прошлой неделе", "прошлая неделя"),
    ("в 2025 году", "2025"),
])
def test_timeparse(text, label_part):
    now = datetime(2026, 10, 16, 12, 0, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
    tr = parse_time_range(text, now)
    assert tr is not None and label_part in tr.label
    assert tr.start < tr.end


def test_timeparse_month_in_future_means_last_year():
    now = datetime(2026, 3, 10, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
    tr = parse_time_range("в декабре", now)
    assert tr.label == "2025-12"


def test_timeparse_none():
    assert parse_time_range("как дела?", 1.7e9) is None
