"""Run:  pytest -q"""
import json
from pathlib import Path

import pytest

from agents.evaluator import FaultInjectingEvaluator, OfflineDemoEvaluator
from agents.orchestrator import InputValidationError, SupplierInput, run_evaluation
from db import database as dbm
from tools.pdf_tool import DocumentError, extract_text
from tools.ranking import rank_suppliers, recompute_from_run
from tools.validator import ParseError, validate_scorecard

ROOT = Path(__file__).resolve().parent.parent
PDFS = ROOT / "sample_pdfs"

CRITERIA = [
    {"criterion_id": 1, "name": "Technical Capability", "description": "", "weight": 30, "max_score": 10},
    {"criterion_id": 2, "name": "Implementation Plan", "description": "", "weight": 20, "max_score": 10},
    {"criterion_id": 3, "name": "Commercial Value", "description": "", "weight": 20, "max_score": 10},
    {"criterion_id": 4, "name": "Security & Compliance", "description": "", "weight": 20, "max_score": 10},
    {"criterion_id": 5, "name": "Support & Experience", "description": "", "weight": 10, "max_score": 10},
]


def card(name, scores):
    return validate_scorecard({"supplier_name": name, "criteria": [
        {"criterion_id": i + 1, "score": s, "justification": "j", "evidence": "e"} for i, s in enumerate(scores)]},
        CRITERIA, name)


def meta(name, d="2026-10-01", exp=3.0):
    return {"supplier_name": name, "submission_date": d, "experience_rating": exp}


# ------------------------------------------------------------------ formulas
def test_absolute_score_benchmark_gap_relative_ppi():
    res = rank_suppliers([card("A", [8, 6, 5, 9, 7]), card("B", [6, 8, 10, 4, 7])],
                         [meta("A"), meta("B")], CRITERIA)
    a = next(s for s in res["suppliers"] if s["supplier_name"] == "A")
    # absolute = .8*30 + .6*20 + .5*20 + .9*20 + .7*10 = 24+12+10+18+7 = 71
    assert a["absolute_score"] == pytest.approx(71.0)
    tech = a["criteria"][0]
    assert tech["benchmark"] == 8 and tech["gap"] == 0 and tech["relative_pct"] == 100
    impl = a["criteria"][1]
    assert impl["benchmark"] == 8 and impl["gap"] == -2 and impl["relative_pct"] == pytest.approx(75.0)
    # PPI = (100*30 + 75*20 + 50*20 + 100*20 + 100*10)/100 = 85
    assert a["ppi"] == pytest.approx(85.0)


def test_zero_benchmark_is_safe():
    res = rank_suppliers([card("A", [0, 5, 5, 5, 5]), card("B", [0, 5, 5, 5, 5])],
                         [meta("A"), meta("B")], CRITERIA)
    for s in res["suppliers"]:
        assert s["criteria"][0]["relative_pct"] == 100.0
        assert s["criteria"][0]["gap"] == 0


# ------------------------------------------------------------------ tie-breaks
@pytest.mark.parametrize("metas, expected, rule", [
    ([meta("Zeta", "2026-10-01"), meta("Alpha", "2026-10-05")], ["Zeta", "Alpha"], "rule 2"),
    ([meta("Zeta", "2026-10-01", 4.5), meta("Alpha", "2026-10-01", 3.0)], ["Zeta", "Alpha"], "rule 3"),
    ([meta("Zeta", "2026-10-01", 3.0), meta("Alpha", "2026-10-01", 3.0)], ["Alpha", "Zeta"], "rule 4"),
])
def test_tie_breaks(metas, expected, rule):
    cards = [card(m["supplier_name"], [7, 7, 7, 7, 7]) for m in metas]
    res = rank_suppliers(cards, metas, CRITERIA)
    assert [s["supplier_name"] for s in res["suppliers"]] == expected
    assert [s["final_rank"] for s in res["suppliers"]] == [1, 2]
    assert rule in res["tie_break_explanations"][0]


def test_ranking_is_order_independent():
    cards = [card("A", [8, 6, 5, 9, 7]), card("B", [6, 8, 10, 4, 7]), card("C", [7, 7, 7, 7, 7])]
    metas = [meta("A"), meta("B"), meta("C")]
    r1 = rank_suppliers(cards, metas, CRITERIA)
    r2 = rank_suppliers(cards[::-1], metas[::-1], CRITERIA)
    assert [(s["supplier_name"], s["ppi"]) for s in r1["suppliers"]] == \
           [(s["supplier_name"], s["ppi"]) for s in r2["suppliers"]]


# ------------------------------------------------------------------ validator
def test_validator_normalises_bad_output():
    raw = "```json\n" + json.dumps({"supplier_name": "X", "criteria": [
        {"criterion_id": 1, "score": 14, "evidence": "e", "justification": "j"},
        {"criterion_id": "2", "score": "seven", "evidence": "e"},
        {"criterion_id": 2, "score": 3, "evidence": "dup"},
        {"criterion_id": 3, "score": "6/10", "evidence": ""},
        {"criterion_id": 99, "score": 5},
        {"criterion_name": "security & compliance", "score": -2, "evidence": "e"},
    ]}) + "\n```"
    out = validate_scorecard(raw, CRITERIA, "X")
    scores = {r["criterion_id"]: (r["score"], r["validation_flags"]) for r in out["criteria"]}
    assert scores[1] == (10.0, ["CLIPPED"])
    assert scores[2] == (0.0, ["INVALID_SCORE"])
    assert scores[3] == (6.0, ["NO_EVIDENCE"])
    assert scores[4] == (0.0, ["CLIPPED"])
    assert scores[5] == (0.0, ["MISSING"])
    assert len(out["criteria"]) == 5
    assert any("unknown" in w for w in out["warnings"]) and any("Duplicate" in w for w in out["warnings"])


def test_validator_rejects_non_json():
    with pytest.raises(ParseError):
        validate_scorecard("I think the supplier is good.", CRITERIA, "X")


def test_validator_bad_schema_treated_as_missing():
    out = validate_scorecard({"criteria": "oops"}, CRITERIA, "X")
    assert all(r["validation_flags"] == ["MISSING"] for r in out["criteria"])


# ------------------------------------------------------------------ document tool
def test_pdf_extraction_and_blank_pdf_rejected():
    doc = extract_text((PDFS / "NexaWorks_RFP_Response.pdf").read_bytes(), "NexaWorks.pdf")
    assert "SAP" in doc.text and doc.page_count >= 2
    with pytest.raises(DocumentError):
        extract_text((PDFS / "ERROR_CASE_Zenith_Scanned_No_Text.pdf").read_bytes(), "Zenith.pdf")
    with pytest.raises(DocumentError):
        extract_text(b"hello", "fake.pdf")


# ------------------------------------------------------------------ end-to-end (offline evaluator)
def _inputs():
    rows = [("Apex Systems", "Apex_Systems_RFP_Response.pdf", "2026-10-10", 4.0),
            ("BrightPath Tech", "BrightPath_Tech_RFP_Response.pdf", "2026-10-08", 2.5),
            ("NexaWorks", "NexaWorks_RFP_Response.pdf", "2026-10-12", 4.0),
            ("Orbit Digital", "Orbit_Digital_RFP_Response.pdf", "2026-10-10", 4.5)]
    return [SupplierInput(n, d, e, f, (PDFS / f).read_bytes()) for n, f, d, e in rows]


def test_end_to_end_persists_and_is_deterministic(tmp_path):
    db = tmp_path / "t.db"
    dbm.init_db(db)
    run = run_evaluation(_inputs(), OfflineDemoEvaluator(), db_path=db)
    assert [s["final_rank"] for s in run["suppliers"]] == [1, 2, 3, 4]
    stored = dbm.load_run(run["rfp_run_id"], db)
    assert stored["leaderboard"] == run["leaderboard"]
    assert dbm.list_runs(db)[0]["suppliers"] == 4
    again = recompute_from_run(stored)
    assert [s["supplier_name"] for s in again["suppliers"]] == [s["supplier_name"] for s in run["suppliers"]]


def test_end_to_end_fault_injection(tmp_path):
    db = tmp_path / "t.db"
    dbm.init_db(db)
    run = run_evaluation(_inputs(), FaultInjectingEvaluator(OfflineDemoEvaluator(), "Orbit Digital"), db_path=db)
    orbit = next(s for s in run["suppliers"] if s["supplier_name"] == "Orbit Digital")
    flags = {f for r in orbit["criteria"] for f in r["validation_flags"]}
    assert {"CLIPPED", "INVALID_SCORE", "NO_EVIDENCE", "MISSING"} <= flags


def test_input_validation_blocks_bad_batch(tmp_path):
    db = tmp_path / "t.db"
    dbm.init_db(db)
    bad = _inputs()[:2]
    bad[1].supplier_name = "apex systems"         # duplicate (case-insensitive)
    bad[0].experience_rating = 9                  # out of range
    with pytest.raises(InputValidationError) as e:
        run_evaluation(bad, OfflineDemoEvaluator(), db_path=db)
    assert len(e.value.errors) == 2
    blank = _inputs()[:2] + [SupplierInput("Zenith", "2026-10-01", 3, "z.pdf",
                                           (PDFS / "ERROR_CASE_Zenith_Scanned_No_Text.pdf").read_bytes())]
    with pytest.raises(InputValidationError):
        run_evaluation(blank, OfflineDemoEvaluator(), db_path=db)
    assert dbm.list_runs(db) == []                # nothing persisted, no LLM spend


def test_weights_must_total_100(tmp_path):
    db = tmp_path / "t.db"
    dbm.init_db(db)
    rows = dbm.get_all_criteria(db)
    rows[0]["is_active"] = 0
    dbm.upsert_criteria(rows, db)
    with pytest.raises(InputValidationError, match="total 70"):
        run_evaluation(_inputs(), OfflineDemoEvaluator(), db_path=db)
