# Data-quality and assumptions log (FR-01)

## Metric definitions in our own words

| Metric | What it tells an executive | How we compute it |
|---|---|---|
| **Adoption** | What share of the people who have a licence actually used the tool in the most recent week. | Weekly active users in the latest supplied week ÷ licensed users. |
| **WAU change** | Whether usage is growing or shrinking across the reporting window. | (Latest-week WAU − first-week WAU) ÷ first-week WAU, over the three supplied weeks. |
| **ROI** | How much value has come back for every dollar spent so far; negative means it has not yet earned back its cost. | (Realised benefit to date − total cost to date) ÷ total cost to date. |
| **Average monthly benefit** | The typical value delivered per month since go-live. | Realised benefit to date ÷ months live. |
| **Payback (months)** | How many months of benefit at the current rate it takes to recover the cost to date. | Total cost to date ÷ average monthly benefit. "Not reached" when benefit is zero. |
| **Run-rate vs plan** | Whether the current pace of benefit is on track for the annual plan (100% = on plan). | (Average monthly benefit × 12) ÷ planned annual benefit. |
| **Portfolio status** | A traffic light for attention. | **Red** if adoption < 30% or ROI < 0; otherwise **Green** if adoption ≥ 60% and ROI > 0; otherwise **Amber**. "Insufficient data" if adoption or ROI cannot be computed. |

All values are computed in deterministic Python (`app/scorecard/metrics.py`); thresholds live in
`config/status_rules.yaml`. When an input is missing or a denominator is zero, the metric is `None` with a
written reason — never a guessed value.

## Assumptions

- **A1 Months live.** From the go-live date to the as-of date (end of the latest usage week, 2026-11-15), in
  fractional months: days ÷ 30.44.
- **A2 Undefined aggregates.** Portfolio-level averages or totals (e.g. "portfolio average ROI") are not defined
  metrics, so they are not computed; the assistant replies "I do not have that in the data provided".
- **A3 Charter figures.** Numbers written inside charters are never shown as answers; charter text is shown only as
  quoted evidence. Every number shown comes from the scorecard.
- **A4 Weeks used.** "First week" and "latest week" are the portfolio's first and latest supplied weeks (the same for
  every initiative). A missing middle week is only flagged. A missing or excluded first or latest week (e.g. WAU above
  licensed users) makes the affected metrics `None` with the reason; no other week is substituted.
- **A5 Currency.** All money is USD. "USD '000" means thousands (×1,000). No currency conversion; any other currency
  is rejected for that value and logged.

Data rules applied during cleaning (each correction is logged in the change log):
- Numeric dates are day-first (07/09/2026 = 7 September 2026); ISO `YYYY-MM-DD` is parsed first.
- A negative weekly-active-user count is treated as a sign typo (absolute value). Negative money is excluded, not flipped.
- WAU above licensed users is flagged, excluded and logged.
- Monthly cost rows are summed up to the as-of date; for cumulative rows the latest report on or before the as-of date is used.
- A supplied `reported_roi_pct` is never used; ROI is recomputed and every mismatch is logged (the supplied figure
  matches benefit ÷ cost × 100, a different convention).
- The practice dataset is synthetic, because no data files were supplied; real files need edits to `config/*.yaml` only.

## Client clarification question

> **Should partially completed months count as live months?** We currently measure months live as fractional months
> from the go-live date to the as-of date (days ÷ 30.44), so an initiative live for 11 months and 15 days counts as
> about 11.5 months. If finance counts only completed calendar months (11), average monthly benefit, payback and
> run-rate vs plan all change, which can move an initiative across the payback or run-rate figures executives compare.

Other questions we would raise: whether a WAU figure above licensed users should be treated as a data error (our
assumption) or as unlicensed usage; and whether the supplied `reported_roi_pct` convention (benefit ÷ cost) is used
anywhere in existing executive reporting.

## Planted data corrections and standardisation decisions

The full, row-level record is produced by every pipeline run: `data/processed/change_log.csv`, the dashboard's
"Data quality" section, and `GET /data-quality`. The rule catalogue (`app/data/changelog.py`) covers duplicates, ID
formats, names, numbers stored as text, metric and measure aliases, unit scaling, date formats, negative values,
WAU above licences, missing weeks, monthly roll-up, superseded cumulative reports, rows after the as-of date, the
reported-ROI mismatch, and defensive rules (invalid values, unknown measures or initiatives, conflicting values).
