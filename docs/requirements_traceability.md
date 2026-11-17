# Requirements traceability (use case 2b)

Every functional requirement, expected submission and evaluation dimension in `docs/problem_statement.md`, mapped to where it is implemented, how it is verified, and where to see it in the demo.

## Functional requirements

| ID | Requirement | Implementation | Verified by | Demo |
|---|---|---|---|---|
| FR-01 | Metric definitions in own words, assumptions, client clarification | `docs/assumptions.md` | Review | How it works page |
| FR-02 | Load and clean data, fix planted issues, normalise names, units and conventions, change log with effects | `nimbus/pipeline.py`, `config/pipeline.yaml` | `tests/test_nimbus_core.py` (every issue type logged, before/after effect), `app/` cleaning tests | Data quality page |
| FR-03 | Every metric and status in deterministic code | `nimbus/pipeline.py` (scorecard section) | Golden test against the independent answer key on 8 and 40 initiatives (max difference 0) | Scorecard page and drill-down |
| FR-04 | Charter chunks with filename, initiative ID and section; embeddings; vector store | `nimbus/charters.py` (MD/PDF/DOCX parsing, section chunks, Titan V2, ChromaDB, hybrid search) | Evaluation citation checks (Q05 to Q07) | Drill-down: Charter evidence |
| FR-05 | Route numeric, narrative and mixed questions | `nimbus/assistant.py` (`route`) | Evaluation: routing accuracy 100% on 15 labelled questions | Route badge on every answer |
| FR-06 | Concise grounded answers with a source for every statement | `nimbus/assistant.py` (metric templates, grounded narrative, `[S#]` / `[C#]` citations) | Evaluation: required facts present, cited section correct | Sources panel in chat |
| FR-07 | Clear "not available" response | Exact fallback `I do not have that in the data provided` | Q10, Q11, Q14 | "What are the risks of the Sales Forecast Model?" |
| FR-08 | Refuse personal data, ignore charter instructions, never show a number not from the scorecard | Input guard; injection flag and `strip_injection`; number guard on LLM output; metric answers never use the LLM | Q12 (personal), Q13 (charter injection), Q15 (user injection); unit tests | Guardrail buttons; 🛡️ notes |
| FR-09 | Weekly report: G/A/R, why attention is needed, traceable evidence | `nimbus/report.py` | Report generated in tests and API; footnotes per figure | Weekly report page; `outputs/weekly_report_*.md` |
| FR-10 | Simple interface: questions, sources, scorecard, report | `frontend/index.html` + `nimbus/api.py` | Rendered and clicked through in a headless browser | Whole web app |

## Expected submissions

| Item | Location |
|---|---|
| Data-quality and assumptions log | `outputs/change_log_*.csv`, `docs/assumptions.md` |
| Computed value scorecard | `outputs/scorecard_demo_8.csv`, `outputs/scorecard_scale_40.csv` |
| Grounded assistant | Web app, Ask the assistant |
| Weekly executive report | `outputs/weekly_report_*.md`, Weekly report page |
| Guardrail demonstration | `eval/questions.yaml` Q12 to Q15, assistant guardrail buttons |
| Evaluation summary | `eval/results.md`, live Evaluation page |
| Technical documentation | `README.md`, `docs/architecture.md`, this file |

## Evaluation guidance

| Dimension | Evidence |
|---|---|
| Scorecard correctness | Golden test: 8/8 and 40/40 statuses, max metric difference 0 vs the answer key |
| Data-quality handling | 11 planted issue types (17 instances in the demo set, 138 in the scale set) detected and logged with effects |
| Retrieval and citation quality | Section-aware chunks, hybrid vector + keyword ranking, expected section cited for narrative questions |
| Grounded numeric answers | Numbers come only from scorecard templates; LLM drafts containing digits are rejected |
| Question routing | 100% on the labelled set |
| No-answer and guardrail behaviour | Fallback, personal-data refusal, charter and user injection, undefined-aggregate refusal all pass |
| Executive usefulness | Overview (quadrant, attention list), drill-down per initiative, weekly report with reasons |
