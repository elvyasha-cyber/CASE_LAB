"""Сборка конвейера: источник → извлечение → политика → одно действие → запись в журнал."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from case_lab.actions import persist_action
from case_lab.audit import audit_record
from case_lab.extract import build_extractor
from case_lab.gates import Gate, Reason, Verdict, evaluate
from case_lab.loaders import (
    SourceProblem,
    append_jsonl,
    load_catalog,
    load_inbox,
    load_policy,
    load_registry,
    project_root,
    read_json,
    write_json,
)
from case_lab.schemas import InboundEmail
from case_lab.textutil import email_fingerprint


@dataclass
class PipelineResult:
    out_dir: Path
    records: list[dict]


def run_pipeline(
    *,
    root: Path | None = None,
    inbox_dir: Path | None = None,
    cassette_dir: Path | None = None,
    out_dir: Path | None = None,
    mode: str | None = None,
) -> PipelineResult:
    root = root or project_root()
    inbox_dir = inbox_dir or (root / "data" / "inbox")
    cassette_dir = cassette_dir or (root / "data" / "cassettes")
    out_dir = out_dir or (root / "out")
    policy = load_policy(root / "data" / "policy.json")
    catalog = load_catalog(root / "data" / "catalog.json")
    registry = load_registry(root / "data" / "clients.json")
    extractor = build_extractor(cassette_dir, policy, mode)
    state_path = out_dir / "state.json"
    audit_path = out_dir / "audit.jsonl"
    state = _load_state(state_path)
    records: list[dict] = []

    for item in load_inbox(inbox_dir):
        if isinstance(item, SourceProblem):
            record = _source_problem(item, policy.version, state, out_dir)
            append_jsonl(audit_path, record)
            records.append(record)
            write_json(state_path, state)
            continue
        record = _process_email(
            email=item,
            extractor=extractor,
            catalog=catalog,
            registry=registry,
            policy=policy,
            state=state,
            out_dir=out_dir,
        )
        append_jsonl(audit_path, record)
        records.append(record)
        write_json(state_path, state)

    return PipelineResult(out_dir=out_dir, records=records)


def _process_email(*, email, extractor, catalog, registry, policy, state, out_dir) -> dict:
    digest = email_fingerprint(email.id, email.received_at, email.sender, email.subject, email.body)
    previous = state["processed"].get(email.id)
    if previous and previous["input_sha256"] != digest:
        return audit_record(
            message_id=email.id,
            subject=email.subject,
            sender=email.sender,
            input_sha256=digest,
            decision="source_changed",
            action_id=previous.get("action_id"),
            policy_version=policy.version,
            prompt_version=policy.prompt_version,
            prompt_sha256=None,
            model=None,
            extraction=None,
            verdict=None,
            reasons=[Reason("source_changed", "Текст письма изменился после записанного решения.").as_dict()],
            email=email,
        )
    if previous:
        return audit_record(
            message_id=email.id,
            subject=email.subject,
            sender=email.sender,
            input_sha256=digest,
            decision="skip_duplicate",
            action_id=previous.get("action_id"),
            policy_version=policy.version,
            prompt_version=policy.prompt_version,
            prompt_sha256=None,
            model=None,
            extraction=None,
            verdict=None,
            reasons=[],
            email=email,
        )

    extracted = extractor.extract(email, catalog, registry)
    trace = {
        "message_id": email.id,
        "input_sha256": digest,
        "prompt_version": extracted.prompt_version,
        "prompt_sha256": extracted.prompt_sha256,
        "policy_version": policy.version,
        "model": extracted.model,
        "temperature": policy.temperature,
    }
    if extracted.error_code or extracted.extraction is None:
        verdict = Verdict(
            decision="escalate",
            summary="нужны уточнения",
            next_action="передать менеджеру",
            escalate=True,
            confidence=None,
        )
        verdict.reasons.append(Reason(extracted.error_code or "schema_invalid", extracted.error_detail or "Пустой ответ."))
        verdict.gates = [Gate("extractor", "fail", extracted.error_detail or "")]
        action_id = _next_id(state, "escalations", email.received_at.year)
        persist_action(out_dir, email, verdict, action_id=action_id, trace=trace, extraction=None)
        state["processed"][email.id] = {"input_sha256": digest, "decision": "escalate", "action_id": action_id}
        return audit_record(
            message_id=email.id,
            subject=email.subject,
            sender=email.sender,
            input_sha256=digest,
            decision="escalate",
            action_id=action_id,
            policy_version=policy.version,
            prompt_version=extracted.prompt_version,
            prompt_sha256=extracted.prompt_sha256,
            model=extracted.model,
            extraction=None,
            verdict=verdict,
            email=email,
        )

    verdict = evaluate(email, extracted.extraction, catalog, registry, policy)
    action_id = _action_id(state, verdict.decision, email)
    persist_action(
        out_dir,
        email,
        verdict,
        action_id=action_id,
        trace=trace,
        extraction=extracted.extraction,
    )
    state["processed"][email.id] = {
        "input_sha256": digest,
        "decision": verdict.decision,
        "action_id": action_id,
    }
    return audit_record(
        message_id=email.id,
        subject=email.subject,
        sender=email.sender,
        input_sha256=digest,
        decision=verdict.decision,
        action_id=action_id,
        policy_version=policy.version,
        prompt_version=extracted.prompt_version,
        prompt_sha256=extracted.prompt_sha256,
        model=extracted.model,
        extraction=extracted.extraction,
        verdict=verdict,
        email=email,
    )


def _action_id(state: dict, decision: str, email: InboundEmail) -> str:
    if decision == "create_draft":
        return _next_id(state, "orders", email.received_at.year)
    if decision == "escalate":
        return _next_id(state, "escalations", email.received_at.year)
    return f"CLOSED-{email.id}"


def _next_id(state: dict, kind: str, year: int) -> str:
    state[kind] += 1
    prefix = "ORD" if kind == "orders" else "ESC"
    return f"{prefix}-{year}-{state[kind]:04d}"


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {"orders": 0, "escalations": 0, "processed": {}}
    raw = read_json(path)
    raw.setdefault("orders", 0)
    raw.setdefault("escalations", 0)
    raw.setdefault("processed", {})
    return raw


def _source_problem(problem: SourceProblem, policy_version: str, state: dict, out_dir: Path) -> dict:
    previous = state["processed"].get(problem.id)
    if previous:
        return audit_record(
            message_id=problem.id,
            subject="",
            sender="",
            input_sha256="",
            decision="skip_duplicate",
            action_id=previous.get("action_id"),
            policy_version=policy_version,
            prompt_version=None,
            prompt_sha256=None,
            model=None,
            extraction=None,
            verdict=None,
            reasons=[],
            body="",
        )
    reason = Reason("source_invalid", problem.detail)
    action_id = f"SRC-{problem.id}"
    write_json(
        out_dir / "escalations" / f"{action_id}.json",
        {
            "action_id": action_id,
            "action": "escalate",
            "status": "open",
            "posting": "forbidden",
            "commercial_status": "preview_not_approved",
            "escalate": True,
            "summary": "нужны уточнения",
            "next_action": "передать менеджеру",
            "message_id": problem.id,
            "reasons": [reason.as_dict()],
            "suggestion": "Файл письма повреждён. Разобрать вручную, в заказ не ставить.",
            "not_approved": True,
        },
    )
    state["processed"][problem.id] = {
        "input_sha256": "",
        "decision": "escalate",
        "action_id": action_id,
    }
    return audit_record(
        message_id=problem.id,
        subject="",
        sender="",
        input_sha256="",
        decision="escalate",
        action_id=action_id,
        policy_version=policy_version,
        prompt_version=None,
        prompt_sha256=None,
        model=None,
        extraction=None,
        verdict=None,
        reasons=[reason.as_dict()],
        body="",
    )


__all__ = ["PipelineResult", "run_pipeline"]
