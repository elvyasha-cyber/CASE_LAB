"""Отчёт прогона: решения, совпадение с эталоном и экономика из отдельных вводных."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from case_lab.economics import Scenario, load_economics
from case_lab.loaders import load_goldens, load_policy, project_root, read_jsonl
from case_lab.reasons import DECISION_TITLE, REASON_TITLE


def write_report(out_dir: Path, root: Path | None = None) -> str:
    root = root or project_root()
    records = read_jsonl(out_dir / "audit.jsonl")
    if not records:
        raise FileNotFoundError("Журнал пуст. Сначала выполните прогон.")
    policy = load_policy(root / "data" / "policy.json")
    goldens = load_goldens(root / "data" / "golden")
    economics = load_economics(root / "data" / "economics.json")
    text = render(records, goldens, economics, policy.version, policy.min_confidence)
    path = out_dir / "report.md"
    path.write_text(text, encoding="utf-8")
    return text


def render(records: list[dict], goldens, economics, policy_version: str, min_confidence: str) -> str:
    business = _first_business(records)
    mismatches = compare_to_golden(business, goldens)
    counts = Counter(record["decision"] for record in business.values())
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        "# Прогон кейса «СеверСнаб»",
        "",
        f"Сформирован: {generated}. Политика: {policy_version}.",
        "",
        f"Контрольных писем в эталоне: {len(goldens)}. "
        f"Черновики: {counts['create_draft']}. "
        f"Эскалации: {counts['escalate']}. "
        f"Без заказа: {counts['close_no_action']}.",
        f"Совпадение с эталоном: {len(goldens) - len(mismatches)}/{len(goldens)}.",
        "",
        "Контрольный ящик специально насыщен ошибками. Долю черновиков в нём нельзя подставлять в расчёт окупаемости.",
        "",
        "## Решения",
        "",
        "| Письмо | Решение | Действие | Клиент | Сумма, ₽ | Почему |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for message_id in sorted(business):
        record = business[message_id]
        if record["reasons"]:
            why = ", ".join(REASON_TITLE.get(item["code"], item["code"]) for item in record["reasons"])
        elif record["decision"] == "close_no_action":
            why = "это не заявка"
        else:
            why = "гейты пройдены"
        total = "—" if record["total_rub"] is None else _rub(record["total_rub"])
        lines.append(
            "| {id} | {decision} | {action} | {client} | {total} | {why} |".format(
                id=record["message_id"],
                decision=DECISION_TITLE.get(record["decision"], record["decision"]),
                action=record["action_id"] or "—",
                client=record["client_id"] or "—",
                total=total,
                why=why,
            )
        )

    lines.extend(["", "## Сверх ответа модели", ""])
    corrections = [record for record in business.values() if record["corrections"]]
    if corrections:
        for record in corrections:
            for item in record["corrections"]:
                lines.append(
                    f"- {record['message_id']}: артикул {item['from_sku']} заменён на {item['to_sku']} "
                    "по однозначному названию в каталоге. Цена взята из каталога."
                )
    else:
        lines.append("- Поправок артикула не было.")
    from case_lab.domain import CONFIDENCE_RANK

    stopped = []
    for record in business.values():
        if record["decision"] != "escalate" or record["confidence"] is None:
            continue
        if CONFIDENCE_RANK.get(str(record["confidence"]), -1) < CONFIDENCE_RANK.get(min_confidence, 0):
            continue
        if any(item["code"] == "low_confidence" for item in record["reasons"]):
            continue
        stopped.append(record)
    if stopped:
        lines.append("")
        lines.append("Эскалации при уверенности модели не ниже порога. Самооценка не была основанием для черновика:")
        lines.append("")
        for record in stopped:
            codes = ", ".join(item["code"] for item in record["reasons"])
            lines.append(f"- {record['message_id']}: уверенность {record['confidence']}, стоп по {codes}.")

    lines.extend(["", "## Эталон", ""])
    if mismatches:
        lines.append("Есть расхождения:")
        lines.append("")
        for item in mismatches:
            lines.append(f"- {item}")
    else:
        lines.append("Каждое письмо совпало с золотым решением: действие, причины, клиент, позиции, сумма и поправки артикула.")

    lines.extend(["", "## Экономика", ""])
    lines.append(economics.interpretation)
    lines.append("")
    lines.append(
        f"Поток по вводным: {economics.orders_per_month} заявок в месяц. "
        f"Базовый ФОТ приёма: {_rub(economics.labor_baseline_rub)} ₽. "
        f"Базовые потери от ошибок: {_rub(economics.error_baseline_rub)} ₽. "
        f"Сопровождение и модель: {_rub(economics.monthly_opex_rub)} ₽ в месяц. "
        f"Фикс пилота: {_rub(economics.pilot_fixed_rub)} ₽."
    )
    lines.append("")
    lines.append("| Контур | Доля черновиков | Экономия ФОТ | Меньше потерь | Чистый эффект в месяц | Окупаемость фикса |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for scenario in economics.scenarios:
        lines.append(_scenario_row(scenario))
    repeats = sum(1 for record in records if record["decision"] in {"skip_duplicate", "source_changed"})
    if repeats:
        lines.extend(["", f"Повторных событий в журнале: {repeats}. Первое решение по письму не переписывалось."])
    model = next((record["model"] for record in business.values() if record.get("model")), "—")
    prompt = next((record["prompt_version"] for record in business.values() if record.get("prompt_version")), "—")
    lines.extend(
        [
            "",
            "## Как читать журнал",
            "",
            f"Источник ответа модели в этом прогоне: `{model}`. Версия промпта: `{prompt}`. Temperature: 0.2.",
            "В `audit.jsonl` хранятся вход, результат и статус; плюс отпечаток, гейты и версии.",
            "Черновик лежит в `orders/`, эскалация — в `escalations/`. Поле `posting` везде `forbidden`.",
            "",
        ]
    )
    return "\n".join(lines)


def compare_to_golden(business: dict[str, dict], goldens) -> list[str]:
    mismatches = []
    for golden in goldens:
        record = business.get(golden.message_id)
        if record is None:
            mismatches.append(f"{golden.message_id}: нет решения в журнале.")
            continue
        if record["decision"] != golden.expected_decision:
            mismatches.append(
                f"{golden.message_id}: решение {record['decision']}, ожидалось {golden.expected_decision}."
            )
        actual_reasons = sorted(item["code"] for item in record["reasons"])
        expected_reasons = sorted(golden.reason_codes)
        if actual_reasons != expected_reasons:
            mismatches.append(
                f"{golden.message_id}: причины {actual_reasons}, ожидались {expected_reasons}."
            )
        if record.get("client_id") != golden.client_id:
            mismatches.append(
                f"{golden.message_id}: клиент {record.get('client_id')}, ожидался {golden.client_id}."
            )
        if record.get("action_id") != golden.action_id:
            mismatches.append(
                f"{golden.message_id}: действие {record.get('action_id')}, ожидалось {golden.action_id}."
            )
        if record.get("total_rub") != golden.total_rub:
            mismatches.append(
                f"{golden.message_id}: сумма {record.get('total_rub')}, ожидалась {golden.total_rub}."
            )
        if golden.lines is not None:
            actual_lines = sorted((line["sku"], line["qty"]) for line in record["lines"])
            expected_lines = sorted((line.sku, line.qty) for line in golden.lines)
            if actual_lines != expected_lines:
                mismatches.append(
                    f"{golden.message_id}: позиции {actual_lines}, ожидались {expected_lines}."
                )
        actual_corrections = [item["to_sku"] for item in record["corrections"]]
        if actual_corrections != golden.correction_to_skus:
            mismatches.append(
                f"{golden.message_id}: поправки {actual_corrections}, ожидались {golden.correction_to_skus}."
            )
    return mismatches


def _first_business(records: list[dict]) -> dict[str, dict]:
    chosen: dict[str, dict] = {}
    for record in records:
        if record["decision"] in {"skip_duplicate", "source_changed"}:
            continue
        chosen.setdefault(record["message_id"], record)
    return chosen


def _scenario_row(scenario: Scenario) -> str:
    share = f"{int((scenario.share_auto * 100).to_integral_value())}%"
    payback = "—" if scenario.payback_months is None else str(scenario.payback_months).replace(".", ",")
    return (
        f"| {scenario.title} | {share} | {_rub(scenario.labor_saved_rub)} | "
        f"{_rub(scenario.error_saved_rub)} | {_rub(scenario.net_rub)} | {payback} мес. |"
    )


def _rub(value: int) -> str:
    return f"{value:,}".replace(",", " ")
