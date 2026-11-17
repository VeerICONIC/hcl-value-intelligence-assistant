# PROGRESS: Nimbus Value Intelligence Assistant

Session log. Read at the start of every session; update at the end of every step.
Build order: architecture.md §10.

| Step | Status |
|---|---|
| 1 Skeleton | ✅ Done (2026-11-17) |
| 2 Practice data generator + answer key | ✅ Done (dataset supplied by the developer, 2026-11-17) |
| 3 Data pipeline + scorecard + analytics API | ✅ Done (2026-11-17) |
| 4 Dashboard v1 (no LLM) | ✅ Done (sprint M1) |
| 5 Charter indexing + retrieval | ✅ Done (sprint M2) |
| 6 Router + query engine + guards + fallback | ✅ Done (sprint M2) |
| 7 Composer + number guard + `/ask` | ✅ Done (sprint M2, simplified) |
| 8 Dashboard v2 (Ask panel) | ✅ Done (sprint M2) |
| 9 Weekly report | ✅ Done (sprint M3) |
| 10 Evaluation + README + assumptions log | ✅ Done (sprint M4) |

---

## 2026-11-17: Step 1 Skeleton

### Done
- `CLAUDE.md` (principles, D1–D13, rules, doc map, commands), pinned `requirements.txt`, `.gitignore`, `.env.example`, `pytest.ini` (`live` marker, excluded by default).
- Folder structure per architecture.md §7. Packages only, no placeholder modules.
- `app/core/`: `config.py` (pydantic-settings, D2 defaults, derived Chroma collection name per D3, `FALLBACK_MESSAGE` constant), `logging.py`, `exceptions.py` (`NimbusError` hierarchy), `bedrock.py` (copied; + `aws_credentials_available()` local check).
- `app/schemas/`: all §6 contracts, unchanged.
- Infrastructure copied from the practice repo (`C:\Users\Veer\OneDrive\Desktop\HCl-Hackathon`): `app/charters/{embeddings,store,retriever}.py`, `app/charters/parsers/{base,markdown_parser,pdf_parser}.py`, `scripts/test_bedrock.py`.
- `GET /health` (no AWS by default; `?check_aws=true` for a local credential check), `app/main.py` app factory.
- `ui/dashboard.py`: Streamlit shell showing backend status via the API only (D13).
- Tests: 34 passing, all offline (settings, schemas, health, copied modules incl. Chroma round-trip + PDF/MD parsing, dashboard via `AppTest`).

### Decisions taken (approved in the Step 1 plan)
- **Helper code folded in, not copied:** the listed files imported 5 unlisted practice-repo modules. Only the needed pieces were moved into the destination files (Block/ParsedDocument → `parsers/base.py`; Embedder/EmbeddingError → `embeddings.py`; tokenize + hit dataclasses → `retriever.py`; parse errors → `core/exceptions.py`).
- **Store adapted to `CharterChunk`** (class renamed `CharterStore`): Doc Q&A bookkeeping removed; `score` is filled with cosine similarity on query and 0.0 otherwise (no contract change); `page=None` stored as -1 internally.
- `requirements.txt` pins the versions verified in the practice venv; new: `openpyxl==3.1.5`, `python-docx==1.2.0`.
- The dashboard reads `API_BASE_URL` from the environment instead of importing `app/` (strict D13; also avoids `sys.path` issues under `streamlit run`).

### Open points
- architecture.md §4 comment says the status ranges "overlap". They don't (Green and Red can't both hold), so check order has no effect. Harmless; fix the comment if desired.
- `ScorecardQuery.status_filter` can't express "Insufficient data". Revisit in Step 6 (contract change needs approval).
- For the Step 2 plan: define DQ-09's documented rule (WAU > licensed users); INR conversion rate for `"12.5 lakh"` (A5); `07/09/2026` must parse as dd/mm.
- Live Bedrock not exercised yet: run `scripts\test_bedrock.py --all` once credentials are signed in.

### Next
Step 2: practice dataset generator + answer key (plan first).

---

## 2026-11-17: Step 2 Practice dataset (supplied, not generated)

### Done
- The developer added the dataset: `data/` (8 initiatives) and `data_scale_40/` (40 initiatives), both produced by
  `scripts/generate_practice_data.py` (`--size N`) and checked by `scripts/verify_practice_data.py`. No generator was written in this session.
- **Source of truth for data is now `data/README.md` + `data/answer_key/planted_issues.json`.** The old architecture.md §9 examples were illustrations only.
- `docs/architecture.md` §9 rewritten to match: as-of date 2026-11-15, weeks from 2026-10-26, financials with `reported_roi_pct`,
  planted issues DQ-01..DQ-11 (with a/b/c sub-ids), scale-set `R-` issues, charters (PDF = INIT-003/INIT-008, DOCX = INIT-006,
  **no-Risks charter = INIT-003**, injection = INIT-005). A5 changed to "all money USD, no conversion".
- Verified: `python scripts/verify_practice_data.py data` and `... data_scale_40` both report max abs difference 0.00e+00.

### Decisions (answers from the developer)
- **DQ-09 WAU > licensed users:** flag, exclude, log. If it ever hits the first or latest week, that metric is `None` with a reason; never guess.
- **Currency:** everything is USD; only `USD '000` needs x1,000. The INR question is closed.
- **Dates:** numeric dates are day-first; parse ISO `YYYY-MM-DD` first (dateutil `dayfirst=True` misreads `2025-09-01`).

### Open points
- `scripts/generate_practice_data.py` imports `fpdf` (package `fpdf2`), which is not in `requirements.txt`; regenerating data fails until it is added.
- `data_scale_40/README.md` is a copy of the 8-initiative README (says "8 initiatives", "DQ-01 to DQ-11"); cosmetic.
- `expected_scorecard.csv` stores `months_live` rounded to 4 decimals while other metrics are full precision; the golden test must compare it at 4 dp.

### Next
Step 3: data pipeline + scorecard engine + analytics API (plan first).

---

## 2026-11-17: Folder move + Step 1 re-check

### Done
- Project moved to `C:\dev\hcl-value-intelligence-assistant` (OneDrive broke the venv); `.venv` recreated with Python 3.12.0.
- **Step 1 gap found and fixed:** the new venv only had the data libraries (no pydantic, FastAPI, pytest, chromadb, ...).
  Installed everything with `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- `requirements.txt`: added `python-dateutil==2.9.0.post0` and `fpdf2==2.9.0` (closes the fpdf2 open point above).
  **dateutil is pinned to 2.9.0.post0, not 4.0.0:** botocore 1.44.x requires `python-dateutil<3`, so 4.0.0 makes pip's
  resolver fail. The ISO-first date rule still applies on 2.9 (`dayfirst=True` misreads `2025-09-01` there too).
- Verified: `pytest` 34 passed; `from app.main import app` OK; `verify_practice_data.py` on `data` and `data_scale_40`
  both report max abs difference 0.00e+00.
- architecture.md §9 already matched `data/README.md` + `planted_issues.json` (done in the Step 2 entry); re-checked, no change needed.
- Data check for the Step 3 design: in both sets every initiative has at most one cumulative row per measure, and no
  initiative mixes cumulative and monthly cost rows; monthly rows are only `monthly_cost` in USD.

### Next
Step 3 plan approved ("go").

---

## 2026-11-17: Step 3 Data pipeline + scorecard + analytics API

### Done
- **Config (D10):** `config/metric_dictionary.yaml` (file/column aliases, ID format, date rules, as-of rule,
  number parsing, usage metric + financial measure aliases with roles, units with multipliers, basis values,
  reported-ROI tolerance), `config/initiatives.yaml` (canonical names for the 8 curated initiatives + acronyms),
  `config/status_rules.yaml` (thresholds). Validated at load by `app/core/yaml_config.py` (typos -> one readable error).
- **Pipeline** (`app/data/`): `loader.py` (reads everything as text, maps headers via config, keeps source row numbers),
  `normalize.py` (pure parsers: IDs, ISO-first dates, numbers with `$`/`,`/`k`, Decimal arithmetic),
  `cleaning.py` (all rules + financial roll-up), `changelog.py` (rule catalogue + effects filled from the final scorecard),
  `pipeline.py` (`run_pipeline`; writes `data/processed/{clean_*.csv, scorecard.csv, scorecard.json, change_log.csv, data_version.txt}`).
- **Scorecard** (`app/scorecard/`): `metrics.py` (one pure function per metric -> `MetricValue` with formula, inputs,
  source rows, display, note), `status.py` (Red, then Green, else Amber; "Insufficient data" when adoption/ROI missing),
  `engine.py`.
- **API:** `POST /pipeline/run` (optional `raw_dir`, must be inside the repo), `GET /scorecard`, `GET /data-quality`,
  `GET /usage`. Reads return 409 until a run. CLI: `scripts/build_scorecard.py`.
- **Golden result:** both `data/` and `data_scale_40/` reproduce `expected_scorecard.csv` exactly (all metrics,
  names, statuses; empty payback = `None`), with the same code and config. Every planted issue maps to a change-log
  entry for the right rule, file and initiative (see the R-DUP-INIT-029 note below).
- Tests: 127 passing (93 new): normalisers, metric formulas + status boundaries, 14 damaged-data cleaning tests,
  golden tests on both datasets, config-driven tests (renamed columns, new alias, new unit, edited thresholds,
  bad config), API tests.

### Decisions taken (approved in the Step 3 plan)
- **Contract addition:** `app/schemas/pipeline.py` (PipelineRunRequest/Response, ScorecardResponse, RuleSummary,
  DataQualityResponse, UsagePoint, UsageResponse). `ChangeLogEntry.rule_id` comment now names generic rule IDs;
  no field changed.
- **Rule IDs are generic** (`UNIT_SCALE`, `MONTHLY_ROLLUP`, ...; catalogue in `app/data/changelog.py`). The pipeline
  never sees `DQ-`/`R-` IDs; the planted-issue -> rule mapping lives in `tests/test_pipeline_golden.py`.
- **A4 tightened** (architecture.md §4, §11): first/latest week = portfolio-wide first/latest supplied week; a missing
  middle week is only flagged; a missing or excluded first/latest week -> metric `None` + reason.
- **ROI display** is signed percent (`+66.7%`, `0.0%` for exactly zero); the value stays a ratio. Payback with zero
  benefit displays "Not reached".
- New files beyond §7: `app/core/yaml_config.py`, `app/data/pipeline.py`, `app/api/routes/usage.py`,
  `app/schemas/pipeline.py`, `scripts/build_scorecard.py` (§7 updated).
- Defensive rules beyond the planted issues (tested on damaged copies): unknown measure, unparseable value, unknown
  initiative, conflicting duplicates, mixed cumulative/monthly basis, older cumulative report superseded, rows after
  the as-of date, negative money (excluded, not flipped), non-USD currency (not converted).
- Name repair: canonical name from config when listed; otherwise trim, and title-case all-lower-case names
  (keeps acronyms). That generic rule handles the 32 extra scale initiatives.
- A missing benefit or cost row gives `None` + reason (the throwaway verifier defaults benefit to 0; no initiative needs that).

### Open points
- **Answer-key defect (needs your decision):** `data_scale_40/answer_key/planted_issues.json` lists `R-DUP-INIT-029`,
  but the raw file has no duplicate for INIT-029. Cause: the generator queued a duplicate of INIT-029's week-2 row and
  then `R-MISS-INIT-029` deleted that row (`scripts/generate_practice_data.py` lines 346-358 add dups after misses and
  silently skip dropped rows). The scorecard is unaffected. The golden test lists it in `KNOWN_ANSWER_KEY_DEFECTS`, and a
  guard test fails if the defect disappears. Fix options: in the generator, skip `dup` on a row that `miss` removes
  (or apply `miss` first), then regenerate; or leave as is.
- Carried over: architecture.md §4 comment "ranges overlap"; `ScorecardQuery.status_filter` cannot express
  "Insufficient data" (Step 6); live Bedrock not yet exercised; `data_scale_40/README.md` is a copy of the 8-set README.

### Next
Step 4: Dashboard v1 (no LLM): sidebar with Run pipeline, overview tiles, scorecard table with drill-down, charts,
data-quality log (plan first).

---

## 2026-11-17: Demo sprint (M0-M4), developer-approved change of plan

The developer switched to sprint mode (under two hours to the demo): no "go" between steps, commit per milestone,
keep it simple. The R-DUP-INIT-029 generator fix was skipped (known-defect note kept). Note: the generator code
fix was already included in the Step 3 commit, but the data was NOT regenerated, so the guard test still holds.

### Done
- **M0 Bedrock:** `scripts/test_bedrock.py --all` -> FAIL, no AWS credentials signed in. `.env` sets
  `LLM_MODE=extractive` (new setting, also on `/health`). Bedrock paths (Titan + Chroma, Nova Converse) are
  implemented with automatic fallback, but were not exercised live.
- **M1 Dashboard v1** (`ui/dashboard.py`): sidebar (dataset, Run pipeline, Index charters, backend status), tiles,
  colour-coded scorecard + drill-down (formula, inputs, source rows), adoption chart with 30%/60% lines, ROI bars
  around zero, change log with rule filter.
- **M2 RAG + chat:** `app/charters/chunker.py` (md/pdf/docx -> one chunk per section, INIT id from title, PDF line
  fragments joined), `injection.py` (flag + strip), `index.py` (BM25 + preferred-section lookup; Titan/Chroma in
  bedrock mode). `app/orchestration/router.py` (rules), `guards.py` (personal data, number guard), `answer.py`
  (templates for metric answers, extractive or Nova narrative, exact fallback). `app/generation/llm.py` (Nova).
  Endpoints `POST /charters/index`, `POST /ask` (charters follow the pipeline's dataset). Chat section on the page.
- **M3 Weekly report:** `app/generation/report_writer.py` + `POST /report/weekly` (deterministic Markdown, Red then
  Amber with status reason and cited top charter risk; INIT-003 shows the fallback). Dashboard Generate + download.
- **M4:** `eval/questions.yaml` (12), `eval/run_eval.py` -> `eval/results.md` (12/12 pass; scorecard 56/56 and
  280/280 cells), `docs/assumptions.md`, `README.md`.
- Tests: 147 passing, all offline. Real uvicorn + streamlit startup verified.

### Decisions (sprint, developer-specified)
- `AskResponse` (route, status, answer, scorecard_sources, charter_sources, guard_notes, data_version) added in
  `app/schemas/answer.py` per the developer's /ask spec; the §6 `AnswerResponse` is not used yet.
- Metric answers never use the LLM (templates); narrative answers in extractive mode quote only digit-free charter
  sentences, so the number guard holds by construction.
- Router: "overview" words are ignored when a metric is asked (keeps "What is the adoption of X" a metric question).

### Open points (after the demo)
- Not done from the earlier review: change-log BEFORE/AFTER effects, restart survival of processed data,
  `docs/requirements_traceability.md`.
- Exercise Bedrock live after `aws login` (`LLM_MODE=bedrock`), then re-run `eval/run_eval.py`.
- architecture.md not yet updated for the sprint files (chunker, injection, index, router, guards, answer, report).
