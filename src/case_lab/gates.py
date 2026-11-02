"""Политика qc. Уверенность модели не заменяет гейт. Пустое коммерческое поле из письма не достраивается."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from case_lab.domain import Catalog, Client, Policy, Registry
from case_lab.reasons import REASON_TITLE
from case_lab.resolve import match_address, match_skus, resolve_client
from case_lab.schemas import Extraction, InboundEmail, LineExtract
from case_lab.textutil import is_blocking_assumption, norm

SAFE_NEXT_ACTION = "передать менеджеру"
SAFE_SUMMARY = "нужны уточнения"


@dataclass(frozen=True)
class Reason:
    code: str
    detail: str

    def as_dict(self) -> dict:
        return {"code": self.code, "title": REASON_TITLE.get(self.code, self.code), "detail": self.detail}


@dataclass(frozen=True)
class Gate:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class Correction:
    line_index: int
    raw_name: str
    from_sku: str | None
    to_sku: str

    def as_dict(self) -> dict:
        return {
            "line_index": self.line_index,
            "raw_name": self.raw_name,
            "from_sku": self.from_sku,
            "to_sku": self.to_sku,
        }


@dataclass(frozen=True)
class ResolvedLine:
    raw_name: str
    sku: str
    name: str
    qty: int
    unit: str
    price_rub: int
    sum_rub: int
    resolution: str

    def as_dict(self) -> dict:
        return {
            "raw_name": self.raw_name,
            "sku": self.sku,
            "name": self.name,
            "qty": self.qty,
            "unit": self.unit,
            "price_rub": self.price_rub,
            "sum_rub": self.sum_rub,
            "resolution": self.resolution,
        }


@dataclass
class Verdict:
    decision: str
    gates: list[Gate] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)
    client: Client | None = None
    address_id: str | None = None
    address_full: str | None = None
    lines: list[ResolvedLine] = field(default_factory=list)
    requested_date: str | None = None
    total_rub: int | None = None
    notes: list[str] = field(default_factory=list)
    summary: str = ""
    priority: str = "medium"
    next_action: str = ""
    confidence: str | None = None
    escalate: bool = True

    @property
    def reason_codes(self) -> list[str]:
        return [item.code for item in self.reasons]


def evaluate(email: InboundEmail, extraction: Extraction, catalog: Catalog, registry: Registry, policy: Policy) -> Verdict:
    verdict = Verdict(
        decision="escalate",
        summary=extraction.summary or SAFE_SUMMARY,
        priority=extraction.priority,
        next_action=extraction.next_action or SAFE_NEXT_ACTION,
        confidence=extraction.confidence,
        escalate=True,
    )

    if not policy.confidence_ok(extraction.confidence):
        verdict.gates.append(
            Gate("confidence", "fail", f"{extraction.confidence} ниже порога {policy.min_confidence}.")
        )
        verdict.reasons.append(
            Reason("low_confidence", f"Уверенность {extraction.confidence} ниже порога {policy.min_confidence}.")
        )
    else:
        verdict.gates.append(
            Gate("confidence", "pass", f"{extraction.confidence} при пороге {policy.min_confidence}.")
        )

    if extraction.data_gaps:
        detail = "; ".join(extraction.data_gaps)
        verdict.gates.append(Gate("data_gaps", "fail", detail))
        verdict.reasons.append(Reason("data_gaps", detail))
    else:
        verdict.gates.append(Gate("data_gaps", "pass", "Явных пробелов во входе модель не отметила."))

    if extraction.intent == "not_order":
        _finish_not_order(extraction, verdict)
        return _finalize(extraction, verdict)

    if extraction.intent == "unclear":
        verdict.gates.append(Gate("intent", "fail", "Модель не поняла, заявка это или нет."))
        verdict.reasons.append(Reason("intent_unclear", "Намерение письма не определено."))
    else:
        verdict.gates.append(Gate("intent", "pass", "Письмо распознано как заявка."))

    _apply_assumptions(extraction, verdict)
    client = _apply_client(email, extraction, registry, verdict)
    _apply_address(extraction, client, verdict)
    line_ok = _apply_lines(extraction, catalog, policy, verdict)
    _apply_date(email, extraction, policy, verdict)
    _apply_credit(client, line_ok, verdict)

    if verdict.reasons or extraction.escalate:
        verdict.decision = "escalate"
    else:
        verdict.decision = "create_draft"
    return _finalize(extraction, verdict)


def _finalize(extraction: Extraction, verdict: Verdict) -> Verdict:
    if extraction.escalate and "model_escalate" not in verdict.reason_codes and verdict.decision == "escalate":
        if not verdict.reasons:
            verdict.reasons.append(Reason("model_escalate", "Модель выставила escalate=true."))
    if verdict.decision == "escalate":
        verdict.escalate = True
        verdict.next_action = SAFE_NEXT_ACTION
        if not verdict.summary.strip():
            verdict.summary = SAFE_SUMMARY
    elif verdict.decision == "close_no_action":
        verdict.escalate = False
        verdict.next_action = extraction.next_action or "закрыть без заказа"
    else:
        verdict.escalate = False
        verdict.next_action = extraction.next_action or "создать черновик заказа"
    return verdict


def _finish_not_order(extraction: Extraction, verdict: Verdict) -> None:
    has_lines = bool(extraction.fields and extraction.fields.lines)
    if has_lines:
        verdict.gates.append(Gate("intent", "fail", "Метка not_order, но в письме есть позиции."))
        verdict.reasons.append(Reason("intent_conflict", "Нельзя закрыть письмо без заказа: в извлечении есть позиции."))
    else:
        verdict.gates.append(Gate("intent", "pass", "Письмо не содержит заявку на поставку."))
    for name in ("assumptions", "client", "address", "lines", "date", "credit"):
        verdict.gates.append(Gate(name, "skip", "Для письма без заявки коммерческие гейты не применяются."))
    if verdict.reasons or extraction.escalate:
        verdict.decision = "escalate"
    else:
        verdict.decision = "close_no_action"


def _apply_assumptions(extraction: Extraction, verdict: Verdict) -> None:
    blocking = [item for item in extraction.assumptions if is_blocking_assumption(item.field)]
    notes = [item for item in extraction.assumptions if not is_blocking_assumption(item.field)]
    verdict.notes.extend(f"{item.field}: {item.detail}" for item in notes)
    if blocking:
        detail = "; ".join(f"{item.field}: {item.detail}" for item in blocking)
        verdict.gates.append(Gate("assumptions", "fail", detail))
        verdict.reasons.append(Reason("assumption_blocking", detail))
        return
    if notes:
        verdict.gates.append(Gate("assumptions", "pass", "Есть служебный комментарий, коммерческие поля не додуманы."))
        return
    verdict.gates.append(Gate("assumptions", "pass", "Допущений нет."))


def _apply_client(email: InboundEmail, extraction: Extraction, registry: Registry, verdict: Verdict) -> Client | None:
    resolution = resolve_client(email.sender, extraction.fields, registry)
    if resolution.status == "ok" and resolution.client is not None:
        verdict.client = resolution.client
        verdict.gates.append(Gate("client", "pass", resolution.client.legal_name))
        return resolution.client
    code = "client_conflict" if resolution.status == "conflict" else "client_unresolved"
    verdict.gates.append(Gate("client", "fail", resolution.detail))
    verdict.reasons.append(Reason(code, resolution.detail))
    return None


def _apply_address(extraction: Extraction, client: Client | None, verdict: Verdict) -> None:
    if client is None:
        verdict.gates.append(Gate("address", "skip", "Нет однозначно определённого клиента."))
        return
    raw = extraction.fields.delivery_address if extraction.fields else None
    if raw is None or not raw.strip():
        verdict.gates.append(Gate("address", "fail", "Адрес доставки пуст."))
        verdict.reasons.append(Reason("address_missing", "В структуре нет адреса. Из текста письма он не достраивается."))
        return
    status, address, detail = match_address(client, raw)
    if status == "ok" and address is not None:
        verdict.address_id = address.id
        verdict.address_full = address.full
        verdict.gates.append(Gate("address", "pass", address.full))
        return
    code = {"missing": "address_missing", "unresolved": "address_unresolved", "ambiguous": "address_ambiguous"}[status]
    verdict.gates.append(Gate("address", "fail", detail))
    verdict.reasons.append(Reason(code, detail))


def _apply_lines(extraction: Extraction, catalog: Catalog, policy: Policy, verdict: Verdict) -> bool:
    order = extraction.fields
    if order is None or not order.lines:
        verdict.gates.append(Gate("lines", "fail", "Позиций нет."))
        verdict.reasons.append(Reason("lines_empty", "В заявке нет строк."))
        return False

    reasons: list[Reason] = []
    resolved: list[ResolvedLine] = []
    corrections: list[Correction] = []
    for index, line in enumerate(order.lines, start=1):
        line_reasons, line_corrections, ready = _resolve_line(index, line, catalog, policy)
        reasons.extend(line_reasons)
        corrections.extend(line_corrections)
        if ready is not None:
            resolved.append(ready)

    if reasons:
        verdict.gates.append(Gate("lines", "fail", "; ".join(item.detail for item in reasons)))
        verdict.reasons.extend(reasons)
        return False

    verdict.lines = resolved
    verdict.corrections = corrections
    verdict.total_rub = sum(line.sum_rub for line in resolved)
    note = f"Позиций: {len(resolved)}. Сумма по каталогу: {verdict.total_rub} ₽."
    if corrections:
        fixed = ", ".join(f"{item.from_sku} → {item.to_sku}" for item in corrections)
        note = f"{note} Артикулы поправлены справочником: {fixed}."
    verdict.gates.append(Gate("lines", "pass", note))
    return True


def _resolve_line(
    index: int,
    line: LineExtract,
    catalog: Catalog,
    policy: Policy,
) -> tuple[list[Reason], list[Correction], ResolvedLine | None]:
    label = f"Позиция {index} «{line.raw_name}»"
    hits = match_skus(line.raw_name, catalog)
    known = catalog.by_sku.get(line.sku) if line.sku else None
    chosen = None
    reasons: list[Reason] = []

    if len(hits) == 1:
        chosen = catalog.by_sku[hits[0]]
        if known is not None and known.sku != chosen.sku:
            reasons.append(Reason("sku_conflict", f"{label}: артикул {known.sku} и название указывают на {chosen.sku}."))
            chosen = None
    elif len(hits) == 0:
        if known is not None:
            reasons.append(Reason("sku_unsupported", f"{label}: артикул {known.sku} текстом позиции не подтверждён."))
        else:
            shown = line.sku or "пустой артикул"
            reasons.append(Reason("sku_unresolved", f"{label}: {shown} не сопоставлен с каталогом."))
    else:
        options = ", ".join(hits)
        reasons.append(Reason("sku_ambiguous", f"{label}: неоднозначно, подходят {options}."))

    limit = chosen.max_qty if chosen is not None else policy.max_qty_default
    if line.qty < 1 or line.qty > limit:
        reasons.append(Reason("qty_invalid", f"{label}: количество {line.qty} вне диапазона 1…{limit}."))
        chosen = None

    if chosen is not None and norm(line.unit) != norm(chosen.unit):
        reasons.append(Reason("unit_mismatch", f"{label}: единица «{line.unit}» вместо «{chosen.unit}»."))
        chosen = None

    if reasons or chosen is None:
        return reasons, [], None

    resolution = "catalog_match"
    corrections: list[Correction] = []
    if line.sku and line.sku != chosen.sku:
        resolution = "catalog_corrected"
        corrections.append(Correction(index, line.raw_name, line.sku, chosen.sku))
    ready = ResolvedLine(
        raw_name=line.raw_name,
        sku=chosen.sku,
        name=chosen.name,
        qty=line.qty,
        unit=chosen.unit,
        price_rub=chosen.price_rub,
        sum_rub=chosen.price_rub * line.qty,
        resolution=resolution,
    )
    return [], corrections, ready


def _apply_date(email: InboundEmail, extraction: Extraction, policy: Policy, verdict: Verdict) -> None:
    if extraction.fields is None:
        verdict.gates.append(Gate("date", "skip", "Нет блока заказа."))
        return
    raw = extraction.fields.requested_date
    if raw is None or not str(raw).strip():
        verdict.gates.append(Gate("date", "fail", "Дата поставки пуста."))
        verdict.reasons.append(Reason("date_missing", "Дата поставки не извлечена и не назначается правилом."))
        return
    try:
        requested = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        verdict.gates.append(Gate("date", "fail", f"«{raw}» не является датой ГГГГ-ММ-ДД."))
        verdict.reasons.append(Reason("date_unparsed", f"Дата «{raw}» не принята. Относительные формулировки здесь не вычисляются."))
        return
    received = email.received_at.date()
    if requested < received:
        verdict.gates.append(Gate("date", "fail", f"{raw} раньше даты письма {received.isoformat()}."))
        verdict.reasons.append(Reason("date_in_past", f"Дата {raw} раньше дня письма. На сегодня она не переносится."))
        return
    horizon = received + timedelta(days=policy.max_horizon_days)
    if requested > horizon:
        verdict.gates.append(Gate("date", "fail", f"{raw} дальше горизонта {horizon.isoformat()}."))
        verdict.reasons.append(Reason("date_too_far", f"Дата {raw} дальше {policy.max_horizon_days} дней от письма."))
        return
    verdict.requested_date = raw
    verdict.gates.append(Gate("date", "pass", raw))


def _apply_credit(client: Client | None, line_ok: bool, verdict: Verdict) -> None:
    if client is None or not line_ok or verdict.total_rub is None:
        verdict.gates.append(Gate("credit", "skip", "Лимит считаем только при известном клиенте и полностью разобранных позициях."))
        if not line_ok:
            verdict.total_rub = None
        return
    total = verdict.total_rub
    if total > client.credit_limit_rub:
        detail = f"Сумма {total} ₽ выше лимита {client.credit_limit_rub} ₽."
        verdict.gates.append(Gate("credit", "fail", detail))
        verdict.reasons.append(Reason("credit_limit", detail))
        return
    verdict.gates.append(Gate("credit", "pass", f"{total} ₽ в пределах лимита {client.credit_limit_rub} ₽."))
