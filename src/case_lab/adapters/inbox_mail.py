"""Слот входа из почты. Подключение: заполнить MAIL_* в .env и дописать клиент IMAP."""

from __future__ import annotations

from case_lab.adapters.base import AdapterNotConfigured
from case_lab.config import Settings
from case_lab.schemas import InboundEmail


def fetch_mail_inbox(settings: Settings) -> list[InboundEmail]:
    missing = [
        name
        for name, value in (
            ("MAIL_HOST", settings.mail_host),
            ("MAIL_USER", settings.mail_user),
            ("MAIL_PASSWORD", settings.mail_password),
        )
        if not value
    ]
    if missing:
        raise AdapterNotConfigured(
            "Вход mail ещё не подключён. Заполните в .env: "
            + ", ".join(missing)
            + ". Затем в adapters/inbox_mail.py добавляется IMAP-клиент."
        )
    raise AdapterNotConfigured(
        "MAIL_* заданы, но IMAP-клиент ещё не подключён. "
        f"Ожидаемый ящик: {settings.mail_user} @ {settings.mail_host}, папка {settings.mail_folder}."
    )
