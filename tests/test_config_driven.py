"""D10: loading is config-driven. Renamed columns, new aliases and new units need YAML edits, not code."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

from app.core.exceptions import ConfigurationError
from app.core.yaml_config import load_pipeline_config
from app.data.pipeline import run_pipeline

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path):
    raw, cfg = tmp_path / "raw", tmp_path / "config"
    shutil.copytree(REPO / "data" / "raw", raw, ignore=shutil.ignore_patterns(".gitkeep"))
    shutil.copytree(REPO / "config", cfg, ignore=shutil.ignore_patterns(".gitkeep"))
    return raw, cfg


def _edit_yaml(path: Path, fn) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _baseline():
    return {r.initiative_id: r.metrics["adoption"].value
            for r in run_pipeline(REPO / "data" / "raw", REPO / "config").scorecard}


def test_renamed_columns_and_new_metric_alias_need_only_config(workspace):
    raw, cfg = workspace
    p = raw / "weekly_usage.csv"
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    df = df.rename(columns={"week_start": "Week Commencing", "value": "Reading"})
    df.loc[df.metric_name == "WAU", "metric_name"] = "Weekly Actives"
    df.to_csv(p, index=False)

    with pytest.raises(Exception, match="missing required column"):
        run_pipeline(raw, cfg)                                 # unknown headers: clear failure

    def add_aliases(d):
        d["files"]["weekly_usage"]["columns"]["week_start"].append("Week Commencing")
        d["files"]["weekly_usage"]["columns"]["value"].append("Reading")
        d["usage_metrics"]["weekly_active_users"]["aliases"].append("Weekly Actives")
    _edit_yaml(cfg / "metric_dictionary.yaml", add_aliases)

    result = run_pipeline(raw, cfg)                            # same code, edited config
    assert {r.initiative_id: r.metrics["adoption"].value for r in result.scorecard} == _baseline()


def test_new_unit_needs_only_config(workspace):
    raw, cfg = workspace
    p = raw / "financials.xlsx"
    df = pd.read_excel(p, dtype=str, keep_default_na=False)
    mask = (df.initiative_id == "INIT-004") & (df.measure == "total_cost")
    df.loc[mask, "value"], df.loc[mask, "unit"] = "0.09", "USD m"
    df.to_excel(p, sheet_name="financials", index=False)

    _edit_yaml(cfg / "metric_dictionary.yaml",
               lambda d: d["units"].update({"USD m": {"multiplier": 1_000_000, "kind": "money"}}))
    result = run_pipeline(raw, cfg)
    roi = next(r for r in result.scorecard if r.initiative_id == "INIT-004").metrics["roi"]
    assert roi.inputs["cost_to_date"] == 90000
    assert any(e.rule_id == "UNIT_SCALE" and e.initiative_id == "INIT-004" for e in result.change_log)


def test_thresholds_come_from_status_rules(workspace):
    raw, cfg = workspace
    _edit_yaml(cfg / "status_rules.yaml", lambda d: d["green_if_all"].update({"adoption_at_least": 0.70}))
    statuses = {r.initiative_id: r.status for r in run_pipeline(raw, cfg).scorecard}
    assert statuses["INIT-001"] == "Green"      # 72% >= 70%
    assert statuses["INIT-002"] == "Amber"      # 65% now below the edited threshold


def test_bad_config_fails_at_load_with_a_readable_message(workspace):
    _, cfg = workspace
    _edit_yaml(cfg / "metric_dictionary.yaml", lambda d: d["units"]["USD"].pop("multiplier"))
    with pytest.raises(ConfigurationError, match=r"metric_dictionary.yaml.*\n.*units.USD.multiplier"):
        load_pipeline_config(cfg)


def test_alias_under_two_measures_is_rejected(workspace):
    _, cfg = workspace
    _edit_yaml(cfg / "metric_dictionary.yaml",
               lambda d: d["financial_measures"]["cost_to_date"]["aliases"].append("realised_benefit"))
    with pytest.raises(ConfigurationError, match="maps to both"):
        load_pipeline_config(cfg)
