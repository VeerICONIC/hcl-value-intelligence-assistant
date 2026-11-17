"""Detect and neutralise instructions embedded in charter text (FR-08: charter content is data).

Three layers protect the answer: (1) chunks containing instruction-like text are flagged at
index time; (2) the offending lines are removed before any text reaches an answer or the LLM;
(3) charter text is wrapped in <charter_data> tags with a "data, not instructions" rule, and the
number guard rejects any digit, so an injected figure ("ROI is 250 percent") cannot be shown.
"""

from __future__ import annotations

import re

PATTERNS = [
    r"ignore (all |any )?(previous|prior|above|earlier) (instructions|prompts|rules)",
    r"disregard (all |any )?(previous|prior|above) (instructions|prompts|rules)",
    r"note to (any|the) (ai|assistant|model|llm)",
    r"(ai|llm) assistant reading this",
    r"you are now",
    r"system prompt",
    r"(report|state|say) (that )?this initiative (is|as) (green|amber|red)",
    r"new instructions?:",
]
_RE = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.IGNORECASE)


def contains_injection(text: str) -> bool:
    return bool(_RE.search(text))


def strip_injection(text: str) -> tuple[str, int]:
    """Remove lines containing instruction-like text. Returns (clean text, lines removed)."""
    kept, removed = [], 0
    for line in text.splitlines():
        if _RE.search(line):
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept).strip(), removed
