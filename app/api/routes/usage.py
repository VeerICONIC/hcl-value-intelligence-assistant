"""GET /usage: weekly active users per initiative per week (dashboard WAU chart, section 3).

Excluded rows are returned too (``included: false`` with the reason), so the chart can show
what was left out instead of hiding it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.routes.pipeline import require_result
from app.data.cleaning import WAU_METRIC, ref
from app.data.loader import ROW_COL
from app.data.pipeline import opt_float
from app.schemas.pipeline import UsagePoint, UsageResponse

router = APIRouter(tags=["analytics"])


@router.get("/usage", response_model=UsageResponse)
def usage(request: Request) -> UsageResponse:
    result = require_result(request)
    names = dict(zip(result.initiatives["initiative_id"], result.initiatives["name"]))
    usage_df = result.usage[result.usage["metric"] == WAU_METRIC]
    points = [
        UsagePoint(initiative_id=r["initiative_id"], name=names.get(r["initiative_id"], r["initiative_id"]),
                   week_start=r["week_start"], wau=opt_float(r["value"]), included=bool(r["included"]),
                   note=r["note"] if isinstance(r["note"], str) else None,
                   source_ref=ref(result.files["weekly_usage"], int(r[ROW_COL])))
        for r in usage_df.to_dict("records")
    ]
    return UsageResponse(data_version=result.data_version, as_of=result.as_of, weeks=result.weeks, points=points)
