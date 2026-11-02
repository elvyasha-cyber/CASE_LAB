"""Граница данных. Схема извлечения — контракт модели. Лишние поля, включая цену, отбрасываются."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InboundEmail(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(min_length=1)
    received_at: datetime
    sender: str = Field(alias="from", min_length=3)
    subject: str = ""
    body: str = Field(min_length=1)


class Assumption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str
    detail: str


class LineExtract(BaseModel):
    model_config = ConfigDict(extra="ignore")

    raw_name: str
    sku: str | None = None
    qty: int
    unit: str


class OrderFields(BaseModel):
    """Коммерческие поля заявки внутри fields. Цену модель не назначает."""

    model_config = ConfigDict(extra="ignore")

    client_name: str | None = None
    client_inn: str | None = None
    delivery_address: str | None = None
    requested_date: str | None = None
    comment: str | None = None
    lines: list[LineExtract] = Field(default_factory=list)


class Extraction(BaseModel):
    """Схема курса: структурирование входа + сигнал эскалации. Политика может усилить escalate."""

    model_config = ConfigDict(extra="ignore")

    intent: Literal["order", "not_order", "unclear"]
    category: Literal["sales_order", "non_order", "unclear"] | None = None
    summary: str = ""
    priority: Literal["low", "medium", "high"] = "medium"
    next_action: str = ""
    fields: OrderFields | None = None
    confidence: Literal["low", "medium", "high"]
    escalate: bool = False
    assumptions: list[Assumption] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def fill_defaults(self) -> Extraction:
        if self.category is None:
            mapping = {
                "order": "sales_order",
                "not_order": "non_order",
                "unclear": "unclear",
            }
            self.category = mapping[self.intent]
        return self


class Cassette(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    note: str | None = None
    extraction: Extraction


class GoldenLine(BaseModel):
    sku: str
    qty: int


class Golden(BaseModel):
    message_id: str
    expected_decision: Literal["create_draft", "escalate", "close_no_action"]
    reason_codes: list[str]
    client_id: str | None
    action_id: str
    lines: list[GoldenLine] | None = None
    total_rub: int | None = None
    correction_to_skus: list[str] = Field(default_factory=list)
