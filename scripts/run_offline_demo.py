"""Run the full pipeline on the sample PDFs WITHOUT an API key and export the JSON.

    python scripts/run_offline_demo.py                 # offline heuristic evaluator
    OPENAI_API_KEY=sk-... python scripts/run_offline_demo.py --openai   # real LLM run
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.evaluator import OfflineDemoEvaluator, OpenAIEvaluator  # noqa: E402
from agents.orchestrator import SupplierInput, run_evaluation  # noqa: E402
from db import database as dbm  # noqa: E402

SUPPLIERS = [("Apex Systems", "Apex_Systems_RFP_Response.pdf", "2026-10-10", 4.0),
             ("BrightPath Tech", "BrightPath_Tech_RFP_Response.pdf", "2026-10-08", 2.5),
             ("NexaWorks", "NexaWorks_RFP_Response.pdf", "2026-10-12", 4.0),
             ("Orbit Digital", "Orbit_Digital_RFP_Response.pdf", "2026-10-10", 4.5)]

if __name__ == "__main__":
    dbm.init_db()
    use_openai = "--openai" in sys.argv
    ev = OpenAIEvaluator(os.environ["OPENAI_API_KEY"]) if use_openai else OfflineDemoEvaluator()
    inputs = [SupplierInput(n, d, e, f, (ROOT / "sample_pdfs" / f).read_bytes()) for n, f, d, e in SUPPLIERS]
    run = run_evaluation(inputs, ev, progress=lambda p, t: print(f"{p:5.0%}  {t}"))
    out = ROOT / "sample_output" / ("sample_run_openai.json" if use_openai else "sample_run_offline_demo.json")
    out.write_text(json.dumps(run, indent=2))
    print("\nLeaderboard")
    for r in run["leaderboard"]:
        print(f"  #{r['final_rank']} {r['supplier_name']:<16} abs={r['absolute_score']:6.2f}  PPI={r['ppi']:7.3f}")
    print(f"\nSaved {out}")
