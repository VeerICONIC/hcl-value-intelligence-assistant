"""The §6 contracts accept valid data and reject invalid values."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    AnswerResponse,
    ChangeLogEntry,
    CharterChunk,
    DraftStatement,
    MetricValue,
    Route,
    ScorecardQuery,
    ScorecardRow,
)


def _metric(**over) -> MetricValue:
    data = dict(initiative_id="INIT-001", metric="adoption", value=0.72, display="72.0%",
                formula="latest_wau / licensed_users", inputs={"latest_wau": 360.0, "licensed_users": 500.0},
                source_refs=["weekly_usage.csv row 3", "initiatives.csv row 1"], note=None)
    data.update(over)
    return MetricValue(**data)


def _chunk(**over) -> CharterChunk:
    data = dict(chunk_id="INIT-001:0001", initiative_id="INIT-001", source_file="INIT-001_charter.md",
                section="Risks and Mitigations", page=None, text="Low adoption risk...", score=0.81,
                injection_flag=False)
    data.update(over)
    return CharterChunk(**data)


def test_change_log_entry():
    e = ChangeLogEntry(rule_id="DQ-05", file="financials.xlsx", row=14, column="value", initiative_id="INIT-004",
                       old_value="45", new_value="45000", reason="Reported in USD '000",
                       effect="ROI for INIT-004 changes from -0.99 to 0.42")
    assert e.row == 14


def test_metric_value_allows_undefined_value():
    m = _metric(metric="payback_months", value=None, display="not reached", note="benefit to date is 0")
    assert m.value is None


def test_scorecard_row_status_literal():
    row = ScorecardRow(initiative_id="INIT-001", name="HR Policy Copilot",
                       metrics={"adoption": _metric()}, status="Green", status_reason="adoption >= 60% and ROI > 0")
    assert row.status == "Green"
    with pytest.raises(ValidationError):
        ScorecardRow(initiative_id="INIT-001", name="x", metrics={}, status="Purple", status_reason="")


def test_scorecard_query_rejects_undefined_operation_d8():
    with pytest.raises(ValidationError):
        ScorecardQuery(operation="average")


def test_scorecard_query_defaults_are_not_shared():
    a, b = ScorecardQuery(operation="lookup"), ScorecardQuery(operation="lookup")
    a.initiative_ids.append("INIT-001")
    assert b.initiative_ids == []
    assert a.descending is True and a.top_k is None


def test_charter_chunk_and_route():
    q = ScorecardQuery(operation="rank", rank_by="roi", top_k=3)
    r = Route(kind="mixed", initiative_ids=["INIT-004"], scorecard_query=q, reason="metric + risk words")
    assert r.scorecard_query.rank_by == "roi"
    assert _chunk().page is None
    with pytest.raises(ValidationError):
        Route(kind="chitchat", initiative_ids=[], scorecard_query=None, reason="")


def test_answer_response_json_round_trip():
    ans = AnswerResponse(
        route="mixed", status="answered", answer="INIT-004 adoption is 22.0% [S1].",
        statements=[DraftStatement(text="INIT-004 adoption is {{F1}}.", fact_ids=["F1"], chunk_ids=[]).model_dump()],
        scorecard_sources=[_metric(initiative_id="INIT-004", value=0.22, display="22.0%")],
        charter_sources=[_chunk()], guard_report={"ok": True, "attempts": 1}, trace=[{"step": "route"}],
    )
    again = AnswerResponse.model_validate_json(ans.model_dump_json())
    assert again == ans
    with pytest.raises(ValidationError):
        AnswerResponse(**{**ans.model_dump(), "status": "maybe"})
