"""Общие типы адаптеров."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AdapterNotConfigured(RuntimeError):
    """Слот есть, но секреты/доступ ещё не заполнены."""


@dataclass(frozen=True)
class ProcessResult:
    """Короткий итог для доставки менеджеру."""

    message_id: str
    decision: str
    action_id: str | None
    status: str
    summary: str | None
    next_action: str | None
    escalate: bool
    payload: dict[str, Any]
