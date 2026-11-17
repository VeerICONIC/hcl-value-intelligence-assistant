"""Markdown parser.

Line-based and deliberately light: headings define structure, while fenced code,
tables and lists are kept verbatim as single blocks. Inline Markdown syntax is not
stripped, so no meaning is lost.
"""

from __future__ import annotations

import re

from app.charters.parsers.base import Block, DocumentParser, ParsedDocument, decode_text, title_from_headings

_ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_TABLE_SEP = re.compile(r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$")
_LIST_ITEM = re.compile(r"^[ \t]*([-*+]|\d+[.)])[ \t]+\S")
_TITLE_KEY = re.compile(r"^title:\s*(.+?)\s*$", re.I)


def _front_matter(lines: list[str]) -> tuple[str, int]:
    """Return (title, index of first body line) for a leading YAML block."""
    if lines and lines[0].strip() == "---":
        for j in range(1, min(len(lines), 60)):
            if lines[j].strip() in ("---", "..."):
                title = ""
                for k in range(1, j):
                    m = _TITLE_KEY.match(lines[k])
                    if m:
                        title = m.group(1).strip("'\"")
                return title, j + 1
    return "", 0


def _continues_list(line: str) -> bool:
    return bool(line.strip()) and (bool(_LIST_ITEM.match(line)) or line[:1] in (" ", "\t"))


class MarkdownParser(DocumentParser):
    doc_type = "md"
    extensions = ("md", "markdown")

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        lines = decode_text(data, filename).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        fm_title, i = _front_matter(lines)
        n = len(lines)
        blocks: list[Block] = []
        para: list[str] = []

        def flush() -> None:
            if para:
                blocks.append(Block("paragraph", "\n".join(para)))
                para.clear()

        while i < n:
            line = lines[i]
            fence = _FENCE.match(line)
            atx = _ATX.match(line)
            if fence:
                flush()
                marker = fence.group(1)
                j = i + 1
                while j < n and not lines[j].lstrip().startswith(marker[0] * len(marker)):
                    j += 1
                end = min(j, n - 1)
                blocks.append(Block("code", "\n".join(lines[i:end + 1])))
                i = end + 1
            elif atx:
                flush()
                blocks.append(Block("heading", atx.group(2), level=len(atx.group(1))))
                i += 1
            elif (not para and line.strip() and i + 1 < n and _SETEXT.match(lines[i + 1])
                  and not _LIST_ITEM.match(line) and not _HR.match(line)):
                level = 1 if lines[i + 1].strip().startswith("=") else 2
                blocks.append(Block("heading", line.strip(), level=level))
                i += 2
            elif _HR.match(line):
                flush()
                i += 1
            elif "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
                flush()
                j = i
                while j < n and lines[j].strip() and "|" in lines[j]:
                    j += 1
                blocks.append(Block("table", "\n".join(lines[i:j])))
                i = j
            elif _LIST_ITEM.match(line):
                flush()
                j = i + 1
                while j < n:
                    if _continues_list(lines[j]):
                        j += 1
                    elif not lines[j].strip() and j + 1 < n and _continues_list(lines[j + 1]):
                        j += 1
                    else:
                        break
                blocks.append(Block("list", "\n".join(lines[i:j])))
                i = j
            elif not line.strip():
                flush()
                i += 1
            else:
                para.append(line.rstrip())
                i += 1
        flush()

        title = fm_title or title_from_headings(blocks)
        return ParsedDocument(filename=filename, doc_type="md", title=title, blocks=blocks)
