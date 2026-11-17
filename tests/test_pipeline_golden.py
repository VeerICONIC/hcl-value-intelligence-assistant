"""Golden tests: the pipeline reproduces each dataset's answer key, with the SAME code and config.

Done criteria for Step 3 (architecture.md §9.1 / §10):
- cleaning ``raw/`` reproduces ``answer_key/expected_scorecard.csv``;
- every planted issue in ``answer_key/planted_issues.json`` appears in the change log;
- identical behaviour on ``data/`` (8 curated initiatives) and ``data_scale_40/`` (40, random issues).

The mapping from planted issue to rule lives HERE, on the answer-key side. The pipeline never
sees planted-issue IDs; it applies generic rules, and this test checks the right rule fired
for the right file and initiative.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd
import pytest

from app.data.pipeline import run_pipeline
from app.scorecard.metrics import METRIC_ORDER

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config"
DATASETS = ["data", "data_scale_40"]

# Planted issue -> the generic rule that must handle it.
DQ_RULES = {
    "DQ-01": "DUPLICATE_ROW", "DQ-02a": "NAME_FORMAT", "DQ-02b": "ID_FORMAT", "DQ-02c": "ID_FORMAT",
    "DQ-03a": "NUMBER_TEXT", "DQ-03b": "NUMBER_TEXT", "DQ-03c": "NUMBER_TEXT", "DQ-04": "METRIC_ALIAS",
    "DQ-04b": "MEASURE_ALIAS", "DQ-05": "UNIT_SCALE", "DQ-06": "MONTHLY_ROLLUP", "DQ-07": "DATE_FORMAT",
    "DQ-07b": "DATE_FORMAT", "DQ-08": "NEGATIVE_VALUE", "DQ-09": "WAU_ABOVE_LICENSED", "DQ-10": "MISSING_WEEK",
    "DQ-11": "REPORTED_ROI_MISMATCH",
}
R_RULES = {   # scale-set issue types R-<TYPE>-<INIT>
    "DATE": "DATE_FORMAT", "NAME": "NAME_FORMAT", "MONEY": "NUMBER_TEXT", "NEG": "NEGATIVE_VALUE",
    "DUP": "DUPLICATE_ROW", "BAD": "WAU_ABOVE_LICENSED", "ID": "ID_FORMAT", "MISS": "MISSING_WEEK",
    "ALIAS": "METRIC_ALIAS", "TEXT": "NUMBER_TEXT", "MONTHLY": "MONTHLY_ROLLUP", "KTEXT": "NUMBER_TEXT",
    "K": "UNIT_SCALE", "MEASURE": "MEASURE_ALIAS", "FID": "ID_FORMAT",
}


@pytest.fixture(scope="module", params=DATASETS)
def run(request, tmp_path_factory):
    folder = REPO / request.param
    out = tmp_path_factory.mktemp(f"processed_{request.param}")
    return request.param, folder, run_pipeline(folder / "raw", CONFIG, out_dir=out), out


def _same(got, exp, places=None) -> bool:
    exp_missing = exp is None or (isinstance(exp, float) and math.isnan(exp))
    if got is None or exp_missing:
        return got is None and exp_missing
    if places is not None:
        return round(got, places) == round(exp, places)
    return math.isclose(got, exp, rel_tol=1e-9, abs_tol=1e-9)


def test_scorecard_matches_answer_key(run):
    name, folder, result, _ = run
    expected = pd.read_csv(folder / "answer_key" / "expected_scorecard.csv").set_index("initiative_id")
    got = {r.initiative_id: r for r in result.scorecard}
    assert sorted(got) == sorted(expected.index), f"{name}: initiative set differs"
    problems = []
    for iid, exp in expected.iterrows():
        row = got[iid]
        if row.name != exp["name"]:
            problems.append(f"{iid} name {row.name!r} != {exp['name']!r}")
        if row.status != exp["status"]:
            problems.append(f"{iid} status {row.status} != {exp['status']}")
        for metric in METRIC_ORDER:
            places = 4 if metric == "months_live" else None     # answer key stores months_live at 4 dp
            value = row.metrics[metric].value
            if not _same(value, exp[metric], places):
                problems.append(f"{iid} {metric} {value} != {exp[metric]}")
    assert not problems, f"{name}:\n" + "\n".join(problems)


def _rule_for(issue_id: str) -> str:
    if issue_id.startswith("R-"):
        return R_RULES[issue_id.split("-")[1]]
    return DQ_RULES[issue_id]


def _initiatives_for(issue: dict) -> set[str]:
    if issue["id"].startswith("R-"):
        return {re.search(r"INIT-\d{3}$", issue["id"]).group(0)}
    return set(re.findall(r"INIT-\d{3}", issue["description"]))


# Answer-key defects: issues listed in planted_issues.json that are NOT present in the raw files.
# R-DUP-INIT-029: the generator queued a duplicate of INIT-029's week-2 row, then the R-MISS issue
# deleted that row, so the duplicate was never written (generate_practice_data.py lines 346-358).
# test_known_answer_key_defects_are_still_defects keeps this list honest.
KNOWN_ANSWER_KEY_DEFECTS = {"data_scale_40": {"R-DUP-INIT-029"}}


def test_known_answer_key_defects_are_still_defects():
    usage = pd.read_csv(REPO / "data_scale_40" / "raw" / "weekly_usage.csv", dtype=str, keep_default_na=False)
    rows = usage[usage["initiative_id"].str.contains(r"(?i)init\W*0*29\b", regex=True)]
    assert not rows.duplicated().any(), "INIT-029 now has a duplicate row: remove it from KNOWN_ANSWER_KEY_DEFECTS"


def test_every_planted_issue_is_in_the_change_log(run):
    name, folder, result, _ = run
    issues = json.loads((folder / "answer_key" / "planted_issues.json").read_text(encoding="utf-8"))
    issues = [i for i in issues if i["id"] not in KNOWN_ANSWER_KEY_DEFECTS.get(name, set())]
    missing = []
    for issue in issues:
        rule = _rule_for(issue["id"])
        hits = [e for e in result.change_log if e.rule_id == rule and e.file == issue["file"]]
        if not hits:
            missing.append(f"{issue['id']}: no {rule} entry for {issue['file']}")
            continue
        for iid in _initiatives_for(issue):
            if not any(e.initiative_id == iid for e in hits):
                missing.append(f"{issue['id']}: no {rule} entry for {iid} in {issue['file']}")
    assert not missing, f"{name}:\n" + "\n".join(missing)


def test_change_log_entries_are_complete(run):
    _, _, result, _ = run
    for e in result.change_log:
        assert e.reason and e.effect, e
        if e.rule_id not in ("MISSING_WEEK", "MONTHLY_ROLLUP"):     # file-level summaries have no single row
            assert e.row is not None and e.row >= 2, e


def test_outputs_written(run):
    _, _, result, out = run
    for f in ("clean_initiatives.csv", "clean_weekly_usage.csv", "clean_financials.csv", "scorecard.csv",
              "scorecard.json", "change_log.csv", "data_version.txt"):
        assert (out / f).is_file(), f
    assert (out / "data_version.txt").read_text(encoding="utf-8").startswith(result.data_version)
    assert len(pd.read_csv(out / "change_log.csv")) == len(result.change_log)


def test_rerun_is_deterministic(run):
    _, folder, result, _ = run
    again = run_pipeline(folder / "raw", CONFIG)
    assert again.data_version == result.data_version
    assert [r.model_dump() for r in again.scorecard] == [r.model_dump() for r in result.scorecard]
    assert again.change_log == result.change_log


def test_datasets_have_different_versions():
    versions = {run_pipeline(REPO / d / "raw", CONFIG).data_version for d in DATASETS}
    assert len(versions) == 2
