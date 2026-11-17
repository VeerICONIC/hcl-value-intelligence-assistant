"""Amazon Titan Text Embeddings V2 via the shared ``BedrockRuntime`` client.

The same class embeds charter chunks and user queries, so both always share one
model and dimension. Titan has no batch endpoint: texts are sent as individual
requests, ``embedding_batch_size`` at a time in parallel. Throttling is retried with
exponential backoff; every other Bedrock error is raised immediately.

Copied from the practice repo (``app/embeddings/titan.py``, verified live). The
``Embedder`` protocol and ``EmbeddingError`` were folded in from its ``base.py``.
"""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, Protocol

from app.core.bedrock import BedrockError, BedrockRuntime, ThrottlingError
from app.core.config import Settings, get_settings

# Titan V2 accepts up to 8192 tokens; this character guard fails fast well beyond that.
MAX_INPUT_CHARS = 50_000


class EmbeddingError(BedrockError):
    """Embedding failed. ``__cause__`` holds the underlying Bedrock error, if any."""


class Embedder(Protocol):
    """What indexing and retrieval need from an embedder (tests supply a fake)."""

    dimension: int
    model_id: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class TitanEmbedder:
    def __init__(
        self,
        runtime: Optional[BedrockRuntime] = None,
        settings: Optional[Settings] = None,
        *,
        max_retries: int = 4,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings or get_settings()
        self.runtime = runtime or BedrockRuntime(self.settings)
        self.model_id = self.settings.bedrock_embed_model_id
        self.dimension = self.settings.bedrock_embed_dim
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._sleep = sleep

    # -- public API --------------------------------------------------------
    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` preserving order. Raises EmbeddingError on the first failure."""
        for i, t in enumerate(texts):
            self._validate_text(t, i)
        if not texts:
            return []
        workers = max(1, self.settings.embedding_batch_size)
        out: list[list[float]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for start in range(0, len(texts), workers):
                batch = texts[start:start + workers]
                out.extend(pool.map(self._embed_one, batch))
        return out

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _validate_text(text: str, index: int = 0) -> None:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError(f"cannot embed empty text (item {index})")
        if len(text) > MAX_INPUT_CHARS:
            raise EmbeddingError(f"text too long to embed ({len(text)} characters, item {index})")

    def _embed_one(self, text: str) -> list[float]:
        self._validate_text(text)
        body = json.dumps({"inputText": text, "dimensions": self.dimension, "normalize": True})
        attempt = 0
        while True:
            try:
                raw = self.runtime.invoke_model(self.model_id, body)
                break
            except ThrottlingError as exc:
                if attempt >= self._max_retries:
                    raise EmbeddingError(f"embedding throttled after {attempt + 1} attempts: {exc}") from exc
                self._sleep(self._backoff * (2 ** attempt))
                attempt += 1
            except BedrockError as exc:
                raise EmbeddingError(str(exc)) from exc
        return self._parse(raw)

    def _parse(self, raw: bytes) -> list[float]:
        try:
            vec = json.loads(raw)["embedding"]
        except (ValueError, KeyError, TypeError):
            raise EmbeddingError("unexpected response from the embedding model (no 'embedding' field)") from None
        if not isinstance(vec, list) or len(vec) != self.dimension:
            got = len(vec) if isinstance(vec, list) else type(vec).__name__
            raise EmbeddingError(f"embedding has dimension {got}, expected BEDROCK_EMBED_DIM={self.dimension}")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vec):
            raise EmbeddingError("embedding contains non-numeric or non-finite values")
        return [float(x) for x in vec]
