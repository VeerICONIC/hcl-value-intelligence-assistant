# Metric definitions, assumptions and client clarification (FR-01)

## Metric definitions in our own words

| Metric | What it tells an executive | How we calculate it |
|---|---|---|
| Adoption | What share of the people who have access actually used the tool in the most recent week | Latest-week weekly active users ÷ licensed users |
| Weekly active users change | Whether usage is growing or shrinking over the three supplied weeks | (Latest-week users − first-week users) ÷ first-week users |
| ROI | How much value has come back for every dollar spent so far (negative = losing money) | (Realised benefit to date − total cost to date) ÷ total cost to date |
| Average monthly benefit | The value delivered per month since go-live | Realised benefit to date ÷ months live |
| Payback period | How many months of benefit it takes to cover the cost so far | Total cost to date ÷ average monthly benefit ("Not reached" when no benefit yet) |
| Run-rate versus plan | Whether the current pace of benefit is on track for the annual plan | Average monthly benefit × 12 ÷ planned annual benefit |
| Status | One traffic light per initiative | **Red** if adoption < 30% or ROI < 0 (checked first); otherwise **Green** if adoption ≥ 60% and ROI > 0; otherwise **Amber** |

## Assumptions

- **A0 Data:** no data files were supplied, so the team generated a synthetic, seeded dataset (8 curated initiatives plus a 40-initiative scale set) with planted data-quality issues and an independent answer key. See `data/README.md`.
- **A1 Months live:** from the go-live date to the as-of date, in fractional months (days ÷ 30.44). The as-of date is the end of the latest supplied usage week (week start + 6 days).
- **A2 Undefined aggregates:** portfolio-level averages or totals are not defined metrics, so they are not computed; the assistant returns the fallback.
- **A3 Charter numbers:** numbers inside charter text are not scorecard figures, so the assistant never states them. Charter excerpts are shown only as cited source evidence.
- **A4 Weeks:** the first and latest weeks are the portfolio's first and latest supplied weeks. A missing middle week is only flagged; a missing or excluded first or latest week makes the affected metric unavailable, with a reason (never a substituted week).
- **A5 Currency and units:** all money is USD. "USD '000" means thousands. A supplied ROI column is never used; ROI is recomputed with the governed formula and differences are logged.
- **A6 Dates:** ISO dates (YYYY-MM-DD) are parsed first; other numeric dates are day-first (07/09/2026 = 7 September 2026).
- **A7 Corrections:** a negative user count is treated as a sign typo; active users above licensed users are excluded as invalid; exact duplicate rows are dropped; monthly cost rows up to the as-of date are summed into cost to date.

## Client clarification question

> **Should a partially completed month count towards "months live"?** We currently use fractional months (days ÷ 30.44). Counting only completed calendar months would raise average monthly benefit for recently launched initiatives (for example INIT-008, live about five and a half months), which changes payback and run-rate versus plan.

Further questions we would raise: should benefit "to date" be audited realised value or forecast-adjusted value; and should an initiative with no licensed-user figure be reported as "Insufficient data" (current behaviour) or excluded from the scorecard?
