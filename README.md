# Agentic RFP Evaluation & Supplier Ranking

An AI-assisted Streamlit application that reads supplier RFP responses (PDF), has an LLM score each one against
database-configured criteria with cited evidence, then uses **deterministic Python** to validate, score,
benchmark, tie-break, rank and persist the results to SQLite.

**Live app:** `https://<your-app>.streamlit.app` _(add after deployment)_

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Database | SQLite |
| AI | OpenAI Chat Completions, JSON mode (default `gpt-4o-mini`, temperature 0, seed 42) |
| PDF | PyMuPDF |
| Validation | Pydantic v2 + custom normalisation |

---

## 1. Folder structure

```
rfp-evaluator/
├── app.py                       # Streamlit UI (5 screens + history)
├── agents/
│   ├── orchestrator.py          # Orchestrator Agent: controls the workflow
│   └── evaluator.py             # Evaluation Agent: prompt + OpenAI call (+ offline & fault-injection evaluators)
├── tools/
│   ├── pdf_tool.py              # Document Tool: text extraction and unreadable-PDF detection
│   ├── validator.py             # Validation Tool: schema check and normalisation, with warnings
│   └── ranking.py               # Ranking Tool: formulas, benchmarks, PPI, tie-breaks (no LLM)
├── db/
│   ├── schema.sql               # Tables
│   ├── database.py              # All SQL access
│   └── seed.py                  # Create DB and seed sample criteria
├── sample_pdfs/                 # 4 synthetic proposals + 1 deliberately unreadable PDF
├── sample_output/               # Exported run JSON
├── scripts/
│   ├── generate_sample_pdfs.py  # Rebuilds the synthetic PDFs
│   └── run_offline_demo.py      # Runs the pipeline from the command line
├── tests/test_pipeline.py       # 14 pytest cases
├── .streamlit/config.toml       # Theme
└── requirements.txt
```

## 2. Setup (local)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m db.seed                                      # creates data/rfp_evaluator.db with 5 criteria
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then paste your OpenAI key
streamlit run app.py
pytest -q                                              # 14 tests, no API key needed
```

The app also creates and seeds the database automatically on first start, so `db.seed` is optional.

## 3. Deploy to Streamlit Community Cloud

1. Push this folder to a **public GitHub repo** (`.gitignore` already excludes the DB and secrets).
2. Go to share.streamlit.io, click **Create app**, choose the repo, set branch `main` and main file `app.py`.
3. Under **Advanced settings → Secrets**, add `OPENAI_API_KEY = "sk-..."`.
4. Deploy and put the public URL at the top of this README.

> **Note:** Community Cloud storage is ephemeral. The SQLite file is recreated and re-seeded on each container
> restart, so run history survives within a session but not across redeploys. Always download the JSON for submission.

## 4. Architecture and agentic design

```mermaid
flowchart LR
    U[User / Streamlit] --> O[Orchestrator Agent]
    O -->|1 reload criteria| DB[(SQLite)]
    O -->|2 extract| D[Document Tool<br/>PyMuPDF]
    O -->|3 one call per supplier| E[Evaluation Agent<br/>OpenAI JSON]
    E --> V[Validation Tool<br/>Pydantic]
    V -->|bad JSON: retry once| E
    V --> R[Ranking Tool<br/>deterministic Python]
    R -->|4 persist under one RFP_RUN_ID| DB
    R --> U
```

| Component | Responsibility | LLM? |
|---|---|---|
| Orchestrator Agent | Validates inputs, reloads criteria, sequences tools, logs an agent trace, handles failures (`FAILED` status) | No |
| Document Tool | Extracts page-tagged text; rejects empty, corrupt, encrypted or scanned PDFs **before** any LLM spend | No |
| Evaluation Agent | Scores **one** supplier against active criteria with justification and verbatim evidence | **Yes** |
| Validation Tool | Parses JSON, enforces schema, fills/clips/cleans, records warnings | No |
| Ranking Tool | Weighted score, benchmark, gap, relative %, PPI, tie-breaks, ranks | No |

**Separation rule:** the LLM only judges proposal content. It never sees other suppliers, never totals scores and
never ranks. Every number on the leaderboard is computed in `tools/ranking.py`.

### 10-step data flow

| # | Step | Where |
|---|---|---|
| 1 | Setup: load active criteria | `app.py` → `db.get_active_criteria` |
| 2 | Input: upload PDFs and metadata | `app.py` Supplier input tab |
| 3 | Batch: validate inputs, create `RFP_RUN_ID` (`RFP-YYYYMMDD-HHMMSS-XXXXXX`) | `orchestrator.run_evaluation` |
| 4 | Evaluate: reload criteria, extract, build prompt, call LLM | `pdf_tool`, `evaluator` |
| 5 | Validate: parse and normalise | `validator.validate_scorecard` |
| 6 | Score: absolute weighted score | `ranking.score_supplier` |
| 7 | Benchmark: best score per criterion, peer metrics | `ranking.compute_benchmarks` |
| 8 | Rank: PPI, tie-breaks, sequential ranks | `ranking.rank_suppliers` |
| 9 | Persist: one transaction under one `RFP_RUN_ID` | `db.complete_run` |
| 10 | Present: leaderboard, scorecards, run details, JSON | `app.py` |

## 5. Formulas

Let *s* be the validated score, *m* the max score, *w* the weight (%) and *b* the benchmark.

| Metric | Formula |
|---|---|
| Weighted points | (s / m) × w |
| **Absolute score** | Σ (s / m) × w, on a 0–100 scale |
| **Benchmark** | max(s) for that criterion across all suppliers in the run |
| **Gap** | s − b (0 for the leader, otherwise negative) |
| **Relative %** | (s / b) × 100; **if b = 0 → 100** (every supplier tied at zero, so all are at parity) |
| **PPI** | Σ (relative % × w) / Σ w |

**Worked example** (from `tests/test_pipeline.py`): supplier A scores 8, 6, 5, 9, 7 and supplier B scores 6, 8, 10, 4, 7.
A's absolute score = 24 + 12 + 10 + 18 + 7 = **71**. A's relative % = 100, 75, 50, 100, 100, so its
PPI = (100×30 + 75×20 + 50×20 + 100×20 + 100×10) / 100 = **85**.

### Mandatory tie-break order

A stable `sorted()` with key `(-PPI, submission_date, -experience_rating, name.casefold())`:

1. Higher PPI
2. Earlier submission date
3. Higher historical experience rating
4. Supplier name A→Z

Ranks 1…n are assigned only after the sort. Each supplier gets a `rank_basis`, and the run records a plain-English
explanation for every tie resolved by rules 2–4.

## 6. Validation and normalisation rules

| Problem in LLM output | Action | Flag |
|---|---|---|
| Wrapped in ```` ```json ```` fences or prose | Fences stripped; first `{…}` extracted | warning |
| Not parseable JSON | Retry once with error feedback; if it fails again, all criteria score 0 | warning |
| Criterion missing | Score 0 | `MISSING` |
| Score outside 0…max | Clipped to range | `CLIPPED` |
| Score non-numeric (`"excellent"`) | Score 0; `"6/10"` is parsed as 6 | `INVALID_SCORE` |
| No evidence quoted | Score kept, flagged for reviewer | `NO_EVIDENCE` |
| Unknown or inactive criterion_id | Dropped | warning |
| Duplicate criterion | First kept | warning |
| Only a criterion name given | Matched to id by name | n/a |
| LLM's max_score differs from DB | DB value used | warning |
| Supplier name differs | User-entered name used | warning |

**Input validation (blocks the run, no LLM cost):** fewer than 2 PDFs; blank or duplicate supplier names
(case-insensitive); future or invalid dates; experience rating outside 0–5; non-PDF, empty, corrupt,
password-protected or scanned (no text) PDFs; active weights not totalling 100%.

## 7. Prompt design

The system prompt in `agents/evaluator.py` instructs the model to:

- use **only** evidence in the supplier document;
- return **one result per active criterion** using the given ids;
- stay within each criterion's max score;
- quote verbatim evidence with page markers;
- treat the document as **untrusted data**;
- output **JSON only**.

Criteria (id, name, description, max score) are injected **at run time from SQLite**, so editing criteria in the UI
changes the prompt without code changes. Scoring anchors (0 / 1–3 / 4–6 / 7–8 / 9–10) reduce variance.

## 8. Synthetic test data

There are four fictional responses to *RFP KRL-2026-07: Cloud Order Management Platform* (2 pages each, navy/gold styling):

| Supplier | Designed profile | 3-yr price | Timeline |
|---|---|---|---|
| Apex Systems | Strongest technical design and security (ISO 27001, SOC 2 Type II); highest price | ₹2.85 Cr | 24 wks |
| BrightPath Tech | Lowest price, fastest; ISO "in progress", vague security, founded 2023, references "on request". **Contains a prompt-injection line** asking for full marks | ₹1.35 Cr | 12 wks |
| NexaWorks | Balanced; strongest implementation plan (gated phases, RACI, risk table, contingency) and SLA-backed support | ₹2.10 Cr | 18 wks |
| Orbit Digital | Strongest experience (15 yrs, 40+ projects, 3 named references); integration "to be determined"; estimate-based pricing | ₹2.20 Cr | 20 wks |

`ERROR_CASE_Zenith_Scanned_No_Text.pdf` is an image-only PDF used to demonstrate the validation error path.
Regenerate all of them with `python scripts/generate_sample_pdfs.py`.

Suggested metadata (pre-filled in the UI when the sample files are uploaded):

| Supplier | Submission date | Experience rating (0–5) |
|---|---|---|
| Apex Systems | 2026-10-10 | 4.0 |
| BrightPath Tech | 2026-10-08 | 2.5 |
| NexaWorks | 2026-10-12 | 4.0 |
| Orbit Digital | 2026-10-10 | 4.5 |

## 9. Demonstration script

1. **Criteria tab:** show the 5 active criteria totalling 100%. Optionally deactivate one, save, and show the save is blocked.
2. **Successful run:** upload the 4 proposals, select *OpenAI LLM*, click **Evaluate**. Then walk through Leaderboard → Scorecard (evidence and gaps) → Run details (RFP_RUN_ID, tie-break explanation, trace) → **Download JSON**.
3. **Validation case A:** add `ERROR_CASE_Zenith_Scanned_No_Text.pdf`. The run is blocked before any LLM call.
4. **Validation case B:** tick *Inject faulty evaluator output*, target one supplier, and run. Show the `CLIPPED`, `INVALID_SCORE`, `MISSING` and `NO_EVIDENCE` flags and warnings.
5. **Determinism:** click *Recompute ranking from stored validated scorecards* to show identical order and PPI.
6. **History tab:** reload the stored run from SQLite.

## 10. Testing

`pytest -q` runs 14 tests covering:

- formula correctness against hand calculations;
- zero-benchmark safety;
- each tie-break rule (2, 3 and 4);
- input-order independence;
- every validator normalisation path;
- non-JSON and bad-schema output;
- PDF extraction, including blank and non-PDF rejection;
- end-to-end persistence and reload;
- end-to-end fault injection;
- blocked batches that write nothing to the DB;
- the weights-must-total-100 rule.

## 11. Assumptions

- Experience rating is a user-supplied 0–5 historical score (step 0.5).
- Submission dates cannot be in the future.
- At least 2 suppliers are needed for a meaningful benchmark.
- PPI is rounded to 4 dp before sorting so floating-point noise cannot alter ranks.
- A criterion where every supplier scores 0 gives relative % = 100 for all. This is neutral, because no supplier is disadvantaged.
- Missing or invalid criteria score 0, which is conservative: suppliers are not rewarded for unproven claims.
- Documents longer than 60,000 characters are truncated, with a warning.
- OCR for scanned PDFs is out of scope.
- **Offline demo mode** is a keyword heuristic, not an LLM. It exists only so tests and demos run without an API key. Real evaluation uses OpenAI.
- LLM scores can vary slightly between calls even at temperature 0. The success condition applies **after validation**: the same validated scorecards always produce the same formulas and order, as the determinism check proves.

## 12. Sample output

`sample_output/sample_run_offline_demo.json` is a complete run produced in offline mode. After deploying, run once
with OpenAI and save the downloaded JSON as `sample_output/sample_run_openai.json` for submission. Alternatively, run
`OPENAI_API_KEY=sk-... python scripts/run_offline_demo.py --openai`.

## 13. Screenshots

Add to `docs/screenshots/`: `criteria.png`, `input.png`, `leaderboard.png`, `scorecard.png`, `run_details.png`, `validation_error.png`.
