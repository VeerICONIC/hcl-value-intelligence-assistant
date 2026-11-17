"""Scorecard contracts (architecture.md §6). Changing a field needs the developer's approval."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class MetricValue(BaseModel):
    """One computed metric for one initiative, with full provenance (FR-03).

    ``display`` is formatted once, here, by scorecard code ("24.0%", "8.4 months").
    It is the only text form of a number the assistant may show (D5).
    """

    initiative_id: str
    metric: str
    value: float | None           # None when undefined (e.g. payback with zero benefit)
    display: str
    formula: str
    inputs: dict[str, float | None]
    source_refs: list[str]        # e.g. "financials.xlsx row 14"
    note: str | None              # reason when value is None, or an assumption used


class ScorecardRow(BaseModel):
    """All metrics + status for one initiative."""

    initiative_id: str
    name: str
    metrics: dict[str, MetricValue]
    status: Literal["Green", "Amber", "Red", "Insufficient data"]
    status_reason: str


class ScorecardQuery(BaseModel):
    """The only operations the scorecard query engine supports (D8): no new calculations."""

    operation: Literal["lookup", "filter", "rank", "count"]
    initiative_ids: list[str] = []          # Pydantic copies defaults per instance, so this is safe
    metrics: list[str] = []
    status_filter: list[Literal["Green", "Amber", "Red"]] = []
    rank_by: str | None = None
    top_k: int | None = None
    descending: bool = True
