-- Agentic RFP Evaluator: SQLite schema
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS evaluation_criteria (
    criterion_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    description   TEXT    NOT NULL,
    weight        REAL    NOT NULL CHECK (weight >= 0 AND weight <= 100),
    max_score     INTEGER NOT NULL DEFAULT 10 CHECK (max_score > 0),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rfp_runs (
    rfp_run_id    TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    evaluator     TEXT,
    criteria_json TEXT,              -- snapshot of criteria used for this run
    run_json      TEXT,              -- complete exported result
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS supplier_results (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    rfp_run_id         TEXT    NOT NULL REFERENCES rfp_runs(rfp_run_id) ON DELETE CASCADE,
    supplier_name      TEXT    NOT NULL,
    submission_date    TEXT    NOT NULL,
    experience_rating  REAL    NOT NULL,
    absolute_score     REAL,
    ppi                REAL,
    final_rank         INTEGER,
    result_json        TEXT    NOT NULL,
    UNIQUE (rfp_run_id, supplier_name)
);

CREATE INDEX IF NOT EXISTS idx_results_run ON supplier_results(rfp_run_id);
