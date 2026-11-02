"""Доставка результата менеджеру. file — рабочий; email — слот SMTP."""

from __future__ import annotations

import json
from pathlib import Path

from case_lab.adapters.base import AdapterNotConfigured, ProcessResult
from case_lab.config import Settings
from case_lab.loaders import write_json


def notify_manager(settings: Settings, result: ProcessResult, *, out_dir: Path) -> Path | None:
    mode = settings.notify_mode
    if mode in {"none", "off", "false"}:
        return None
    if mode == "file":
        path = out_dir / "notifications" / f"{result.action_id or result.message_id}.json"
        write_json(
            path,
            {
                "channel": "file",
                "to": "manager",
                "message_id": result.message_id,
                "decision": result.decision,
                "status": result.status,
                "summary": result.summary,
                "next_action": result.next_action,
                "escalate": result.escalate,
                "action_id": result.action_id,
                "payload": result.payload,
            },
        )
        return path
    if mode == "email":
        return _notify_email(settings, result)
    raise AdapterNotConfigured(
        f"Неизвестный CASE_NOTIFY={mode!r}. Допустимо: file, email, none."
    )


def _notify_email(settings: Settings, result: ProcessResult) -> Path | None:
    missing = [
        name
        for name, value in (
            ("MANAGER_EMAIL", settings.manager_email),
            ("SMTP_HOST", settings.smtp_host),
            ("SMTP_USER", settings.smtp_user),
            ("SMTP_PASSWORD", settings.smtp_password),
        )
        if not value
    ]
    if missing:
        raise AdapterNotConfigured(
            "Уведомление email ещё не подключено. Заполните в .env: " + ", ".join(missing)
        )
    # Каркас: когда появятся SMTP-данные, здесь отправка.
    # Пока не шлём письмо молча — явно говорим, что слот готов к доработке.
    raise AdapterNotConfigured(
        "SMTP-параметры заданы, но отправка письма ещё не включена в коде. "
        f"Получатель: {settings.manager_email}. "
        f"Тема была бы: [{result.decision}] {result.message_id}. "
        f"Тело: {json.dumps({'summary': result.summary, 'next_action': result.next_action}, ensure_ascii=False)}"
    )
