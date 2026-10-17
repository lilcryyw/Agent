"""Работа с русским текстом без языковой модели: нормализация, основы слов, сигналы важности."""

from __future__ import annotations

import re
from functools import lru_cache

import snowballstemmer

_WORD = re.compile(r"[0-9a-zа-яё]+(?:-[0-9a-zа-яё]+)*", re.IGNORECASE)
_stemmer_ru = snowballstemmer.stemmer("russian")
_stemmer_en = snowballstemmer.stemmer("english")

STOPWORDS = frozenset(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее её мне
    было вот от меня еще ещё нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до
    вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их
    чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой
    совсем ним здесь этом один почти мой тем чтобы нее неё сейчас были куда зачем всех никогда можно при
    наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три
    эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно
    всю между это мне меня мой моя мои твой твоя ваш наш это эта эти джарвис пожалуйста скажи
    the a an and or of to in on is are was be it this that i you he she we they
    """.split()
)


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


@lru_cache(maxsize=50_000)
def stem(word: str) -> str:
    if re.search(r"[а-я]", word):
        return _stemmer_ru.stemWord(word)
    return _stemmer_en.stemWord(word)


def stems(text: str, *, keep_stopwords: bool = False) -> list[str]:
    out = []
    for w in words(text):
        if not keep_stopwords and w in STOPWORDS:
            continue
        if len(w) == 1 and not w.isdigit():
            continue
        out.append(stem(w))
    return out


def fts_text(text: str) -> str:
    """Текст для полнотекстового индекса: основы слов через пробел."""
    return " ".join(stems(text))


def fts_query(text: str) -> str | None:
    """Запрос к FTS5: основы слов через OR (каждая в кавычках — без спецсинтаксиса)."""
    terms = sorted(set(stems(text)))
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in terms)


def alias_norm(name: str) -> str:
    """Нормальная форма имени для словаря прозвищ: основы слов через пробел (падежи не важны)."""
    return " ".join(stem(w) for w in words(name))


def estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов (кириллица «дороже» латиницы)."""
    cyr = sum(1 for ch in text if "а" <= ch.lower() <= "я" or ch in "ёЁ")
    other = len(text) - cyr
    return int(cyr / 2.4 + other / 3.6) + 1


# --- Сигналы важности (без ИИ) ---

_EXPLICIT = re.compile(
    r"\b(запомни|запиши|не забудь|напомни|важно|обязательно|никогда не|всегда|"
    r"мой день рождения|день рождения|годовщин|аллерги|пароль|адрес|телефон)\w*",
    re.IGNORECASE,
)
_CORRECTION = re.compile(
    r"(^|\b)(нет[,.!]? (не|это)|не так|ты ошиб|неправильно|на самом деле|вообще-то|поправ|исправ)",
    re.IGNORECASE,
)
_EMOTION_POS = re.compile(
    r"\b(рад|счастлив|ура|люблю|обожаю|отлично|прекрасно|замечательно|восторг|спасибо)\w*", re.IGNORECASE
)
_EMOTION_NEG = re.compile(
    r"\b(грустн|печал|плох|боюсь|страшн|ненавиж|злюсь|бесит|устал|больн|болит|умер|умерл|похорон|"
    r"развод|уволи|беда|ужасн|тревож|плачу|депресс)\w*",
    re.IGNORECASE,
)
_TOPIC_SHIFT = re.compile(r"\b(кстати|другой вопрос|о другом|смени(м|ть) тему|теперь про|а еще|а ещё)\b", re.IGNORECASE)
_DATE_HINT = re.compile(
    r"\b(\d{1,2}[./]\d{1,2}([./]\d{2,4})?|\d{4}|январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|"
    r"октябр|ноябр|декабр|понедельник|вторник|сред[уа]|четверг|пятниц|суббот|воскресень|завтра|вчера)\w*",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d")
# Эффект самоотнесённости (Rogers et al., 1977): сведения о себе и близких запоминаются лучше.
_SELF = re.compile(r"\b(я|мне|меня|мой|моя|моё|мое|мои|моего|моей|моих|мы|нас|наш|наша|наше|наши|у меня|у нас)\b",
                   re.IGNORECASE)
# Команды и вопросы к ассистенту — это поручения, а не сведения о жизни.
_COMMAND = re.compile(
    r"^\s*(включи|выключи|поставь|найди|переведи|расскажи|покажи|напиши|подскажи|скажи|сколько|какая|какой|какие|"
    r"как|что|где|когда|почему|зачем|открой|закрой|сделай|дай|предложи)\b", re.IGNORECASE)


def is_correction(text: str) -> bool:
    return bool(_CORRECTION.search(text))


def is_topic_shift(text: str) -> bool:
    return bool(_TOPIC_SHIFT.search(text))


def emotion(text: str) -> float:
    """Эмоциональная окраска: -1..1 (знак) — по словарю. Модуль важнее знака."""
    pos = len(_EMOTION_POS.findall(text))
    neg = len(_EMOTION_NEG.findall(text))
    if pos == neg == 0:
        return 0.0
    return max(-1.0, min(1.0, (pos - neg) / 2.0 if pos != neg else 0.5 * (1 if pos else -1)))


def salience(text: str, *, speaker: str, has_new_entity: bool = False) -> float:
    """Важность реплики 0..1 по простым признакам (как миндалина + «новизна»).

    Это быстрая оценка при записи. Точнее важность уточнит «подсознание» при кодировании эпизода.
    """
    s = 0.25 if speaker == "user" else 0.12
    n_explicit = len(_EXPLICIT.findall(text))
    if n_explicit:
        s += 0.3 + 0.15 * (n_explicit > 1)  # «запомни» + «аллергия» — важнее, чем что-то одно
    if is_correction(text):
        s += 0.25
    if _DATE_HINT.search(text):
        s += 0.1
    if _NUMBER.search(text):
        s += 0.05
    if has_new_entity:
        s += 0.1
    is_question = text.rstrip().endswith("?") or bool(_COMMAND.search(text))
    if speaker == "user":
        if _SELF.search(text) and not is_question:
            s += 0.15  # рассказ о себе/семье
        if is_question:
            s -= 0.1   # поручение ассистенту
    s += 0.2 * abs(emotion(text))
    n = len(words(text))
    if n <= 2:
        s -= 0.1  # «ага», «спасибо» — малоинформативно
    elif n > 12:
        s += 0.05
    return max(0.0, min(1.0, s))
