"""Governed formulas, edge cases (None + reason, never a guess) and the status rule boundaries."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.yaml_config import GreenRule, RedRule, StatusRules
from app.scorecard import metrics as m
from app.scorecard.status import evaluate_status

S = m.Sourced
RULES = StatusRules(red_if_any=RedRule(adoption_below=0.30, roi_below=0.0),
                    green_if_all=GreenRule(adoption_at_least=0.60, roi_above=0.0))


def test_adoption_and_provenance():
    mv = m.adoption("INIT-001", S(720, ("weekly_usage.csv row 6",)), S(1000, ("initiatives.csv row 2",)))
    assert mv.value == 0.72 and mv.display == "72.0%"
    assert mv.inputs == {"latest_week_wau": 720, "licensed_users": 1000}
    assert mv.source_refs == ["weekly_usage.csv row 6", "initiatives.csv row 2"]
    assert mv.formula == m.FORMULAS["adoption"]


def test_wau_change_signed_display():
    assert m.wau_change("X", S(640), S(720)).display == "+12.5%"
    assert m.wau_change("X", S(130), S(110)).display == "-15.4%"


def test_roi_zero_has_no_sign():
    mv = m.roi("X", S(160000), S(160000))
    assert mv.value == 0.0 and mv.display == "0.0%"


def test_roi_cost_zero_is_none_with_reason():
    mv = m.roi("X", S(100), S(0))
    assert mv.value is None and mv.note == "cost to date is 0" and mv.display == m.NOT_AVAILABLE


def test_missing_input_carries_its_reason():
    mv = m.adoption("X", S(None, note="latest-week WAU is not usable: above licensed users"), S(100))
    assert mv.value is None and "above licensed users" in mv.note


def test_payback_not_reached_when_benefit_zero():
    mv = m.payback_months("INIT-008", S(210000), S(0.0))
    assert mv.value is None and mv.display == m.NOT_REACHED


def test_months_live_and_chain():
    months = m.months_live("X", date(2025, 11, 15), ("initiatives.csv row 2",), None, date(2026, 11, 15), 30.44)
    assert months.value == pytest.approx(365 / 30.44)
    avg = m.avg_monthly_benefit("X", S(300000), m.as_sourced(months))
    assert avg.value == pytest.approx(300000 / (365 / 30.44))
    assert "initiatives.csv row 2" in avg.source_refs     # provenance flows through the chain
    run = m.run_rate_vs_plan("X", m.as_sourced(avg), S(320000))
    assert run.value == pytest.approx(avg.value * 12 / 320000)


def test_months_live_go_live_after_as_of():
    mv = m.months_live("X", date(2027, 1, 1), (), None, date(2026, 11, 15), 30.44)
    assert mv.value is None and "after the as-of date" in mv.note


def _status(adoption, roi):
    a = m.MetricValue(initiative_id="X", metric="adoption", value=adoption, display="a", formula="", inputs={},
                      source_refs=[], note=None if adoption is not None else "no WAU")
    r = m.MetricValue(initiative_id="X", metric="roi", value=roi, display="r", formula="", inputs={},
                      source_refs=[], note=None if roi is not None else "no cost")
    return evaluate_status(a, r, RULES)[0]


@pytest.mark.parametrize("adoption, roi, expected", [
    (0.72, 0.67, "Green"),
    (0.60, 0.01, "Green"),      # adoption exactly 60% counts as Green
    (0.63, 0.0, "Amber"),       # ROI exactly 0 is not "above 0" -> Amber (INIT-006)
    (0.30, 0.5, "Amber"),       # adoption exactly 30% is not "below 30%"
    (0.2999, 0.5, "Red"),
    (0.68, -0.25, "Red"),       # negative ROI despite good adoption (INIT-005)
    (0.22, 0.56, "Red"),        # low adoption despite positive ROI (INIT-004)
    (None, 0.5, "Insufficient data"),
    (0.5, None, "Insufficient data"),
])
def test_status_rule(adoption, roi, expected):
    assert _status(adoption, roi) == expected


def test_status_reason_quotes_display_values():
    a = m.adoption("X", S(110), S(500))
    r = m.roi("X", S(140000), S(90000))
    status, reason = evaluate_status(a, r, RULES)
    assert status == "Red" and reason == "Red: adoption 22.0% is below 30%"
