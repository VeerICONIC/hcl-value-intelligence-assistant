"""Portfolio status: Green / Amber / Red (problem_statement.md §4), thresholds from config/status_rules.yaml.

Red is checked first, then Green, otherwise Amber. If adoption or ROI is not available the
status is "Insufficient data" with the reason: a status is never guessed from partial data.
The reason text quotes the metrics' display strings, so it matches the scorecard exactly.
"""

from __future__ import annotations

from app.core.yaml_config import StatusRules
from app.schemas import MetricValue


def _pct(threshold: float) -> str:
    return f"{threshold * 100:g}%"


def evaluate_status(adoption: MetricValue, roi: MetricValue, rules: StatusRules) -> tuple[str, str]:
    """Return ``(status, status_reason)``."""
    missing = [f"{label} is not available ({m.note})" if m.note else f"{label} is not available"
               for label, m in (("adoption", adoption), ("ROI", roi)) if m.value is None]
    if missing:
        return "Insufficient data", "Insufficient data: " + "; ".join(missing)

    a, r = adoption.value, roi.value
    red, green = rules.red_if_any, rules.green_if_all

    red_reasons = []
    if a < red.adoption_below:
        red_reasons.append(f"adoption {adoption.display} is below {_pct(red.adoption_below)}")
    if r < red.roi_below:
        red_reasons.append(f"ROI {roi.display} is below {_pct(red.roi_below)}")
    if red_reasons:
        return "Red", "Red: " + " and ".join(red_reasons)

    if a >= green.adoption_at_least and r > green.roi_above:
        return "Green", (f"Green: adoption {adoption.display} is at least {_pct(green.adoption_at_least)} "
                         f"and ROI {roi.display} is above {_pct(green.roi_above)}")

    amber_reasons = []
    if a < green.adoption_at_least:
        amber_reasons.append(f"adoption {adoption.display} is below {_pct(green.adoption_at_least)}")
    if r <= green.roi_above:
        amber_reasons.append(f"ROI {roi.display} is not above {_pct(green.roi_above)}")
    return "Amber", "Amber: not Red, but " + " and ".join(amber_reasons)
