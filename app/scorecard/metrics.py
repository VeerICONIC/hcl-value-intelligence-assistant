"""The governed metric formulas (problem_statement.md §4, FR-03).

One pure function per metric. Each returns a ``MetricValue`` that carries the value, the
formula, every input with its source rows, a display string formatted **once, here**, and
a ``note`` explaining why the value is ``None`` when it cannot be computed. Nothing is
ever guessed: a missing or zero denominator gives ``None`` + a reason.

This module is the only place a portfolio number is computed (principle 1, D5): the
assistant later displays ``MetricValue.display`` strings, it never calculates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.schemas import MetricValue

METRIC_ORDER = ["months_live", "adoption", "wau_change", "roi",
                "avg_monthly_benefit", "payback_months", "run_rate_vs_plan"]

METRIC_LABELS = {
    "months_live": "months live",
    "adoption": "adoption",
    "wau_change": "WAU change",
    "roi": "ROI",
    "avg_monthly_benefit": "average monthly benefit",
    "payback_months": "payback",
    "run_rate_vs_plan": "run-rate vs plan",
}

FORMULAS = {
    "months_live": "(as-of date - go-live date) in days / days per month",
    "adoption": "latest-week weekly active users / licensed users",
    "wau_change": "(latest-week WAU - first-week WAU) / first-week WAU",
    "roi": "(benefit to date - cost to date) / cost to date",
    "avg_monthly_benefit": "benefit to date / months live",
    "payback_months": "cost to date / average monthly benefit",
    "run_rate_vs_plan": "(average monthly benefit x 12) / planned annual benefit",
}

NOT_AVAILABLE = "Not available"
NOT_REACHED = "Not reached"


@dataclass(frozen=True)
class Sourced:
    """An input value with provenance. ``note`` says why ``value`` is None."""

    value: float | None
    refs: tuple[str, ...] = ()
    note: str | None = None


# --- display formatting (the only place numbers become text) -----------------------
def fmt_pct(v: float, signed: bool = False) -> str:
    return f"{v * 100:+.1f}%" if signed else f"{v * 100:.1f}%"


def fmt_money(v: float) -> str:
    return f"${v:,.0f}"


def fmt_months(v: float) -> str:
    return f"{v:.1f} months"


# --- helpers -----------------------------------------------------------------------
def _refs(*inputs: Sourced) -> list[str]:
    seen: list[str] = []
    for s in inputs:
        for r in s.refs:
            if r not in seen:
                seen.append(r)
    return seen


def _make(iid: str, metric: str, value: float | None, display: str,
          inputs: dict[str, Sourced], note: str | None = None) -> MetricValue:
    return MetricValue(initiative_id=iid, metric=metric, value=value, display=display,
                       formula=FORMULAS[metric], inputs={k: s.value for k, s in inputs.items()},
                       source_refs=_refs(*inputs.values()), note=note)


def _missing_input(iid: str, metric: str, inputs: dict[str, Sourced]) -> MetricValue | None:
    """``None``-valued MetricValue if any input is missing, else None."""
    for name, s in inputs.items():
        if s.value is None:
            why = s.note or f"{name.replace('_', ' ')} is not available"
            return _make(iid, metric, None, NOT_AVAILABLE, inputs, note=why)
    return None


def as_sourced(mv: MetricValue) -> Sourced:
    """Use a computed metric as the input of another (keeps its sources and its reason)."""
    return Sourced(mv.value, tuple(mv.source_refs), mv.note)


# --- the metrics -------------------------------------------------------------------
def months_live(iid: str, go_live: date | None, go_live_refs: tuple[str, ...], go_live_note: str | None,
                as_of: date, days_per_month: float) -> MetricValue:
    """Assumption A1: fractional months from go-live to the as-of date."""
    if go_live is None:
        return _make(iid, "months_live", None, NOT_AVAILABLE,
                     {"days_live": Sourced(None, go_live_refs), "days_per_month": Sourced(days_per_month)},
                     note=go_live_note or "go-live date is not available")
    days = float((as_of - go_live).days)
    inputs = {"days_live": Sourced(days, go_live_refs), "days_per_month": Sourced(days_per_month)}
    if days < 0:
        return _make(iid, "months_live", None, NOT_AVAILABLE, inputs,
                     note=f"go-live date {go_live.isoformat()} is after the as-of date {as_of.isoformat()}")
    value = days / days_per_month
    return _make(iid, "months_live", value, fmt_months(value), inputs,
                 note=f"from go-live {go_live.isoformat()} to as-of {as_of.isoformat()} (assumption A1)")


def adoption(iid: str, latest_wau: Sourced, licensed_users: Sourced) -> MetricValue:
    inputs = {"latest_week_wau": latest_wau, "licensed_users": licensed_users}
    if (m := _missing_input(iid, "adoption", inputs)) is not None:
        return m
    if licensed_users.value <= 0:
        return _make(iid, "adoption", None, NOT_AVAILABLE, inputs, note="licensed users is 0")
    value = latest_wau.value / licensed_users.value
    return _make(iid, "adoption", value, fmt_pct(value), inputs)


def wau_change(iid: str, first_wau: Sourced, latest_wau: Sourced) -> MetricValue:
    inputs = {"first_week_wau": first_wau, "latest_week_wau": latest_wau}
    if (m := _missing_input(iid, "wau_change", inputs)) is not None:
        return m
    if first_wau.value == 0:
        return _make(iid, "wau_change", None, NOT_AVAILABLE, inputs, note="first-week WAU is 0")
    value = (latest_wau.value - first_wau.value) / first_wau.value
    return _make(iid, "wau_change", value, fmt_pct(value, signed=True), inputs)


def roi(iid: str, benefit: Sourced, cost: Sourced) -> MetricValue:
    inputs = {"benefit_to_date": benefit, "cost_to_date": cost}
    if (m := _missing_input(iid, "roi", inputs)) is not None:
        return m
    if cost.value <= 0:
        return _make(iid, "roi", None, NOT_AVAILABLE, inputs, note="cost to date is 0")
    value = (benefit.value - cost.value) / cost.value
    return _make(iid, "roi", value, fmt_pct(value, signed=True), inputs)


def avg_monthly_benefit(iid: str, benefit: Sourced, months: Sourced) -> MetricValue:
    inputs = {"benefit_to_date": benefit, "months_live": months}
    if (m := _missing_input(iid, "avg_monthly_benefit", inputs)) is not None:
        return m
    if months.value <= 0:
        return _make(iid, "avg_monthly_benefit", None, NOT_AVAILABLE, inputs,
                     note="the initiative has not been live before the as-of date")
    value = benefit.value / months.value
    return _make(iid, "avg_monthly_benefit", value, fmt_money(value), inputs)


def payback_months(iid: str, cost: Sourced, avg_benefit: Sourced) -> MetricValue:
    inputs = {"cost_to_date": cost, "avg_monthly_benefit": avg_benefit}
    if (m := _missing_input(iid, "payback_months", inputs)) is not None:
        return m
    if avg_benefit.value <= 0:
        return _make(iid, "payback_months", None, NOT_REACHED, inputs,
                     note="average monthly benefit is 0, so the cost is not paid back at the current rate")
    value = cost.value / avg_benefit.value
    return _make(iid, "payback_months", value, fmt_months(value), inputs)


def run_rate_vs_plan(iid: str, avg_benefit: Sourced, planned_annual_benefit: Sourced) -> MetricValue:
    inputs = {"avg_monthly_benefit": avg_benefit, "planned_annual_benefit": planned_annual_benefit}
    if (m := _missing_input(iid, "run_rate_vs_plan", inputs)) is not None:
        return m
    if planned_annual_benefit.value <= 0:
        return _make(iid, "run_rate_vs_plan", None, NOT_AVAILABLE, inputs, note="planned annual benefit is 0")
    value = avg_benefit.value * 12 / planned_annual_benefit.value
    return _make(iid, "run_rate_vs_plan", value, fmt_pct(value), inputs)
