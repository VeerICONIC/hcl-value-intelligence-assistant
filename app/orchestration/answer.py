"""Answer a question: one explicit function (D4), no framework.

    input guard -> route -> metric facts (deterministic templates, NO LLM)
                         -> charter chunks (retrieval) -> narrative text (Nova or extractive)
                         -> number guard -> answer with sources, or the exact fallback

Numbers in answers come only from ``MetricValue.display`` strings produced by scorecard code.
Narrative text (LLM or extractive) is never allowed to contain a digit.
"""

from __future__ import annotations

import logging
import re

from app.charters.index import CharterIndex
from app.charters.injection import strip_injection
from app.core.config import FALLBACK_MESSAGE, Settings
from app.orchestration import guards
from app.orchestration.router import RouteResult, route
from app.schemas import CharterChunk, MetricValue, ScorecardRow
from app.schemas.answer import AskResponse
from app.scorecard.metrics import METRIC_LABELS

logger = logging.getLogger(__name__)

PAYBACK_LOWER_IS_BETTER = {"payback_months"}


def _label(row: ScorecardRow) -> str:
    return f"{row.initiative_id} {row.name}"


# --- metric answers (deterministic templates) --------------------------------------
def metric_answer(r: RouteResult, rows: dict[str, ScorecardRow], data_version: str) -> tuple[str, list[MetricValue]]:
    sources: list[MetricValue] = []
    cite = f"[source: scorecard, data version {data_version}]"
    if r.operation == "lookup":
        parts = []
        for iid in r.initiative_ids:
            row = rows[iid]
            facts = [f"{METRIC_LABELS[m]} is {row.metrics[m].display}" for m in r.metrics]
            sources += [row.metrics[m] for m in r.metrics]
            if facts:
                text = f"For {_label(row)}, " + ", ".join(facts) + f". Its status is {row.status}."
            else:
                text = f"{_label(row)} is {row.status}. {row.status_reason}."
                sources += [row.metrics["adoption"], row.metrics["roi"]]
            parts.append(text)
        return " ".join(parts) + f" {cite}", sources

    if r.operation == "filter":
        order = {"Red": 0, "Amber": 1, "Insufficient data": 2, "Green": 3}
        chosen = sorted((row for row in rows.values() if row.status in r.status_filter),
                        key=lambda row: (order[row.status], row.initiative_id))
        sources = [row.metrics["adoption"] for row in chosen] + [row.metrics["roi"] for row in chosen]
        if set(r.status_filter) == {"Red", "Amber", "Insufficient data"}:
            if not chosen:
                return f"No initiative needs attention: all are Green. {cite}", sources
            listed = "; ".join(f"{_label(row)} ({row.status}: {row.status_reason.split(': ', 1)[-1]})"
                               for row in chosen)
            return f"Initiatives needing attention (Red first, then Amber): {listed}. {cite}", sources
        names = ", ".join(_label(row) for row in chosen) or "none"
        return f"{' or '.join(r.status_filter)} initiatives: {names}. {cite}", sources

    if r.operation == "count":
        chosen = [row for row in rows.values() if not r.status_filter or row.status in r.status_filter]
        what = f"{' or '.join(r.status_filter)} " if r.status_filter else ""
        sources = [row.metrics["adoption"] for row in chosen] + [row.metrics["roi"] for row in chosen]
        listed = ", ".join(_label(row) for row in chosen)
        return f"{len(chosen)} {what}initiative{'s' if len(chosen) != 1 else ''}: {listed}. {cite}", sources

    # rank
    metric = r.metrics[0]
    desc = r.descending
    if metric in PAYBACK_LOWER_IS_BETTER:      # "best payback" = shortest
        desc = not desc
    pool = [row for row in rows.values() if row.metrics[metric].value is not None
            and (not r.status_filter or row.status in r.status_filter)]
    pool.sort(key=lambda row: (row.metrics[metric].value, row.initiative_id), reverse=desc)
    top = pool[: max(1, r.top_k)]
    sources = [row.metrics[metric] for row in top]
    word = "Highest" if desc else "Lowest"
    if metric in PAYBACK_LOWER_IS_BETTER:
        word = "Longest" if desc else "Shortest"
    listed = "; ".join(f"{_label(row)} ({row.metrics[metric].display}, {row.status})" for row in top)
    return f"{word} {METRIC_LABELS[metric]}: {listed}. {cite}", sources


# --- narrative answers ---------------------------------------------------------------
def _clean_line(line: str) -> str:
    line = re.sub(r"^\s*[-*]\s*", "", line).strip()
    return line.replace(" Mitigation:", "; mitigation:")


def extractive_answer(chunks: list[CharterChunk], names: dict[str, str]) -> str:
    """Answer built only from charter sentences that contain no digits (number guard by construction)."""
    parts = []
    for c in chunks:
        lines = [_clean_line(l) for l in c.text.splitlines() if l.strip()]
        lines = [l for l in lines if l and not guards.has_digit(l)]
        if not lines:
            continue
        body = " ".join(l if l.endswith(".") else l + "." for l in lines)
        parts.append(f"The {c.section} section of the charter for {c.initiative_id} {names.get(c.initiative_id, '')} "
                     f"says: {body} [source: {c.source_file}, {c.section}]")
    return " ".join(parts)


def narrative_answer(question: str, chunks: list[CharterChunk], names: dict[str, str], settings: Settings,
                     notes: list[str]) -> str:
    if settings.llm_mode == "bedrock":
        from app.generation.llm import nova_answer
        extra = ""
        for attempt in (1, 2):
            try:
                text = nova_answer(question, chunks, settings, extra_rule=extra)
            except Exception as exc:   # noqa: BLE001 - Bedrock down -> extractive
                notes.append(f"LLM unavailable ({type(exc).__name__}); answered from cited excerpts")
                break
            if FALLBACK_MESSAGE.lower() in text.lower():
                return FALLBACK_MESSAGE
            if not guards.has_digit(text):
                cites = "; ".join(f"{c.source_file}, {c.section}" for c in chunks)
                return f"{text} [source: {cites}]"
            notes.append(f"Number guard rejected LLM draft {attempt} (contained a digit)")
            extra = "Your previous answer contained digits. Answer again with NO digits at all."
        else:
            notes.append("Number guard: both drafts rejected; showing cited excerpts instead")
    return extractive_answer(chunks, names)


# --- the one function ------------------------------------------------------------------
def answer_question(question: str, scorecard: list[ScorecardRow], data_version: str, index: CharterIndex,
                    settings: Settings) -> AskResponse:
    notes: list[str] = []

    def done(route_kind: str, status: str, answer: str, sc=None, ch=None) -> AskResponse:
        return AskResponse(route=route_kind, status=status, answer=answer, scorecard_sources=sc or [],
                           charter_sources=ch or [], guard_notes=notes, data_version=data_version)

    word = guards.personal_data_request(question)
    if word:
        notes.append(f"Input guard: personal-data request ('{word}')")
        return done("refused", "refused", guards.REFUSAL_MESSAGE)

    rows = {r.initiative_id: r for r in scorecard}
    names = {r.initiative_id: r.name for r in scorecard}
    r = route(question, names)
    notes.append(f"Router: {r.kind} ({r.reason})")
    if r.kind == "unsupported":
        return done("unsupported", "no_evidence", FALLBACK_MESSAGE)

    metric_text, sc_sources = ("", [])
    if r.kind in ("metric", "mixed"):
        metric_text, sc_sources = metric_answer(r, rows, data_version)

    chunks: list[CharterChunk] = []
    narrative = ""
    if r.kind in ("narrative", "mixed"):
        found = index.search(question, r.initiative_ids, r.sections)
        for c in found:
            clean, removed = strip_injection(c.text)
            if removed:
                notes.append(f"Injection guard: ignored {removed} instruction-like line(s) in {c.source_file} "
                             f"({c.section})")
            chunks.append(c.model_copy(update={"text": clean}))
        if chunks:
            narrative = narrative_answer(question, chunks, names, settings, notes)

    if r.kind == "metric":
        return done("metric", "answered", metric_text, sc_sources)
    if r.kind == "narrative":
        if not narrative or narrative == FALLBACK_MESSAGE:
            return done("narrative", "no_evidence", FALLBACK_MESSAGE)
        return done("narrative", "answered", narrative, ch=chunks)
    # mixed
    if not narrative or narrative == FALLBACK_MESSAGE:
        notes.append("No charter evidence for the narrative part")
        return done("mixed", "answered", f"{metric_text} On the charter part of the question: {FALLBACK_MESSAGE}.",
                    sc_sources)
    return done("mixed", "answered", f"{metric_text} {narrative}", sc_sources, chunks)
