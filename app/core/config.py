"""Application settings (pydantic-settings).

Values come from environment variables, then an optional ``.env`` file, then the
defaults below. Defaults follow architecture.md D2/D3, so the app runs with no
``.env`` at all.

AWS credentials are deliberately NOT settings (D11). boto3's default chain
(``aws login`` / SSO profile, environment, shared credentials file, IAM role)
resolves them. Only the region and an optional profile *name* are configured here.

Adapted from the practice repo's ``app/core/config.py`` (Bedrock/Chroma parts only).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigurationError

APP_NAME = "Nimbus Value Intelligence Assistant"
APP_VERSION = "0.1.0"

# The one and only no-evidence answer (FR-07). A constant, not a setting, so it
# cannot be changed by an environment variable.
FALLBACK_MESSAGE = "I do not have that in the data provided"

# Repository root. Relative paths in settings and API requests are resolved against this,
# never against the current working directory (which differs between uvicorn, streamlit,
# scripts and pytest).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_project_path(path: str | Path) -> Path:
    """Absolute path for ``path``; relative paths are taken from the repository root."""
    p = Path(path)
    return (p if p.is_absolute() else PROJECT_ROOT / p).resolve()


# Output dimensions supported by Titan Text Embeddings V2.
TITAN_V2_DIMENSIONS = (256, 512, 1024)

# ChromaDB collection-name rule: 3-512 chars of [a-zA-Z0-9._-], alnum at both ends.
_CHROMA_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,510}[A-Za-z0-9]")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # unrelated .env entries are ignored, never loaded
    )

    # --- AWS / Bedrock (D2) --------------------------------------------------
    aws_region: str = Field("ap-south-1", description="AWS region for Bedrock Runtime.")
    aws_profile: Optional[str] = Field(None, description="Optional named AWS profile (e.g. SSO).")
    bedrock_embed_model_id: str = Field("amazon.titan-embed-text-v2:0", description="Titan embeddings model ID.")
    bedrock_embed_dim: int = Field(
        1024, description="Embedding dimension. Fixed once charters are indexed; changing it means re-indexing."
    )
    bedrock_llm_model_id: str = Field(
        "apac.amazon.nova-lite-v1:0", description="Nova Lite via the APAC cross-region inference profile."
    )
    llm_max_tokens: int = Field(800, ge=64, le=4096, description="Max tokens Nova may generate per call.")
    llm_temperature: float = Field(0.0, ge=0.0, le=1.0, description="0 = most deterministic.")
    embedding_batch_size: int = Field(
        8, ge=1, le=64, description="Concurrent Titan requests per batch (Titan has no batch API)."
    )

    # --- Vector store (D3) ---------------------------------------------------
    chroma_path: Path = Field(Path("data/chroma"), description="ChromaDB persistence directory.")
    chroma_collection_prefix: str = Field("charters", description="Collection name prefix; model + dim are appended.")

    # --- Paths ---------------------------------------------------------------
    config_dir: Path = Field(Path("config"), description="YAML configuration (D10).")
    raw_data_dir: Path = Field(Path("data/raw"), description="Input spreadsheets.")
    charters_dir: Path = Field(Path("data/charters"), description="Input initiative charters.")
    processed_dir: Path = Field(Path("data/processed"), description="Pipeline outputs.")
    answer_key_dir: Path = Field(Path("data/answer_key"), description="Practice-data answer key.")

    # --- API / dashboard (D13) -----------------------------------------------
    api_base_url: str = Field("http://localhost:8000", description="Backend URL used by the Streamlit dashboard.")
    log_level: str = Field("INFO", description="Root log level.")

    # --- validators ------------------------------------------------------------
    @field_validator("aws_profile", mode="before")
    @classmethod
    def _blank_profile_is_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("aws_region", "bedrock_embed_model_id", "bedrock_llm_model_id",
                     "chroma_collection_prefix", "api_base_url")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return v

    @field_validator("bedrock_embed_dim")
    @classmethod
    def _positive_dim(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v

    @model_validator(mode="after")
    def _cross_field_checks(self) -> "Settings":
        if ("titan-embed-text-v2" in self.bedrock_embed_model_id
                and self.bedrock_embed_dim not in TITAN_V2_DIMENSIONS):
            raise ValueError(
                f"BEDROCK_EMBED_DIM={self.bedrock_embed_dim} is not supported by Titan "
                f"Text Embeddings V2; use one of {TITAN_V2_DIMENSIONS}"
            )
        if not _CHROMA_NAME.fullmatch(self.chroma_collection):
            raise ValueError(
                f"derived Chroma collection name {self.chroma_collection!r} breaks Chroma's naming rule "
                "(3-512 chars of [a-zA-Z0-9._-], letter or digit at both ends); change CHROMA_COLLECTION_PREFIX"
            )
        return self

    # --- derived values --------------------------------------------------------
    @property
    def embed_model_slug(self) -> str:
        """'amazon.titan-embed-text-v2:0' -> 'titan-embed-text-v2' (provider and version dropped)."""
        slug = self.bedrock_embed_model_id.split(":")[0]
        if "." in slug:
            slug = slug.split(".", 1)[1]
        return re.sub(r"[^A-Za-z0-9-]+", "-", slug).strip("-")

    @property
    def chroma_collection(self) -> str:
        """D3: the name encodes model + dimension, so an index built with other settings is never reused."""
        return f"{self.chroma_collection_prefix}__{self.embed_model_slug}__{self.bedrock_embed_dim}"


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Invalid configuration (check environment variables / .env):"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "settings"
        lines.append(f"  - {loc.upper()}: {err['msg']}")
    return "\n".join(lines)


def load_settings(**overrides) -> Settings:
    """Build Settings, converting validation failures into one readable ConfigurationError."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached process-wide settings. Tests call ``get_settings.cache_clear()``."""
    return load_settings()
