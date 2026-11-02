from decimal import Decimal

import pytest

from case_lab.economics import EconomicsError, load_economics


def test_roi_matches_the_published_formula(root):
    report = load_economics(root / "data" / "economics.json")
    assert report.orders_per_month == 990
    assert report.labor_baseline_rub == 173250
    assert report.error_baseline_rub == 42768
    assert report.monthly_opex_rub == 35000
    assert report.pilot_fixed_rub == 180000

    target, cautious = report.scenarios
    assert target.labor_saved_rub == 122430
    assert target.error_saved_rub == 27799
    assert target.gross_rub == 150229
    assert target.net_rub == 115229
    assert target.payback_months == Decimal("1.6")

    assert cautious.labor_saved_rub == 108570
    assert cautious.error_saved_rub == 25661
    assert cautious.net_rub == 99231
    assert cautious.payback_months == Decimal("1.8")


def test_rate_outside_the_unit_interval_is_rejected(tmp_path, root):
    raw = (root / "data" / "economics.json").read_text(encoding="utf-8")
    broken = tmp_path / "economics.json"
    broken.write_text(raw.replace('"0.60"', '"1.20"'), encoding="utf-8")
    with pytest.raises(EconomicsError):
        load_economics(broken)
