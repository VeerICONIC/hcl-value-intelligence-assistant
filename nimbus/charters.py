"""
Charter indexing and retrieval (FR-04).

Parse Markdown / PDF / DOCX charters, split by section heading, attach metadata
(source file, initiative ID, section), flag instruction-like lines (prompt injection),
embed (Titan, or local fallback) and store in a persistent ChromaDB collection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import chromadb

from nimbus import llm
from nimbus.settings import CHROMA_DIR, ROOT

SECTIONS = ["Overview", "Objectives", "Scope", "Success Measures", "Benefits Plan",
            "Risks and Mitigations", "Stakeholders", "Timeline"]
INJECTION = re.compile(r"(ignore (all )?(previous|prior|above) instructions|disregard .*instructions|note to (any )?ai|"
                       r"you must (now )?(report|say|state)|system prompt|act as|report this initiative as|state that its)", re.I)


def strip_injection(text: str) -> tuple[str, int]:
    """Drop every bullet / sentence that contains an instruction-like pattern. Returns (clean text, removed count)."""
    parts = re.split(r"\s(?=- )", text)
    kept = [p for p in parts if not INJECTION.search(p)]
    return " ".join(kept), len(parts) - len(kept)
ID_RE = re.compile(r"\(?(INIT-\d{3})\)?", re.I)


@dataclass
class Chunk:
    chunk_id: str
    initiative_id: str
    initiative_name: str
    source_file: str
    section: str
    text: str
    injection_flag: bool
    score: float = 0.0


def _lines(path: Path) -> list[tuple[str, bool]]:
    """Return (line, is_heading) pairs."""
    if path.suffix == ".md":
        out = []
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.startswith("#"):
                out.append((ln.lstrip("#").strip(), True))
            elif ln.strip():
                out.append((ln.strip(), False))
        return out
    if path.suffix == ".docx":
        from docx import Document

        return [(p.text.strip(), p.style.name.lower().startswith("heading")) for p in Document(path).paragraphs if p.text.strip()]
    if path.suffix == ".pdf":
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        out = []
        for ln in text.splitlines():
            s = ln.strip()
            if s:
                out.append((s, s in SECTIONS or s.startswith("Initiative Charter")))
        return out
    raise ValueError(f"Unsupported charter format: {path.name}")


def parse_charter(path: Path) -> list[Chunk]:
    lines = _lines(path)
    title = next((t for t, h in lines if h), path.stem)
    m = ID_RE.search(title)
    iid = m.group(1).upper() if m else "UNKNOWN"
    name = re.sub(r"^Initiative Charter:\s*", "", ID_RE.sub("", title)).strip(" ()")
    chunks, section, buf = [], None, []

    def flush():
        if section and buf:
            text = " ".join(buf)
            chunks.append(Chunk(f"{path.name}::{len(chunks):02d}", iid, name, path.name, section, text,
                                bool(INJECTION.search(text))))

    for text, is_head in lines:
        if is_head and text != title:
            flush()
            section, buf = text, []
        elif not is_head:
            buf.append(text)
    flush()
    return chunks


class CharterIndex:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self.mode = "local"
        self.collection = None

    def build(self, charter_dir: str | Path) -> dict:
        d = Path(charter_dir)
        d = d if d.is_absolute() else ROOT / d
        self.chunks = [c for p in sorted(d.iterdir()) if p.suffix in (".md", ".pdf", ".docx") for c in parse_charter(p)]
        self.mode = llm.embedding_mode()
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        name = f"charters_{self.mode}_{d.parent.name}"
        try:
            client.delete_collection(name)
        except Exception:  # noqa: BLE001
            pass
        self.collection = client.create_collection(name=name, embedding_function=None,
                                                   configuration={"hnsw": {"space": "cosine"}})
        texts = [f"Initiative: {c.initiative_name} ({c.initiative_id}). Section: {c.section}. {c.text}" for c in self.chunks]
        note = ""
        try:
            vectors = llm.embed(texts, self.mode, budget_s=llm.TITAN_INDEX_BUDGET_S if self.mode == "titan" else None)
        except Exception as e:  # e.g. Titan throttled / credentials expired: index locally instead of failing the run
            why = "took too long" if type(e).__name__ == "TimeoutError" else f"failed ({type(e).__name__})"
            note = f"Titan embedding {why}; indexed with local embeddings instead"
            client.delete_collection(name)
            self.mode = "local"
            name = f"charters_local_{d.parent.name}"
            try:
                client.delete_collection(name)
            except Exception:  # noqa: BLE001
                pass
            self.collection = client.create_collection(name=name, embedding_function=None,
                                                       configuration={"hnsw": {"space": "cosine"}})
            vectors = llm.embed(texts, "local")
        self.collection.add(ids=[c.chunk_id for c in self.chunks], embeddings=vectors, documents=[c.text for c in self.chunks],
                            metadatas=[{"initiative_id": c.initiative_id, "source_file": c.source_file, "section": c.section,
                                        "injection_flag": c.injection_flag} for c in self.chunks])
        files = sorted({c.source_file for c in self.chunks})
        return {"charters": len(files), "chunks": len(self.chunks), "embedding_mode": self.mode, "note": note,
                "flagged_chunks": [c.chunk_id for c in self.chunks if c.injection_flag]}

    def section(self, iid: str, section: str) -> list[Chunk]:
        return [c for c in self.chunks if c.initiative_id == iid and c.section.lower() == section.lower()]

    def has_initiative(self, iid: str) -> bool:
        return any(c.initiative_id == iid for c in self.chunks)

    def search(self, query: str, iids: list[str] | None = None, k: int = 3, sections: list[str] | None = None) -> list[Chunk]:
        if not self.collection or not self.chunks:
            return []
        conds = []
        if iids:
            conds.append({"initiative_id": iids[0]} if len(iids) == 1 else {"initiative_id": {"$in": iids}})
        if sections:
            conds.append({"section": sections[0]} if len(sections) == 1 else {"section": {"$in": sections}})
        where = None if not conds else (conds[0] if len(conds) == 1 else {"$and": conds})
        by_id = {c.chunk_id: c for c in self.chunks}
        q_terms = _terms(query)
        try:
            res = self.collection.query(query_embeddings=llm.embed([query], self.mode), n_results=min(k * 4, len(self.chunks)), where=where)
            pairs = list(zip(res["ids"][0], res["distances"][0]))
        except Exception:  # e.g. Bedrock credentials expired mid-demo: fall back to keyword-only ranking
            cand = [c for c in self.chunks if (not iids or c.initiative_id in iids) and (not sections or c.section in sections)]
            pairs = [(c.chunk_id, 1.0) for c in cand]          # distance 1.0 -> vector part contributes 0
        out = []
        for cid, dist in pairs:
            c = by_id[cid]
            overlap = len(q_terms & _terms(c.text)) / len(q_terms) if q_terms else 0.0
            score = 0.6 * (1 - dist) + 0.4 * overlap          # hybrid: vector similarity + keyword overlap
            out.append(Chunk(**{**c.__dict__, "score": round(score, 4)}))
        return sorted(out, key=lambda c: -c.score)[:k]


def _terms(text: str) -> set[str]:
    return {llm._stem(w) for w in re.findall(r"[a-z]+", text.lower()) if w not in llm.STOP and len(w) > 2}
