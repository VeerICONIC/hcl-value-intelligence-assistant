"""Rule-based question router (FR-05, D9): metric | narrative | mixed | unsupported.

Deterministic keyword rules, no LLM: easy to test, explain and defend. The router also
extracts what the answer step needs: initiatives (by ID or name), metrics, the scorecard
operation (lookup / filter / rank / count, D8), status filter and preferred charter sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

METRIC_WORDS = {
    "adoption": "adoption", "adopted": "adoption", "adopting": "adoption",
    "roi": "roi", "return on investment": "roi", "return": "roi", "cost": "roi", "costs": "roi",
    "payback": "payback_months", "pay back": "payback_months",
    "run-rate": "run_rate_vs_plan", "run rate": "run_rate_vs_plan", "runrate": "run_rate_vs_plan",
    "versus plan": "run_rate_vs_plan", "vs plan": "run_rate_vs_plan",
    "wau": "wau_change", "users": "wau_change", "active users": "wau_change", "usage": "wau_change",
    "growth": "wau_change",
    "benefit": "avg_monthly_benefit", "benefits": "avg_monthly_benefit", "value delivered": "avg_monthly_benefit",
    "months live": "months_live",
}
STATUS_WORDS = {"green": "Green", "amber": "Amber", "red": "Red"}
STATUS_TRIGGERS = ("status", "rag", "attention", "performing", "on track")
ATTENTION_WORDS = ("attention", "at risk", "concern", "concerns", "struggling", "underperforming", "off track")
RANK_DESC = ("highest", "best", "top", "most", "largest", "biggest", "leading")
RANK_ASC = ("lowest", "worst", "least", "smallest", "bottom", "weakest")
COUNT_WORDS = ("how many", "number of", "count")
UNDEFINED_CALC = ("average", "mean", "median", "total", "sum of", "combined", "overall", "aggregate")

NARRATIVE_SECTIONS = [   # keyword -> preferred charter sections (first available wins)
    (("risk", "risks", "mitigation", "mitigations", "threat"), ["Risks and Mitigations"]),
    (("objective", "objectives", "goal", "goals", "aim", "aims"), ["Objectives"]),
    (("scope", "in scope", "out of scope"), ["Scope"]),
    (("stakeholder", "stakeholders", "sponsor", "owner", "who leads", "who owns"), ["Stakeholders"]),
    (("timeline", "milestone", "milestones", "phase", "phases", "schedule"), ["Timeline"]),
    (("benefits plan", "plan", "how are benefits"), ["Benefits Plan"]),
    (("success measure", "success measures", "kpi", "measured", "success"), ["Success Measures"]),
    (("overview", "what is", "what does", "purpose", "describe", "about"), ["Overview"]),
    (("why",), ["Risks and Mitigations", "Objectives"]),
]


@dataclass
class RouteResult:
    kind: str                                   # metric | narrative | mixed | unsupported
    initiative_ids: list[str] = field(default_factory=list)
    operation: str | None = None                # lookup | filter | rank | count
    metrics: list[str] = field(default_factory=list)
    status_filter: list[str] = field(default_factory=list)
    descending: bool = True
    top_k: int = 1
    sections: list[str] = field(default_factory=list)
    reason: str = ""


def _has(q: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", q) is not None


def find_initiatives(question: str, initiatives: dict[str, str]) -> list[str]:
    """Initiatives mentioned by ID ('INIT-004', 'init 4') or by name (all name words present)."""
    q = question.lower()
    found: list[str] = []
    for m in re.finditer(r"init[\s_-]*0*(\d{1,3})\b", q):
        iid = f"INIT-{int(m.group(1)):03d}"
        if iid in initiatives and iid not in found:
            found.append(iid)
    words = set(re.findall(r"[a-z0-9]+", q))
    for iid, name in initiatives.items():
        name_words = re.findall(r"[a-z0-9]+", name.lower())
        if iid not in found and name_words and (name.lower() in q or set(name_words) <= words):
            found.append(iid)
    return found


def route(question: str, initiatives: dict[str, str]) -> RouteResult:
    q = " ".join(question.lower().split())
    iids = find_initiatives(q, initiatives)
    q_wo_amb = q.replace("average monthly benefit", "benefit")        # a defined metric, not an aggregate

    metrics = list(dict.fromkeys(m for w, m in METRIC_WORDS.items() if _has(q_wo_amb, w)))
    statuses = [s for w, s in STATUS_WORDS.items() if _has(q, w)]
    status_asked = bool(statuses) or any(_has(q, w) for w in STATUS_TRIGGERS)
    rank_desc, rank_asc = any(_has(q, w) for w in RANK_DESC), any(_has(q, w) for w in RANK_ASC)
    count = any(_has(q, w) for w in COUNT_WORDS)
    sections: list[str] = []
    for words, secs in NARRATIVE_SECTIONS:
        if any(_has(q, w) for w in words):
            sections = secs
            break
    is_metric = bool(metrics) or status_asked or rank_desc or rank_asc or count
    if is_metric and sections == ["Overview"]:
        sections = []          # "what is the adoption of X" is a metric question, not a request for the overview
    is_narrative = bool(sections)

    # D8: portfolio aggregates are not defined metrics -> no calculation, fallback
    if any(_has(q_wo_amb, w) for w in UNDEFINED_CALC) and (metrics or "portfolio" in q):
        return RouteResult("unsupported", iids, reason="asks for an aggregate that is not a defined metric (D8)")

    if not is_metric and not is_narrative:
        return RouteResult("unsupported", iids, reason="no metric or charter topic recognised")

    r = RouteResult("metric", iids, metrics=metrics, sections=sections)
    if is_metric and is_narrative:
        r.kind = "mixed"
    elif is_narrative:
        r.kind = "narrative"

    if r.kind in ("metric", "mixed"):
        if count:
            r.operation = "count"
        elif rank_desc or rank_asc:
            r.operation = "rank"
            r.descending = rank_desc and not rank_asc
            m = re.search(r"\b(?:top|bottom|lowest|highest|best|worst)\s+(\d{1,2})\b", q)
            r.top_k = int(m.group(1)) if m else 1
            if not r.metrics:
                r.metrics = ["roi"]
        elif iids:
            r.operation = "lookup"
        elif statuses:
            r.operation = "filter"
        elif any(_has(q, w) for w in ATTENTION_WORDS):
            r.operation = "filter"            # "needs attention" = not Green
            statuses = ["Red", "Amber", "Insufficient data"]
        else:
            if r.kind == "metric":
                return RouteResult("unsupported", iids, reason="metric question without an initiative or a ranking")
            r.kind = "narrative"
        r.status_filter = statuses
    if r.kind in ("narrative", "mixed") and not iids:
        if r.kind == "mixed" and r.operation in ("filter", "rank", "count"):
            r.kind, r.sections = "metric", []       # portfolio question; narrative part needs an initiative
        else:
            return RouteResult("unsupported", iids, reason="charter question without a recognised initiative")
    r.reason = (f"metric words {r.metrics or []}, status {r.status_filter or status_asked}, "
                f"sections {r.sections or []}, initiatives {r.initiative_ids or []}")
    return r
