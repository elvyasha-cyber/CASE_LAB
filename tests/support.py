from case_lab.schemas import Extraction, InboundEmail


def mail(
    body: str = "Просим поставить бумагу.",
    sender: str = "zakup@ladoga-office.example",
    received: str = "2026-10-26T09:00:00+03:00",
    message_id: str = "T-1",
) -> InboundEmail:
    return InboundEmail.model_validate(
        {
            "id": message_id,
            "received_at": received,
            "from": sender,
            "subject": "Заявка",
            "body": body,
        }
    )


def extraction(**overrides) -> Extraction:
    base = {
        "intent": "order",
        "category": "sales_order",
        "summary": "Тестовая заявка на бумагу А4.",
        "priority": "medium",
        "next_action": "создать черновик заказа",
        "confidence": "high",
        "escalate": False,
        "assumptions": [],
        "data_gaps": [],
        "fields": {
            "client_name": "ООО «Ладога Офис»",
            "client_inn": "7801000001",
            "delivery_address": "Лиговский 50",
            "requested_date": "2026-10-30",
            "comment": None,
            "lines": [
                {
                    "raw_name": "бумага А4 «Север 500»",
                    "sku": "SKU-A4-500",
                    "qty": 10,
                    "unit": "пач",
                }
            ],
        },
    }
    base.update(overrides)
    return Extraction.model_validate(base)
