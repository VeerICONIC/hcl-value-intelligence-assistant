"""Weekly executive report (FR-09): deterministic Markdown, NO LLM.

Every figure is a ``MetricValue.display`` string from the governed scorecard, and every
charter statement is a quoted excerpt with its source file and section. Nothing is generated
by a model, so the report is reproducible from the data version printed in its header.
"""

from __future__ import annotations

from datetime import datetime

from app.charters.index import CharterIndex
from app.charters.injection import strip_injection
from app.core.config import FALLBACK_MESSAGE
from app.data.pipeline import PipelineResult

STATUS_ICON = {"Green": "🟢", "Amber": "🟠", "Red": "🔴", "Insufficient data": "⚪"}
TABLE_METRICS = {"adoption": "Adoption", "wau_change": "WAU change", "roi": "ROI",
                 "avg_monthly_benefit": "Avg monthly benefit", "payback_months": "Payback", "run_rate_vs_plan": "Run-rate vs plan"}


def _top_risk(index: CharterIndex, iid: str) -> tuple[str, str | None]:
    """First risk line of the charter's Risks section (injection lines removed), with its citation."""
    chunk = index.risks_for(iid)
    if chunk is None:
        return f"Charter has no Risks and Mitigations section: {FALLBACK_MESSAGE}.", None
    clean, _ = strip_injection(chunk.text)
    lines = [l.lstrip("-* ").strip() for l in clean.splitlines() if l.strip()]
    if not lines:
        return FALLBACK_MESSAGE + ".", None
    cite = f"{chunk.source_file}, {chunk.section}"
    return lines[0], cite


def build_weekly_report(result: PipelineResult, index: CharterIndex) -> str:
    rows = result.scorecard
    counts = {s: sum(r.status == s for r in rows) for s in STATUS_ICON}
    v = result.data_version
    out = [
        "# Nimbus AI Portfolio: Weekly Executive Report",
        "",
        f"**Reporting period:** weeks starting {result.weeks[0].isoformat()} to {result.weeks[-1].isoformat()} "
        f"(as of {result.as_of.isoformat()})  ",
        f"**Data version:** `{v}`  ",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')} (deterministic; no language model used)",
        "",
        "## Portfolio summary",
        "",
        f"- Initiatives: **{len(rows)}**",
        f"- 🟢 Green: **{counts['Green']}** · 🟠 Amber: **{counts['Amber']}** · 🔴 Red: **{counts['Red']}**"
        + (f" · ⚪ Insufficient data: **{counts['Insufficient data']}**" if counts["Insufficient data"] else ""),
        "",
        "Status rule: Red if adoption is below 30% or ROI is below 0; Green if adoption is at least 60% and ROI "
        "is above 0; otherwise Amber.",
        "",
        "## Scorecard",
        "",
        "| Initiative | Status | " + " | ".join(TABLE_METRICS.values()) + " |",
        "|---|---|" + "---:|" * len(TABLE_METRICS),
    ]
    for r in rows:
        cells = " | ".join(r.metrics[m].display for m in TABLE_METRICS)
        out.append(f"| {r.initiative_id} {r.name} | {STATUS_ICON[r.status]} {r.status} | {cells} |")
    out += ["", f"All figures: governed scorecard, data version `{v}` [S]. Formulas, inputs and source rows "
                "for every cell are in `data/processed/scorecard.json`.", ""]

    out += ["## Initiatives requiring attention", ""]
    attention = [r for r in rows if r.status == "Red"] + [r for r in rows if r.status in ("Amber", "Insufficient data")]
    if not attention:
        out.append("No initiative is Red or Amber this week.")
    cited: list[str] = []
    for r in attention:
        risk, cite = _top_risk(index, r.initiative_id)
        out += [f"### {STATUS_ICON[r.status]} {r.initiative_id} {r.name} ({r.status})", "",
                f"- **Why:** {r.status_reason} [S]",
                f"- **Key metrics:** adoption {r.metrics['adoption'].display}, ROI {r.metrics['roi'].display}, "
                f"run-rate vs plan {r.metrics['run_rate_vs_plan'].display} [S]"]
        if cite:
            cited.append(cite)
            out.append(f"- **Top charter risk:** \"{risk}\" [C{len(cited)}]")
        else:
            out.append(f"- **Top charter risk:** {risk}")
        out.append("")

    out += ["## Sources", "",
            f"- [S] Governed scorecard, data version `{v}`, computed from "
            f"{', '.join(result.files.values())} (see the data-quality change log for every correction).",
            *[f"- [C{i}] {c}" for i, c in enumerate(cited, 1)], ""]
    return "\n".join(out)



