"""
Throwaway reference cleaner: proves a generated dataset can be cleaned back to its answer key.

This is NOT the application pipeline. It exists only to check that the generator's raw files
are solvable with the documented rules. The real pipeline (app/data, app/scorecard) must pass
the same comparison.

Run:  python scripts/verify_practice_data.py data
      python scripts/verify_practice_data.py data_scale_40
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dateutil import parser as dp

AS_OF = pd.Timestamp("2026-11-15")
BENEFIT = {"benefit_to_date", "Benefit to date", "realised_benefit", "value_delivered"}
COST = {"cost_to_date", "Cost to date", "total_cost", "spend", "monthly_cost"}


def norm_id(x) -> str:
    return f"INIT-{int(re.findall(r'\d+', str(x))[0]):03d}"


def num(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace("$", "").replace(",", "")
    mult = 1000 if s.lower().endswith("k") else 1
    return float(s.rstrip("kK")) * mult


def parse_date(x) -> pd.Timestamp:
    s = str(x).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):          # ISO first: dayfirst=True would misread it
        return pd.Timestamp(s[:10])
    return pd.Timestamp(dp.parse(s, dayfirst=True))


def main(folder: str) -> None:
    root = Path(folder)
    ini = pd.read_csv(root / "raw/initiatives.csv")
    ini["initiative_id"] = ini.initiative_id.map(norm_id)
    for c in ("licensed_users", "planned_annual_benefit"):
        ini[c] = ini[c].map(num)
    ini["go_live_date"] = ini.go_live_date.map(parse_date)

    u = pd.read_csv(root / "raw/weekly_usage.csv").drop_duplicates()
    u["initiative_id"] = u.initiative_id.map(norm_id)
    u["week_start"] = u.week_start.map(parse_date)
    u["value"] = u.value.map(num).abs()
    u = u.merge(ini[["initiative_id", "licensed_users"]])
    u = u[u.value <= u.licensed_users]

    f = pd.read_excel(root / "raw/financials.xlsx")
    f["initiative_id"] = f.initiative_id.map(norm_id)
    f["value"] = f.value.map(num)
    f.loc[f.unit.astype(str).str.contains("000"), "value"] *= 1000
    f["report_date"] = f.report_date.map(parse_date)
    f = f[f.report_date <= AS_OF]
    benefit = f[f.measure.isin(BENEFIT)].groupby("initiative_id").value.sum()
    cost = f[f.measure.isin(COST)].groupby("initiative_id").value.sum()

    rows = []
    for _, r in ini.iterrows():
        w = u[u.initiative_id == r.initiative_id].sort_values("week_start").value.tolist()
        months = (AS_OF - r.go_live_date).days / 30.44
        b, c = benefit.get(r.initiative_id, 0.0), cost[r.initiative_id]
        avg = b / months
        rows.append(dict(initiative_id=r.initiative_id, adoption=w[-1] / r.licensed_users,
                         wau_change=(w[-1] - w[0]) / w[0], roi=(b - c) / c, avg_monthly_benefit=avg,
                         payback_months=(c / avg if avg else np.nan),
                         run_rate_vs_plan=avg * 12 / r.planned_annual_benefit))
    got = pd.DataFrame(rows).set_index("initiative_id").sort_index()
    exp = pd.read_csv(root / "answer_key/expected_scorecard.csv").set_index("initiative_id").sort_index()[got.columns]
    diff = (got - exp).abs().max().max()
    print(f"{folder}: {len(got)} initiatives, max abs difference vs answer key = {diff:.2e}")
    assert diff < 1e-6, "MISMATCH"
    print("OK: raw files clean back to the expected scorecard")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")
