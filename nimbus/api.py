"""
FastAPI backend + web frontend.

Run:   uvicorn nimbus.api:app --port 8000
Open:  http://localhost:8000          (web app)
       http://localhost:8000/docs     (API docs)
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from nimbus import llm
from nimbus.assistant import DIGIT_OK, answer_to_dict
from nimbus.charters import strip_injection
from nimbus.pipeline import METRIC_LABELS, fmt_metric
from nimbus.service import SERVICE
from nimbus.settings import ROOT

app = FastAPI(title="Nimbus Value Intelligence Assistant", version="2.0")
FRONTEND = ROOT / "frontend" / "index.html"
METRICS = ["adoption", "wau_change", "roi", "avg_monthly_benefit", "payback_months", "run_rate_vs_plan"]
INPUTS = ["licensed_users", "wau_first", "wau_latest", "benefit_to_date", "cost_to_date", "planned_annual_benefit", "months_live"]


class RunRequest(BaseModel):
    dataset_dir: str = Field("data", description="Folder containing raw/ and charters/, inside the project")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


def _need_run():
    if not SERVICE.ready:
        raise HTTPException(409, "Run the pipeline first")


def _clean(obj):
    return json.loads(json.dumps(obj, default=str).replace("NaN", "null"))


def _row(r) -> dict:
    d = {k: r[k] for k in r.index}
    d["display"] = {m: fmt_metric(m, r[m]) for m in METRICS + INPUTS}
    return d


# ------------------------------------------------------------------ web app
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND)


# ------------------------------------------------------------------ API
@app.get("/api/health")
def health():
    return {"status": "ok", "pipeline_ready": SERVICE.ready, "bedrock": llm.status()}


@app.get("/api/datasets")
def datasets():
    return [p.name for p in sorted(ROOT.iterdir()) if p.is_dir() and (p / "raw").is_dir()]


@app.post("/api/pipeline/run")
def run(req: RunRequest):
    target = (ROOT / req.dataset_dir).resolve()
    if ROOT.resolve() not in target.parents:
        raise HTTPException(400, "dataset_dir must be inside the project folder")
    if not (target / "raw").is_dir():
        raise HTTPException(404, f"{req.dataset_dir}/raw not found")
    return _clean(SERVICE.run(str(target)))


@app.get("/api/overview")
def overview():
    _need_run()
    r = SERVICE.result
    sc = r.scorecard
    attention = sc[sc.status.isin(["Red", "Amber"])].sort_values(["status", "roi"], ascending=[False, True])
    return _clean({
        "dataset": Path(r.raw_dir).parent.name, "data_version": r.data_version, "as_of": r.as_of.isoformat(),
        "weeks": [w.isoformat() for w in r.weeks], "initiatives": len(sc),
        "status_counts": sc.status.value_counts().to_dict(), "changes": len(r.changes),
        "change_rules": r.changes.rule.nunique(), "charters": SERVICE.index_info, "bedrock": llm.status(),
        "attention": [{"initiative_id": x.initiative_id, "name": x["name"], "status": x.status, "reason": x.status_reason}
                      for _, x in attention.iterrows()],
    })


@app.get("/api/scorecard")
def scorecard():
    _need_run()
    r = SERVICE.result
    usage = r.usage[r.usage.included]
    rows = []
    for _, x in r.scorecard.iterrows():
        d = _row(x)
        u = usage[usage.initiative_id == x.initiative_id].sort_values("week_start")
        d["trend"] = [{"week": w.isoformat(), "value": v} for w, v in zip(u.week_start, u.value)]
        rows.append(d)
    return _clean({"data_version": r.data_version, "as_of": r.as_of.isoformat(), "labels": METRIC_LABELS, "rows": rows})


@app.get("/api/initiative/{iid}")
def initiative(iid: str):
    _need_run()
    r = SERVICE.result
    sc = r.scorecard.set_index("initiative_id")
    if iid not in sc.index:
        raise HTTPException(404, f"{iid} not found")
    x = sc.loc[iid]
    x["initiative_id"] = iid
    sections = []
    for c in SERVICE.index.chunks:
        if c.initiative_id == iid:
            text, removed = strip_injection(c.text)
            sections.append({"section": c.section, "text": text, "source_file": c.source_file, "injection_removed": removed})
    ch = r.changes[r.changes.initiative_id == iid]
    u = r.usage[r.usage.initiative_id == iid].sort_values("week_start")
    return _clean({"row": _row(x), "sections": sections, "changes": ch.to_dict(orient="records"),
                   "usage": [{"week": w.isoformat(), "value": v, "included": inc} for w, v, inc in zip(u.week_start, u.value, u.included)]})


@app.get("/api/data-quality")
def data_quality():
    _need_run()
    ch = SERVICE.result.changes
    return _clean({"data_version": SERVICE.result.data_version, "counts": ch.rule.value_counts().to_dict(),
                   "changes": ch.to_dict(orient="records")})


log = logging.getLogger("nimbus")


@app.post("/api/ask")
def ask(req: AskRequest):
    _need_run()
    try:
        return _clean({"data_version": SERVICE.result.data_version, **answer_to_dict(SERVICE.assistant.ask(req.question))})
    except Exception as e:  # never show a raw server error in the demo; log the details instead
        log.error("ask failed for %r\n%s", req.question, traceback.format_exc())
        return {"data_version": SERVICE.result.data_version, "question": req.question, "route": "unsupported", "status": "no_evidence",
                "answer": "I do not have that in the data provided.", "scorecard_sources": [], "charter_sources": [],
                "guard_notes": [f"Internal error handled safely ({type(e).__name__}); details in the server log"], "initiatives": []}


@app.get("/api/report", response_class=PlainTextResponse)
def report():
    _need_run()
    return SERVICE.report()


@app.get("/api/assumptions", response_class=PlainTextResponse)
def assumptions():
    p = ROOT / "docs" / "assumptions.md"
    return p.read_text(encoding="utf-8") if p.exists() else "No assumptions file found."


@app.post("/api/evaluation/run")
def evaluation():
    """Runs the labelled question set against the live assistant plus the golden scorecard check."""
    _need_run()
    import pandas as pd

    from nimbus.pipeline import run_pipeline

    golden = []
    for folder in ("data", "data_scale_40"):
        key = ROOT / folder / "answer_key" / "expected_scorecard.csv"
        if key.exists():
            res = run_pipeline(ROOT / folder / "raw", write=False)
            exp = pd.read_csv(key).set_index("initiative_id")
            got = res.scorecard.set_index("initiative_id").loc[exp.index]
            diff = float((got[METRICS].astype(float) - exp[METRICS]).abs().max().max())
            golden.append({"dataset": folder, "initiatives": len(exp), "max_abs_diff": 0.0 if diff != diff else diff,
                           "status_match": int((got.status == exp.status).sum()), "changes": len(res.changes)})
    qs = yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text(encoding="utf-8"))
    rows = []
    for q in qs:
        a = SERVICE.assistant.ask(q["question"])
        t = a.answer.lower()
        checks = {"route": a.route == q["expect_route"], "status": a.status == q["expect_status"],
                  "facts": all(s.lower() in t for s in q.get("must_contain", [])),
                  "forbidden": not any(s.lower() in t for s in q.get("must_not_contain", []))}
        if "expect_source_section" in q:
            checks["citation"] = any(s["section"] == q["expect_source_section"] for s in a.charter_sources)
        if a.route == "narrative" and a.status == "answered":
            checks["no_numbers"] = not re.search(r"\d", re.sub(r"\[number omitted\]", "", DIGIT_OK.sub("", a.answer)))
        rows.append({"id": q["id"], "type": q["type"], "question": q["question"], "route": a.route, "status": a.status,
                     "checks": checks, "pass": all(checks.values())})
    return _clean({"golden": golden, "questions": rows, "passed": sum(r["pass"] for r in rows), "total": len(rows),
                   "routing_accuracy": sum(r["checks"]["route"] for r in rows) / len(rows), "llm": llm.status()})


# ------------------------------------------------------------------ backwards-compatible routes
@app.get("/health", include_in_schema=False)
def health_legacy():
    return health()
