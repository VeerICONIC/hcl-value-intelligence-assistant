"""Charter retrieval building blocks: BM25 lexical search and Reciprocal Rank Fusion.

Step 1 provides the pieces; Step 5 adds ``search_charters(query, initiative_ids, k)``,
which runs vector search (Titan + Chroma) and BM25 and fuses them with ``rrf_fuse``.

Why hybrid? Vector search finds paraphrases ("adoption problems" ~ "low usage");
BM25 finds exact terms (initiative names, "Risks and Mitigations"). RRF combines the
two rankings without needing their scores to be comparable.

Copied from the practice repo (``app/retrieval/bm25_retriever.py`` + ``rrf_fuse`` from
``hybrid_ranker.py``). ``tokenize`` (from ``retrieval/text.py``) and the hit dataclasses
(from ``retrieval/models.py``) were folded in; chunks are now ``CharterChunk``.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

from app.schemas import CharterChunk

# --------------------------------------------------------------------------
# Tokenisation
# --------------------------------------------------------------------------
# Words with no retrieval value. Deliberately small and English-only (documented limitation).
STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have how i if in into is it its
may might must of on or our shall should so than that the their them then there these they this those to
was we were what when where which who whom why will with would you your not no any all each per via also
my me mine his her him she he us ours yours
""".split())

# word characters, optionally joined by - or . so identifiers like "init-003" survive intact
_TOKEN = re.compile(r"[^\W_]+(?:[-.][^\W_]+)*", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lower-cased content tokens. Compound identifiers are kept whole *and* split,
    so both ``init-003`` and ``003`` match. Stop words and single letters are dropped."""
    out: list[str] = []
    for tok in _TOKEN.findall(text.lower()):
        parts = re.split(r"[-.]", tok)
        if len(parts) > 1:
            out.append(tok)
        out.extend(parts)
    return [t for t in out if t not in STOPWORDS and (len(t) > 1 or t.isdigit())]


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------
class ChunkSource(Protocol):
    """What BM25 needs from a store (satisfied by ``CharterStore``)."""

    def get_all_chunks(self, where: Optional[dict] = None) -> list[CharterChunk]: ...


@dataclass(frozen=True)
class VectorHit:
    chunk: CharterChunk
    similarity: float   # cosine similarity
    rank: int           # 1-based


@dataclass(frozen=True)
class Bm25Hit:
    chunk: CharterChunk
    score: float        # raw BM25 score (only meaningful within one query)
    rank: int           # 1-based
    coverage: float     # fraction of distinct query terms present in the chunk


@dataclass
class FusedCandidate:
    chunk: CharterChunk
    rrf: float                          # raw reciprocal-rank-fusion sum
    score: float                        # rrf normalised to 0..1
    vector_rank: Optional[int] = None
    bm25_rank: Optional[int] = None
    vector_score: Optional[float] = None
    coverage: float = 0.0


# --------------------------------------------------------------------------
# BM25
# --------------------------------------------------------------------------
class Bm25Index:
    """Okapi BM25. IDF is ``ln(1 + (N - n + 0.5) / (n + 0.5))``, never negative,
    unlike some library variants that misbehave on small corpora (we have ~8 charters)."""

    def __init__(self, chunks: Sequence[CharterChunk], k1: float = 1.5, b: float = 0.75):
        self._chunks = list(chunks)
        self._k1, self._b = k1, b
        self._tf = [Counter(tokenize(c.text)) for c in self._chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self._chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query_terms: Sequence[str], n: int) -> list[Bm25Hit]:
        terms = list(dict.fromkeys(query_terms))
        if not terms or not self._chunks:
            return []
        scored: list[tuple[float, float, CharterChunk]] = []
        for chunk, tf, dl in zip(self._chunks, self._tf, self._len):
            score = 0.0
            present = 0
            for t in terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                present += 1
                norm = 1 - self._b + self._b * (dl / self._avg if self._avg else 1.0)
                score += self._idf[t] * f * (self._k1 + 1) / (f + self._k1 * norm)
            if score > 0:
                scored.append((score, present / len(terms), chunk))
        scored.sort(key=lambda r: (-r[0], r[2].chunk_id))
        return [Bm25Hit(c, s, rank, cov) for rank, (s, cov, c) in enumerate(scored[:n], 1)]


_MAX_CACHED_FILTERS = 8


class Bm25Retriever:
    """BM25 over the chunks in the store, cached per metadata filter.

    The cache key includes the store's ``revision`` counter, which every write through
    the store bumps, so re-indexing invalidates it automatically. A store without
    ``revision`` is never cached. Limitation: the counter is per process.
    """

    def __init__(self, store: ChunkSource, k1: float = 1.5, b: float = 0.75):
        self._store, self._k1, self._b = store, k1, b
        self._cache: dict[str, tuple[int, Bm25Index]] = {}
        self._lock = threading.Lock()
        self.builds = 0  # number of index builds (observable in tests)

    def _index(self, where: Optional[dict]) -> Bm25Index:
        revision = getattr(self._store, "revision", None)
        key = json.dumps(where, sort_keys=True, default=str) if where else ""
        with self._lock:
            hit = self._cache.get(key)
            if revision is not None and hit is not None and hit[0] == revision:
                return hit[1]
            index = Bm25Index(self._store.get_all_chunks(where), self._k1, self._b)
            self.builds += 1
            if revision is not None:
                if len(self._cache) >= _MAX_CACHED_FILTERS:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = (revision, index)
            return index

    def search(self, query: str, n: int, where: Optional[dict] = None) -> list[Bm25Hit]:
        """Top-n lexical matches. Empty/punctuation-only queries and empty corpora give []."""
        terms = tokenize(query)
        if not terms:
            return []
        return self._index(where).search(terms, n)


# --------------------------------------------------------------------------
# Reciprocal Rank Fusion
# --------------------------------------------------------------------------
_SYSTEMS = 2


def rrf_fuse(vector_hits: Sequence[VectorHit], bm25_hits: Sequence[Bm25Hit], k: int = 60) -> list[FusedCandidate]:
    """Fuse two rankings: ``rrf(d) = sum over lists containing d of 1 / (k + rank)``.

    Uses only positions, never the text. ``score`` = rrf relative to the best possible
    value (rank 1 in both lists), so 0..1; it expresses rank agreement, NOT a probability.
    Ties: higher cosine similarity first (unknown last), then chunk_id. Deduplicates by chunk_id.
    """
    if k < 1:
        raise ValueError("RRF constant k must be >= 1")
    best = _SYSTEMS / (k + 1)
    by_id: dict[str, FusedCandidate] = {}

    def entry(chunk: CharterChunk) -> FusedCandidate:
        if chunk.chunk_id not in by_id:
            by_id[chunk.chunk_id] = FusedCandidate(chunk=chunk, rrf=0.0, score=0.0)
        return by_id[chunk.chunk_id]

    for h in vector_hits:
        e = entry(h.chunk)
        if e.vector_rank is None:  # first occurrence wins if a list ever repeats an ID
            e.vector_rank, e.vector_score = h.rank, h.similarity
            e.rrf += 1.0 / (k + h.rank)
    for h in bm25_hits:
        e = entry(h.chunk)
        if e.bm25_rank is None:
            e.bm25_rank, e.coverage = h.rank, h.coverage
            e.rrf += 1.0 / (k + h.rank)

    for e in by_id.values():
        e.score = min(1.0, e.rrf / best)
    return sorted(
        by_id.values(),
        key=lambda e: (-e.rrf, -(e.vector_score if e.vector_score is not None else float("-inf")), e.chunk.chunk_id),
    )
