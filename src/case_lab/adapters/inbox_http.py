"""Слот HTTP-входа: POST /ingest. Поднимается командой case_lab serve."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from case_lab.adapters.base import ProcessResult
from case_lab.adapters.notify_manager import notify_manager
from case_lab.config import get_settings
from case_lab.loaders import project_root
from case_lab.pipeline import run_pipeline
from case_lab.schemas import InboundEmail


class IngestRequest(BaseModel):
    id: str | None = None
    sender: str = Field(alias="from", default="api@local.example")
    subject: str = ""
    body: str = Field(min_length=1)
    received_at: datetime | None = None

    model_config = {"populate_by_name": True}


def build_app():
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:  # pragma: no cover - зависит от доп. установки
        raise RuntimeError(
            "Для HTTP-входа установите зависимости: python -m pip install -e \".[api]\""
        ) from exc

    app = FastAPI(title="СеверСнаб ingest", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        settings = get_settings()
        return {
            "status": "ok",
            "case_llm": settings.case_llm,
            "input": "http",
            "notify": settings.notify_mode,
        }

    @app.post("/ingest")
    def ingest(payload: IngestRequest) -> dict[str, Any]:
        root = project_root()
        settings = get_settings()
        stamp = payload.received_at or datetime.now(timezone.utc)
        message_id = payload.id or f"API-{stamp.strftime('%Y%m%d%H%M%S')}"
        inbox_dir = root / "out" / "http_inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        email = InboundEmail.model_validate(
            {
                "id": message_id,
                "received_at": stamp.isoformat(),
                "from": payload.sender,
                "subject": payload.subject,
                "body": payload.body,
            }
        )
        path = inbox_dir / f"{message_id}.json"
        path.write_text(
            json.dumps(email.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        mode = settings.case_llm if settings.case_llm in {"replay", "live"} else "replay"
        try:
            result = run_pipeline(
                root=root,
                inbox_dir=inbox_dir,
                out_dir=root / "out",
                mode=mode,
            )
        except Exception as exc:  # noqa: BLE001 - отдаём клиенту понятную ошибку
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        record = next((item for item in reversed(result.records) if item["message_id"] == message_id), None)
        if record is None:
            raise HTTPException(status_code=500, detail="Письмо принято, но запись в журнале не найдена.")

        process = ProcessResult(
            message_id=message_id,
            decision=record["decision"],
            action_id=record.get("action_id"),
            status=record.get("status") or record["decision"],
            summary=record.get("summary"),
            next_action=record.get("next_action"),
            escalate=bool(record.get("escalate")),
            payload=record,
        )
        notification = None
        try:
            notification_path = notify_manager(settings, process, out_dir=root / "out")
            notification = str(notification_path) if notification_path else None
        except Exception as exc:  # noqa: BLE001
            notification = f"notify_skipped: {exc}"

        return {
            "message_id": message_id,
            "decision": process.decision,
            "action_id": process.action_id,
            "status": process.status,
            "escalate": process.escalate,
            "summary": process.summary,
            "next_action": process.next_action,
            "notification": notification,
        }

    return app


app = None


def get_app():
    global app
    if app is None:
        app = build_app()
    return app
