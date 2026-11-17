"""GET /data-quality: the change log of the latest pipeline run, plus counts per rule (dashboard section 4)."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Request

from app.api.routes.pipeline import require_result
from app.data.changelog import RULES
from app.schemas.pipeline import DataQualityResponse, RuleSummary

router = APIRouter(tags=["analytics"])


@router.get("/data-quality", response_model=DataQualityResponse)
def data_quality(request: Request) -> DataQualityResponse:
    result = require_result(request)
    counts = Counter(e.rule_id for e in result.change_log)
    rules = [RuleSummary(rule_id=rule, description=RULES[rule], count=n) for rule, n in counts.most_common()]
    return DataQualityResponse(data_version=result.data_version, as_of=result.as_of,
                               entries=result.change_log, rules=rules)
