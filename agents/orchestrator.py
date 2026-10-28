"""Orchestrator Agent: controls the workflow and calls each tool/agent in a fixed order.

    validate inputs -> reload criteria -> extract (Document Tool) -> create run
    -> per supplier: Evaluation Agent -> Validation Tool (retry once on bad JSON)
    -> Ranking Tool -> persist (one RFP_RUN_ID) -> return complete result
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable

from db import database as dbm
from tools.pdf_tool import DocumentError, extract_text
from tools.ranking import rank_suppliers
from tools.validator import ParseError, fallback_scorecard, validate_scorecard

EXPERIENCE_MIN, EXPERIENCE_MAX = 0.0, 5.0
MIN_SUPPLIERS = 2


class InputValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class SupplierInput:
    supplier_name: str
    submission_date: str | date
    experience_rating: float
    file_name: str
    pdf_bytes: bytes


def new_run_id() -> str:
    return f"RFP-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6].upper()}"


def validate_inputs(inputs: list[SupplierInput]) -> list[str]:
    errors = []
    if len(inputs) < MIN_SUPPLIERS:
        errors.append(f"Upload at least {MIN_SUPPLIERS} supplier PDFs; peer benchmarking needs a comparison set.")
    seen = {}
    for i, s in enumerate(inputs, start=1):
        label = s.file_name or f"Supplier #{i}"
        name = (s.supplier_name or "").strip()
        if not name:
            errors.append(f"{label}: supplier name is required.")
        elif name.casefold() in seen:
            errors.append(f"{label}: supplier name '{name}' duplicates {seen[name.casefold()]}.")
        else:
            seen[name.casefold()] = label
        try:
            d = s.submission_date if isinstance(s.submission_date, date) else date.fromisoformat(str(s.submission_date))
            if d > date.today():
                errors.append(f"{label}: submission date {d} is in the future.")
        except (TypeError, ValueError):
            errors.append(f"{label}: submission date must be YYYY-MM-DD.")
        try:
            r = float(s.experience_rating)
            if not EXPERIENCE_MIN <= r <= EXPERIENCE_MAX:
                errors.append(f"{label}: experience rating must be between {EXPERIENCE_MIN:g} and {EXPERIENCE_MAX:g}.")
        except (TypeError, ValueError):
            errors.append(f"{label}: experience rating must be a number.")
        if not s.file_name.lower().endswith(".pdf"):
            errors.append(f"{label}: only PDF files are accepted.")
    return errors


def run_evaluation(inputs: list[SupplierInput], evaluator, db_path=dbm.DEFAULT_DB_PATH,
                   progress: Callable[[float, str], None] | None = None) -> dict:
    trace: list[dict] = []
    t0 = time.perf_counter()

    def log(step: str, actor: str, detail: str):
        trace.append({"step": step, "actor": actor, "detail": detail,
                      "elapsed_s": round(time.perf_counter() - t0, 2)})
        if progress:
            progress(min(len(trace) / (4 + 2 * len(inputs)), 0.99), f"{step}: {detail}")

    # 1. Input validation (no LLM spend if this fails)
    errors = validate_inputs(inputs)
    if errors:
        raise InputValidationError(errors)
    for s in inputs:
        s.supplier_name = s.supplier_name.strip()
        s.submission_date = str(s.submission_date if isinstance(s.submission_date, date)
                                else date.fromisoformat(str(s.submission_date)))
    log("Input", "Orchestrator", f"{len(inputs)} supplier submissions validated")

    # 2. Reload active criteria at run time (never hard-coded in the prompt)
    criteria = dbm.get_active_criteria(db_path)
    crit_errors = dbm.validate_criteria(criteria)
    if crit_errors:
        raise InputValidationError(crit_errors)
    log("Setup", "SQLite", f"{len(criteria)} active criteria loaded (weights total 100%)")

    # 3. Document Tool – extract everything before spending on the LLM
    docs, doc_errors, run_warnings = {}, [], []
    for s in inputs:
        try:
            d = extract_text(s.pdf_bytes, s.file_name)
            docs[s.supplier_name] = d
            run_warnings.extend(d.warnings)
        except DocumentError as exc:
            doc_errors.append(str(exc))
    if doc_errors:
        raise InputValidationError(doc_errors)
    log("Extract", "Document Tool", f"text extracted from {len(docs)} PDFs")

    # 4. Batch
    run_id = new_run_id()
    created_at = dbm.create_run(run_id, evaluator.name, criteria, db_path)
    log("Batch", "Orchestrator", f"run {run_id} created")

    try:
        # 5. Evaluate + Validate (each supplier independently)
        cards = []
        for s in inputs:
            doc = docs[s.supplier_name]
            raw = evaluator.evaluate(s.supplier_name, doc.text, criteria)
            log("Evaluate", "Evaluation Agent", f"{s.supplier_name} scored by {evaluator.name}")
            try:
                card = validate_scorecard(raw, criteria, s.supplier_name)
            except ParseError as first:
                log("Validate", "Validation Tool", f"{s.supplier_name}: {first} – retrying once")
                raw = evaluator.evaluate(s.supplier_name, doc.text, criteria, retry_feedback=str(first))
                try:
                    card = validate_scorecard(raw, criteria, s.supplier_name)
                    card["warnings"].insert(0, f"[{s.supplier_name}] First response invalid ({first}); retry succeeded.")
                except ParseError as second:
                    card = fallback_scorecard(criteria, s.supplier_name, str(second))
            log("Validate", "Validation Tool",
                f"{s.supplier_name}: {len(card['warnings'])} warning(s) after normalisation")
            cards.append(card)

        # 6-8. Score, Benchmark, Rank – deterministic Python only
        meta = [{"supplier_name": s.supplier_name, "submission_date": s.submission_date,
                 "experience_rating": float(s.experience_rating), "file_name": s.file_name} for s in inputs]
        ranking = rank_suppliers(cards, meta, criteria)
        log("Rank", "Ranking Tool", "absolute scores, benchmarks, PPI and tie-breaks computed")

        all_warnings = run_warnings + [w for c in cards for w in c["warnings"]]
        run = {
            "rfp_run_id": run_id,
            "created_at": created_at,
            "status": "COMPLETED",
            "evaluator": evaluator.name,
            "criteria": [{k: c[k] for k in ("criterion_id", "name", "description", "weight", "max_score")}
                         for c in criteria],
            "formulas": {
                "absolute_score": "sum((score / max_score) * weight)",
                "benchmark": "max(score) per criterion across suppliers in this run",
                "gap": "score - benchmark",
                "relative_pct": "(score / benchmark) * 100; 100 if benchmark == 0",
                "ppi": "sum(relative_pct * weight) / sum(weight)",
            },
            "benchmarks": ranking["benchmarks"],
            "leaderboard": [{k: s[k] for k in ("final_rank", "supplier_name", "absolute_score", "ppi",
                                               "submission_date", "experience_rating")}
                            for s in ranking["suppliers"]],
            "suppliers": ranking["suppliers"],
            "tie_break_order": ranking["tie_break_order"],
            "tie_break_explanations": ranking["tie_break_explanations"],
            "warnings": all_warnings,
            "documents": [{"supplier_name": n, "file_name": d.file_name, "pages": d.page_count,
                           "characters": d.char_count} for n, d in docs.items()],
        }
        log("Persist", "SQLite", f"{len(run['suppliers'])} supplier rows written under {run_id}")
        run["trace"] = trace
        dbm.complete_run(run, db_path)
        if progress:
            progress(1.0, "Completed")
        return run
    except Exception as exc:
        dbm.fail_run(run_id, f"{type(exc).__name__}: {exc}", db_path)
        raise
