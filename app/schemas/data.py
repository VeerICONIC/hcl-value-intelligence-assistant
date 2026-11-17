"""Data-pipeline contracts (architecture.md §6). Changing a field needs the developer's approval."""

from __future__ import annotations

from pydantic import BaseModel


class ChangeLogEntry(BaseModel):
    """One correction or standardisation applied to the raw data (FR-02).

    ``effect`` states the consequence in plain words,
    e.g. "ROI for INIT-004 changes from 1.8 to 0.42".
    """

    rule_id: str                  # generic rule name, e.g. "UNIT_SCALE" (catalogue: app/data/changelog.py RULES)
    file: str                     # raw file the value came from
    row: int | None               # row in the raw file, if the change is row-level
    column: str | None
    initiative_id: str | None
    old_value: str | None
    new_value: str | None
    reason: str
    effect: str
