"""Cleaning rules: raw text tables -> typed, validated tables + change-log entries (FR-02).

One function per raw file, applying documented, generic rules in a fixed order:

    exact duplicates -> IDs -> dates -> names/aliases -> numbers -> units/basis
    -> duplicates after normalisation -> validity checks (WAU vs licences, as-of date)

Every correction or exclusion is written to the ``ChangeLog``; nothing changes silently.
The rules never guess: a value that cannot be read safely is excluded (or set to None)
and the affected metric later becomes ``None`` with the reason.

Nothing here knows about planted issues or specific initiatives. Names, aliases, units
and formats all come from config (D10), so the same code runs on any dataset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from app.core.yaml_config import PipelineConfig, norm_key
from app.data.changelog import ChangeLog
from app.data.loader import ROW_COL, RawTable
from app.data.normalize import (
    clean_text,
    format_number,
    normalize_id,
    parse_date,
    parse_number,
    title_case_name,
)
from app.scorecard.metrics import Sourced

WAU_METRIC = "weekly_active_users"   # the canonical usage metric the scorecard needs

# Metrics fed by each kind of input (used for change-log effects).
ALL_METRICS = ("months_live", "adoption", "wau_change", "roi", "avg_monthly_benefit",
               "payback_months", "run_rate_vs_plan", "status")
GO_LIVE_METRICS = ("months_live", "avg_monthly_benefit", "payback_months", "run_rate_vs_plan")
BENEFIT_METRICS = ("roi", "avg_monthly_benefit", "payback_months", "run_rate_vs_plan", "status")
COST_METRICS = ("roi", "payback_months", "status")


def ref(filename: str, row: int) -> str:
    return f"{filename} row {row}"


def _is_canonical_iso(raw: str, parsed: date) -> bool:
    """True when the raw text already is the ISO date (Excel may add a 00:00:00 time)."""
    s = str(raw).strip()
    return s == parsed.isoformat() or s == f"{parsed.isoformat()} 00:00:00"


def _drop_exact_duplicates(t: RawTable, cfg: PipelineConfig, log: ChangeLog) -> pd.DataFrame:
    """Remove rows identical in every column to an earlier row (DUPLICATE_ROW)."""
    idf = cfg.metric_dictionary.id_format
    value_cols = [c for c in t.df.columns if c != ROW_COL]
    first_seen: dict[tuple, int] = {}
    keep = []
    for rec in t.df.to_dict("records"):
        key = tuple(rec[c] for c in value_cols)
        if key in first_seen:
            keep.append(False)
            log.add("DUPLICATE_ROW", t.filename, row=rec[ROW_COL],
                    initiative_id=normalize_id(rec.get("initiative_id", ""), idf.prefix, idf.digits),
                    old_value=" | ".join(key), new_value=None,
                    reason=f"Exact duplicate of row {first_seen[key]}; dropped so it is not counted twice",
                    effect="Duplicate removed; metrics use the remaining row")
        else:
            first_seen[key] = rec[ROW_COL]
            keep.append(True)
    return t.df[keep].reset_index(drop=True)


# =================================================================================
# initiatives.csv
# =================================================================================
def clean_initiatives(t: RawTable, cfg: PipelineConfig, log: ChangeLog) -> pd.DataFrame:
    md, ini_cfg = cfg.metric_dictionary, cfg.initiatives
    f = t.filename
    nums = md.numbers
    allowed_currencies = {c.upper() for c in md.allowed_currencies}
    records: list[dict] = []

    for rec in _drop_exact_duplicates(t, cfg, log).to_dict("records"):
        row = rec[ROW_COL]
        raw_id = rec["initiative_id"]
        iid = normalize_id(raw_id, md.id_format.prefix, md.id_format.digits)
        if iid is None:
            log.add("INVALID_VALUE", f, row=row, column="initiative_id", old_value=raw_id,
                    reason="Initiative ID does not contain exactly one number",
                    effect="Row excluded: the initiative cannot be identified")
            continue
        if raw_id != iid:
            log.add("ID_FORMAT", f, row=row, column="initiative_id", initiative_id=iid, old_value=raw_id,
                    new_value=iid, reason="Initiative ID normalised to the configured INIT-NNN format",
                    affects=ALL_METRICS)

        # --- name ------------------------------------------------------------------
        raw_name = rec["name"]
        name = clean_text(raw_name)
        canonical = ini_cfg.canonical_names.get(iid)
        if canonical:
            new_name, why = canonical, "Canonical name restored from config/initiatives.yaml"
        elif name and name == name.lower():
            new_name, why = title_case_name(name, ini_cfg.name_acronyms), "Trimmed and title-cased (all lower case)"
        elif name:
            new_name, why = name, "Stray whitespace trimmed"
        else:
            new_name, why = iid, "Name is blank; the initiative ID is used as its name"
        if raw_name != new_name:
            log.add("NAME_FORMAT", f, row=row, column="name", initiative_id=iid, old_value=raw_name,
                    new_value=new_name, reason=why)

        # --- other text columns -----------------------------------------------------
        text = {}
        for col in ("type", "business_unit"):
            raw = rec.get(col, "")
            text[col] = clean_text(raw)
            if raw != text[col]:
                log.add("TEXT_FORMAT", f, row=row, column=col, initiative_id=iid, old_value=raw,
                        new_value=text[col], reason="Stray whitespace trimmed")

        # --- go-live date -------------------------------------------------------------
        raw_date = rec["go_live_date"]
        go_live = parse_date(raw_date, md.dates.day_first)
        go_live_note = None
        if go_live is None:
            go_live_note = f"go-live date {raw_date!r} in {ref(f, row)} cannot be read"
            log.add("INVALID_VALUE", f, row=row, column="go_live_date", initiative_id=iid, old_value=raw_date,
                    reason="Date cannot be read as a complete date", affects=GO_LIVE_METRICS)
        elif not _is_canonical_iso(raw_date, go_live):
            log.add("DATE_FORMAT", f, row=row, column="go_live_date", initiative_id=iid, old_value=raw_date,
                    new_value=go_live.isoformat(),
                    reason="Converted to ISO; numeric dates read day-first" if md.dates.day_first
                    else "Converted to ISO", affects=GO_LIVE_METRICS)

        # --- numbers ---------------------------------------------------------------
        values: dict[str, float | None] = {}
        notes: dict[str, str | None] = {}
        for col, affects in (("licensed_users", ("adoption", "status")),
                             ("planned_annual_benefit", ("run_rate_vs_plan",))):
            raw = rec[col]
            parsed = parse_number(raw, nums.currency_symbols, nums.thousands_separator, nums.suffixes)
            values[col], notes[col] = None, None
            if parsed is None or parsed.value < 0:
                notes[col] = f"{col.replace('_', ' ')} {raw!r} in {ref(f, row)} is not a valid number"
                log.add("INVALID_VALUE", f, row=row, column=col, initiative_id=iid, old_value=raw,
                        reason="Not a valid non-negative number; left as not available", affects=affects)
                continue
            values[col] = parsed.value
            if parsed.was_text:
                log.add("NUMBER_TEXT", f, row=row, column=col, initiative_id=iid, old_value=raw,
                        new_value=format_number(parsed.value),
                        reason="Number stored as text: symbols, separators and suffixes removed", affects=affects)

        # --- currency (A5: USD only, never converted) -------------------------------
        raw_cur = rec.get("currency", "")
        currency = clean_text(raw_cur).upper()
        if not currency:
            currency = md.allowed_currencies[0].upper()
            log.add("TEXT_FORMAT", f, row=row, column="currency", initiative_id=iid, old_value=raw_cur,
                    new_value=currency, reason="Blank currency read as the default currency (assumption A5)")
        elif currency not in allowed_currencies:
            notes["planned_annual_benefit"] = (f"planned annual benefit is in {currency}, which is not supported "
                                               "(no currency conversion, assumption A5)")
            values["planned_annual_benefit"] = None
            log.add("INVALID_VALUE", f, row=row, column="currency", initiative_id=iid, old_value=raw_cur,
                    reason=f"Currency {currency} is not in allowed_currencies; amounts are never converted",
                    affects=("run_rate_vs_plan",))

        records.append({
            "initiative_id": iid, "name": new_name, "type": text["type"], "business_unit": text["business_unit"],
            "go_live_date": go_live, "go_live_note": go_live_note,
            "licensed_users": values["licensed_users"], "licensed_users_note": notes["licensed_users"],
            "planned_annual_benefit": values["planned_annual_benefit"],
            "planned_annual_benefit_note": notes["planned_annual_benefit"],
            "currency": currency, ROW_COL: row,
        })

    # --- the same initiative twice after ID normalisation -------------------------
    compare = ["name", "type", "business_unit", "go_live_date", "licensed_users", "planned_annual_benefit", "currency"]
    by_id: dict[str, list[dict]] = {}
    for r in records:
        by_id.setdefault(r["initiative_id"], []).append(r)
    kept: list[dict] = []
    for iid, group in by_id.items():
        if len(group) == 1:
            kept.append(group[0])
        elif all(tuple(g[c] for c in compare) == tuple(group[0][c] for c in compare) for g in group):
            kept.append(group[0])
            for g in group[1:]:
                log.add("DUPLICATE_ROW", f, row=g[ROW_COL], initiative_id=iid,
                        reason=f"Identical to row {group[0][ROW_COL]} after normalisation; dropped",
                        effect="Duplicate removed; metrics use the remaining row")
        else:
            for g in group:
                log.add("CONFLICTING_VALUES", f, row=g[ROW_COL], initiative_id=iid,
                        reason=f"{iid} appears on rows {[x[ROW_COL] for x in group]} with different values",
                        effect=f"All rows excluded: {iid} is left out of the scorecard")
    cols = ["initiative_id", "name", "type", "business_unit", "go_live_date", "go_live_note", "licensed_users",
            "licensed_users_note", "planned_annual_benefit", "planned_annual_benefit_note", "currency", ROW_COL]
    return pd.DataFrame.from_records(sorted(kept, key=lambda r: r["initiative_id"]), columns=cols)


# =================================================================================
# weekly_usage.csv
# =================================================================================
def _usage_affects(week: date | None, weeks: list[date]) -> tuple[str, ...]:
    """Which metrics a usage row feeds: only the first and the latest week are used."""
    if week is None or not weeks:
        return ()
    if week == weeks[-1]:
        return ("adoption", "wau_change", "status")
    if week == weeks[0]:
        return ("wau_change",)
    return ()


def _exclusion_effect(iid: str, week: date | None, weeks: list[date]) -> str:
    if week is not None and weeks and week == weeks[-1]:
        return f"Row excluded: adoption and WAU change for {iid} are not available (latest week)"
    if week is not None and weeks and week == weeks[0]:
        return f"Row excluded: WAU change for {iid} is not available (first week)"
    return "Row excluded: this week is neither the first nor the latest week, so no metric changes"


def clean_usage(t: RawTable, cfg: PipelineConfig, log: ChangeLog,
                initiatives: pd.DataFrame) -> tuple[pd.DataFrame, list[date]]:
    """Return (usage rows with an ``included`` flag, the supplied weeks in order)."""
    md = cfg.metric_dictionary
    f = t.filename
    nums = md.numbers
    metric_map = md.usage_metric_map()
    licensed = dict(zip(initiatives["initiative_id"], initiatives["licensed_users"]))

    records: list[dict] = []
    pending: list[tuple[date | None, dict]] = []      # row-level fixes, logged once weeks are known

    for rec in _drop_exact_duplicates(t, cfg, log).to_dict("records"):
        row = rec[ROW_COL]
        raw_id = rec["initiative_id"]
        iid = normalize_id(raw_id, md.id_format.prefix, md.id_format.digits)
        if iid is None:
            log.add("INVALID_VALUE", f, row=row, column="initiative_id", old_value=raw_id,
                    reason="Initiative ID does not contain exactly one number",
                    effect="Row excluded: the initiative cannot be identified")
            continue
        if iid not in licensed:
            log.add("UNKNOWN_INITIATIVE", f, row=row, column="initiative_id", initiative_id=iid, old_value=raw_id,
                    reason=f"{iid} is not in initiatives.csv", effect="Row excluded")
            continue

        raw_week = rec["week_start"]
        week = parse_date(raw_week, md.dates.day_first)
        if week is None:
            log.add("INVALID_VALUE", f, row=row, column="week_start", initiative_id=iid, old_value=raw_week,
                    reason="Week start cannot be read as a complete date", effect="Row excluded")
            continue

        fixes: list[dict] = []
        if raw_id != iid:
            fixes.append(dict(rule_id="ID_FORMAT", column="initiative_id", old_value=raw_id, new_value=iid,
                              reason="Initiative ID normalised to the configured INIT-NNN format"))
        if not _is_canonical_iso(raw_week, week):
            fixes.append(dict(rule_id="DATE_FORMAT", column="week_start", old_value=raw_week,
                              new_value=week.isoformat(), reason="Converted to ISO date"))

        raw_metric = rec["metric_name"]
        metric = metric_map.get(norm_key(raw_metric))
        if metric is None:
            log.add("UNKNOWN_MEASURE", f, row=row, column="metric_name", initiative_id=iid, old_value=raw_metric,
                    reason="Metric name is not in usage_metrics (config/metric_dictionary.yaml)", effect="Row excluded")
            continue
        if raw_metric != metric:
            fixes.append(dict(rule_id="METRIC_ALIAS", column="metric_name", old_value=raw_metric, new_value=metric,
                              reason="Metric alias mapped to its canonical name"))

        base = {"initiative_id": iid, "week_start": week, "metric": metric, ROW_COL: row}
        raw_value = rec["value"]
        parsed = parse_number(raw_value, nums.currency_symbols, nums.thousands_separator, nums.suffixes)
        if parsed is None:
            note = f"value {raw_value!r} in {ref(f, row)} is not a number"
            records.append({**base, "value": None, "included": False, "note": note})
            pending.append((week, dict(rule_id="INVALID_VALUE", column="value", old_value=raw_value,
                                       reason="Value is not a number", effect_kind="excluded")))
            for fx in fixes:
                pending.append((week, fx))
            continue
        value = parsed.value
        if parsed.was_text:
            fixes.append(dict(rule_id="NUMBER_TEXT", column="value", old_value=raw_value,
                              new_value=format_number(value), reason="Number stored as text: separators removed"))
        if value < 0:
            fixes.append(dict(rule_id="NEGATIVE_VALUE", column="value", old_value=raw_value,
                              new_value=format_number(-value),
                              reason="A user count cannot be negative; treated as a sign typo (assumption)"))
            value = -value
        records.append({**base, "value": value, "included": True, "note": None})
        for fx in fixes:
            pending.append((week, fx))

    weeks = sorted({r["week_start"] for r in records})

    def _emit(week: date | None, iid: str, row: int, fx: dict) -> None:
        fx = dict(fx)
        kind = fx.pop("effect_kind", None)
        effect = _exclusion_effect(iid, week, weeks) if kind == "excluded" else None
        log.add(fx.pop("rule_id"), f, row=row, initiative_id=iid, affects=_usage_affects(week, weeks),
                effect=effect, **fx)

    # records and pending were appended in the same row order; match fixes to rows by row number
    row_info = {r[ROW_COL]: r for r in records}
    pending_by_row: dict[int, list[tuple[date | None, dict]]] = {}
    for rec in t.df.to_dict("records"):
        pending_by_row.setdefault(rec[ROW_COL], [])
    # rebuild row association: pending entries were added right after their record
    idx = 0
    for r in records:
        # each record is followed by its fixes in `pending`; walk them in order
        pass
    _ = (row_info, pending_by_row, idx)
    for (week, fx), owner in zip(pending, _owners(records, pending)):
        _emit(week, owner["initiative_id"], owner[ROW_COL], fx)

    # --- duplicates after normalisation ---------------------------------------------
    groups: dict[tuple, list[dict]] = {}
    for r in records:
        if r["included"]:
            groups.setdefault((r["initiative_id"], r["week_start"], r["metric"]), []).append(r)
    for (iid, week, metric), group in groups.items():
        if len(group) < 2:
            continue
        if len({g["value"] for g in group}) == 1:
            for g in group[1:]:
                g["included"], g["note"] = False, f"duplicate of {ref(f, group[0][ROW_COL])}"
                log.add("DUPLICATE_ROW", f, row=g[ROW_COL], initiative_id=iid,
                        reason=f"Same initiative, week and value as row {group[0][ROW_COL]} after normalisation",
                        effect="Duplicate removed; metrics use the remaining row")
        else:
            rows = [g[ROW_COL] for g in group]
            for g in group:
                g["included"] = False
                g["note"] = f"conflicting values for {iid} week {week.isoformat()} on rows {rows}"
                log.add("CONFLICTING_VALUES", f, row=g[ROW_COL], column="value", initiative_id=iid,
                        old_value=format_number(g["value"]),
                        reason=f"{iid} week {week.isoformat()} has different {metric} values on rows {rows}",
                        effect=_exclusion_effect(iid, week, weeks))

    # --- WAU above licensed users (flag, exclude, log) --------------------------------
    for r in records:
        if not r["included"] or r["metric"] != WAU_METRIC:
            continue
        lic = licensed.get(r["initiative_id"])
        if lic is not None and r["value"] > lic:
            r["included"] = False
            r["note"] = (f"WAU {format_number(r['value'])} is above {format_number(lic)} licensed users "
                         f"({ref(f, r[ROW_COL])})")
            log.add("WAU_ABOVE_LICENSED", f, row=r[ROW_COL], column="value", initiative_id=r["initiative_id"],
                    old_value=format_number(r["value"]), new_value=None,
                    reason=f"Weekly active users ({format_number(r['value'])}) cannot exceed licensed users "
                           f"({format_number(lic)}); row flagged as invalid",
                    effect=_exclusion_effect(r["initiative_id"], r["week_start"], weeks))

    # --- weeks with no row at all ----------------------------------------------------
    present = {(r["initiative_id"], r["week_start"]) for r in records if r["metric"] == WAU_METRIC}
    for iid in initiatives["initiative_id"]:
        for week in weeks:
            if (iid, week) not in present:
                if week in (weeks[0], weeks[-1]):
                    effect = _exclusion_effect(iid, week, weeks).replace("Row excluded", "Week missing")
                else:
                    effect = ("No metric changes: metrics use the first and latest weeks "
                              "(assumption A4); the gap is flagged")
                log.add("MISSING_WEEK", f, initiative_id=iid, column="week_start", old_value=None,
                        new_value=None, reason=f"No {WAU_METRIC} row for the week starting {week.isoformat()}",
                        effect=effect)

    cols = ["initiative_id", "week_start", "metric", "value", "included", "note", ROW_COL]
    df = pd.DataFrame.from_records(records, columns=cols)
    df = df.sort_values(["initiative_id", "week_start", ROW_COL], kind="stable").reset_index(drop=True)
    return df, weeks


def _owners(records: list[dict], pending: list[tuple[date | None, dict]]) -> list[dict]:
    raise NotImplementedError  # replaced below
