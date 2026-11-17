"""The change log: one ``ChangeLogEntry`` per correction or standardisation (FR-02).

Every cleaning rule writes here through ``ChangeLog.add``. Rule IDs are our own generic
rule names (``RULES`` below), never the answer key's planted-issue IDs: the pipeline does
not know which issues were planted, it applies documented rules to whatever data arrives.

The ``effect`` column needs the final scorecard (e.g. "Feeds adoption (65.0%) for INIT-002"),
so entries are collected first and ``finalize`` fills effects after scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import ChangeLogEntry, ScorecardRow
from app.scorecard.metrics import METRIC_LABELS

# rule_id -> what the rule does (shown in GET /data-quality and the dashboard).
RULES: dict[str, str] = {
    "DUPLICATE_ROW": "Duplicate row removed (exact, or identical after normalisation)",
    "ID_FORMAT": "Initiative ID normalised to the INIT-NNN format",
    "NAME_FORMAT": "Initiative name trimmed; canonical name restored",
    "TEXT_FORMAT": "Text value trimmed of stray whitespace",
    "NUMBER_TEXT": "Number stored as text converted (currency symbol, separators, k suffix)",
    "METRIC_ALIAS": "Usage metric name mapped to its canonical name",
    "MEASURE_ALIAS": "Financial measure name mapped to its canonical name",
    "UNIT_SCALE": "Value scaled to USD (e.g. USD '000 x 1,000)",
    "DATE_FORMAT": "Date converted to ISO (ISO first, then day-first for numeric dates)",
    "NEGATIVE_VALUE": "Negative user count treated as a sign typo (absolute value used)",
    "WAU_ABOVE_LICENSED": "Weekly active users above licensed users: row flagged and excluded",
    "MISSING_WEEK": "No usage row for one of the supplied weeks",
    "MONTHLY_ROLLUP": "Monthly rows summed up to the as-of date into a to-date total",
    "CUMULATIVE_SUPERSEDED": "Older cumulative report replaced by the latest one before the as-of date",
    "AFTER_AS_OF": "Row dated after the as-of date: excluded",
    "REPORTED_ROI_MISMATCH": "Supplied ROI differs from the governed ROI formula: ignored",
    "INVALID_VALUE": "Value cannot be read safely: excluded or marked not available",
    "UNKNOWN_MEASURE": "Metric or measure name not in the metric dictionary: excluded",
    "UNKNOWN_INITIATIVE": "Initiative ID not found in initiatives.csv: excluded",
    "CONFLICTING_VALUES": "Same item reported with different values: all copies excluded",
}

NO_METRIC_EFFECT = "No scorecard metric uses this value"


@dataclass
class _Pending:
    rule_id: str
    file: str
    row: int | None
    column: str | None
    initiative_id: str | None
    old_value: str | None
    new_value: str | None
    reason: str
    affects: tuple[str, ...]
    effect: str | None


@dataclass
class ChangeLog:
    _items: list[_Pending] = field(default_factory=list)

    def add(self, rule_id: str, file: str, *, reason: str, row: int | None = None,
            column: str | None = None, initiative_id: str | None = None,
            old_value: object = None, new_value: object = None,
            affects: tuple[str, ...] | list[str] = (), effect: str | None = None) -> None:
        """Record one change. ``affects`` lists the metrics fed by the changed value;
        ``effect`` overrides the generated effect text when the rule knows better."""
        if rule_id not in RULES:
            raise ValueError(f"unknown change-log rule {rule_id!r}")
        self._items.append(_Pending(
            rule_id=rule_id, file=file, row=row, column=column, initiative_id=initiative_id,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
            reason=reason, affects=tuple(affects), effect=effect))

    def __len__(self) -> int:
        return len(self._items)

    def finalize(self, scorecard: list[ScorecardRow]) -> list[ChangeLogEntry]:
        """Fill each entry's effect from the final scorecard and return the contract objects."""
        rows = {r.initiative_id: r for r in scorecard}
        return [ChangeLogEntry(rule_id=p.rule_id, file=p.file, row=p.row, column=p.column,
                               initiative_id=p.initiative_id, old_value=p.old_value, new_value=p.new_value,
                               reason=p.reason, effect=p.effect or _effect_text(p, rows))
                for p in self._items]


def _effect_text(p: _Pending, rows: dict[str, ScorecardRow]) -> str:
    if not p.affects:
        return NO_METRIC_EFFECT
    if p.initiative_id is None:
        names = ", ".join(METRIC_LABELS.get(m, m) for m in p.affects)
        return f"Feeds {names} for every initiative in this file"
    row = rows.get(p.initiative_id)
    if row is None:
        names = ", ".join(METRIC_LABELS.get(m, m) for m in p.affects)
        return f"Would feed {names} for {p.initiative_id}, which is not in the scorecard"
    parts = []
    for m in p.affects:
        if m == "status":
            parts.append(f"status ({row.status})")
        elif m in row.metrics:
            parts.append(f"{METRIC_LABELS.get(m, m)} ({row.metrics[m].display})")
    return f"Feeds {', '.join(parts)} for {p.initiative_id}" if parts else NO_METRIC_EFFECT
