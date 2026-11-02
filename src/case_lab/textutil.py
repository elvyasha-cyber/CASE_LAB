"""Нормализация текста и отпечатки. Общая для справочников и гейтов."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

# Слово целиком, не подстрока: иначе поле «update» содержит «date».
_BLOCKING_WORDS = frozenset(
    {
        "qty",
        "sku",
        "unit",
        "address",
        "date",
        "client",
        "price",
        "количество",
        "артикул",
        "адрес",
        "дата",
        "цена",
        "клиент",
        "единица",
    }
)


def norm(value: str) -> str:
    text = value.lower().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_inn(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def email_domain(value: str) -> str:
    match = re.search(r"@([A-Za-z0-9.-]+)", value)
    return match.group(1).lower() if match else ""


def is_blocking_assumption(field: str) -> bool:
    words = set(norm(field).split())
    return bool(words & _BLOCKING_WORDS)


def shorten(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def email_fingerprint(email_id: str, received_at: datetime, sender: str, subject: str, body: str) -> str:
    payload = {
        "id": email_id,
        "received_at": received_at.isoformat(),
        "from": sender,
        "subject": subject,
        "body": body,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(raw)
