"""Шлюз чтения: кто что может видеть.

Правило простое и строгое:
  • 'family' — видят все члены семьи;
  • 'private' — только владелец записи (owner).
Даже владелец системы (ты) не видит личную память родственников — приватность в семье.
Проверка делается ДО ранжирования: чужое вообще не попадает в кандидаты.
"""

from __future__ import annotations


def can_see(viewer: str, owner: str | None, visibility: str) -> bool:
    return visibility == "family" or owner == viewer


def sql_visible(owner_col: str, vis_col: str = "visibility") -> str:
    """Кусок SQL-условия; параметр — id смотрящего."""
    return f"({vis_col}='family' OR {owner_col}=?)"
