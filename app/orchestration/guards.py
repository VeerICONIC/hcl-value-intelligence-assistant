"""Guardrails (FR-08): personal-data input guard and the number guard.

- Input guard: requests for personal details are refused. The approved data has names and
  roles in charters only; no phone numbers, emails, addresses, salaries or ages.
- Number guard: narrative text (LLM or extractive) may not contain any digit, except inside
  initiative IDs like INIT-005. Every number shown to the user comes from scorecard code.
"""

from __future__ import annotations

import re

PERSONAL_WORDS = ("phone", "telephone", "mobile number", "email", "e-mail", "address", "salary", "salaries",
                  "pay grade", "age", "date of birth", "birthday", "contact", "personal", "home", "linkedin")
REFUSAL_MESSAGE = ("I can't share personal details. The approved data contains only the names and roles "
                   "listed in the initiative charters; no contact details, salaries or other personal information.")

_ALLOWED = re.compile(r"INIT-\d{3}")


def personal_data_request(question: str) -> str | None:
    q = question.lower()
    for w in PERSONAL_WORDS:
        if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", q):
            return w
    return None


def has_digit(text: str) -> bool:
    """True if ``text`` has a digit outside initiative IDs."""
    return bool(re.search(r"\d", _ALLOWED.sub("", text)))
