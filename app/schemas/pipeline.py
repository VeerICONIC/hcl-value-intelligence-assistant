"""Analytics API contracts: request/response bodies for the Step 3 endpoints.

Added in Step 3 with the developer's approval (docs/PROGRESS.md). They wrap the §6
contracts (``ScorecardRow``, ``ChangeLogEntry``) and add the data version + as-of date
to every response, so the dashboard can show which scorecard version it is looking at (D12).
Changing a field needs the developer's approval.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.schemas.data import ChangeLogEntry
from app.schemas.scorecard import ScorecardRow


class PipelineRunRequest(BaseModel):
    """Optional raw-data folder, relative to the repository root (default: settings RAW_DATA_DIR)."""

    raw_dir: str | None = None


class PipelineRunResponse(BaseModel):
    data_version: str
    as_of: date
    raw_dir: str
    weeks: list[date]
    initiative_count: int
    status_counts: dict[str, int]
    change_count: int
    rule_counts: dict[str, int]


class ScorecardResponse(BaseModel):
    data_version: str
    as_of: date
    rows: list[ScorecardRow]


class RuleSummary(BaseModel):
    rule_id: str
    description: str
    count: int


class DataQualityResponse(BaseModel):
    data_version: str
    as_of: date
    entries: list[ChangeLogEntry]
    rules: list[RuleSummary]


class UsagePoint(BaseModel):
    """One weekly-active-users row. ``included`` is False for rows the cleaning excluded (``note`` says why)."""

    initiative_id: str
    name: str
    week_start: date
    wau: float | None
    included: bool
    note: str | None
    source_ref: str


class UsageResponse(BaseModel):
    data_version: str
    as_of: date
    weeks: list[date]
    points: list[UsagePoint]
