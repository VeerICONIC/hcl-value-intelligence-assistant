"""Cleaning rules on deliberately damaged copies of data/raw (including rules the practice data never triggers).

Each test copies the 8-initiative raw files to a temp folder, breaks one thing, runs the
real pipeline and checks two promises: the problem is in the change log, and the affected
metric is ``None`` with a reason (never a guessed value).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from app.core.exceptions import DataValidationError
from app.data.pipeline import run_pipeline

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config"


@pytest.fixture
def raw(tmp_path) -> Path:
    d = tmp_path / "raw"
    shutil.copytree(REPO / "data" / "raw", d, ignore=shutil.ignore_patterns(".gitkeep"))
    return d


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def edit_usage(raw: Path, fn) -> None:
    p = raw / "weekly_usage.csv"
    fn(read_csv(p)).to_csv(p, index=False)


def edit_financials(raw: Path, fn) -> None:
    p = raw / "financials.xlsx"
    fn(pd.read_excel(p, dtype=str, keep_default_na=False)).to_excel(p, sheet_name="financials", index=False)


def edit_initiatives(raw: Path, fn) -> None:
    p = raw / "initiatives.csv"
    fn(read_csv(p)).to_csv(p, index=False)


def run(raw: Path):
    return run_pipeline(raw, CONFIG)


def row(result, iid):
    return next(r for r in result.scorecard if r.initiative_id == iid)


def entries(result, rule, iid=None):
    return [e for e in result.change_log if e.rule_id == rule and (iid is None or e.initiative_id == iid)]


def test_wau_above_licensed_in_latest_week_gives_none_not_a_guess(raw):
    def f(df):
        df.loc[(df.initiative_id == "INIT-001") & (df.week_start == "2026-11-09"), "value"] = "5000"
        return df
    edit_usage(raw, f)
    r = run(raw)
    adoption = row(r, "INIT-001").metrics["adoption"]
    assert adoption.value is None and "above 1000 licensed users" in adoption.note
    assert row(r, "INIT-001").metrics["wau_change"].value is None
    assert row(r, "INIT-001").status == "Insufficient data"
    [e] = entries(r, "WAU_ABOVE_LICENSED", "INIT-001")
    assert "latest week" in e.effect


def test_missing_latest_week_gives_none(raw):
    edit_usage(raw, lambda df: df[~((df.initiative_id == "INIT-006") & (df.week_start == "2026-11-09"))])
    r = run(raw)
    assert row(r, "INIT-006").metrics["adoption"].value is None
    [e] = entries(r, "MISSING_WEEK", "INIT-006")
    assert e.effect.startswith("Week missing: adoption")


def test_unknown_metric_name_is_excluded(raw):
    def f(df):
        df.loc[(df.initiative_id == "INIT-001") & (df.week_start == "2026-10-26"), "metric_name"] = "Monthly users"
        return df
    edit_usage(raw, f)
    r = run(raw)
    assert entries(r, "UNKNOWN_MEASURE", "INIT-001")
    assert row(r, "INIT-001").metrics["wau_change"].value is None     # first week gone -> None


def test_conflicting_duplicate_excludes_both(raw):
    extra = pd.DataFrame([{"initiative_id": "INIT-006", "week_start": "2026-11-09",
                           "metric_name": "weekly_active_users", "value": "999"}])
    edit_usage(raw, lambda df: pd.concat([df, extra], ignore_index=True))
    r = run(raw)
    assert len(entries(r, "CONFLICTING_VALUES", "INIT-006")) == 2
    assert row(r, "INIT-006").metrics["adoption"].value is None


def test_duplicate_after_normalisation_is_dropped(raw):
    extra = pd.DataFrame([{"initiative_id": "init_6", "week_start": "09/11/2026",
                           "metric_name": "WAU", "value": "126"}])
    edit_usage(raw, lambda df: pd.concat([df, extra], ignore_index=True))
    r = run(raw)
    assert entries(r, "DUPLICATE_ROW", "INIT-006")
    assert row(r, "INIT-006").metrics["adoption"].value == pytest.approx(126 / 200)


def test_unknown_initiative_in_financials(raw):
    extra = pd.DataFrame([{"initiative_id": "INIT-099", "report_date": "2026-11-15", "measure": "cost_to_date",
                           "value": "1000", "unit": "USD", "basis": "cumulative"}])
    edit_financials(raw, lambda df: pd.concat([df, extra], ignore_index=True))
    r = run(raw)
    assert entries(r, "UNKNOWN_INITIATIVE", "INIT-099")
    assert len(r.scorecard) == 8


def test_monthly_row_after_as_of_is_excluded(raw):
    extra = pd.DataFrame([{"initiative_id": "INIT-002", "report_date": "2026-11-30", "measure": "monthly_cost",
                           "value": "20000", "unit": "USD", "basis": "monthly"}])
    edit_financials(raw, lambda df: pd.concat([df, extra], ignore_index=True))
    r = run(raw)
    assert entries(r, "AFTER_AS_OF", "INIT-002")
    assert row(r, "INIT-002").metrics["roi"].inputs["cost_to_date"] == 220000


def test_mixed_cost_basis_is_not_guessed(raw):
    extra = pd.DataFrame([{"initiative_id": "INIT-002", "report_date": "2026-11-15", "measure": "cost_to_date",
                           "value": "230000", "unit": "USD", "basis": "cumulative"}])
    edit_financials(raw, lambda df: pd.concat([df, extra], ignore_index=True))
    r = run(raw)
    assert entries(r, "CONFLICTING_VALUES", "INIT-002")
    roi = row(r, "INIT-002").metrics["roi"]
    assert roi.value is None and "both cumulatively and monthly" in roi.note


def test_older_cumulative_report_is_superseded_not_added(raw):
    extra = pd.DataFrame([{"initiative_id": "INIT-001", "report_date": "2026-06-30", "measure": "Cost to date",
                           "value": "100000", "unit": "USD", "basis": "cumulative"}])
    edit_financials(raw, lambda df: pd.concat([df, extra], ignore_index=True))
    r = run(raw)
    assert entries(r, "CUMULATIVE_SUPERSEDED", "INIT-001")
    assert row(r, "INIT-001").metrics["roi"].inputs["cost_to_date"] == 180000


def test_negative_money_is_excluded_not_flipped(raw):
    def f(df):
        df.loc[(df.initiative_id == "INIT-004") & (df.measure == "total_cost"), "value"] = "-90000"
        return df
    edit_financials(raw, f)
    r = run(raw)
    assert any(e.column == "value" for e in entries(r, "INVALID_VALUE", "INIT-004"))
    assert row(r, "INIT-004").metrics["roi"].value is None


def test_unsupported_currency_is_not_converted(raw):
    def f(df):
        df.loc[df.initiative_id == "INIT-004", "currency"] = "INR"
        return df
    edit_initiatives(raw, f)
    r = run(raw)
    run_rate = row(r, "INIT-004").metrics["run_rate_vs_plan"]
    assert run_rate.value is None and "INR" in run_rate.note
    assert entries(r, "INVALID_VALUE", "INIT-004")


def test_unreadable_go_live_date(raw):
    def f(df):
        df.loc[df.initiative_id == "INIT-003", "go_live_date"] = "sometime in 2026"
        return df
    edit_initiatives(raw, f)
    r = run(raw)
    months = row(r, "INIT-003").metrics["months_live"]
    assert months.value is None and "cannot be read" in months.note
    assert row(r, "INIT-003").metrics["roi"].value is not None    # unrelated metrics still computed


def test_missing_required_column_fails_clearly(raw):
    edit_usage(raw, lambda df: df.drop(columns=["value"]))
    with pytest.raises(DataValidationError, match="missing required column"):
        run(raw)


def test_missing_file_fails_clearly(raw):
    (raw / "financials.xlsx").unlink()
    with pytest.raises(DataValidationError, match="financials.xlsx"):
        run(raw)
