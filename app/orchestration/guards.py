"""Guardrails (FR-08): personal-data input guard and the number guard.

- Input guard: requests for personal details are refused. The approved data has names and
  roles in charters only; no phone numbers, emails, addresses, salaries or ages.
- Number guard: narrative text (LLM or extractive) may not contain any digit, except inside
  initiative IDs like INIT-005. Every number shown to the user comes from scorecard code.
"""

from __future__ import annotations

import re

# Regex patterns for personal-detail requests. Phrases rather than bare words, so business questions such as
# "how does X address its risks" or "contact-centre volume" are not refused.
PERSONAL_PATTERNS = (
    r"\b(tele)?phone\b", r"\bmobile (number|phone)\b", r"\be-?mail\b",
    r"\b(home|postal|street|residential|house) address\b", r"\baddress (of|for)\b", r"\bwhere (does|do) .* live\b",
    r"\bsalar(y|ies)\b", r"\bpay ?grade\b", r"\bhow much (does|do) .* (earn|make)\b", r"\bage\b",
    r"\bhow old\b", r"\bdate of birth\b", r"\bbirthday\b",
    r"\bcontact (details|number|info|information)\b", r"\bhow (can|do) i (contact|reach)\b",
    r"\bpersonal (details|information|info|data|life|history)\b", r"\blinkedin\b", r"\bmarital\b",
)
REFUSAL_MESSAGE = ("I can't share personal details. The approved data contains only the names and roles "
                   "listed in the initiative charters; no contact details, salaries or other personal information.")

_ALLOWED = re.compile(r"INIT-\d{3}")


def personal_data_request(question: str) -> str | None:
    q = question.lower()
    for pattern in PERSONAL_PATTERNS:
        m = re.search(pattern, q)
        if m:
            return m.group(0)
    return None


def has_digit(text: str) -> bool:
    """True if ``text`` has a digit outside initiative IDs."""
    return bool(re.search(r"\d", _ALLOWED.sub("", text)))
