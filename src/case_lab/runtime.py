"""Боевой контур: выбирает вход/LLM/уведомление по настройкам, сердцевина — тот же pipeline."""

from __future__ import annotations

from pathlib import Path

from case_lab.adapters.base import AdapterNotConfigured, ProcessResult
from case_lab.adapters.inbox_mail import fetch_mail_inbox
from case_lab.adapters.notify_manager import notify_manager
from case_lab.config import Settings, get_settings
from case_lab.loaders import project_root
from case_lab.pipeline import PipelineResult, run_pipeline


def run_live_batch(
    *,
    root: Path | None = None,
    inbox_dir: Path | None = None,
    out_dir: Path | None = None,
    settings: Settings | None = None,
) -> PipelineResult:
    settings = settings or get_settings()
    root = root or project_root()
    out_dir = out_dir or (root / "out")
    inbox_dir = inbox_dir or (root / "data" / "inbox")

    if settings.input_mode == "http":
        raise AdapterNotConfigured(
            "CASE_INPUT=http. Поднимите точку входа командой: python -m case_lab serve"
        )
    if settings.input_mode == "mail":
        fetch_mail_inbox(settings)

    if settings.input_mode != "files":
        raise AdapterNotConfigured(
            f"Неизвестный CASE_INPUT={settings.input_mode!r}. Допустимо: files, http, mail."
        )

    if settings.case_llm == "live" and not settings.api_key:
        raise AdapterNotConfigured(
            "CASE_LLM=live, но OPENAI_API_KEY пуст. Укажите ключ Proxy API в .env."
        )

    result = run_pipeline(
        root=root,
        inbox_dir=inbox_dir,
        out_dir=out_dir,
        mode=settings.case_llm,
    )
    _notify_batch(settings, result, out_dir=out_dir)
    return result


def _notify_batch(settings: Settings, result: PipelineResult, *, out_dir: Path) -> None:
    for record in result.records:
        if record["decision"] in {"skip_duplicate", "source_changed"}:
            continue
        process = ProcessResult(
            message_id=record["message_id"],
            decision=record["decision"],
            action_id=record.get("action_id"),
            status=record.get("status") or record["decision"],
            summary=record.get("summary"),
            next_action=record.get("next_action"),
            escalate=bool(record.get("escalate")),
            payload=record,
        )
        notify_manager(settings, process, out_dir=out_dir)
