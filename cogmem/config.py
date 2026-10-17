"""Настройки памяти. Все числа — в одном месте, чтобы стенд измерений мог их подбирать."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Budgets:
    """Бюджет рабочей памяти в токенах (по разделам)."""

    core: int = 600
    facts: int = 600
    episodes: int = 1000
    procedures: int = 300
    intentions: int = 200


@dataclass
class ScoreWeights:
    """Веса итоговой оценки воспоминания при вспоминании."""

    relevance: float = 0.55   # смысловая + словесная близость к подсказке
    activation: float = 0.15  # ACT-R: частота и давность использования
    importance: float = 0.15  # важность при записи
    graph: float = 0.10       # распространение активации по графу сущностей
    context: float = 0.05     # совпадение контекста (устройство, канал)


@dataclass
class MemoryConfig:
    # --- Сегментация эпизодов ---
    episode_gap_minutes: float = 30.0      # пауза, после которой начинается новый эпизод
    episode_max_events: int = 60           # жёсткий предел длины эпизода
    topic_shift_threshold: float = 0.12    # сходство с центром эпизода ниже порога = смена темы
    topic_shift_min_events: int = 6        # смену темы проверяем только в достаточно длинном эпизоде

    # --- ACT-R ---
    decay_d: float = 0.5                   # степень затухания (канон ACT-R)
    activation_tau: float = -6.0           # «порог» для приведения активации к 0..1

    # --- Вспоминание ---
    candidates_per_source: int = 120        # подобрано на стенде: 40 → 87%, 120 → 100% (e5-large)
    min_score: float = 0.10                # ниже — не показываем вовсе
    # Шлюз релевантности (важность и свежесть не должны протаскивать несвязанное в промпт).
    min_relevance: float = 0.15            # абсолютный порог близости к подсказке (0..1)
    relative_relevance: float = 0.45       # и не ниже этой доли от лучшего кандидата запроса
    graph_keep: float = 0.35               # сильная связь по графу с упомянутым — проходит без порога
    habituation: float = 0.15              # штраф за «показано, но не пригодилось» (за каждый лишний показ)
    habituation_days: float = 3.0          # окно привыкания
    relative_sim: float = 0.0              # доля относительной (внутри кандидатов) смысловой близости
    # z-нормировка близости: насколько запись выделяется среди всех записей для запроса (в σ).
    # 0 — выключено (по умолчанию, пока не проверено на стенде); пробовать 0.3–0.5.
    z_sim: float = 0.0
    z_lo: float = 1.0                      # z ниже — «не выделяется» (0)
    z_hi: float = 4.0                      # z выше — «явно про это» (1)
    z_min_n: int = 30                      # на маленьких таблицах σ ненадёжна — не применяем
    mmr_lambda: float = 0.75               # баланс релевантность/разнообразие
    neighbor_episodes: int = 1             # сколько соседних по времени эпизодов подтягивать
    ppr_alpha: float = 0.5                 # вероятность «телепортации» к затравкам в PageRank
    ppr_iterations: int = 20

    # --- Ядро ---
    core_max_tokens: int = 600

    # --- Сон ---
    reconcile_sample: int = 8              # сколько фактов за ночь сверять с оригиналом

    budgets: Budgets = field(default_factory=Budgets)
    weights: ScoreWeights = field(default_factory=ScoreWeights)
