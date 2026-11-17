"""Runtime settings from environment variables / .env (never credentials: those come from the boto3 chain)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

try:  # optional .env support
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover
    pass

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
EMBED_MODEL_ID = os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
LLM_MODEL_ID = os.getenv("BEDROCK_LLM_MODEL_ID", "apac.amazon.nova-lite-v1:0")
LLM_MODE = os.getenv("LLM_MODE", "auto").lower()            # auto | bedrock | extractive
EMBED_MODE = os.getenv("EMBED_MODE", "auto").lower()        # auto | titan | local
CHROMA_DIR = ROOT / os.getenv("CHROMA_PERSIST_DIRECTORY", "data/chroma")
PROCESSED_DIR = ROOT / "data" / "processed"

FALLBACK = "I do not have that in the data provided"


def load_pipeline_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config" / "pipeline.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key in ("files", "column_aliases", "metric_aliases", "measure_aliases", "units", "status_rules"):
        if key not in cfg:
            raise ValueError(f"config/pipeline.yaml is missing the '{key}' section")
    return cfg
