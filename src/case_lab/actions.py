"""Действия на выходе. Проведение документа политика запрещает: наружу уходит черновик, эскалация или закрытие."""

from __future__ import annotations

from pathlib import Path

from case_lab.gates import SAFE_NEXT_ACTION, SAFE_SUMMARY, Verdict
from case_lab.loaders import write_json
from case_lab.reasons import suggestion_for
from case_lab.schemas import Extraction, InboundEmail


def persist_action(
    out_dir: Path,
    email: InboundEmail,
    verdict: Verdict,
    *,
    action_id: str,
    trace: dict,
    extraction: Extraction | None,
) -> dict:
    if verdict.decision == "create_draft":
        payload = _draft(email, verdict, action_id, trace, extraction)
        write_json(out_dir / "orders" / f"{action_id}.json", payload)
        return payload
    if verdict.decision == "escalate":
        payload = _escalation(email, verdict, action_id, trace, extraction)
        write_json(out_dir / "escalations" / f"{action_id}.json", payload)
        return payload
    payload = _close(email, action_id, trace, extraction, verdict)
    write_json(out_dir / "closed" / f"{action_id}.json", payload)
    return payload


def _draft(
    email: InboundEmail,
    verdict: Verdict,
    action_id: str,
    trace: dict,
    extraction: Extraction | None,
) -> dict:
    client = verdict.client
    assert client is not None
    return {
        "action_id": action_id,
        "action": "create_draft",
        "status": "draft",
        "posting": "forbidden",
        "commercial_status": "draft_not_posted",
        "escalate": False,
        "summary": verdict.summary,
        "priority": verdict.priority,
        "next_action": verdict.next_action,
        "confidence": verdict.confidence,
        "approval": {
            "auto_posting": False,
            "reason": "Политика разрешает только черновик. Проведение в учёте остаётся действием человека.",
        },
        "message_id": email.id,
        "client_id": client.id,
        "client_name": client.legal_name,
        "delivery_address_id": verdict.address_id,
        "delivery_address": verdict.address_full,
        "requested_date": verdict.requested_date,
        "currency": "RUB",
        "lines": [line.as_dict() for line in verdict.lines],
        "total_rub": verdict.total_rub,
        "notes": verdict.notes,
        "corrections": [item.as_dict() for item in verdict.corrections],
        "extraction": extraction.model_dump() if extraction else None,
        "trace": trace,
    }


def _escalation(
    email: InboundEmail,
    verdict: Verdict,
    action_id: str,
    trace: dict,
    extraction: Extraction | None,
) -> dict:
    codes = verdict.reason_codes
    return {
        "action_id": action_id,
        "action": "escalate",
        "status": "open",
        "posting": "forbidden",
        "commercial_status": "preview_not_approved",
        "escalate": True,
        "summary": verdict.summary or SAFE_SUMMARY,
        "priority": verdict.priority,
        "next_action": SAFE_NEXT_ACTION,
        "confidence": verdict.confidence,
        "message_id": email.id,
        "client_id": verdict.client.id if verdict.client else None,
        "reasons": [item.as_dict() for item in verdict.reasons],
        "suggestion": suggestion_for(codes),
        "requested_date": verdict.requested_date,
        "lines_preview": [line.as_dict() for line in verdict.lines],
        "total_rub": verdict.total_rub,
        "not_approved": True,
        "extraction_intent": extraction.intent if extraction else None,
        "extraction_confidence": extraction.confidence if extraction else None,
        "gates": [gate.as_dict() for gate in verdict.gates],
        "extraction": extraction.model_dump() if extraction else None,
        "trace": trace,
    }


def _close(
    email: InboundEmail,
    action_id: str,
    trace: dict,
    extraction: Extraction | None,
    verdict: Verdict,
) -> dict:
    return {
        "action_id": action_id,
        "action": "close_no_action",
        "status": "closed",
        "posting": "forbidden",
        "escalate": False,
        "summary": verdict.summary,
        "priority": verdict.priority,
        "next_action": verdict.next_action,
        "confidence": verdict.confidence,
        "message_id": email.id,
        "reason": "Письмо не содержит заявку на поставку.",
        "extraction": extraction.model_dump() if extraction else None,
        "trace": trace,
    }
