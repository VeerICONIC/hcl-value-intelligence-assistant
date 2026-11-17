"""Evaluation: assistant questions + scorecard correctness -> eval/results.md.

Runs in-process against the FastAPI app (no server needed). Uses LLM_MODE from the
environment/.env (extractive = offline). Run from the repo root:

    .\\.venv\\Scripts\\python.exe eval\\run_eval.py
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.data.pipeline import run_pipeline  # noqa: E402
from app.main import create_app  # noqa: E402
from app.orchestration.guards import has_digit  # noqa: E402
from app.scorecard.metrics import METRIC_ORDER  # noqa: E402


def check_question(client: TestClient, q: dict) -> tuple[bool, list[str], dict]:
    r = client.post("/ask", json={"question": q["question"]}).json()
    fails = []
    if r["route"] != q["route"]:
        fails.append(f"route {r['route']} != {q['route']}")
    if r["status"] != q["status"]:
        fails.append(f"status {r['status']} != {q['status']}")
    if "exact" in q and r["answer"] != q["exact"]:
        fails.append("answer is not the exact fallback")
    for s in q.get("must_include", []):
        if s.lower() not in r["answer"].lower():
            fails.append(f"missing '{s}'")
    for s in q.get("must_not_include", []):
        if s.lower() in r["answer"].lower():
            fails.append(f"contains forbidden '{s}'")
    if q.get("expect_source") and q["expect_source"] not in {c["source_file"] for c in r["charter_sources"]}:
        fails.append(f"source {q['expect_source']} not cited")
    if r["route"] == "narrative" and has_digit(r["answer"]):
        fails.append("digit in narrative answer")
    return not fails, fails, r


def scorecard_check(folder: str) -> tuple[int, int, int, int]:
    """(initiatives, cells checked, cells matching, status matches) against answer_key/expected_scorecard.csv."""
    res = run_pipeline(ROOT / folder / "raw", ROOT / "config")
    exp = pd.read_csv(ROOT / folder / "answer_key" / "expected_scorecard.csv").set_index("initiative_id")
    got = {r.initiative_id: r for r in res.scorecard}
    cells = ok = status_ok = 0
    for iid, e in exp.iterrows():
        status_ok += got[iid].status == e["status"]
        for m in METRIC_ORDER:
            cells += 1
            v, x = got[iid].metrics[m].value, e[m]
            if (v is None and (isinstance(x, float) and math.isnan(x))) or (
                    v is not None and not (isinstance(x, float) and math.isnan(x))
                    and math.isclose(round(v, 4) if m == "months_live" else v, x, rel_tol=1e-9, abs_tol=1e-9)):
                ok += 1
    return len(exp), cells, ok, status_ok


def main() -> int:
    questions = yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text(encoding="utf-8"))
    client = TestClient(create_app())
    run = client.post("/pipeline/run", json={"raw_dir": "data/raw"}).json()
    rows, passed = [], 0
    for q in questions:
        ok, fails, r = check_question(client, q)
        passed += ok
        answer = r["answer"].replace("|", "/").replace("\n", " ")
        rows.append(f"| {q['id']} | {q['category']} | {q['question']} | {r['route']} | {r['status']} | "
                    f"{'✅ pass' if ok else '❌ ' + '; '.join(fails)} | {answer[:160]}{'…' if len(answer) > 160 else ''} |")

    sc_lines = []
    for folder in ("data", "data_scale_40"):
        n, cells, ok, st = scorecard_check(folder)
        sc_lines.append(f"| `{folder}` | {n} | {ok}/{cells} | {st}/{n} |")

    md = [
        "# Evaluation results", "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} by `eval/run_eval.py` · answer mode **{get_settings().llm_mode}** · "
        f"data version `{run['data_version']}`", "",
        "## Scorecard correctness (golden comparison with the answer key)", "",
        "| Dataset | Initiatives | Metric cells matching | Status matching |", "|---|---:|---:|---:|", *sc_lines, "",
        "Also covered by `tests/test_pipeline_golden.py`: every planted data-quality issue appears in the change log "
        "with the right rule, file and initiative.", "",
        f"## Assistant questions: {passed}/{len(questions)} passed", "",
        "Checks: route, status, required facts, forbidden text (injection), cited source file (citation accuracy), "
        "exact fallback text, and no digits in narrative answers (number guard).", "",
        "| ID | Category | Question | Route | Status | Result | Answer (truncated) |",
        "|---|---|---|---|---|---|---|", *rows, "",
        "## Known limitations", "",
        "- Router is keyword rules (D9): unusual phrasings can be misrouted or get the fallback. "
        "Initiatives must be named by ID or full name.",
        "- Without AWS credentials the assistant runs in extractive mode: narrative answers quote charter sentences "
        "(sentences containing digits are left out of the answer and remain visible in the sources) and retrieval is "
        "BM25 + section matching instead of Titan vectors. Nova Lite / Titan paths are implemented but were not "
        "exercised live in this environment.",
        "- Retrieval relevance is evaluated on a small hand-written set (12 questions); no large-scale relevance metric.",
        "- Injection detection is pattern-based; novel phrasings could pass the flag, but the number guard and "
        "scorecard-only figures still prevent injected numbers or statuses from being shown.",
        "- Practice data is synthetic (no data was supplied); real files need `config/*.yaml` edits.",
        "- One answer-key defect in `data_scale_40` (R-DUP-INIT-029 listed but not present in the raw file) is "
        "documented and excluded in the golden test.", "",
    ]
    out = ROOT / "eval" / "results.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"{passed}/{len(questions)} questions passed; scorecard: {'; '.join(sc_lines)}")
    print(f"wrote {out}")
    return 0 if passed == len(questions) else 1


if __name__ == "__main__":
    raise SystemExit(main())
