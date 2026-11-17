# PROGRESS: Nimbus Value Intelligence Assistant

Session log. Read at the start of every session; update at the end of every step.
Build order: architecture.md §10.

| Step | Status |
|---|---|
| 1 Skeleton | ✅ Done (2026-11-17) |
| 2 Practice data generator + answer key | ✅ Done (dataset supplied by the developer, 2026-11-17) |
| 3 Data pipeline + scorecard + analytics API | ⏭ Next (plan proposed) |
| 4 Dashboard v1 (no LLM) | |
| 5 Charter indexing + retrieval | |
| 6 Router + query engine + guards + fallback | |
| 7 Composer + number guard + `/ask` | |
| 8 Dashboard v2 (Ask panel) | |
| 9 Weekly report | |
| 10 Evaluation + README + assumptions log | |

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
Step 3 plan presented; waiting for the developer's "go".
