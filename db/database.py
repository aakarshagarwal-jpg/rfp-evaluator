"""SQLite persistence layer. All SQL lives here; no other module touches the DB."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "db" / "schema.sql"
DEFAULT_DB_PATH = Path(os.environ.get("RFP_DB_PATH", ROOT / "data" / "rfp_evaluator.db"))

DEFAULT_CRITERIA = [
    ("Technical Capability",
     "Solution architecture, integrations/APIs, scalability, performance and overall technical fit to the requirement.",
     30, 10),
    ("Implementation Plan",
     "Timeline realism, milestones, team structure and staffing, methodology, dependencies and delivery risk plan.",
     20, 10),
    ("Commercial Value",
     "Pricing clarity, total cost of ownership, payment terms, stated assumptions and exclusions.",
     20, 10),
    ("Security & Compliance",
     "Security controls, certifications (e.g. ISO 27001, SOC 2), data privacy, encryption, access control and auditability.",
     20, 10),
    ("Support & Experience",
     "Support model and SLAs, relevant similar projects, client references and years of experience.",
     10, 10),
]


@contextmanager
def connect(db_path: Path | str = DEFAULT_DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str = DEFAULT_DB_PATH, seed: bool = True) -> None:
    """Create tables (idempotent) and seed criteria if the table is empty."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        if seed:
            count = conn.execute("SELECT COUNT(*) FROM evaluation_criteria").fetchone()[0]
            if count == 0:
                conn.executemany(
                    "INSERT INTO evaluation_criteria (name, description, weight, max_score, is_active) "
                    "VALUES (?, ?, ?, ?, 1)",
                    DEFAULT_CRITERIA,
                )


# ---------------------------------------------------------------- criteria
def get_all_criteria(db_path=DEFAULT_DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM evaluation_criteria ORDER BY criterion_id").fetchall()
    return [dict(r) for r in rows]


def get_active_criteria(db_path=DEFAULT_DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT criterion_id, name, description, weight, max_score, is_active "
            "FROM evaluation_criteria WHERE is_active = 1 ORDER BY criterion_id"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_criteria(rows: list[dict], db_path=DEFAULT_DB_PATH) -> None:
    """Save edits from the UI. Rows with a criterion_id are updated; others inserted."""
    with connect(db_path) as conn:
        for r in rows:
            vals = (r["name"].strip(), r["description"].strip(), float(r["weight"]),
                    int(r["max_score"]), 1 if r["is_active"] else 0)
            if r.get("criterion_id"):
                conn.execute(
                    "UPDATE evaluation_criteria SET name=?, description=?, weight=?, max_score=?, "
                    "is_active=?, updated_at=datetime('now') WHERE criterion_id=?",
                    (*vals, int(r["criterion_id"])),
                )
            else:
                conn.execute(
                    "INSERT INTO evaluation_criteria (name, description, weight, max_score, is_active) "
                    "VALUES (?, ?, ?, ?, ?)", vals)


def validate_criteria(criteria: list[dict]) -> list[str]:
    """Return blocking errors for an active criteria set (empty list = OK)."""
    errors = []
    if not criteria:
        errors.append("No active criteria. Activate at least one criterion.")
        return errors
    total = round(sum(float(c["weight"]) for c in criteria), 6)
    if abs(total - 100.0) > 1e-6:
        errors.append(f"Active criteria weights total {total:g}%, but must total exactly 100%.")
    for c in criteria:
        if int(c["max_score"]) <= 0:
            errors.append(f"Criterion '{c['name']}' has a non-positive max score.")
        if float(c["weight"]) < 0:
            errors.append(f"Criterion '{c['name']}' has a negative weight.")
    return errors


# ---------------------------------------------------------------- runs
def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_run(rfp_run_id: str, evaluator: str, criteria: list[dict], db_path=DEFAULT_DB_PATH) -> str:
    created = utc_now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO rfp_runs (rfp_run_id, created_at, status, evaluator, criteria_json) "
            "VALUES (?, ?, 'RUNNING', ?, ?)",
            (rfp_run_id, created, evaluator, json.dumps(criteria)),
        )
    return created


def fail_run(rfp_run_id: str, message: str, db_path=DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE rfp_runs SET status='FAILED', error_message=? WHERE rfp_run_id=?",
                     (message[:2000], rfp_run_id))


def complete_run(run: dict, db_path=DEFAULT_DB_PATH) -> None:
    """Write every supplier row and the full run JSON in ONE transaction."""
    rid = run["rfp_run_id"]
    with connect(db_path) as conn:
        conn.execute("DELETE FROM supplier_results WHERE rfp_run_id=?", (rid,))
        conn.executemany(
            "INSERT INTO supplier_results (rfp_run_id, supplier_name, submission_date, experience_rating, "
            "absolute_score, ppi, final_rank, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(rid, s["supplier_name"], s["submission_date"], s["experience_rating"],
              s["absolute_score"], s["ppi"], s["final_rank"], json.dumps(s)) for s in run["suppliers"]],
        )
        conn.execute("UPDATE rfp_runs SET status='COMPLETED', run_json=? WHERE rfp_run_id=?",
                     (json.dumps(run), rid))


def list_runs(db_path=DEFAULT_DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT r.rfp_run_id, r.created_at, r.status, r.evaluator, "
            "COUNT(s.id) AS suppliers, r.error_message "
            "FROM rfp_runs r LEFT JOIN supplier_results s ON s.rfp_run_id = r.rfp_run_id "
            "GROUP BY r.rfp_run_id ORDER BY r.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def load_run(rfp_run_id: str, db_path=DEFAULT_DB_PATH) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT run_json FROM rfp_runs WHERE rfp_run_id=?", (rfp_run_id,)).fetchone()
    return json.loads(row["run_json"]) if row and row["run_json"] else None
