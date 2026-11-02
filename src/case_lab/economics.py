"""Окупаемость пилота. Цифры считаются из явных вводных, а не из контрольного ящика."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from case_lab.loaders import read_json


class EconomicsError(ValueError):
    pass


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    share_auto: Decimal
    labor_saved_rub: int
    error_saved_rub: int
    gross_rub: int
    net_rub: int
    payback_months: Decimal | None


@dataclass(frozen=True)
class EconomicsReport:
    orders_per_month: int
    labor_baseline_rub: int
    error_baseline_rub: int
    monthly_opex_rub: int
    pilot_fixed_rub: int
    monthly_model_cost_rub: int
    monthly_support_cost_rub: int
    interpretation: str
    scenarios: tuple[Scenario, ...]


def load_economics(path: Path) -> EconomicsReport:
    raw = read_json(path)
    orders_per_day = _positive_int(raw["orders_per_day"], "orders_per_day")
    workdays = _positive_int(raw["workdays_per_month"], "workdays_per_month")
    minutes_manual = _positive_int(raw["minutes_manual"], "minutes_manual")
    minutes_auto = _non_negative_int(raw["minutes_auto_review"], "minutes_auto_review")
    minutes_escalation = _non_negative_int(raw["minutes_escalation"], "minutes_escalation")
    rate = _positive_int(raw["loaded_hourly_rate_rub"], "loaded_hourly_rate_rub")
    baseline_error = _rate(raw["baseline_error_rate"], "baseline_error_rate")
    costly_share = _rate(raw["share_errors_costly"], "share_errors_costly")
    error_cost = _positive_int(raw["cost_per_costly_error_rub"], "cost_per_costly_error_rub")
    auto_error = _rate(raw["auto_residual_error_rate"], "auto_residual_error_rate")
    escalation_error = _rate(raw["escalation_error_rate"], "escalation_error_rate")
    pilot = _positive_int(raw["pilot_fixed_cost_rub"], "pilot_fixed_cost_rub")
    model_cost = _non_negative_int(raw["monthly_model_cost_rub"], "monthly_model_cost_rub")
    support_cost = _non_negative_int(raw["monthly_support_cost_rub"], "monthly_support_cost_rub")

    orders = orders_per_day * workdays
    minute_cost = Decimal(rate) / Decimal(60)
    labor_baseline = _rub(Decimal(orders) * Decimal(minutes_manual) * minute_cost)
    error_baseline = _rub(Decimal(orders) * baseline_error * costly_share * Decimal(error_cost))
    opex = model_cost + support_cost
    scenarios = []
    for item in raw["scenarios"]:
        share_auto = _rate(item["share_auto"], item["id"])
        mix_minutes = share_auto * Decimal(minutes_auto) + (Decimal(1) - share_auto) * Decimal(minutes_escalation)
        labor_new = _rub(Decimal(orders) * mix_minutes * minute_cost)
        labor_saved = labor_baseline - labor_new
        blended = share_auto * auto_error + (Decimal(1) - share_auto) * escalation_error
        error_new = _rub(Decimal(orders) * blended * costly_share * Decimal(error_cost))
        error_saved = error_baseline - error_new
        gross = labor_saved + error_saved
        net = gross - opex
        payback = None
        if net > 0:
            payback = (Decimal(pilot) / Decimal(net)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        scenarios.append(
            Scenario(
                id=item["id"],
                title=item["title"],
                share_auto=share_auto,
                labor_saved_rub=labor_saved,
                error_saved_rub=error_saved,
                gross_rub=gross,
                net_rub=net,
                payback_months=payback,
            )
        )
    return EconomicsReport(
        orders_per_month=orders,
        labor_baseline_rub=labor_baseline,
        error_baseline_rub=error_baseline,
        monthly_opex_rub=opex,
        pilot_fixed_rub=pilot,
        monthly_model_cost_rub=model_cost,
        monthly_support_cost_rub=support_cost,
        interpretation=raw["interpretation"],
        scenarios=tuple(scenarios),
    )


def _rub(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _rate(value, name: str) -> Decimal:
    number = Decimal(str(value))
    if number < 0 or number > 1:
        raise EconomicsError(f"{name} должен быть от 0 до 1.")
    return number


def _positive_int(value, name: str) -> int:
    number = int(value)
    if number <= 0:
        raise EconomicsError(f"{name} должен быть больше нуля.")
    return number


def _non_negative_int(value, name: str) -> int:
    number = int(value)
    if number < 0:
        raise EconomicsError(f"{name} не может быть отрицательным.")
    return number
