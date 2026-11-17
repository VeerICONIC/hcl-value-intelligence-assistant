"""GET /scorecard: the governed scorecard of the latest pipeline run (dashboard sections 1-3).

Every row carries all metrics as ``MetricValue`` (value, display text, formula, inputs,
source rows, note), so the dashboard drill-down needs no extra calls and no calculation.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.routes.pipeline import require_result
from app.schemas.pipeline import ScorecardResponse

router = APIRouter(tags=["analytics"])


@router.get("/scorecard", response_model=ScorecardResponse)
def scorecard(request: Request) -> ScorecardResponse:
    result = require_result(request)
    return ScorecardResponse(data_version=result.data_version, as_of=result.as_of, rows=result.scorecard)
