"""GET /health: liveness plus the configuration the dashboard sidebar shows (§3.3).

By default it never touches AWS or ChromaDB, so it is instant and free, and it works
even when Bedrock is down (D12: analytics must not depend on the LLM).
``?check_aws=true`` additionally reports whether the boto3 credential chain resolves.
That is a local check only: no model is invoked and no secret is returned.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core import bedrock
from app.core.config import APP_NAME, APP_VERSION, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(check_aws: bool = Query(False, description="Also check that AWS credentials resolve (no Bedrock call).")) -> dict:
    s = get_settings()
    body: dict = {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "aws_region": s.aws_region,
        "embed_model": s.bedrock_embed_model_id,
        "llm_model": s.bedrock_llm_model_id,
        "chroma_collection": s.chroma_collection,
        "llm_mode": s.llm_mode,
    }
    if check_aws:
        body["aws_credentials"] = bedrock.aws_credentials_available(s)
    return body
