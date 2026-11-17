"""Persistent ChromaDB store for charter chunks (D3).

* One collection whose name encodes the embedding model and dimension
  (``Settings.chroma_collection``, e.g. ``charters__titan-embed-text-v2__1024``).
* Cosine space; embeddings are always supplied by us (``embedding_function=None``),
  so Chroma never downloads or runs a model of its own.
* The collection also records the model id and dimension in its metadata; opening
  it with different settings fails loudly instead of mixing vector spaces.
* Stored per chunk: the ``CharterChunk`` fields except ``text`` (stored as the
  document) and ``score`` (a per-query value, never stored). Chroma metadata only
  accepts scalars, so ``page=None`` is stored as ``-1`` and mapped back on read.
* ``query`` returns chunks whose ``score`` is the cosine similarity (1 - distance).

Adapted from the practice repo's ``app/vectorstore/chroma_store.py`` (verified live):
the Doc Q&A document bookkeeping (doc versions, incremental re-ingest) was removed
and the record type changed to our ``CharterChunk`` contract.
"""

from __future__ import annotations

import logging
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

import chromadb

from app.core.config import Settings, get_settings
from app.core.exceptions import VectorStoreError
from app.schemas import CharterChunk

logger = logging.getLogger(__name__)

# CharterChunk fields kept in Chroma metadata (chunk_id is the record id, text the document).
_META_FIELDS = ("chunk_id", "initiative_id", "source_file", "section", "page", "injection_flag")
_CONTRACT_FIELDS = frozenset(CharterChunk.model_fields)
_SCALARS = (str, int, float, bool)
_NO_PAGE = -1
_READ_PAGE = 5000


@contextmanager
def _guard(op: str) -> Iterator[None]:
    """Turn any chromadb exception into a VectorStoreError with context."""
    try:
        yield
    except VectorStoreError:
        raise
    except Exception as exc:  # chromadb raises many exception types
        logger.exception("vector store failure during %s", op)
        raise VectorStoreError(f"vector store error during {op}: {exc}") from exc


class CharterStore:
    def __init__(self, settings: Optional[Settings] = None, *, path: Optional[str] = None,
                 collection_name: Optional[str] = None):
        s = settings or get_settings()
        self._path = str(Path(path or s.chroma_path))
        self._name = collection_name or s.chroma_collection
        self._model_id = s.bedrock_embed_model_id
        self._dim = s.bedrock_embed_dim
        self._client: Any = None
        self._col: Any = None
        self._revision = 0

    # -- lifecycle ---------------------------------------------------------
    @property
    def collection(self):
        """Open (or create) the collection lazily, verifying its embedding configuration."""
        if self._col is None:
            with _guard("opening the collection"):
                Path(self._path).mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(path=self._path)
                col = self._client.get_or_create_collection(
                    name=self._name,
                    metadata={"hnsw:space": "cosine", "embed_model_id": self._model_id, "embed_dim": self._dim},
                    embedding_function=None,
                )
                meta = col.metadata or {}
                if (meta.get("embed_model_id"), meta.get("embed_dim")) != (self._model_id, self._dim):
                    raise VectorStoreError(
                        f"collection '{self._name}' was built with embedding model "
                        f"{meta.get('embed_model_id')!r} at dimension {meta.get('embed_dim')!r}, but the "
                        f"current configuration is {self._model_id!r} at {self._dim}. Mixing vector spaces "
                        "is not allowed: re-index the charters."
                    )
                self._col = col
        return self._col

    @property
    def name(self) -> str:
        return self._name

    @property
    def revision(self) -> int:
        """Counter bumped by every write through this object (BM25 cache invalidation key)."""
        return self._revision

    def close(self) -> None:
        """Drop handles and Chroma's shared client cache (releases file locks on Windows)."""
        self._col = None
        self._client = None
        try:
            from chromadb.api.shared_system_client import SharedSystemClient
            SharedSystemClient.clear_system_cache()
        except Exception:  # best effort
            pass

    def reset(self) -> None:
        """Delete every chunk by dropping and recreating the collection (full re-index)."""
        with _guard("resetting the collection"):
            _ = self.collection  # make sure the client exists
            self._client.delete_collection(name=self._name)
            self._col = None
            self._revision += 1
            _ = self.collection

    def health(self) -> dict[str, Any]:
        with _guard("health check"):
            return {"collection": self._name, "path": self._path, "chunks": self.count(),
                    "embed_model_id": self._model_id, "embed_dim": self._dim}

    # -- writes ------------------------------------------------------------
    def upsert(self, chunks: list[CharterChunk], embeddings: list[list[float]],
               extra_metadata: Optional[Mapping[str, Any]] = None) -> None:
        """Insert or replace chunks by ``chunk_id``. ``extra_metadata`` (scalars) is added to every chunk."""
        if len(chunks) != len(embeddings):
            raise VectorStoreError(f"{len(chunks)} chunks but {len(embeddings)} embeddings")
        if not chunks:
            return
        extra = dict(extra_metadata or {})
        bad = [k for k, v in extra.items() if k in _CONTRACT_FIELDS or not isinstance(v, _SCALARS)]
        if bad:
            raise VectorStoreError(f"invalid extra metadata keys (scalars only, no contract fields): {bad}")
        for emb in embeddings:
            if len(emb) != self._dim:
                raise VectorStoreError(f"embedding dimension {len(emb)} != configured {self._dim}")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise VectorStoreError("duplicate chunk_id values in one upsert")
        metadatas = [{**self._to_metadata(c), **extra} for c in chunks]
        self._revision += 1
        with _guard("upserting chunks"):
            step = max(1, min(self._client_batch_limit(), 1000))
            for i in range(0, len(ids), step):
                self.collection.upsert(
                    ids=ids[i:i + step],
                    embeddings=embeddings[i:i + step],
                    documents=[c.text for c in chunks[i:i + step]],
                    metadatas=metadatas[i:i + step],
                )

    def _client_batch_limit(self) -> int:
        _ = self.collection
        try:
            return int(self._client.get_max_batch_size())
        except Exception:
            return 1000

    def delete_ids(self, ids: list[str]) -> int:
        if not ids:
            return 0
        self._revision += 1
        with _guard("deleting chunks"):
            self.collection.delete(ids=list(ids))
        return len(ids)

    # -- reads -------------------------------------------------------------
    def count(self) -> int:
        with _guard("counting chunks"):
            return int(self.collection.count())

    def _get_all(self, *, where: Optional[dict] = None, include: list[str]) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            page = self.collection.get(where=where, include=include, limit=_READ_PAGE, offset=offset)
            ids = page["ids"]
            if not ids:
                return
            for idx, cid in enumerate(ids):
                row: dict[str, Any] = {"id": cid}
                if "metadatas" in include:
                    row["metadata"] = page["metadatas"][idx]
                if "documents" in include:
                    row["document"] = page["documents"][idx]
                yield row
            if len(ids) < _READ_PAGE:
                return
            offset += _READ_PAGE

    def get_all_chunks(self, where: Optional[dict] = None) -> list[CharterChunk]:
        """All chunks (optionally filtered, e.g. ``{"initiative_id": "INIT-003"}``), ordered by chunk_id.

        ``score`` is 0.0 because no query was involved.
        """
        with _guard("reading all chunks"):
            rows = self._get_all(where=where or None, include=["metadatas", "documents"])
            chunks = [self._to_chunk(r["document"], r["metadata"], 0.0) for r in rows]
        return sorted(chunks, key=lambda c: c.chunk_id)

    def get_embeddings(self, ids: list[str]) -> dict[str, list[float]]:
        """Stored embeddings for the given chunk IDs (unknown IDs are omitted)."""
        if not ids:
            return {}
        with _guard("reading embeddings"):
            res = self.collection.get(ids=list(ids), include=["embeddings"])
            embs = res["embeddings"]
            return {cid: [float(x) for x in embs[i]] for i, cid in enumerate(res["ids"])}

    def query(self, embedding: list[float], top_k: int, where: Optional[dict] = None) -> list[CharterChunk]:
        """Nearest chunks to ``embedding``, best first; each ``score`` is the cosine similarity.

        Chroma returns cosine *distance* (``1 - cos``); it is converted to similarity and
        clamped to [-1, 1] to absorb float32 rounding. Ties are broken by chunk_id so
        results are deterministic. Malformed stored records are skipped with a warning.
        """
        self._validate_query_embedding(embedding)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise VectorStoreError(f"top_k must be a positive integer, got {top_k!r}")
        with _guard("querying"):
            total = self.count()
            if total == 0:
                return []
            res = self.collection.query(
                query_embeddings=[[float(x) for x in embedding]],
                n_results=min(top_k, total),
                where=where or None,
                include=["documents", "metadatas", "distances"],
            )
        results: list[CharterChunk] = []
        for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]):
            try:
                if dist is None or not math.isfinite(dist):
                    raise ValueError(f"invalid distance {dist!r}")
                similarity = max(-1.0, min(1.0, 1.0 - float(dist)))
                results.append(self._to_chunk(doc, meta, similarity))
            except Exception as exc:  # malformed stored record
                logger.warning("skipping malformed chunk %s in query results: %s", cid, exc)
        results.sort(key=lambda c: (-c.score, c.chunk_id))
        return results

    # -- mapping between CharterChunk and Chroma records ----------------------
    @staticmethod
    def _to_metadata(chunk: CharterChunk) -> dict[str, Any]:
        meta = {k: getattr(chunk, k) for k in _META_FIELDS}
        if meta["page"] is None:
            meta["page"] = _NO_PAGE
        return meta

    @staticmethod
    def _to_chunk(text: str, meta: Mapping[str, Any], score: float) -> CharterChunk:
        page = meta.get("page", _NO_PAGE)
        return CharterChunk(
            chunk_id=meta["chunk_id"],
            initiative_id=meta["initiative_id"],
            source_file=meta["source_file"],
            section=meta["section"],
            page=None if page == _NO_PAGE else int(page),
            text=text,
            score=score,
            injection_flag=bool(meta["injection_flag"]),
        )

    def _validate_query_embedding(self, embedding: list[float]) -> None:
        if embedding is None or len(embedding) == 0:
            raise VectorStoreError("query embedding is empty")
        if len(embedding) != self._dim:
            raise VectorStoreError(f"query embedding dimension {len(embedding)} != configured {self._dim}")
        try:
            vals = [float(x) for x in embedding]
        except (TypeError, ValueError):
            raise VectorStoreError("query embedding contains non-numeric values") from None
        if not all(math.isfinite(x) for x in vals):
            raise VectorStoreError("query embedding contains non-finite values")
        if not any(vals):
            raise VectorStoreError("query embedding is the zero vector; cosine similarity is undefined")
