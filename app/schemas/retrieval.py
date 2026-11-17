"""Charter-retrieval contract (architecture.md §6). Changing a field needs the developer's approval."""

from __future__ import annotations

from pydantic import BaseModel


class CharterChunk(BaseModel):
    """A section-aware piece of an initiative charter (FR-04).

    ``score`` is the retrieval relevance for the current query (0.0 when the chunk
    was read without a query). ``injection_flag`` is set at index time when the text
    matches a prompt-injection pattern; such text is data, never instructions.
    """

    chunk_id: str
    initiative_id: str
    source_file: str
    section: str
    page: int | None              # None for formats without pages (Markdown, DOCX)
    text: str
    score: float
    injection_flag: bool
