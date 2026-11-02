"""Журнал обработки: вход + результат + статус. Отпечаток сохраняется для идемпотентности."""

from __future__ import annotations

from datetime import datetime, timezone

from case_lab.gates import Verdict
from case_lab.schemas import Extraction, InboundEmail


def audit_record(
    *,
    message_id: str,
    subject: str,
    sender: str,
    input_sha256: str,
    decision: str,
    action_id: str | None,
    policy_version: str,
    prompt_version: str | None,
    prompt_sha256: str | None,
    model: str | None,
    extraction: Extraction | None,
    verdict: Verdict | None,
    reasons: list[dict] | None = None,
    email: InboundEmail | None = None,
    body: str | None = None,
) -> dict:
    input_payload = {
        "id": message_id,
        "from": sender,
        "subject": subject,
        "body": body if body is not None else (email.body if email else ""),
        "received_at": email.received_at.isoformat() if email else None,
    }
    reasons_out = reasons if reasons is not None else ([item.as_dict() for item in verdict.reasons] if verdict else [])
    result = {
        "decision": decision,
        "action_id": action_id,
        "escalate": verdict.escalate if verdict else decision == "escalate",
        "summary": verdict.summary if verdict else None,
        "priority": verdict.priority if verdict else None,
        "next_action": verdict.next_action if verdict else None,
        "confidence": verdict.confidence if verdict else (extraction.confidence if extraction else None),
        "intent": extraction.intent if extraction else None,
        "category": extraction.category if extraction else None,
        "extraction": extraction.model_dump() if extraction else None,
        "client_id": verdict.client.id if verdict and verdict.client else None,
        "total_rub": verdict.total_rub if verdict else None,
        "lines": [line.as_dict() for line in verdict.lines] if verdict else [],
        "corrections": [item.as_dict() for item in verdict.corrections] if verdict else [],
        "reasons": reasons_out,
        "gates": [gate.as_dict() for gate in verdict.gates] if verdict else [],
    }
    return {
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "message_id": message_id,
        "status": decision,
        "input": input_payload,
        "result": result,
        "subject": subject,
        "sender_domain": sender.split("@")[-1].lower() if "@" in sender else "",
        "input_sha256": input_sha256,
        "decision": decision,
        "action_id": action_id,
        "policy_version": policy_version,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256,
        "model": model,
        "intent": result["intent"],
        "confidence": result["confidence"],
        "client_id": result["client_id"],
        "total_rub": result["total_rub"],
        "lines": result["lines"],
        "corrections": result["corrections"],
        "reasons": reasons_out,
        "gates": result["gates"],
        "escalate": result["escalate"],
        "summary": result["summary"],
        "priority": result["priority"],
        "next_action": result["next_action"],
    }
