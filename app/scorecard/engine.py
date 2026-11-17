"""Scorecard engine: governed inputs per initiative -> one ``ScorecardRow`` each (FR-03).

The engine only wires metric functions together in dependency order
(months live -> average monthly benefit -> payback / run-rate) and applies the status
rule. All arithmetic lives in ``metrics.py``; all thresholds in config/status_rules.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from app.core.yaml_config import StatusRules
from app.schemas import ScorecardRow
from app.scorecard import metrics as m
from app.scorecard.status import evaluate_status


@dataclass(frozen=True)
class InitiativeInputs:
    """Everything the formulas need for one initiative, each value with its sources."""

    initiative_id: str
    name: str
    go_live: date | None
    go_live_refs: tuple[str, ...]
    go_live_note: str | None
    licensed_users: m.Sourced
    planned_annual_benefit: m.Sourced
    first_week_wau: m.Sourced
    latest_week_wau: m.Sourced
    benefit_to_date: m.Sourced
    cost_to_date: m.Sourced


def score_initiative(inp: InitiativeInputs, as_of: date, days_per_month: float,
                     rules: StatusRules) -> ScorecardRow:
    iid = inp.initiative_id
    months = m.months_live(iid, inp.go_live, inp.go_live_refs, inp.go_live_note, as_of, days_per_month)
    adoption = m.adoption(iid, inp.latest_week_wau, inp.licensed_users)
    wau = m.wau_change(iid, inp.first_week_wau, inp.latest_week_wau)
    roi = m.roi(iid, inp.benefit_to_date, inp.cost_to_date)
    avg = m.avg_monthly_benefit(iid, inp.benefit_to_date, m.as_sourced(months))
    payback = m.payback_months(iid, inp.cost_to_date, m.as_sourced(avg))
    run_rate = m.run_rate_vs_plan(iid, m.as_sourced(avg), inp.planned_annual_benefit)
    status, reason = evaluate_status(adoption, roi, rules)
    metrics = {"months_live": months, "adoption": adoption, "wau_change": wau, "roi": roi,
               "avg_monthly_benefit": avg, "payback_months": payback, "run_rate_vs_plan": run_rate}
    return ScorecardRow(initiative_id=iid, name=inp.name, metrics=metrics, status=status, status_reason=reason)


def build_scorecard(inputs: list[InitiativeInputs], as_of: date, days_per_month: float,
                    rules: StatusRules) -> list[ScorecardRow]:
    rows = [score_initiative(i, as_of, days_per_month, rules) for i in inputs]
    return sorted(rows, key=lambda r: r.initiative_id)


def scorecard_frame(rows: list[ScorecardRow]) -> pd.DataFrame:
    """Flat table: same columns as answer_key/expected_scorecard.csv, plus status_reason.

    Values are full precision (rounding is for display only); undefined values are empty.
    """
    records = []
    for r in rows:
        rec: dict = {"initiative_id": r.initiative_id, "name": r.name}
        rec.update({k: r.metrics[k].value for k in m.METRIC_ORDER})
        rec.update({"status": r.status, "status_reason": r.status_reason})
        records.append(rec)
    cols = ["initiative_id", "name", *m.METRIC_ORDER, "status", "status_reason"]
    return pd.DataFrame.from_records(records, columns=cols)
