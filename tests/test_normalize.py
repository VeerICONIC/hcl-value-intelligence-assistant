"""Pure parsers: IDs, dates (ISO first, day-first), numbers stored as text, names."""

from __future__ import annotations

from datetime import date

import pytest

from app.data.normalize import format_number, normalize_id, parse_date, parse_number, title_case_name

SYMBOLS, SEP, SUFFIXES = ["$"], ",", {"k": 1000, "m": 1_000_000}


def num(text):
    return parse_number(text, SYMBOLS, SEP, SUFFIXES)


@pytest.mark.parametrize("raw, expected", [
    ("INIT-003", "INIT-003"), ("init_3", "INIT-003"), (" INIT-3 ", "INIT-003"), ("INIT-36", "INIT-036"),
    ("INIT-040", "INIT-040"),
])
def test_normalize_id(raw, expected):
    assert normalize_id(raw, "INIT-", 3) == expected


@pytest.mark.parametrize("raw", ["", "INIT-", "INIT-1-2", "abc"])
def test_normalize_id_rejects_ambiguous(raw):
    assert normalize_id(raw, "INIT-", 3) is None


@pytest.mark.parametrize("raw, expected", [
    ("2025-09-01", date(2025, 9, 1)),        # the dateutil dayfirst trap: must stay 1 September
    ("2026-11-15 00:00:00", date(2026, 11, 15)),  # Excel datetime rendered as text
    ("07/09/2026", date(2026, 9, 7)),        # day-first numeric
    ("15/12/2025", date(2025, 12, 15)),
    ("Nov 2 2026", date(2026, 11, 2)),
    ("Jan 10 2026", date(2026, 1, 10)),
])
def test_parse_date(raw, expected):
    assert parse_date(raw, day_first=True) == expected


@pytest.mark.parametrize("raw", ["", "not a date", "Nov 2026", "2026-02-30", "31/02/2026"])
def test_parse_date_rejects_incomplete_or_invalid(raw):
    assert parse_date(raw, day_first=True) is None


@pytest.mark.parametrize("raw, value, was_text", [
    ("90000", 90000, False), ("166.7", 166.7, False), ("-130", -130, False),
    ("1,000", 1000, True), ("$600,000", 600000, True), ("$97.5k", 97500, True),
    ("$123.4k", 123400, True), ("1,625", 1625, True), ("2M", 2_000_000, True),
])
def test_parse_number(raw, value, was_text):
    parsed = num(raw)
    assert parsed.value == value          # exact: Decimal arithmetic, no float artefacts
    assert parsed.was_text is was_text


@pytest.mark.parametrize("raw", ["", "abc", "NaN", "inf", "$", "1.2.3"])
def test_parse_number_rejects(raw):
    assert num(raw) is None


def test_title_case_keeps_acronyms():
    assert title_case_name("it helpdesk bot", ["IT", "HR"]) == "IT Helpdesk Bot"
    assert title_case_name("onboarding bot 30", []) == "Onboarding Bot 30"


def test_format_number():
    assert format_number(220000.0) == "220000"
    assert format_number(97.5) == "97.5"
    assert format_number(None) is None
