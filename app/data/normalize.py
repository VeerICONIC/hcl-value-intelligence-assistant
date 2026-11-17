"""Small, pure parsers that turn raw text into typed values (FR-02 normalisation).

Each function takes one raw cell (text, because the loader reads everything as text)
and returns the typed value, or ``None`` when the text cannot be read safely. They never
guess: an ambiguous or incomplete value is ``None``, and the caller logs it.

Kept free of pandas and of the change log so every rule is trivially unit-testable.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dateutil import parser as date_parser

_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$")

# Two far-apart defaults: if dateutil fills a missing day/month/year from the default,
# the two parses disagree and we know the text was an incomplete date (e.g. "Nov 2026").
_DEFAULT_A = datetime(2001, 1, 1)
_DEFAULT_B = datetime(2002, 2, 2)


def normalize_id(raw: str, prefix: str, digits: int) -> str | None:
    """'init_3', ' INIT-3 ', 'INIT-003' -> 'INIT-003'. ``None`` unless exactly one number is present."""
    numbers = re.findall(r"\d+", str(raw))
    if len(numbers) != 1:
        return None
    return f"{prefix}{int(numbers[0]):0{digits}d}"


def parse_date(raw: str, day_first: bool = True) -> date | None:
    """Parse a raw date. ISO ``YYYY-MM-DD`` first, then dateutil (day-first for numeric dates).

    ISO must come first: dateutil with ``dayfirst=True`` reads '2025-09-01' as 9 January 2025.
    Incomplete dates ('Nov 2026') return ``None`` rather than borrowing a day from today.
    """
    s = str(raw).strip()
    if not s:
        return None
    m = _ISO.match(s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    try:
        a = date_parser.parse(s, dayfirst=day_first, default=_DEFAULT_A)
        b = date_parser.parse(s, dayfirst=day_first, default=_DEFAULT_B)
    except (ValueError, OverflowError):
        return None
    if a.date() != b.date():
        return None
    return a.date()


@dataclass(frozen=True)
class ParsedNumber:
    value: float
    was_text: bool       # True when symbols, separators or a suffix had to be removed


def parse_number(raw: str, currency_symbols: list[str], thousands_separator: str,
                 suffixes: dict[str, float]) -> ParsedNumber | None:
    """'1,000' -> 1000, '$600,000' -> 600000, '$97.5k' -> 97500, '-130' -> -130.

    Decimal arithmetic avoids binary float artefacts such as 123.4 * 1000 = 123400.00000000001.
    Returns ``None`` for empty, non-numeric, NaN or infinite text.
    """
    s = str(raw).strip()
    if not s:
        return None
    try:
        plain = Decimal(s)
        if plain.is_finite():
            return ParsedNumber(float(plain), was_text=False)
        return None
    except InvalidOperation:
        pass

    cleaned = s
    for sym in currency_symbols:
        cleaned = cleaned.replace(sym, "")
    if thousands_separator:
        cleaned = cleaned.replace(thousands_separator, "")
    cleaned = cleaned.replace(" ", "")
    multiplier = Decimal(1)
    if cleaned and cleaned[-1].casefold() in {k.casefold() for k in suffixes}:
        key = next(k for k in suffixes if k.casefold() == cleaned[-1].casefold())
        multiplier = Decimal(str(suffixes[key]))
        cleaned = cleaned[:-1]
    try:
        number = Decimal(cleaned) * multiplier
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    value = float(number)
    if not math.isfinite(value):
        return None
    return ParsedNumber(value, was_text=True)


def clean_text(raw: str) -> str:
    """Trim and collapse internal whitespace."""
    return " ".join(str(raw).split())


def title_case_name(name: str, acronyms: list[str]) -> str:
    """'marketing content copilot' -> 'Marketing Content Copilot'; acronyms stay upper case ('it' -> 'IT')."""
    upper = {a.casefold(): a.upper() for a in acronyms}
    return " ".join(upper.get(w.casefold(), w[:1].upper() + w[1:]) for w in name.split())


def format_number(value: float | None) -> str | None:
    """Compact text for a number in the change log: 220000.0 -> '220000', 97.5 -> '97.5'."""
    if value is None:
        return None
    return f"{value:.10g}" if value != int(value) else str(int(value))
