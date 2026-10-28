"""Ranking Tool: deterministic Python only. No LLM involvement.

Formulas (w = criterion weight in %, s = validated score, m = max score, b = benchmark):
    weighted_points  = (s / m) * w
    absolute_score   = sum(weighted_points)                          -> 0..100
    benchmark (b)    = max(s) for the criterion across all suppliers in the run
    gap              = s - b                                        -> 0 for the leader, else negative
    relative_pct     = (s / b) * 100, or 100.0 when b == 0 (all suppliers tied at zero)
    PPI              = sum(relative_pct * w) / sum(w)                -> 0..100

Tie-break order (stable sort, then ranks 1..n):
    1) higher PPI  2) earlier submission date  3) higher experience rating  4) supplier name A->Z
"""
from __future__ import annotations

from datetime import date

PPI_DP = 4          # PPI rounded to 4 dp before comparison -> no floating-point "phantom" differences
SCORE_DP = 4

TIE_RULES = [
    "Higher PPI",
    "Earlier submission date",
    "Higher historical experience rating",
    "Supplier name (A→Z)",
]


def _r(x: float, dp: int = SCORE_DP) -> float:
    return round(float(x) + 0.0, dp)


def compute_benchmarks(scorecards: list[dict], criteria: list[dict]) -> dict[int, float]:
    bench = {}
    for c in criteria:
        cid = int(c["criterion_id"])
        scores = [r["score"] for sc in scorecards for r in sc["criteria"] if r["criterion_id"] == cid]
        bench[cid] = max(scores) if scores else 0.0
    return bench


def score_supplier(card: dict, criteria: list[dict], bench: dict[int, float]) -> dict:
    by_id = {r["criterion_id"]: r for r in card["criteria"]}
    total_w = sum(float(c["weight"]) for c in criteria)
    rows, absolute, ppi_num = [], 0.0, 0.0
    for c in sorted(criteria, key=lambda x: int(x["criterion_id"])):
        cid, w, m = int(c["criterion_id"]), float(c["weight"]), float(c["max_score"])
        r = by_id[cid]
        s, b = float(r["score"]), float(bench[cid])
        weighted = (s / m) * w
        rel = 100.0 if b == 0 else (s / b) * 100.0
        absolute += weighted
        ppi_num += rel * w
        rows.append({
            **r,
            "weight": w,
            "weighted_points": _r(weighted),
            "benchmark": b,
            "gap": _r(s - b),
            "relative_pct": _r(rel),
            "is_benchmark_leader": s == b,
        })
    ppi = ppi_num / total_w if total_w else 0.0
    return {"criteria": rows, "absolute_score": _r(absolute), "ppi": _r(ppi, PPI_DP)}


def sort_key(s: dict) -> tuple:
    return (
        -_r(s["ppi"], PPI_DP),
        date.fromisoformat(s["submission_date"]),
        -float(s["experience_rating"]),
        s["supplier_name"].casefold(),
        s["supplier_name"],          # final deterministic fallback for case-only differences
    )


def _deciding_rule(a: dict, b: dict) -> int:
    ka, kb = sort_key(a), sort_key(b)
    for i in range(4):
        if ka[i] != kb[i]:
            return i
    return 3


def rank_suppliers(scorecards: list[dict], suppliers_meta: list[dict], criteria: list[dict]) -> dict:
    """scorecards: validated cards; suppliers_meta: [{supplier_name, submission_date, experience_rating, ...}]."""
    meta = {m["supplier_name"]: m for m in suppliers_meta}
    bench = compute_benchmarks(scorecards, criteria)

    scored = []
    for card in scorecards:
        m = meta[card["supplier_name"]]
        calc = score_supplier(card, criteria, bench)
        scored.append({
            "supplier_name": card["supplier_name"],
            "submission_date": m["submission_date"],
            "experience_rating": float(m["experience_rating"]),
            "file_name": m.get("file_name"),
            "absolute_score": calc["absolute_score"],
            "ppi": calc["ppi"],
            "criteria": calc["criteria"],
            "risks": card.get("risks", []),
            "overall_summary": card.get("overall_summary", ""),
            "warnings": card.get("warnings", []),
        })

    ordered = sorted(scored, key=sort_key)
    explanations = []
    for i, s in enumerate(ordered, start=1):
        s["final_rank"] = i
        if i == 1:
            s["rank_basis"] = "Highest PPI" if len(ordered) == 1 or _deciding_rule(s, ordered[1]) == 0 \
                else f"Tied on PPI with {ordered[1]['supplier_name']}; placed first by: {TIE_RULES[_deciding_rule(s, ordered[1])]}"
            continue
        prev = ordered[i - 2]
        rule = _deciding_rule(prev, s)
        s["rank_basis"] = f"Below {prev['supplier_name']} by: {TIE_RULES[rule]}"
        if rule > 0:
            detail = {
                1: f"{prev['submission_date']} vs {s['submission_date']}",
                2: f"{prev['experience_rating']:g} vs {s['experience_rating']:g}",
                3: f"'{prev['supplier_name']}' vs '{s['supplier_name']}'",
            }[rule]
            explanations.append(
                f"{prev['supplier_name']} and {s['supplier_name']} tied on PPI ({s['ppi']:.4f}); "
                f"resolved by rule {rule + 1} – {TIE_RULES[rule]} ({detail}).")
    if not explanations:
        explanations.append("No PPI ties occurred; ranking determined by PPI alone (rule 1).")

    return {
        "benchmarks": [{"criterion_id": int(c["criterion_id"]), "criterion_name": c["name"],
                        "benchmark_score": bench[int(c["criterion_id"])],
                        "leaders": [s["supplier_name"] for s in ordered
                                    for r in s["criteria"]
                                    if r["criterion_id"] == int(c["criterion_id"]) and r["is_benchmark_leader"]]}
                       for c in criteria],
        "suppliers": ordered,
        "tie_break_order": TIE_RULES,
        "tie_break_explanations": explanations,
    }


def recompute_from_run(run: dict) -> dict:
    """Re-run ranking from a stored run's validated scorecards (determinism check)."""
    criteria = run["criteria"]
    cards = [{"supplier_name": s["supplier_name"],
              "criteria": [{k: r[k] for k in ("criterion_id", "criterion_name", "score", "max_score",
                                              "justification", "evidence", "validation_flags")}
                           for r in s["criteria"]],
              "risks": s.get("risks", []), "overall_summary": s.get("overall_summary", ""),
              "warnings": s.get("warnings", [])} for s in run["suppliers"]]
    meta = [{k: s[k] for k in ("supplier_name", "submission_date", "experience_rating", "file_name")}
            for s in run["suppliers"]]
    return rank_suppliers(cards, meta, criteria)
