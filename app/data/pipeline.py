"""The offline pipeline, end to end (architecture.md §3.1): raw files -> governed scorecard.

    load (config-driven headers) -> clean + normalise (change log) -> to-date totals
    -> scorecard engine -> reported-ROI check -> change-log effects -> data/processed/

One explicit function, no framework (D4). The result object is what the API serves, so the
dashboard and (later) the assistant read the very same scorecard version (D12).

The data version is a hash of the raw files and the config files: the same inputs always
give the same version, and any change to data or rules gives a new one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from app.core.exceptions import ConfigurationError, DataValidationError
from app.core.yaml_config import PipelineConfig, load_pipeline_config
from app.data import cleaning
from app.data.changelog import ChangeLog
from app.data.loader import ROW_COL, load_raw_tables
from app.data.normalize import format_number
from app.schemas import ChangeLogEntry, ScorecardRow
from app.scorecard.engine import InitiativeInputs, build_scorecard, scorecard_frame
from app.scorecard.metrics import Sourced

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    data_version: str
    as_of: date
    raw_dir: Path
    files: dict[str, str]           # "initiatives" | "weekly_usage" | "financials" -> filename
    weeks: list[date]
    initiatives: pd.DataFrame       # cleaned, one row per initiative
    usage: pd.DataFrame             # every usage row kept after exact-duplicate removal, with `included`
    financials: pd.DataFrame        # every valid financial row, with `included`
    scorecard: list[ScorecardRow]
    change_log: list[ChangeLogEntry]

    def scorecard_frame(self) -> pd.DataFrame:
        return scorecard_frame(self.scorecard)

    def change_log_frame(self) -> pd.DataFrame:
        cols = list(ChangeLogEntry.model_fields)
        return pd.DataFrame([e.model_dump() for e in self.change_log], columns=cols)


def opt_float(x) -> float | None:
    """pandas stores None as NaN in numeric columns; turn it back into None (used by the API too)."""
    if x is None:
        return None
    try:
        return None if math.isnan(x) else float(x)
    except TypeError:
        return None


def data_version(raw_paths: list[Path], config_paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in [*raw_paths, *config_paths]:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _wau(usage: pd.DataFrame, iid: str, week: date, label: str, filename: str) -> Sourced:
    rows = usage[(usage["initiative_id"] == iid) & (usage["week_start"] == week)
                 & (usage["metric"] == cleaning.WAU_METRIC)]
    ok = rows[rows["included"]]
    if len(ok) == 1:
        r = ok.iloc[0]
        return Sourced(float(r["value"]), (f"{cleaning.ref(filename, int(r[ROW_COL]))} (week {week.isoformat()})",))
    if not rows.empty:
        notes = "; ".join(n for n in rows["note"] if n)
        return Sourced(None, tuple(cleaning.ref(filename, int(x)) for x in rows[ROW_COL]),
                       note=f"{label} WAU (week {week.isoformat()}) is not usable: {notes}")
    return Sourced(None, note=f"no {label} WAU row for the week starting {week.isoformat()}")


def _build_inputs(ini: pd.DataFrame, usage: pd.DataFrame, weeks: list[date],
                  totals: dict[str, cleaning.FinancialTotals], files: dict[str, str]) -> list[InitiativeInputs]:
    out = []
    for rec in ini.to_dict("records"):
        iid = rec["initiative_id"]
        ref_ini = (cleaning.ref(files["initiatives"], int(rec[ROW_COL])),)
        if len(weeks) >= 2:
            first = _wau(usage, iid, weeks[0], "first-week", files["weekly_usage"])
        else:
            first = Sourced(None, note="fewer than two weeks of usage were supplied")
        latest = _wau(usage, iid, weeks[-1], "latest-week", files["weekly_usage"])
        t = totals[iid]
        out.append(InitiativeInputs(
            initiative_id=iid, name=rec["name"],
            go_live=rec["go_live_date"] if isinstance(rec["go_live_date"], date) else None,
            go_live_refs=ref_ini, go_live_note=rec["go_live_note"],
            licensed_users=Sourced(opt_float(rec["licensed_users"]), ref_ini, rec["licensed_users_note"]),
            planned_annual_benefit=Sourced(opt_float(rec["planned_annual_benefit"]), ref_ini,
                                           rec["planned_annual_benefit_note"]),
            first_week_wau=first, latest_week_wau=latest,
            benefit_to_date=t.benefit_to_date, cost_to_date=t.cost_to_date,
        ))
    return out


def _check_reported_roi(scorecard: list[ScorecardRow], totals: dict[str, cleaning.FinancialTotals],
                        tolerance_pp: float, filename: str, log: ChangeLog) -> None:
    """Compare any supplied ROI with the governed ROI; log mismatches. The supplied value is never used."""
    for row in scorecard:
        t = totals.get(row.initiative_id)
        roi = row.metrics["roi"]
        if t is None or t.reported_roi is None or roi.value is None:
            continue
        governed_pct = roi.value * 100
        reported = t.reported_roi.value_pct
        if abs(reported - governed_pct) <= tolerance_pp:
            continue
        why = (f"Supplied ROI {format_number(reported)}% differs from the governed ROI {roi.display} "
               "((benefit - cost) / cost)")
        b, c = t.benefit_to_date.value, t.cost_to_date.value
        if b is not None and c:
            if abs(reported - b / c * 100) <= tolerance_pp:
                why += "; the supplied figure matches benefit / cost x 100, a different convention"
        row_num = int(t.reported_roi.ref.rsplit(" ", 1)[-1])
        log.add("REPORTED_ROI_MISMATCH", filename, row=row_num, column="value", initiative_id=row.initiative_id,
                old_value=f"{format_number(reported)}%", new_value=f"{roi.display} (governed)", reason=why,
                effect="None: the supplied ROI is ignored; the scorecard uses the governed formula")


def _write_outputs(result: PipelineResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    result.initiatives.to_csv(out_dir / "clean_initiatives.csv", index=False)
    result.usage.to_csv(out_dir / "clean_weekly_usage.csv", index=False)
    result.financials.to_csv(out_dir / "clean_financials.csv", index=False)
    result.scorecard_frame().to_csv(out_dir / "scorecard.csv", index=False)
    (out_dir / "scorecard.json").write_text(json.dumps({
        "data_version": result.data_version, "as_of": result.as_of.isoformat(),
        "rows": [r.model_dump() for r in result.scorecard]}, indent=2), encoding="utf-8")
    result.change_log_frame().to_csv(out_dir / "change_log.csv", index=False)
    (out_dir / "data_version.txt").write_text(
        f"{result.data_version}\nas_of={result.as_of.isoformat()}\nraw_dir={result.raw_dir}\n", encoding="utf-8")


def run_pipeline(raw_dir: Path, config_dir: Path, out_dir: Path | None = None,
                 config: PipelineConfig | None = None) -> PipelineResult:
    """Run the whole pipeline on ``raw_dir``. Writes outputs to ``out_dir`` when given."""
    raw_dir = Path(raw_dir)
    cfg = config or load_pipeline_config(Path(config_dir))
    md = cfg.metric_dictionary
    if cleaning.WAU_METRIC not in md.usage_metrics:
        raise ConfigurationError(f"usage_metrics must define {cleaning.WAU_METRIC!r} (needed for adoption)")

    tables = load_raw_tables(raw_dir, md)
    files = {k: t.filename for k, t in tables.items()}
    log = ChangeLog()

    ini = cleaning.clean_initiatives(tables["initiatives"], cfg, log)
    if ini.empty:
        raise DataValidationError(f"{files['initiatives']}: no valid initiative rows")
    usage, weeks = cleaning.clean_usage(tables["weekly_usage"], cfg, log, ini)
    if not weeks:
        raise DataValidationError(f"{files['weekly_usage']}: no usable week dates")
    as_of = cleaning.as_of_date(weeks, cfg)
    fin = cleaning.clean_financials(tables["financials"], cfg, log, ini, as_of)
    totals = cleaning.rollup_financials(fin, ini, files["financials"], log, as_of)

    inputs = _build_inputs(ini, usage, weeks, totals, files)
    scorecard = build_scorecard(inputs, as_of, md.days_per_month, cfg.status_rules)
    _check_reported_roi(scorecard, totals, md.reported_roi_tolerance_pct_points, files["financials"], log)

    result = PipelineResult(
        data_version=data_version([t.path for t in tables.values()], cfg.source_files),
        as_of=as_of, raw_dir=raw_dir, files=files, weeks=weeks, initiatives=ini, usage=usage, financials=fin,
        scorecard=scorecard, change_log=log.finalize(scorecard))
    logger.info("Pipeline %s on %s: %d initiatives, %d change-log entries, as of %s",
                result.data_version, raw_dir, len(scorecard), len(result.change_log), as_of)
    if out_dir is not None:
        _write_outputs(result, Path(out_dir))
    return result
