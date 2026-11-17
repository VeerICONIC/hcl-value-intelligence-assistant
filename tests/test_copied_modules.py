"""The modules reused from the practice repo import cleanly and still work after adaptation.

All offline: Bedrock is faked and Chroma writes to a pytest temp directory.
"""

from __future__ import annotations

import importlib
import json

import pytest

from app.schemas import CharterChunk

COPIED_MODULES = [
    "app.core.bedrock",
    "app.charters.embeddings",
    "app.charters.store",
    "app.charters.parsers.base",
    "app.charters.parsers.markdown_parser",
    "app.charters.parsers.pdf_parser",
    "app.charters.retriever",
]


@pytest.mark.parametrize("name", COPIED_MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_test_bedrock_script_imports_without_running():
    import runpy
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "test_bedrock.py"
    ns = runpy.run_path(str(script), run_name="not_main")  # defines main() but doesn't call it
    assert callable(ns["main"])


# --- Bedrock + embeddings ------------------------------------------------------
def test_bedrock_runtime_construction_makes_no_aws_call(monkeypatch, settings):
    from app.core import bedrock

    def _boom(*a, **k):
        raise AssertionError("boto3 session created at construction time")

    monkeypatch.setattr(bedrock.boto3, "Session", _boom)
    rt = bedrock.BedrockRuntime(settings)
    assert rt._client is None


class _FakeRuntime:
    """Stands in for BedrockRuntime: returns a fixed-size Titan-shaped response."""

    def __init__(self, dim: int):
        self.dim, self.calls = dim, 0

    def invoke_model(self, model_id, body):
        self.calls += 1
        assert json.loads(body)["dimensions"] == self.dim
        return json.dumps({"embedding": [0.1] * self.dim}).encode()


def test_titan_embedder_with_fake_runtime(settings):
    from app.charters.embeddings import EmbeddingError, TitanEmbedder

    fake = _FakeRuntime(settings.bedrock_embed_dim)
    emb = TitanEmbedder(runtime=fake, settings=settings)
    vecs = emb.embed_documents(["risk one", "risk two", "risk three"])
    assert len(vecs) == 3 and len(vecs[0]) == 1024 and fake.calls == 3
    with pytest.raises(EmbeddingError):
        emb.embed_query("   ")


# --- Chroma store ----------------------------------------------------------------
def _vec(hot: int, dim: int = 1024) -> list[float]:
    v = [0.0] * dim
    v[hot] = 1.0
    return v


def _chunk(cid: str, init: str, text: str, page: int | None) -> CharterChunk:
    return CharterChunk(chunk_id=cid, initiative_id=init, source_file=f"{init}.md", section="Risks and Mitigations",
                        page=page, text=text, score=0.0, injection_flag=False)


@pytest.fixture
def store(settings):
    from app.charters.store import CharterStore

    s = CharterStore(settings)
    yield s
    s.close()


def test_store_round_trip_keeps_page_none_and_scores_by_similarity(store):
    chunks = [_chunk("A:1", "INIT-001", "adoption risk", None),
              _chunk("B:1", "INIT-002", "budget risk", 2)]
    store.upsert(chunks, [_vec(0), _vec(1)])
    assert store.count() == 2
    assert store.name == "charters__titan-embed-text-v2__1024"

    hits = store.query(_vec(0), top_k=2)
    assert [h.chunk_id for h in hits] == ["A:1", "B:1"]
    assert hits[0].score == pytest.approx(1.0) and hits[1].score == pytest.approx(0.0, abs=1e-6)
    assert hits[0].page is None and hits[1].page == 2  # None survived the -1 sentinel

    only_two = store.get_all_chunks({"initiative_id": "INIT-002"})
    assert [c.chunk_id for c in only_two] == ["B:1"] and only_two[0].score == 0.0

    store.reset()
    assert store.count() == 0


def test_store_rejects_wrong_dimension(store):
    from app.core.exceptions import VectorStoreError

    with pytest.raises(VectorStoreError):
        store.upsert([_chunk("A:1", "INIT-001", "x", None)], [[0.1] * 10])


# --- BM25 + RRF ------------------------------------------------------------------
def test_bm25_and_rrf_on_charter_chunks():
    from app.charters.retriever import Bm25Index, VectorHit, rrf_fuse, tokenize

    a = _chunk("A:1", "INIT-001", "Low adoption is the main risk for the HR copilot", None)
    b = _chunk("B:1", "INIT-002", "Budget overrun risk for the helpdesk bot", None)
    hits = Bm25Index([a, b]).search(tokenize("adoption risk"), n=2)
    assert hits[0].chunk.chunk_id == "A:1" and hits[0].coverage == 1.0

    fused = rrf_fuse([VectorHit(b, 0.9, 1), VectorHit(a, 0.5, 2)], hits, k=60)
    assert {f.chunk.chunk_id for f in fused} == {"A:1", "B:1"}
    assert all(0.0 <= f.score <= 1.0 for f in fused)
    assert "init-003" in tokenize("Status of INIT-003?")


# --- Parsers ---------------------------------------------------------------------
def test_markdown_parser_finds_sections():
    from app.charters.parsers.markdown_parser import MarkdownParser

    md = b"# HR Policy Copilot Charter\n\n## Overview\nAnswers HR policy questions.\n\n## Risks and Mitigations\n- Low adoption\n"
    doc = MarkdownParser().parse(md, "INIT-001_charter.md")
    headings = [b.text for b in doc.blocks if b.kind == "heading"]
    assert headings == ["HR Policy Copilot Charter", "Overview", "Risks and Mitigations"]
    assert doc.title == "HR Policy Copilot Charter"


def test_pdf_parser_detects_headings_by_font_size():
    import pymupdf

    from app.charters.parsers.pdf_parser import PdfParser

    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Risks and Mitigations", fontsize=18)
    page.insert_text((72, 110), "Vendor delays could postpone the rollout of the model.", fontsize=11)
    data = pdf.tobytes()
    pdf.close()

    doc = PdfParser().parse(data, "INIT-003_charter.pdf")
    kinds = [(b.kind, b.text) for b in doc.blocks]
    assert ("heading", "Risks and Mitigations") in kinds
    assert all(b.page == 1 for b in doc.blocks)
