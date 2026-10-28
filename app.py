"""Agentic RFP Evaluation & Supplier Ranking: Streamlit UI."""
from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd
import streamlit as st

from agents.evaluator import FaultInjectingEvaluator, OfflineDemoEvaluator, OpenAIEvaluator
from agents.orchestrator import (EXPERIENCE_MAX, EXPERIENCE_MIN, InputValidationError, SupplierInput,
                                 run_evaluation, validate_inputs)
from db import database as dbm
from tools.ranking import recompute_from_run

st.set_page_config(page_title="Agentic RFP Evaluator", page_icon="📑", layout="wide")


@st.cache_resource
def _init():
    dbm.init_db()
    return True


_init()
st.session_state.setdefault("run", None)

# Defaults for the bundled sample PDFs so the demo is quick to set up (editable in the UI).
SAMPLE_META = {
    "apex systems": ("2026-10-10", 4.0),
    "brightpath tech": ("2026-10-08", 2.5),
    "nexaworks": ("2026-10-12", 4.0),
    "orbit digital": ("2026-10-10", 4.5),
}


def guess_name(file_name: str) -> str:
    stem = re.sub(r"\.pdf$", "", file_name, flags=re.I)
    stem = re.sub(r"(?i)_?(rfp|response|proposal|final|v\d+)\b", "", stem)
    return re.sub(r"[_\-]+", " ", stem).strip() or file_name


def get_api_key() -> str:
    try:
        return st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        return ""


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("⚙️ Evaluator")
    mode = st.radio("Evaluation engine", ["OpenAI LLM", "Offline demo (no API key)"],
                    help="Offline demo is a keyword heuristic for testing the pipeline. Use OpenAI for real evaluation.")
    api_key, model = "", ""
    if mode == "OpenAI LLM":
        secret_key = get_api_key()
        if secret_key:
            st.success("API key loaded from secrets.")
            api_key = secret_key
        else:
            api_key = st.text_input("OpenAI API key", type="password", help="Not stored. Prefer Streamlit secrets.")
        model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"], index=0)
    st.divider()
    inject = st.checkbox("Inject faulty evaluator output (validation demo)",
                        help="Corrupts one supplier's JSON: code fences, out-of-range score, non-numeric score, "
                             "missing criterion, unknown criterion id, missing evidence.")
    st.caption("Temperature 0 and a fixed seed are used for OpenAI calls. Arithmetic, benchmarks, tie-breaks "
               "and ranks are computed by deterministic Python, never by the LLM.")

st.title("📑 Agentic RFP Evaluation & Supplier Ranking")
st.caption("LLM judges proposal content → Python validates, scores, benchmarks, ranks, and persists to SQLite.")

tabs = st.tabs(["① Criteria", "② Supplier input", "③ Leaderboard", "④ Scorecards", "⑤ Run details", "🗂 History"])

# ------------------------------------------------------------------ 1. Criteria
with tabs[0]:
    active = dbm.get_active_criteria()
    total = sum(c["weight"] for c in active)
    c1, c2, c3 = st.columns(3)
    c1.metric("Active criteria", len(active))
    c2.metric("Total weight", f"{total:g}%")
    c3.metric("Status", "Valid ✅" if abs(total - 100) < 1e-6 else "Invalid ❌")
    st.dataframe(pd.DataFrame(active)[["criterion_id", "name", "weight", "max_score", "description"]]
                 .rename(columns={"criterion_id": "ID", "name": "Criterion", "weight": "Weight %",
                                  "max_score": "Max score", "description": "What the LLM inspects"}),
                 hide_index=True, width="stretch")
    for e in dbm.validate_criteria(active):
        st.error(e)

    with st.expander("✏️ Edit criteria (activate, deactivate, change weights)"):
        all_c = pd.DataFrame(dbm.get_all_criteria())[["criterion_id", "name", "description", "weight",
                                                      "max_score", "is_active"]]
        all_c["is_active"] = all_c["is_active"].astype(bool)
        edited = st.data_editor(all_c, num_rows="dynamic", hide_index=True, width="stretch",
                                disabled=["criterion_id"], key="crit_editor",
                                column_config={"weight": st.column_config.NumberColumn("weight %", min_value=0, max_value=100),
                                               "max_score": st.column_config.NumberColumn(min_value=1, step=1),
                                               "is_active": st.column_config.CheckboxColumn("active")})
        if st.button("Save criteria", type="primary"):
            rows = edited.dropna(subset=["name"]).to_dict("records")
            for r in rows:
                r["criterion_id"] = None if pd.isna(r.get("criterion_id")) else int(r["criterion_id"])
                r["description"] = r.get("description") or ""
                r["weight"] = 0 if pd.isna(r.get("weight")) else r["weight"]
                r["max_score"] = 10 if pd.isna(r.get("max_score")) else r["max_score"]
            errs = dbm.validate_criteria([r for r in rows if r["is_active"]])
            if errs:
                for e in errs:
                    st.error(e)
            else:
                try:
                    dbm.upsert_criteria(rows)
                    st.success("Criteria saved. The next run will use them automatically.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save: {exc}")

# ------------------------------------------------------------------ 2. Supplier input
with tabs[1]:
    files = st.file_uploader("Upload supplier RFP responses (PDF)", type=["pdf"], accept_multiple_files=True)
    inputs: list[SupplierInput] = []
    if files:
        st.markdown("**Supplier metadata**")
        for f in files:
            key = f"{f.name}-{f.size}"
            nm = guess_name(f.name)
            d_default, r_default = SAMPLE_META.get(nm.lower(), (str(date.today()), 3.0))
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
                c1.markdown(f"📄 `{f.name}`  \n{f.size / 1024:,.0f} KB")
                name = c2.text_input("Supplier name", value=nm, key=f"n-{key}")
                sub = c3.date_input("Submission date", value=date.fromisoformat(d_default),
                                    max_value=date.today(), key=f"d-{key}")
                exp = c4.number_input(f"Experience rating ({EXPERIENCE_MIN:g}–{EXPERIENCE_MAX:g})",
                                      min_value=EXPERIENCE_MIN, max_value=EXPERIENCE_MAX, value=r_default,
                                      step=0.5, key=f"e-{key}")
                inputs.append(SupplierInput(name, sub, exp, f.name, f.getvalue()))

        errs = validate_inputs(inputs)
        for e in errs:
            st.warning(e)
        target = None
        if inject and inputs:
            target = st.selectbox("Supplier to receive faulty evaluator output", [s.supplier_name for s in inputs])

        ready = not errs and (mode != "OpenAI LLM" or bool(api_key))
        if mode == "OpenAI LLM" and not api_key:
            st.info("Enter an OpenAI API key in the sidebar (or add OPENAI_API_KEY to Streamlit secrets).")
        if st.button("🚀 Evaluate suppliers", type="primary", disabled=not ready):
            base = OpenAIEvaluator(api_key, model) if mode == "OpenAI LLM" else OfflineDemoEvaluator()
            evaluator = FaultInjectingEvaluator(base, target) if inject and target else base
            bar = st.progress(0.0, text="Starting…")
            try:
                run = run_evaluation(inputs, evaluator, progress=lambda p, t: bar.progress(p, text=t))
                st.session_state["run"] = run
                n_warn = len(run["warnings"])
                st.success(f"Run **{run['rfp_run_id']}** completed. Winner: "
                           f"**{run['leaderboard'][0]['supplier_name']}**. {n_warn} validation warning(s). "
                           "Open the Leaderboard tab.")
            except InputValidationError as exc:
                bar.empty()
                st.error("Run blocked by validation:")
                for e in exc.errors:
                    st.error(e)
            except Exception as exc:
                bar.empty()
                st.error(f"Run failed and was marked FAILED in the database: {type(exc).__name__}: {exc}")
    else:
        st.info("Upload at least two supplier PDFs. Sample proposals are in the repository's `sample_pdfs/` folder.")

run = st.session_state["run"]

# ------------------------------------------------------------------ 3. Leaderboard
with tabs[2]:
    if not run:
        st.info("No run yet. Evaluate suppliers or load a past run from History.")
    else:
        top = run["leaderboard"][0]
        c1, c2, c3 = st.columns(3)
        c1.metric("🏆 Rank 1", top["supplier_name"])
        c2.metric("PPI", f"{top['ppi']:.2f}")
        c3.metric("Absolute score", f"{top['absolute_score']:.2f} / 100")
        lb = pd.DataFrame([{**r, "rank_basis": s["rank_basis"]}
                           for r, s in zip(run["leaderboard"], run["suppliers"])])
        st.dataframe(lb.rename(columns={"final_rank": "Rank", "supplier_name": "Supplier",
                                        "absolute_score": "Absolute score", "ppi": "PPI",
                                        "submission_date": "Submission date",
                                        "experience_rating": "Experience", "rank_basis": "Rank basis"}),
                     hide_index=True, width="stretch",
                     column_config={"Absolute score": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=100),
                                    "PPI": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=100)})
        st.markdown("**Criterion scores vs benchmark**")
        matrix = {s["supplier_name"]: {r["criterion_name"]: r["score"] for r in s["criteria"]} for s in run["suppliers"]}
        mdf = pd.DataFrame(matrix).T
        mdf.loc["Benchmark (best)"] = {b["criterion_name"]: b["benchmark_score"] for b in run["benchmarks"]}
        st.dataframe(mdf, width="stretch")
        st.bar_chart(lb.set_index("supplier_name")[["absolute_score", "ppi"]], stack=False)

# ------------------------------------------------------------------ 4. Scorecards
with tabs[3]:
    if not run:
        st.info("No run yet.")
    else:
        names = [s["supplier_name"] for s in run["suppliers"]]
        pick = st.selectbox("Supplier", names, format_func=lambda n: f"#{names.index(n) + 1}  {n}")
        s = next(x for x in run["suppliers"] if x["supplier_name"] == pick)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Rank", s["final_rank"])
        c2.metric("Absolute score", f"{s['absolute_score']:.2f}")
        c3.metric("PPI", f"{s['ppi']:.2f}")
        c4.metric("Warnings", len(s["warnings"]))
        st.caption(s["rank_basis"])
        df = pd.DataFrame(s["criteria"])[["criterion_name", "score", "max_score", "benchmark", "gap",
                                          "relative_pct", "weight", "weighted_points", "validation_flags"]]
        df["validation_flags"] = df["validation_flags"].apply(lambda f: ", ".join(f) or "OK")
        st.dataframe(df.rename(columns={"criterion_name": "Criterion", "score": "Score", "max_score": "Max",
                                        "benchmark": "Benchmark", "gap": "Gap", "relative_pct": "Relative %",
                                        "weight": "Weight %", "weighted_points": "Weighted pts",
                                        "validation_flags": "Validation"}),
                     hide_index=True, width="stretch")
        for r in s["criteria"]:
            with st.expander(f"{r['criterion_name']}: {r['score']:g}/{r['max_score']:g}  (gap {r['gap']:+g})"):
                st.markdown(f"**Justification:** {r['justification']}")
                st.markdown(f"**Evidence:** _{r['evidence'] or 'None cited'}_")
        st.markdown("**Overall summary**")
        st.write(s["overall_summary"])
        if s["risks"]:
            st.markdown("**Risks flagged by the evaluator**")
            for rk in s["risks"]:
                st.markdown(f"- {rk}")
        for w in s["warnings"]:
            st.warning(w)

# ------------------------------------------------------------------ 5. Run details
with tabs[4]:
    if not run:
        st.info("No run yet.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("RFP_RUN_ID", run["rfp_run_id"])
        c2.metric("Status", run["status"])
        c3.metric("Evaluator", run["evaluator"])
        st.caption(f"Created {run['created_at']} (UTC)")

        st.subheader("Tie-break rules")
        st.markdown(" → ".join(f"**{i + 1}.** {r}" for i, r in enumerate(run["tie_break_order"])))
        for e in run["tie_break_explanations"]:
            st.info(e)

        st.subheader(f"Validation warnings ({len(run['warnings'])})")
        if run["warnings"]:
            for w in run["warnings"]:
                st.warning(w)
        else:
            st.success("No warnings: every evaluator response passed validation unchanged.")

        st.subheader("Formulas")
        st.json(run["formulas"])
        st.subheader("Agent trace")
        st.dataframe(pd.DataFrame(run.get("trace", [])), hide_index=True, width="stretch")

        st.subheader("Determinism check")
        if st.button("Recompute ranking from stored validated scorecards"):
            re_run = recompute_from_run(run)
            a = [(s["supplier_name"], s["ppi"], s["final_rank"]) for s in run["suppliers"]]
            b = [(s["supplier_name"], s["ppi"], s["final_rank"]) for s in re_run["suppliers"]]
            if a == b:
                st.success("Identical order, PPI and ranks reproduced.")
            else:
                st.error(f"Mismatch: {a} vs {b}")

        st.download_button("⬇️ Download complete result (JSON)", json.dumps(run, indent=2),
                           file_name=f"{run['rfp_run_id']}.json", mime="application/json", type="primary")

# ------------------------------------------------------------------ History
with tabs[5]:
    runs = dbm.list_runs()
    if not runs:
        st.info("No runs stored yet.")
    else:
        st.dataframe(pd.DataFrame(runs), hide_index=True, width="stretch")
        done = [r["rfp_run_id"] for r in runs if r["status"] == "COMPLETED"]
        if done:
            rid = st.selectbox("Load a completed run", done, key="history_pick")
            if st.button("Load run"):
                st.session_state["run"] = dbm.load_run(rid)
                st.rerun()
