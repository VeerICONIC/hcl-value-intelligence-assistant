"""POST /pipeline/run: clean the raw files and compute the scorecard (sidebar "Run pipeline", §3.3).

The result is kept on ``app.state`` (one per app instance, so tests stay isolated) and
served by GET /scorecard, /data-quality and /usage. Until a run has happened those
endpoints answer 409 instead of returning stale or invented data.

``raw_dir`` is resolved against the repository root and must stay inside it, so an API
caller cannot point the pipeline at arbitrary folders on the machine.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, HTTPException, Request

from app.core.config import PROJECT_ROOT, get_settings, resolve_project_path
from app.core.exceptions import ConfigurationError, DataValidationError
from app.data.pipeline import PipelineResult, run_pipeline
from app.schemas.pipeline import PipelineRunRequest, PipelineRunResponse

router = APIRouter(tags=["pipeline"])

NOT_RUN_DETAIL = "The pipeline has not been run yet. Call POST /pipeline/run first."


def require_result(request: Request) -> PipelineResult:
    """The latest pipeline result, or 409 if the pipeline has not run in this app instance."""
    result = getattr(request.app.state, "pipeline_result", None)
    if result is None:
        raise HTTPException(status_code=409, detail=NOT_RUN_DETAIL)
    return result


def _display_path(path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


@router.post("/pipeline/run", response_model=PipelineRunResponse)
def run(request: Request, body: PipelineRunRequest | None = None) -> PipelineRunResponse:
    s = get_settings()
    raw_dir = resolve_project_path(body.raw_dir if body and body.raw_dir else s.raw_data_dir)
    if not raw_dir.is_relative_to(PROJECT_ROOT):
        raise HTTPException(status_code=400, detail="raw_dir must be inside the project folder")
    try:
        result = run_pipeline(raw_dir, resolve_project_path(s.config_dir),
                              out_dir=resolve_project_path(s.processed_dir))
    except (DataValidationError, ConfigurationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    request.app.state.pipeline_result = result
    statuses = Counter(r.status for r in result.scorecard)
    return PipelineRunResponse(
        data_version=result.data_version, as_of=result.as_of, raw_dir=_display_path(raw_dir),
        weeks=result.weeks, initiative_count=len(result.scorecard),
        status_counts={k: statuses.get(k, 0) for k in ("Green", "Amber", "Red", "Insufficient data")},
        change_count=len(result.change_log),
        rule_counts=dict(Counter(e.rule_id for e in result.change_log).most_common()),
    )
