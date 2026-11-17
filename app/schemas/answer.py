"""Question-answering contracts (architecture.md §6). Changing a field needs the developer's approval."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.retrieval import CharterChunk
from app.schemas.scorecard import MetricValue, ScorecardQuery


class Route(BaseModel):
    """Where a question goes (FR-05). Rules first, LLM only for ambiguous cases (D9)."""

    kind: Literal["metric", "narrative", "mixed", "unsupported"]
    initiative_ids: list[str]
    scorecard_query: ScorecardQuery | None
    reason: str


class DraftStatement(BaseModel):
    """One sentence from the LLM. ``text`` holds {{F#}} tokens, never digits (D5)."""

    text: str
    fact_ids: list[str]
    chunk_ids: list[str]


class AnswerResponse(BaseModel):
    """What /ask returns: the rendered answer plus every source and the guard result."""

    route: str
    status: Literal["answered", "no_evidence", "refused"]
    answer: str
    statements: list[dict]
    scorecard_sources: list[MetricValue]
    charter_sources: list[CharterChunk]
    guard_report: dict
    trace: list[dict]


class AskResponse(BaseModel):
    """POST /ask response (Step 7 sprint shape, requested by the developer).

    ``status``: answered | no_evidence (exact fallback message) | refused (input guard).
    ``guard_notes`` explain routing and every guard that fired, for the dashboard and evaluation.
    """

    route: str
    status: Literal["answered", "no_evidence", "refused"]
    answer: str
    scorecard_sources: list[MetricValue]
    charter_sources: list[CharterChunk]
    guard_notes: list[str]
    data_version: str
