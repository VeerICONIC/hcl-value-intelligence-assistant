"""
Governed data pipeline: raw files -> cleaned tables + change log -> scorecard.

Every number shown anywhere in the product comes from this module (FR-03).
Every correction is written to the change log with a reason and its effect (FR-02).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
from dateutil import parser as dateparser

from nimbus.settings import PROCESSED_DIR, ROOT, load_pipeline_config


# --------------------------------------------------------------------------- change log
@dataclass
class Change:
    rule: str
    file: str
    row: int | None
    initiative_id: str | None
    column: str | None
    old: str | None
    new: str | None
    reason: str
    affects: list[str] = field(default_factory=list)
    effect: str = ""


class ChangeLog:
    def __init__(self) -> None:
        self.items: list[Change] = []

    def add(self, rule, file, row, iid, column, old, new, reason, affects=None):
        self.items.append(Change(rule, file, row, iid, column,
                                 None if old is None else str(old), None if new is None else str(new),
                                 reason, affects or []))

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([c.__dict__ for c in self.items])


# --------------------------------------------------------------------------- parsers
def norm_id(raw, pattern: str) -> str | None:
    digits = re.findall(r"\d+", str(raw))
    return pattern.format(int(digits[0])) if digits else None


def parse_number(raw) -> float | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().replace("$", "").replace(",", "").replace(" ", "")
    if s == "":
        return None
    mult = 1.0
    if s[-1:].lower() == "k":
        mult, s = 1000.0, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def parse_date(raw) -> date | None:
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):            # ISO first: dayfirst=True would misread it
        return date.fromisoformat(s[:10])
    try:
        return dateparser.parse(s, dayfirst=True).date()
    except (ValueError, OverflowError):
        return None


def _is_plain_number(raw) -> bool:
    return bool(re.fullmatch(r"-?\d+(\.\d+)?", str(raw).strip()))


# --------------------------------------------------------------------------- loading
def _read(path: Path, aliases: dict) -> pd.DataFrame:
    df = pd.read_excel(path, dtype=str) if path.suffix in (".xlsx", ".xls") else pd.read_csv(path, dtype=str)
    lookup = {a.lower(): canon for canon, al in aliases.items() for a in al}
    df = df.rename(columns={c: lookup.get(c.strip().lower(), c.strip().lower()) for c in df.columns})
    missing = [c for c in aliases if c not in df.columns and c not in ("currency", "type", "business_unit", "basis", "unit")]
    if missing:
        raise ValueError(f"{path.name}: required columns {missing} not found. "
                         f"Add the file's header names to column_aliases in config/pipeline.yaml")
    df["_row"] = range(2, len(df) + 2)                  # spreadsheet row number (header = row 1)
    return df


@dataclass
class PipelineResult:
    scorecard: pd.DataFrame
    changes: pd.DataFrame
    usage: pd.DataFrame
    initiatives: pd.DataFrame
    as_of: date
    weeks: list[date]
    data_version: str
    raw_dir: str


def _version(raw_dir: Path, cfg_path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(raw_dir.glob("*")) + [cfg_path]:
        if p.is_file():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def run_pipeline(raw_dir: str | Path = "data/raw", config_path: Path | None = None, write: bool = True) -> PipelineResult:
    cfg_path = config_path or ROOT / "config" / "pipeline.yaml"
    cfg = load_pipeline_config(cfg_path)
    raw = Path(raw_dir)
    raw = raw if raw.is_absolute() else ROOT / raw
    pat = cfg.get("id_pattern", "INIT-{:03d}")
    log = ChangeLog()
    F = cfg["files"]

    # ---------------- initiatives
    ini = _read(raw / F["initiatives"], cfg["column_aliases"]["initiatives"])
    acr = {a.lower(): a for a in cfg.get("acronyms", [])}
    canon_names = cfg.get("canonical_names", {}) or {}
    rows = []
    for _, r in ini.iterrows():
        iid = norm_id(r.initiative_id, pat)
        if iid != str(r.initiative_id):
            log.add("ID_FORMAT", F["initiatives"], r._row, iid, "initiative_id", r.initiative_id, iid, "Normalised initiative ID")
        name = str(r["name"])
        clean = " ".join(name.split())
        if iid in canon_names:
            clean = canon_names[iid]
        elif clean == clean.lower():
            clean = " ".join(acr.get(w, w.capitalize()) for w in clean.split())
        if clean != name:
            log.add("NAME_FORMAT", F["initiatives"], r._row, iid, "name", name, clean, "Trimmed / restored canonical name")
        gl = parse_date(r.go_live_date)
        if gl and str(r.go_live_date).strip() != gl.isoformat():
            log.add("DATE_FORMAT", F["initiatives"], r._row, iid, "go_live_date", r.go_live_date, gl.isoformat(),
                    "Parsed non-ISO date (ISO first, then day-first)", ["months_live", "avg_monthly_benefit", "payback_months", "run_rate_vs_plan"])
        vals = {}
        for col, aff in (("licensed_users", ["adoption"]), ("planned_annual_benefit", ["run_rate_vs_plan"])):
            v = parse_number(r[col])
            if v is not None and not _is_plain_number(r[col]):
                log.add("NUMBER_TEXT", F["initiatives"], r._row, iid, col, r[col], f"{v:g}", "Number stored as text", aff)
            vals[col] = v
        rows.append({"initiative_id": iid, "name": clean, "type": r.get("type"), "business_unit": r.get("business_unit"),
                     "go_live_date": gl, **vals})
    initiatives = pd.DataFrame(rows).set_index("initiative_id")
    licensed = initiatives.licensed_users.to_dict()

    # ---------------- usage
    u = _read(raw / F["usage"], cfg["column_aliases"]["usage"])
    body = [c for c in u.columns if c != "_row"]
    dup_mask = u.duplicated(subset=body, keep="first")
    for _, r in u[dup_mask].iterrows():
        log.add("DUPLICATE_ROW", F["usage"], r._row, norm_id(r.initiative_id, pat), None, None, None, "Exact duplicate row dropped")
    u = u[~dup_mask]
    malias = {a.lower(): canon for canon, al in cfg["metric_aliases"].items() for a in al}
    logged_alias: set = set()
    recs = []
    for _, r in u.iterrows():
        iid = norm_id(r.initiative_id, pat)
        if iid != str(r.initiative_id):
            log.add("ID_FORMAT", F["usage"], r._row, iid, "initiative_id", r.initiative_id, iid, "Normalised initiative ID", ["adoption", "wau_change"])
        metric = malias.get(str(r.metric_name).strip().lower())
        if metric is None:
            log.add("UNKNOWN_METRIC", F["usage"], r._row, iid, "metric_name", r.metric_name, None, "Unknown metric name; row ignored")
            continue
        if metric != r.metric_name and (iid, r.metric_name) not in logged_alias:
            logged_alias.add((iid, r.metric_name))
            log.add("METRIC_ALIAS", F["usage"], r._row, iid, "metric_name", r.metric_name, metric, "Metric alias mapped", ["adoption", "wau_change"])
        wk = parse_date(r.week_start)
        if wk and str(r.week_start).strip() != wk.isoformat():
            log.add("DATE_FORMAT", F["usage"], r._row, iid, "week_start", r.week_start, wk.isoformat(), "Parsed non-ISO date")
        v = parse_number(r.value)
        if v is None:
            log.add("UNPARSEABLE", F["usage"], r._row, iid, "value", r.value, None, "Value could not be parsed; row ignored")
            continue
        if not _is_plain_number(r.value):
            log.add("NUMBER_TEXT", F["usage"], r._row, iid, "value", r.value, f"{v:g}", "Number stored as text", ["adoption", "wau_change"])
        if v < 0:
            log.add("NEGATIVE_VALUE", F["usage"], r._row, iid, "value", r.value, f"{abs(v):g}", "Negative user count treated as a sign typo", ["adoption", "wau_change"])
            v = abs(v)
        included = True
        lic = licensed.get(iid)
        if lic is not None and v > lic:
            log.add("WAU_ABOVE_LICENSED", F["usage"], r._row, iid, "value", f"{v:g}", None,
                    f"Active users exceed {lic:g} licensed users; row excluded")
            included = False
        recs.append({"initiative_id": iid, "week_start": wk, "value": v, "included": included, "_row": r._row})
    usage = pd.DataFrame(recs).drop_duplicates(subset=["initiative_id", "week_start", "value"])
    conflicts = usage[usage.included].duplicated(subset=["initiative_id", "week_start"], keep=False)
    if conflicts.any():
        for _, r in usage[usage.included][conflicts].iterrows():
            log.add("CONFLICTING_ROWS", F["usage"], r._row, r.initiative_id, "value", f"{r.value:g}", None, "Two different values for the same week; excluded")
        usage.loc[usage.included & usage.duplicated(subset=["initiative_id", "week_start"], keep=False), "included"] = False
    weeks = sorted(usage.week_start.dropna().unique())
    for iid in initiatives.index:
        have = set(usage[(usage.initiative_id == iid)].week_start)
        for w in weeks:
            if w not in have:
                log.add("MISSING_WEEK", F["usage"], None, iid, "week_start", None, w.isoformat(), "No usage row for this week (flagged)")

    as_of_cfg = cfg.get("as_of", "auto")
    as_of = (weeks[-1] + pd.Timedelta(days=6).to_pytimedelta()) if as_of_cfg == "auto" else date.fromisoformat(str(as_of_cfg))

    # ---------------- financials
    f = _read(raw / F["financials"], cfg["column_aliases"]["financials"])
    meas = {a.lower(): canon for canon, al in cfg["measure_aliases"].items() for a in al}
    units = {k: float(v) for k, v in cfg["units"].items()}
    fin = []
    for _, r in f.iterrows():
        iid = norm_id(r.initiative_id, pat)
        if iid != str(r.initiative_id):
            log.add("ID_FORMAT", F["financials"], r._row, iid, "initiative_id", r.initiative_id, iid, "Normalised initiative ID", ["roi"])
        m = meas.get(str(r.measure).strip().lower())
        if m is None:
            log.add("UNKNOWN_MEASURE", F["financials"], r._row, iid, "measure", r.measure, None, "Unknown measure; row ignored")
            continue
        if m != r.measure:
            log.add("MEASURE_ALIAS", F["financials"], r._row, iid, "measure", r.measure, m, "Measure alias mapped", ["roi"])
        v = parse_number(r.value)
        if v is None:
            log.add("UNPARSEABLE", F["financials"], r._row, iid, "value", r.value, None, "Value could not be parsed; row ignored")
            continue
        if not _is_plain_number(r.value):
            log.add("NUMBER_TEXT", F["financials"], r._row, iid, "value", r.value, f"{v:g}", "Number stored as text", ["roi"])
        unit = str(r.get("unit", "USD")).strip()
        mult = units.get(unit)
        if mult is None:
            log.add("UNKNOWN_UNIT", F["financials"], r._row, iid, "unit", unit, None, "Unknown unit; row ignored")
            continue
        raw_v = v
        if mult != 1:
            v = v * mult
            log.add("UNIT_SCALE", F["financials"], r._row, iid, "value", f"{raw_v:g} {unit}", f"{v:g} USD",
                    f"Converted {unit} to USD", ["roi", "avg_monthly_benefit", "payback_months", "run_rate_vs_plan", "status"])
        d = parse_date(r.report_date)
        fin.append({"initiative_id": iid, "measure": m, "value": v, "raw_value": raw_v, "date": d,
                    "basis": str(r.get("basis", "cumulative")).strip().lower(), "_row": r._row})
    fin = pd.DataFrame(fin)

    def money(iid, measure):
        rows_ = fin[(fin.initiative_id == iid) & (fin.measure == measure)]
        rows_ = rows_[rows_.date <= as_of]
        return None if rows_.empty else float(rows_.sort_values("date").value.iloc[-1])

    benefit, cost = {}, {}
    for iid in initiatives.index:
        benefit[iid] = money(iid, "benefit_to_date")
        c = money(iid, "cost_to_date")
        monthly = fin[(fin.initiative_id == iid) & (fin.measure == "monthly_cost")]
        if not monthly.empty:
            used = monthly[monthly.date <= as_of]
            c = (c or 0.0) + float(used.value.sum())
            log.add("MONTHLY_ROLLUP", F["financials"], None, iid, "monthly_cost", f"{len(used)} monthly rows",
                    f"{c:g}", "Summed monthly cost rows up to the as-of date into cost_to_date", ["roi", "payback_months"])
        cost[iid] = c

    # ---------------- scorecard
    rules = cfg["status_rules"]
    dpm = float(cfg.get("days_per_month", 30.44))
    first_w, last_w = weeks[0], weeks[-1]
    out = []
    for iid, r in initiatives.iterrows():
        uw = usage[(usage.initiative_id == iid) & usage.included].set_index("week_start").value
        w_first, w_last = uw.get(first_w), uw.get(last_w)
        notes = []
        lic, plan, b, c = r.licensed_users, r.planned_annual_benefit, benefit.get(iid), cost.get(iid)
        months = (as_of - r.go_live_date).days / dpm if r.go_live_date else None
        adoption = w_last / lic if (w_last is not None and lic) else None
        if adoption is None:
            notes.append("adoption: latest-week users or licensed users missing")
        wau_change = (w_last - w_first) / w_first if (w_first and w_last is not None) else None
        if wau_change is None:
            notes.append("WAU change: first or latest week missing/excluded")
        roi = (b - c) / c if (b is not None and c) else None
        avg = b / months if (b is not None and months) else None
        payback = c / avg if (avg and c is not None) else None
        if avg == 0:
            notes.append("payback: not reached (no benefit realised yet)")
        run_rate = avg * 12 / plan if (avg is not None and plan) else None
        if adoption is None or roi is None:
            status, reason = "Insufficient data", "Adoption or ROI cannot be computed from the data"
        elif adoption < rules["red_below_adoption"] or roi < 0:
            parts = []
            if adoption < rules["red_below_adoption"]:
                parts.append(f"adoption {adoption:.1%} is below {rules['red_below_adoption']:.0%}")
            if roi < 0:
                parts.append(f"ROI {roi:+.1%} is negative")
            status, reason = "Red", "Red because " + " and ".join(parts)
        elif adoption >= rules["green_min_adoption"] and roi > 0:
            status, reason = "Green", f"Green because adoption {adoption:.1%} is at least {rules['green_min_adoption']:.0%} and ROI {roi:+.1%} is positive"
        else:
            why = []
            if adoption < rules["green_min_adoption"]:
                why.append(f"adoption {adoption:.1%} is between {rules['red_below_adoption']:.0%} and {rules['green_min_adoption']:.0%}")
            if roi <= 0:
                why.append(f"ROI {roi:+.1%} is not above zero")
            status, reason = "Amber", "Amber because " + " and ".join(why)
        out.append({"initiative_id": iid, "name": r["name"], "business_unit": r.business_unit, "type": r.type,
                    "licensed_users": lic, "wau_first": w_first, "wau_latest": w_last,
                    "benefit_to_date": b, "cost_to_date": c, "planned_annual_benefit": plan,
                    "months_live": months, "adoption": adoption, "wau_change": wau_change, "roi": roi,
                    "avg_monthly_benefit": avg, "payback_months": payback, "run_rate_vs_plan": run_rate,
                    "status": status, "status_reason": reason, "notes": "; ".join(notes)})
    sc = pd.DataFrame(out)

    # ---------------- reported ROI check + effects
    for _, r in fin[fin.measure == "reported_roi_pct"].iterrows():
        gov = sc.set_index("initiative_id").roi.get(r.initiative_id)
        if gov is not None and abs(r.value - gov * 100) > 0.1:
            log.add("REPORTED_ROI_MISMATCH", F["financials"], r._row, r.initiative_id, "value", f"{r.value:g}%", f"{gov * 100:.1f}%",
                    "Supplied ROI uses a different convention; scorecard uses (benefit - cost) / cost")
    scx = sc.set_index("initiative_id")
    for ch in log.items:
        if ch.initiative_id not in scx.index:
            continue
        row = scx.loc[ch.initiative_id]
        if ch.rule == "UNIT_SCALE" and row.cost_to_date:
            raw_b = parse_number(str(ch.old).split()[0])
            alt = (raw_b - row.cost_to_date) / row.cost_to_date
            ch.effect = f"Without this fix ROI for {ch.initiative_id} would be {alt:+.1%} instead of {row.roi:+.1%} (status {row.status})"
        elif ch.rule == "REPORTED_ROI_MISMATCH":
            ch.effect = f"Supplied ROI {ch.old} ignored; governed ROI is {ch.new}"
        elif ch.affects:
            shown = []
            for m in ch.affects:
                v = row.get(m)
                if m == "status":
                    shown.append(f"status {row.status}")
                elif v is not None and not pd.isna(v):
                    shown.append(f"{m.replace('_', ' ')} {fmt_metric(m, v)}")
            ch.effect = "Feeds " + ", ".join(shown) if shown else ""
        else:
            ch.effect = "No metric affected"

    changes = log.frame()
    version = _version(raw, cfg_path)
    result = PipelineResult(sc, changes, usage.drop(columns=["_row"]), initiatives.reset_index(), as_of, weeks, version, str(raw))
    if write:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        sc.to_csv(PROCESSED_DIR / "scorecard.csv", index=False)
        changes.to_csv(PROCESSED_DIR / "change_log.csv", index=False)
        (PROCESSED_DIR / "data_version.json").write_text(json.dumps({"data_version": version, "as_of": as_of.isoformat(), "raw_dir": str(raw)}))
    return result


# --------------------------------------------------------------------------- formatting (one place)
def fmt_metric(metric: str, v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "Not reached" if metric == "payback_months" else "n/a"
    if metric in ("adoption", "run_rate_vs_plan"):
        return f"{v:.1%}"
    if metric in ("wau_change", "roi"):
        return f"{v:+.1%}"
    if metric == "payback_months":
        return f"{v:.1f} months"
    if metric == "months_live":
        return f"{v:.1f}"
    if metric in ("avg_monthly_benefit", "benefit_to_date", "cost_to_date", "planned_annual_benefit"):
        return f"${v:,.0f}"
    if metric in ("licensed_users", "wau_first", "wau_latest"):
        return f"{v:,.0f}"
    return str(v)


METRIC_LABELS = {
    "adoption": "Adoption", "wau_change": "WAU change", "roi": "ROI", "avg_monthly_benefit": "Avg monthly benefit",
    "payback_months": "Payback", "run_rate_vs_plan": "Run-rate vs plan", "status": "Status",
}
