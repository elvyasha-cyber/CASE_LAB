from datetime import date, timedelta

from case_lab.gates import evaluate
from case_lab.resolve import match_skus
from case_lab.textutil import is_blocking_assumption

from tests.support import extraction, mail


def test_assumption_token_is_a_whole_word():
    assert is_blocking_assumption("lines[0].qty")
    assert is_blocking_assumption("requested_date")
    assert not is_blocking_assumption("comment")
    assert not is_blocking_assumption("updated comment")


def test_specific_paper_wins_over_generic_name(catalog):
    assert match_skus("бумага А4 «Север 500»", catalog) == ["SKU-A4-500"]
    assert match_skus("север премьер", catalog) == ["SKU-A4-PREM"]


def test_generic_paper_stays_ambiguous(catalog):
    hits = match_skus("бумаги А4", catalog)
    assert hits == ["SKU-A4-500", "SKU-A4-PREM"]


def test_clean_order_becomes_draft_and_ignores_invented_price(catalog, registry, policy):
    verdict = evaluate(mail(), extraction(), catalog, registry, policy)
    assert verdict.decision == "create_draft"
    assert verdict.escalate is False
    assert verdict.total_rub == 4200
    assert verdict.lines[0].price_rub == 420


def test_high_confidence_does_not_approve_an_assumption(catalog, registry, policy):
    payload = extraction(
        confidence="high",
        assumptions=[{"field": "lines[0].qty", "detail": "количество не было в письме"}],
    )
    verdict = evaluate(mail(), payload, catalog, registry, policy)
    assert verdict.decision == "escalate"
    assert verdict.escalate is True
    assert verdict.next_action == "передать менеджеру"
    assert verdict.reason_codes == ["assumption_blocking"]


def test_service_note_does_not_block(catalog, registry, policy):
    payload = extraction(assumptions=[{"field": "comment", "detail": "просили позвонить после отгрузки"}])
    verdict = evaluate(mail(), payload, catalog, registry, policy)
    assert verdict.decision == "create_draft"
    assert verdict.notes


def test_low_confidence_blocks_a_clean_order(catalog, registry, policy):
    verdict = evaluate(mail(), extraction(confidence="low", escalate=True), catalog, registry, policy)
    assert verdict.decision == "escalate"
    assert "low_confidence" in verdict.reason_codes

    exact = evaluate(mail(), extraction(confidence="medium"), catalog, registry, policy)
    assert exact.decision == "create_draft"


def test_data_gaps_force_escalation(catalog, registry, policy):
    verdict = evaluate(
        mail(),
        extraction(data_gaps=["нет даты поставки"], escalate=True),
        catalog,
        registry,
        policy,
    )
    assert verdict.decision == "escalate"
    assert "data_gaps" in verdict.reason_codes


def test_unknown_client_stops_even_when_the_model_is_sure(catalog, registry, policy):
    payload = extraction()
    payload.fields.client_name = "ООО «Ромашка»"
    payload.fields.client_inn = "7701000000"
    verdict = evaluate(
        mail(sender="info@romashka.example"),
        payload,
        catalog,
        registry,
        policy,
    )
    assert verdict.decision == "escalate"
    assert verdict.reason_codes == ["client_unresolved"]
    assert verdict.client is None


def test_contradictory_inn_is_a_conflict(catalog, registry, policy):
    payload = extraction()
    payload.fields.client_inn = "7802000002"
    verdict = evaluate(mail(), payload, catalog, registry, policy)
    assert verdict.reason_codes == ["client_conflict"]


def test_missing_address_is_not_scraped_from_the_body(catalog, registry, policy):
    payload = extraction()
    payload.fields.delivery_address = None
    body = "Привезите на Лиговский 50, это точно написано в теле письма."
    verdict = evaluate(mail(body=body), payload, catalog, registry, policy)
    assert verdict.reason_codes == ["address_missing"]
    assert verdict.decision == "escalate"


def test_address_outside_the_client_card(catalog, registry, policy):
    payload = extraction()
    payload.fields.client_name = "ИП Морозова А.В."
    payload.fields.client_inn = "470300000002"
    payload.fields.delivery_address = "Ленина 8"
    verdict = evaluate(mail(sender="morozova@morozova.example"), payload, catalog, registry, policy)
    assert verdict.reason_codes == ["address_unresolved"]


def test_hallucinated_sku_is_corrected_only_when_the_name_is_unique(catalog, registry, policy):
    payload = extraction()
    payload.fields.client_name = "ООО «Невский Порт Сервис»"
    payload.fields.client_inn = "7802000002"
    payload.fields.delivery_address = "Канонерский 5"
    payload.fields.lines[0].raw_name = "картридж аналог CE285A"
    payload.fields.lines[0].sku = "SKU-TONER-XYZ"
    payload.fields.lines[0].unit = "шт"
    payload.fields.lines[0].qty = 2
    verdict = evaluate(mail(sender="supply@port-service.example"), payload, catalog, registry, policy)
    assert verdict.decision == "create_draft"
    assert verdict.lines[0].sku == "SKU-TONER"
    assert verdict.lines[0].price_rub == 2450
    assert verdict.corrections[0].from_sku == "SKU-TONER-XYZ"


def test_model_sku_without_support_in_the_line_text_is_rejected(catalog, registry, policy):
    payload = extraction()
    payload.fields.lines[0].raw_name = "как обычно"
    payload.fields.lines[0].sku = "SKU-A4-500"
    verdict = evaluate(mail(), payload, catalog, registry, policy)
    assert verdict.reason_codes == ["sku_unsupported"]


def test_ambiguous_name_is_not_settled_by_the_model(catalog, registry, policy):
    payload = extraction(confidence="high")
    payload.fields.delivery_address = "Невский 100"
    payload.fields.lines[0].raw_name = "бумаги А4"
    payload.fields.lines[0].sku = "SKU-A4-PREM"
    verdict = evaluate(mail(), payload, catalog, registry, policy)
    assert verdict.reason_codes == ["sku_ambiguous"]
    assert verdict.total_rub is None


def test_sku_and_name_conflict(catalog, registry, policy):
    payload = extraction()
    payload.fields.lines[0].sku = "SKU-MARKER"
    verdict = evaluate(mail(), payload, catalog, registry, policy)
    assert "sku_conflict" in verdict.reason_codes


def test_unit_and_quantity_limits(catalog, registry, policy):
    wrong_unit = extraction()
    wrong_unit.fields.lines[0].unit = "шт"
    assert "unit_mismatch" in evaluate(mail(), wrong_unit, catalog, registry, policy).reason_codes

    too_many = extraction()
    too_many.fields.lines[0].qty = 201
    assert "qty_invalid" in evaluate(mail(), too_many, catalog, registry, policy).reason_codes


def test_credit_limit_allows_the_exact_boundary(catalog, registry, policy):
    from case_lab.domain import build_catalog, build_registry

    tiny_catalog = build_catalog(
        {
            "currency": "RUB",
            "items": [
                {
                    "sku": "SKU-A",
                    "name": "Товар альфа",
                    "unit": "шт",
                    "price_rub": 100,
                    "max_qty": 50,
                    "synonyms": ["товар альфа"],
                }
            ],
        }
    )
    tiny_registry = build_registry(
        [
            {
                "id": "CLT-ONE",
                "legal_name": "ООО «Один»",
                "inn": "7801000001",
                "email_domains": ["one.example"],
                "aliases": [],
                "credit_limit_rub": 1000,
                "addresses": [{"id": "ADDR-1", "full": "Склад 1", "hints": ["склад 1"]}],
            }
        ]
    )
    payload = extraction()
    payload.fields.client_name = "ООО «Один»"
    payload.fields.client_inn = "7801000001"
    payload.fields.delivery_address = "склад 1"
    payload.fields.lines[0].raw_name = "товар альфа"
    payload.fields.lines[0].sku = "SKU-A"
    payload.fields.lines[0].unit = "шт"
    payload.fields.lines[0].qty = 10
    letter = mail(sender="buyer@one.example")
    assert evaluate(letter, payload, tiny_catalog, tiny_registry, policy).decision == "create_draft"

    payload.fields.lines[0].qty = 11
    blocked = evaluate(letter, payload, tiny_catalog, tiny_registry, policy)
    assert blocked.reason_codes == ["credit_limit"]
    assert blocked.total_rub == 1100


def test_dates_use_the_letter_calendar_day(catalog, registry, policy):
    received = date(2026, 10, 26)
    same_day = extraction()
    same_day.fields.requested_date = received.isoformat()
    assert evaluate(mail(), same_day, catalog, registry, policy).decision == "create_draft"

    horizon = extraction()
    horizon.fields.requested_date = (received + timedelta(days=45)).isoformat()
    assert evaluate(mail(), horizon, catalog, registry, policy).decision == "create_draft"

    too_far = extraction()
    too_far.fields.requested_date = (received + timedelta(days=46)).isoformat()
    assert "date_too_far" in evaluate(mail(), too_far, catalog, registry, policy).reason_codes

    unparsed = extraction()
    unparsed.fields.requested_date = "30.10.2026"
    assert "date_unparsed" in evaluate(mail(), unparsed, catalog, registry, policy).reason_codes

    missing = extraction()
    missing.fields.requested_date = None
    assert "date_missing" in evaluate(mail(), missing, catalog, registry, policy).reason_codes


def test_not_an_order_closes_only_when_the_model_is_sure_and_there_are_no_lines(catalog, registry, policy):
    closed = evaluate(
        mail(body="Спасибо, претензий нет."),
        extraction(intent="not_order", category="non_order", confidence="high", fields=None, next_action="закрыть без заказа"),
        catalog,
        registry,
        policy,
    )
    assert closed.decision == "close_no_action"

    unsure = evaluate(
        mail(body="Спасибо, претензий нет."),
        extraction(intent="not_order", category="non_order", confidence="low", escalate=True, fields=None),
        catalog,
        registry,
        policy,
    )
    assert unsure.decision == "escalate"
    assert "low_confidence" in unsure.reason_codes

    conflict = extraction(intent="not_order", category="non_order", confidence="high")
    verdict = evaluate(mail(), conflict, catalog, registry, policy)
    assert "intent_conflict" in verdict.reason_codes
