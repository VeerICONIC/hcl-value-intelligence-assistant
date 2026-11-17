"""POST /charters/index and POST /ask (FR-04..FR-08).

The charters indexed are those next to the raw data of the latest pipeline run
(``<dataset>/charters``), so the assistant always answers from the same dataset and the same
scorecard version that the dashboard shows (D12). /ask builds the index on first use.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.routes.pipeline import require_result
from app.charters.index import CharterIndex
from app.core.config import get_settings, resolve_project_path
from app.orchestration.answer import answer_question
from app.schemas.answer import AskResponse

router = APIRouter(tags=["assistant"])


class AskRequest(BaseModel):
    question: str


def charters_dir_for(request: Request) -> Path:
    result = getattr(request.app.state, "pipeline_result", None)
    if result is not None:
        candidate = Path(result.raw_dir).parent / "charters"
        if candidate.is_dir():
            return candidate
    return resolve_project_path(get_settings().charters_dir)


def get_index(request: Request, rebuild: bool = False) -> tuple[CharterIndex, dict | None]:
    index: CharterIndex | None = getattr(request.app.state, "charter_index", None)
    if index is None:
        index = CharterIndex(get_settings())
        request.app.state.charter_index = index
    folder = charters_dir_for(request)
    summary = None
    if rebuild or not index.chunks or index.source_dir != folder:
        summary = index.build(folder)
    return index, summary


@router.post("/charters/index")
def index_charters(request: Request) -> dict:
    try:
        _, summary = get_index(request, rebuild=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return summary


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request) -> AskResponse:
    if not body.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    result = require_result(request)        # 409 until the pipeline has run: chat uses that scorecard
    index, _ = get_index(request)
    return answer_question(body.question, result.scorecard, result.data_version, index, get_settings())
