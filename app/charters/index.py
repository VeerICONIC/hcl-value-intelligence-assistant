"""Charter index and search (FR-04).

Two retrieval modes, chosen by LLM_MODE:
- ``extractive`` (offline, default when AWS is not signed in): BM25 over section chunks.
- ``bedrock``: Titan Text Embeddings V2 vectors in ChromaDB (cosine). If any Bedrock or Chroma
  call fails, search falls back to BM25, so the assistant never breaks because AWS is down.

Search is always restricted to the initiative(s) the router found, and a preferred section
(e.g. "Risks and Mitigations" for a risk question) is taken directly when the charter has it.
If the charter has no such section, nothing is returned and the assistant gives the fallback,
which is the correct answer for INIT-003's risks (its charter has no Risks section).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.charters.chunker import chunk_folder
from app.charters.retriever import Bm25Index, tokenize
from app.core.config import Settings
from app.core.exceptions import NimbusError
from app.schemas import CharterChunk

logger = logging.getLogger(__name__)

BM25_MIN_SCORE = 0.5          # below this, a lexical match is too weak to count as evidence
VECTOR_MIN_SCORE = 0.30       # cosine similarity threshold for Titan vectors


class CharterIndex:
    """In-memory chunk list (rebuilt in well under a second), plus a Chroma collection in bedrock mode."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.chunks: list[CharterChunk] = []
        self.source_dir: Path | None = None
        self.vector_ready = False

    # -- build -------------------------------------------------------------------
    def build(self, charters_dir: Path) -> dict:
        self.chunks = chunk_folder(charters_dir)
        self.source_dir = Path(charters_dir)
        self.vector_ready = False
        mode = "bm25"
        if self.settings.llm_mode == "bedrock":
            try:
                self._build_vectors()
                mode = "titan+chroma"
            except (NimbusError, Exception) as exc:   # noqa: BLE001 - any AWS/Chroma failure -> offline mode
                logger.warning("Vector indexing failed, using BM25 only: %s", exc)
        files = sorted({c.source_file for c in self.chunks})
        return {"charters_dir": str(self.source_dir), "chunks": len(self.chunks), "files": len(files), "initiatives": len({c.initiative_id for c in self.chunks}),
                "injection_flagged": [c.chunk_id for c in self.chunks if c.injection_flag], "retrieval": mode}

    def _build_vectors(self) -> None:
        from app.charters.embeddings import TitanEmbedder
        from app.charters.store import CharterStore
        store = CharterStore(self.settings)
        store.reset()
        store.upsert(self.chunks, TitanEmbedder(settings=self.settings).embed_documents([c.text for c in self.chunks]))
        self.vector_ready = True

    # -- search ------------------------------------------------------------------
    def search(self, query: str, initiative_ids: list[str], preferred_sections: list[str], k: int = 2
               ) -> list[CharterChunk]:
        pool = [c for c in self.chunks if c.initiative_id in initiative_ids]
        if not pool:
            return []
        if preferred_sections:
            wanted = [s.lower() for s in preferred_sections]
            hits = [c for c in pool if c.section.lower() in wanted]
            hits.sort(key=lambda c: (wanted.index(c.section.lower()), c.chunk_id))
            # one best section per initiative
            out, seen = [], set()
            for c in hits:
                if c.initiative_id not in seen:
                    out.append(c.model_copy(update={"score": 1.0}))
                    seen.add(c.initiative_id)
            return out
        if self.settings.llm_mode == "bedrock" and self.vector_ready:
            try:
                return self._vector_search(query, initiative_ids, k)
            except Exception as exc:   # noqa: BLE001
                logger.warning("Vector search failed, using BM25: %s", exc)
        hits = Bm25Index(pool).search(tokenize(query), k)
        return [h.chunk.model_copy(update={"score": round(h.score, 3)}) for h in hits if h.score >= BM25_MIN_SCORE]

    def _vector_search(self, query: str, initiative_ids: list[str], k: int) -> list[CharterChunk]:
        from app.charters.embeddings import TitanEmbedder
        from app.charters.store import CharterStore
        emb = TitanEmbedder(settings=self.settings).embed_query(query)
        where = {"initiative_id": {"$in": initiative_ids}}
        return [c for c in CharterStore(self.settings).query(emb, k, where=where) if c.score >= VECTOR_MIN_SCORE]

    def risks_for(self, iid: str) -> CharterChunk | None:
        return next((c for c in self.chunks if c.initiative_id == iid and "risk" in c.section.lower()), None)
