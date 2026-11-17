"""Run the data pipeline from the command line and print the scorecard + change-log summary.

Same code as POST /pipeline/run; handy for checking a new dataset before starting the API.

Run (repo root):
    .\\.venv\\Scripts\\python.exe scripts\\build_scorecard.py
    .\\.venv\\Scripts\\python.exe scripts\\build_scorecard.py --raw data_scale_40/raw --out data/processed
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # allow running as a plain script

from app.core.config import get_settings, resolve_project_path  # noqa: E402
from app.core.exceptions import NimbusError  # noqa: E402
from app.data.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", default=str(s.raw_data_dir), help="raw data folder (default: RAW_DATA_DIR)")
    ap.add_argument("--config", default=str(s.config_dir), help="config folder (default: CONFIG_DIR)")
    ap.add_argument("--out", default=str(s.processed_dir), help="output folder (default: PROCESSED_DIR)")
    args = ap.parse_args()
    try:
        r = run_pipeline(resolve_project_path(args.raw), resolve_project_path(args.config),
                         out_dir=resolve_project_path(args.out))
    except NimbusError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"data version {r.data_version} | as of {r.as_of} | weeks {[w.isoformat() for w in r.weeks]}")
    print(f"{'ID':<9} {'Status':<17} {'Adoption':>9} {'WAU chg':>8} {'ROI':>8} {'Avg/month':>11} "
          f"{'Payback':>13} {'Run-rate':>9}  Name")
    for row in r.scorecard:
        m = row.metrics
        print(f"{row.initiative_id:<9} {row.status:<17} {m['adoption'].display:>9} {m['wau_change'].display:>8} "
              f"{m['roi'].display:>8} {m['avg_monthly_benefit'].display:>11} {m['payback_months'].display:>13} "
              f"{m['run_rate_vs_plan'].display:>9}  {row.name}")
    print(f"\nstatus counts: {dict(Counter(row.status for row in r.scorecard))}")
    print(f"change log: {len(r.change_log)} entries {dict(Counter(e.rule_id for e in r.change_log).most_common())}")
    print(f"outputs written to {resolve_project_path(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
