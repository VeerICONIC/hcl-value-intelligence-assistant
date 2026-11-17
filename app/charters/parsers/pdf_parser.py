"""PDF parser (PyMuPDF).

* One page at a time, so a block never spans pages and every block has its page number.
* Headings are inferred from font size/weight relative to the document's body text.
* Repeated running headers/footers and bare page numbers are removed.
* Image-only (scanned) PDFs raise ``OcrRequiredError``; OCR is not implemented.
* Tables are not reconstructed; their text is extracted in reading order.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import pymupdf as fitz  # PyMuPDF (the "fitz" import name is deprecated)

from app.charters.parsers.base import Block, DocumentParser, ParsedDocument, title_from_headings
from app.core.exceptions import (
    CorruptDocumentError,
    EmptyDocumentError,
    EncryptedDocumentError,
    OcrRequiredError,
)

_BOLD_FLAG = 16
_PAGE_NUMBER = re.compile(r"^(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?$", re.I)
_HEADING_MAX_CHARS = 150
_MAX_LEVEL = 4


@dataclass
class _Raw:
    page: int
    text: str
    size: float
    bold: bool
    lines: int
    chars: int


def _join_lines(lines: list[str]) -> str:
    """Join wrapped lines, repairing hyphenation only for 'letter-' + lowercase continuations."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif re.search(r"[A-Za-z]-$", out) and line[:1].islower():
            out = out[:-1] + line
        else:
            out += " " + line
    return out


def _extract_raw(doc: "fitz.Document") -> tuple[list[_Raw], list[int]]:
    raws: list[_Raw] = []
    empty_pages: list[int] = []
    for pno, page in enumerate(doc, 1):
        found = False
        for b in page.get_text("dict", sort=True).get("blocks", []):
            if b.get("type") != 0:
                continue
            line_texts, sizes, bolds, chars = [], [], [], 0
            for ln in b.get("lines", []):
                spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue
                line_texts.append("".join(s["text"] for s in ln["spans"]))
                for s in spans:
                    n = len(s["text"].strip())
                    chars += n
                    sizes.append((round(s["size"] * 2) / 2, n))
                    bolds.append(bool(s["flags"] & _BOLD_FLAG) or "bold" in s.get("font", "").lower())
            text = _join_lines(line_texts)
            if not text:
                continue
            found = True
            raws.append(_Raw(pno, text, max(sz for sz, _ in sizes), all(bolds), len(line_texts), chars))
        if not found:
            empty_pages.append(pno)
    return raws, empty_pages


def _strip_running_text(raws: list[_Raw], page_count: int) -> list[_Raw]:
    """Drop page numbers and headers/footers repeated on most pages (first/last block of a page)."""
    by_page: dict[int, list[int]] = {}
    for idx, r in enumerate(raws):
        by_page.setdefault(r.page, []).append(idx)
    drop: set[int] = set()
    keys: Counter[str] = Counter()
    edge: dict[int, str] = {}
    for idxs in by_page.values():
        for idx in {idxs[0], idxs[-1]}:
            r = raws[idx]
            if len(r.text) > 120:
                continue
            if _PAGE_NUMBER.match(r.text.strip()):
                drop.add(idx)
                continue
            key = re.sub(r"\d+", "#", r.text.lower())
            edge[idx] = key
            keys[key] += 1
    if page_count >= 3:
        for idx, key in edge.items():
            if keys[key] >= max(3, 0.6 * page_count):
                drop.add(idx)
    return [r for i, r in enumerate(raws) if i not in drop]


class PdfParser(DocumentParser):
    doc_type = "pdf"
    extensions = ("pdf",)

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception:  # fitz raises several types for malformed input
            raise CorruptDocumentError(filename, "file is not a readable PDF (corrupted or wrong format)") from None
        try:
            if doc.needs_pass:
                raise EncryptedDocumentError(filename, "PDF is password-protected; remove the password and upload again")
            if doc.page_count == 0:
                raise EmptyDocumentError(filename, "PDF has no pages")
            try:
                raws, empty_pages = _extract_raw(doc)
            except Exception:
                raise CorruptDocumentError(filename, "PDF content could not be read (corrupted file)") from None
            if not raws:
                if any(page.get_images() for page in doc):
                    raise OcrRequiredError(
                        filename,
                        "PDF has no extractable text and appears to be scanned/image-only; "
                        "OCR is required but is not implemented",
                    )
                raise EmptyDocumentError(filename, "PDF contains no text")
            meta_title = (doc.metadata or {}).get("title", "") or ""
            page_count = doc.page_count
        finally:
            doc.close()

        raws = _strip_running_text(raws, page_count)
        if not raws:
            raise EmptyDocumentError(filename, "PDF contains only page numbers/headers and no body text")

        size_chars: Counter[float] = Counter()
        for r in raws:
            size_chars[r.size] += r.chars
        body = size_chars.most_common(1)[0][0]

        def is_heading(r: _Raw) -> bool:
            if len(r.text) > _HEADING_MAX_CHARS or r.lines > 3:
                return False
            if r.size >= body * 1.12:
                return True
            return r.bold and r.lines == 1 and len(r.text) <= 100 and r.size >= body * 0.99 and not r.text.endswith(".")

        sizes = sorted({r.size for r in raws if is_heading(r) and r.size >= body * 1.12}, reverse=True)
        blocks: list[Block] = []
        for r in raws:
            if is_heading(r):
                level = sizes.index(r.size) + 1 if r.size in sizes else len(sizes) + 1
                blocks.append(Block("heading", r.text, level=min(level, _MAX_LEVEL), page=r.page))
            else:
                blocks.append(Block("paragraph", r.text, page=r.page))

        warnings = []
        if empty_pages:
            warnings.append(f"no extractable text on page(s) {empty_pages}; they may be scanned images")
        title = meta_title.strip()
        if not title:
            title = title_from_headings(blocks)
        return ParsedDocument(filename=filename, doc_type="pdf", title=title, blocks=blocks,
                              warnings=warnings, page_count=page_count)
