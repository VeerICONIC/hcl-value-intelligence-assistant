# Nimbus Value Intelligence Assistant (HCLTech hackathon, use case 2b)

An enterprise RAG assistant that turns messy AI-portfolio spreadsheets and initiative charters into a **governed scorecard**, answers plain-English questions **with traceable evidence**, and produces a **weekly executive report**.

> **Design principle:** code for numbers, retrieval for charter evidence, the language model only for explanation. No number shown anywhere is produced by an LLM.

## Quick start (Windows PowerShell, Python 3.12)

```powershell
python -m pip install -r requirements_nimbus.txt
python -m pytest tests/test_nimbus_core.py -q      # golden scorecard + guardrail tests
python -m uvicorn nimbus.api:app --port 8000        # web app: http://localhost:8000 · API docs: /docs
```
Alternative Streamlit dashboard: `python -m streamlit run ui/dashboard.py`.

The web app (`frontend/index.html`, served by FastAPI) has seven views: Executive overview (KPIs, adoption × ROI quadrant, health donut, attention list, ranked bars), Governed scorecard (filter, search, sort, WAU sparklines), an initiative drill-down (metrics with formulas, cleaned inputs, weekly users, charter sections, corrections), Ask the assistant (route badges, cited sources, guardrail notes), Data quality, Weekly report (print / PDF / Markdown) and Live evaluation. It is a single file with no external libraries, works offline, and escapes all charter text before display.
Evaluation (writes `eval/results.md`):
```powershell
python eval/run_eval.py
```
Bedrock is optional. With working AWS credentials (boto3 default chain) and the settings in `.env` (see `.env.example.nimbus`), charters are embedded with **Titan Text Embeddings V2** and narrative answers are written by **Amazon Nova Lite**. Without Bedrock, the app falls back automatically to local embeddings and **extractive, cited answers**, so the demo keeps working.

## What the dashboard shows (one page, top to bottom)

1. **Sidebar:** pick a dataset (`data` = 8 curated initiatives, `data_scale_40` = 40), click **Run pipeline**.
2. **Overview tiles:** initiatives, Green / Amber / Red counts, data corrections.
3. **Governed scorecard:** 7 metrics + status + the reason for the status; formulas and inputs per initiative.
4. **Charts:** adoption against the 30% / 60% thresholds; ROI around zero; weekly active users trend.
5. **Data quality:** the change log (rule, file, row, old to new, reason, effect).
6. **Ask the assistant:** metric, narrative and mixed questions with sources and guardrail notes.
7. **Weekly executive report:** generate, preview, download.

Sections 2–5 never call an LLM. The chat answers from the same scorecard version shown above it.

## Architecture

```
data/raw/*.csv, *.xlsx ─► loader (config/pipeline.yaml aliases) ─► cleaning rules ─► change log
                                                                    │
                                                                    ▼
                                                    governed scorecard (pure Python)
                                                                    │
data/charters/*.md|pdf|docx ─► section chunks + initiative ID ─► injection flag ─► embeddings ─► ChromaDB
                                                                    │
question ─► input guard (personal data) ─► rule-based router ─┬─ metric    ─► scorecard templates (no LLM)
                                                              ├─ narrative ─► hybrid retrieval ─► Nova Lite (no digits allowed) ─► number guard ─► citations
                                                              ├─ mixed     ─► both
                                                              └─ unsupported ─► "I do not have that in the data provided"
```

| Module | Responsibility | FR |
|---|---|---|
| `config/pipeline.yaml` | Column / metric / measure aliases, units, status thresholds | FR-02 |
| `nimbus/pipeline.py` | Load, clean, normalise, change log with effects, scorecard | FR-02, FR-03 |
| `nimbus/charters.py` | Parse MD/PDF/DOCX, section chunks with metadata, injection flag, ChromaDB, hybrid search | FR-04 |
| `nimbus/assistant.py` | Input guard, router, metric templates, grounded narrative, number guard, fallback | FR-05 to FR-08 |
| `nimbus/report.py` | Weekly executive report with footnoted sources | FR-09 |
| `ui/dashboard.py`, `nimbus/api.py` | Streamlit dashboard and FastAPI | FR-10 |
| `eval/` | Labelled questions, metrics, results | Evaluation |
| `docs/assumptions.md` | Metric definitions in our words, assumptions, client clarification | FR-01 |

## Data (synthetic, because none was supplied)

`scripts/generate_practice_data.py` creates a seeded dataset with an **independent answer key**:
`initiatives.csv`, `weekly_usage.csv`, `financials.xlsx` and 8 charters (Markdown, PDF, DOCX). It plants 11 kinds of data-quality issues: duplicates, ID formats, numbers stored as text, metric and measure aliases, values in thousands, monthly instead of cumulative cost, mixed date formats, a negative typo, impossible user counts, a missing week, and a supplied ROI computed with the wrong formula. `--size 40` adds random initiatives with random planted issues. `scripts/verify_practice_data.py` checks any folder against its answer key.

## Guardrails (FR-07, FR-08)

| Risk | Protection | Demo question |
|---|---|---|
| Invented numbers | Metric answers are templates filled by code; narrative LLM output is rejected if it contains any digit (retry once, then cited excerpts) | "Why is the Customer Service Chatbot red?" |
| Prompt injection inside charters | Instruction-like lines flagged at index time and removed before any prompt; charter text wrapped as data; number guard | "What are the risks of the Customer Service Chatbot?" (its charter contains a planted injection) |
| Personal data | Input guard refuses contact / personal requests | "What is the phone number of the HR Policy Copilot sponsor?" |
| Missing evidence | Exact fallback "I do not have that in the data provided" | "What are the risks of the Sales Forecast Model?" (no Risks section) |
| Undefined calculations | Only governed metrics; aggregates refused | "What is the average ROI across the portfolio?" |

## Evaluation

`python eval/run_eval.py`: scorecard golden test on both datasets (max difference 0, all statuses match), plus 15 labelled questions covering metric, narrative, mixed, no-answer and four guardrail types, checking route, status, required facts, forbidden content, cited section and absence of numbers in narrative text. Results in `eval/results.md`. Limitations are listed there.

## Assumptions

See `docs/assumptions.md`: months live in fractional months, ISO-first date parsing, A4 week rule, USD normalisation, plus the client clarification question.
