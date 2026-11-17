"""Common parser interface, the format-independent document model, and shared helpers.

Every charter parser (Markdown, PDF, and DOCX in Step 5) turns raw bytes into a
``ParsedDocument``: an ordered list of ``Block``s (headings, paragraphs, lists,
tables). The chunker then works on blocks and never needs to know the file format.

Copied from the practice repo's ``app/ingestion/parsers/base.py``. ``Block``,
``ParsedDocument`` and ``title_from_headings`` were folded in from its
``app/ingestion/models.py``; errors now come from ``app.core.exceptions``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import ClassVar, Literal, Optional

from app.core.exceptions import CorruptDocumentError, UnsupportedEncodingError

BlockKind = Literal["heading", "paragraph", "list", "table", "code"]
DocType = Literal["md", "pdf", "docx"]


@dataclass(frozen=True)
class Block:
    """A structural unit of a document.

    ``level`` is only meaningful for headings (1 = top). ``page`` is 1-based, or
    -1 when the format has no pages.
    """

    kind: BlockKind
    text: str
    level: int = 0
    page: int = -1

    def with_text(self, text: str) -> "Block":
        return replace(self, text=text)


@dataclass
class ParsedDocument:
    filename: str
    doc_type: DocType
    title: str = ""
    blocks: list[Block] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    page_count: Optional[int] = None


def title_from_headings(blocks: list[Block]) -> str:
    """A heading is only a trustworthy document title when it is the sole level-1 heading."""
    h1 = [b.text for b in blocks if b.kind == "heading" and b.level == 1]
    return h1[0] if len(h1) == 1 else ""


class DocumentParser(ABC):
    """Turns raw file bytes into a ``ParsedDocument``."""

    doc_type: ClassVar[str]
    extensions: ClassVar[tuple[str, ...]]

    @abstractmethod
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        """Parse ``data``; raise a ``DocumentParseError`` subclass on failure."""


def decode_text(data: bytes, filename: str) -> str:
    """Decode text bytes: UTF-8 (with/without BOM) or UTF-16 with BOM. Anything else is an error."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            raise UnsupportedEncodingError(filename, "invalid UTF-16 text") from None
    if b"\x00" in data:
        raise CorruptDocumentError(filename, "file contains binary (NUL) data and is not readable text")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UnsupportedEncodingError(
            filename, "text is not valid UTF-8; re-save the file as UTF-8"
        ) from None
