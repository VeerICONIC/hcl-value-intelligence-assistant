"""
Evaluation: scorecard correctness, routing, retrieval/citation, groundedness checks, no-answer and guardrails.

Run:  python eval/run_eval.py            -> writes eval/results.md and prints a summary
Results are produced by actually running the system; nothing is hand-entered.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from nimbus import llm  # noqa: E402
from nimbus.assistant import DIGIT_OK  # noqa: E402
from nimbus.pipeline import run_pipeline  # noqa: E402
from nimbus.service import Service  # noqa: E402

METRICS = ["adoption", "wau_change", "roi", "avg_monthly_benefit", "payback_months", "run_rate_vs_plan"]


def scorecard_check(folder: str) -> dict:
    r = run_pipeline(ROOT / folder / "raw", write=False)
    exp = pd.read_csv(ROOT / folder / "answer_key" / "expected_scorecard.csv").set_index("initiative_id")
    got = r.scorecard.set_index("initiative_id").loc[exp.index]
    diff = (got[METRICS].astype(float) - exp[METRICS]).abs().max().max()
    return {"dataset": folder, "initiatives": len(exp), "max_abs_diff": float(diff if pd.notna(diff) else 0),
            "status_match": f"{(got.status == exp.status).sum()}/{len(exp)}", "changes_logged": len(r.changes),
            "rules": len(r.changes.rule.unique())}


def main() -> None:
    svc = Service()
    svc.run(str(ROOT / "data"))
    qs = yaml.safe_load((ROOT / "eval" / "questions.yaml").read_text(encoding="utf-8"))
    rows = []
    for q in qs:
        a = svc.assistant.ask(q["question"])
        text = a.answer.lower()
        checks = {
            "route_ok": a.route == q["expect_route"],
            "status_ok": a.status == q["expect_status"],
            "contains": all(s.lower() in text for s in q.get("must_contain", [])),
            "excludes": not any(s.lower() in text for s in q.get("must_not_contain", [])),
        }
        if "expect_source_section" in q:
            checks["citation"] = any(s["section"] == q["expect_source_section"] for s in a.charter_sources)
        if a.route == "narrative" and a.status == "answered":
            narrative_text = re.sub(r"\[number omitted\]", "", DIGIT_OK.sub("", a.answer))
            checks["no_llm_numbers"] = not re.search(r"\d", narrative_text)
        rows.append({"id": q["id"], "type": q["type"], "question": q["question"], "route": a.route, "status": a.status,
                     **{k: "✅" if v else "❌" for k, v in checks.items()},
                     "pass": all(checks.values()), "answer": a.answer.replace("\n", " ")[:160]})
    df = pd.DataFrame(rows)
    sc = [scorecard_check("data"), scorecard_check("data_scale_40")] if (ROOT / "data_scale_40").exists() else [scorecard_check("data")]
    passed = int(df["pass"].sum())
    by_type = df.groupby("type")["pass"].agg(["sum", "count"])
    route_acc = (df.route == pd.Series([q["expect_route"] for q in qs])).mean()

    md = [f"# Evaluation results", "", f"Run {datetime.now():%Y-%m-%d %H:%M} · LLM: {llm.status()['llm']} · embeddings: {svc.index.mode}", "",
          "## 1. Scorecard correctness (golden test against the answer key)", "",
          "| Dataset | Initiatives | Max abs difference | Status match | Changes logged | Distinct rules |", "|---|---|---|---|---|---|"]
    md += [f"| {s['dataset']} | {s['initiatives']} | {s['max_abs_diff']:.1e} | {s['status_match']} | {s['changes_logged']} | {s['rules']} |" for s in sc]
    md += ["", f"## 2. Assistant evaluation: {passed}/{len(df)} questions passed · routing accuracy {route_acc:.0%}", "",
           "| Type | Passed |", "|---|---|"] + [f"| {t} | {int(r['sum'])}/{int(r['count'])} |" for t, r in by_type.iterrows()]
    md += ["", "| ID | Type | Question | Route | Status | Checks | Answer (truncated) |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        ck = " ".join(f"{k}{r[k]}" for k in ("route_ok", "status_ok", "contains", "excludes", "citation", "no_llm_numbers") if k in r)
        md.append(f"| {r['id']} | {r['type']} | {r['question']} | {r['route']} | {r['status']} | {ck} | {r['answer']} |")
    md += ["", "## 3. Method", "",
           "- **Scorecard correctness:** the pipeline runs on the raw files and is compared to the answer key produced independently by the data generator.",
           "- **Routing:** the route of each question is compared to its label.",
           "- **Citation accuracy:** for narrative questions, the expected charter section must be among the cited sources.",
           "- **Groundedness:** required facts must appear; forbidden content (injected values, personal data) must not; narrative answers must contain no numbers.",
           "- **No-answer / guardrails:** unsupported, personal-data, prompt-injection and undefined-calculation questions are checked for the required behaviour.",
           "", "## 4. Limitations", "",
           "- The dataset is synthetic (no data was supplied); the 15 questions are hand-labelled by the team.",
           "- Rule-based routing covers the vocabulary of the portfolio questions; unusual phrasings may fall back to the safe response.",
           "- Groundedness is checked by rules (facts present, numbers absent), not by human review of every sentence.",
           "- Without Bedrock, narrative answers are extractive (cited excerpts) rather than summarised."]
    out = ROOT / "eval" / "results.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(df[["id", "type", "route", "status", "pass"]].to_string(index=False))
    print(f"\n{passed}/{len(df)} passed · routing accuracy {route_acc:.0%}")
    for s in sc:
        print(f"scorecard {s['dataset']}: max diff {s['max_abs_diff']:.1e}, status {s['status_match']}")
    print(f"written {out}")


if __name__ == "__main__":
    main()
