"""Схемы ответов «подсознания». Описания полей — это и есть инструкция модели."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EntityProposal(BaseModel):
    name: str = Field(description="Каноническое имя: «Мама (Ольга Петровна)», «Самара», «iPhone 16».")
    kind: Literal["person", "place", "device", "org", "object", "topic", "pet", "other"]
    aliases: list[str] = Field(description="Как собеседник ещё это называет: «мама», «мамуля», «Оля».")


class FactProposal(BaseModel):
    subject: str = Field(description="О ком/чём факт. «я» — сам собеседник. Иначе имя сущности.")
    predicate: str = Field(description="Короткое отношение: «живёт в», «день рождения», «любит», «работает».")
    object: str | None = Field(description="Сущность-объект, если это человек/место/вещь (иначе null).")
    value: str | None = Field(description="Значение, если это дата/число/описание (иначе null).")
    statement: str = Field(description="Самодостаточное утверждение по-русски, с именами вместо местоимений "
                                        "и абсолютными датами. Пример: «Мама Владимира живёт в Самаре».")
    valid_from: str | None = Field(description="С какой даты это верно (YYYY-MM-DD), если известно; иначе null.")
    op: Literal["new", "update", "confirm"] = Field(
        description="new — новое знание; update — меняет/опровергает известный факт (укажи replaces_fact_id); "
                    "confirm — подтверждает известный факт (укажи replaces_fact_id).")
    replaces_fact_id: int | None = Field(description="Число из [F..] известного факта для update/confirm, иначе null.")
    evidence: list[int] = Field(description="Номера реплик [M..], на которых основан факт.")
    confidence: float = Field(description="0..1 — насколько уверенно это следует из реплик.")
    importance: float = Field(description="0..1 — насколько важно помнить долго (имена близких, здоровье, даты, "
                                          "предпочтения — высоко; мелочи дня — низко).")


class IntentionProposal(BaseModel):
    action: str = Field(description="Что сделать/напомнить, самодостаточно.")
    due: str | None = Field(description="Когда: YYYY-MM-DDTHH:MM по времени собеседника, если ясно; иначе null.")
    trigger: str = Field(description="Если не по времени — условие: «когда придёт домой», «когда позвонит мама».")
    evidence: list[int] = Field(default_factory=list,
                                description="Номера реплик [M..] человека, где он об этом попросил или пообещал.")


class EpisodeEncoding(BaseModel):
    title: str = Field(description="Короткий заголовок эпизода (до 10 слов).")
    gist: str = Field(description="Суть эпизода от третьего лица, 2–6 предложений, с конкретикой: кто, что, "
                                  "когда, числа, решения. Без воды.")
    importance: float = Field(description="0..1 — важность эпизода в целом.")
    surprise: float = Field(description="0..1 — насколько эпизод НЕ предсказывался известными фактами.")
    emotion: float = Field(description="-1..1 — эмоциональная окраска для собеседника.")
    entities: list[EntityProposal]
    facts: list[FactProposal] = Field(description="Только новое или изменившееся относительно известного.")
    intentions: list[IntentionProposal]


class SummaryOut(BaseModel):
    title: str = Field(description="Заголовок периода (до 10 слов).")
    gist: str = Field(description="Сводка периода: главное, решения, изменения в жизни, 3–8 предложений.")
    importance: float = Field(description="0..1")


class VerifyOut(BaseModel):
    verdict: Literal["supported", "partially", "not_supported"] = Field(
        description="Подтверждается ли утверждение исходными репликами.")
    corrected_statement: str | None = Field(description="Если partially — точная формулировка по репликам, иначе null.")
    note: str = Field(description="Коротко почему.")
