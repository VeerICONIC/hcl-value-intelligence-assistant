"""Charter files -> section-aware chunks with metadata (FR-04).

One chunk per level-2 section ("Overview", "Risks and Mitigations", ...), because executives
ask about sections ("what are the risks of X?") and a section is a self-contained unit of
meaning in these charters. Metadata: source_file, initiative_id (from "(INIT-NNN)" in the
title), section, page (PDF only), and an injection flag (see ``injection.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from app.charters.injection import contains_injection
from app.charters.parsers.base import Block
from app.charters.parsers.markdown_parser import MarkdownParser
from app.charters.parsers.pdf_parser import PdfParser
from app.schemas import CharterChunk

_ID = re.compile(r"\((INIT-\d{3})\)")
SUPPORTED = (".md", ".pdf", ".docx")


def _docx_blocks(path: Path) -> list[Block]:
    blocks = []
    for p in Document(str(path)).paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name or "").lower()
        if style.startswith("heading"):
            level = int(re.findall(r"\d+", style)[0]) if re.findall(r"\d+", style) else 1
            blocks.append(Block("heading", text, level=level))
        elif "list" in style:
            blocks.append(Block("list", f"- {text}"))
        else:
            blocks.append(Block("paragraph", text))
    return blocks


def parse_blocks(path: Path) -> list[Block]:
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".md":
        return MarkdownParser().parse(data, path.name).blocks
    if suffix == ".pdf":
        return PdfParser().parse(data, path.name).blocks
    if suffix == ".docx":
        return _docx_blocks(path)
    raise ValueError(f"unsupported charter format: {path.name}")


def chunk_charter(path: Path) -> list[CharterChunk]:
    """Split one charter into one chunk per section. Raises ValueError if no INIT id is found."""
    blocks = parse_blocks(path)
    title = next((b.text for b in blocks if b.kind == "heading" and b.level == 1), "")
    m = _ID.search(title) or _ID.search(" ".join(b.text for b in blocks[:3]))
    if not m:
        raise ValueError(f"{path.name}: no '(INIT-NNN)' found in the title")
    iid = m.group(1)

    sections: list[tuple[str, list[Block]]] = []
    for b in blocks:
        if b.kind == "heading" and b.level == 1:
            continue
        if b.kind == "heading":
            sections.append((b.text.strip(), []))
        elif sections:
            sections[-1][1].append(b)
        else:
            sections.append(("Overview", [b]))

    chunks = []
    for section, body in sections:
        if not body:
            continue
        # PDF lines are split mid-sentence: glue a fragment onto the previous line unless that line
        # ended a sentence or the fragment starts a new list item.
        lines: list[str] = []
        for b in body:
            for line in b.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if lines and not lines[-1].endswith((".", "!", "?", ":")) and not line.startswith(("-", "*", "•")):
                    lines[-1] = f"{lines[-1]} {line}"
                else:
                    lines.append(line)
        text = "\n".join(lines).strip()
        pages = [b.page for b in body if b.page and b.page > 0]
        slug = re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")
        chunks.append(CharterChunk(
            chunk_id=f"{iid}:{slug}", initiative_id=iid, source_file=path.name, section=section,
            page=pages[0] if pages else None, text=text, score=0.0, injection_flag=contains_injection(text)))
    return chunks


def chunk_folder(folder: Path) -> list[CharterChunk]:
    out: list[CharterChunk] = []
    for path in sorted(Path(folder).iterdir()):
        if path.suffix.lower() in SUPPORTED:
            out.extend(chunk_charter(path))
    return out
