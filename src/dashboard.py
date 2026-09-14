"""
Streamlit dashboard for the Industrial Multi-Agent Guardian project.

Reads directly from the SQLite log (src/db.py) - this module contains
NO decision logic and NO LLM calls. It is purely a read-only observability
layer over what the Planner/Resource/Guardrail agents already did.

Run with: streamlit run src/dashboard.py
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so "src.db" resolves correctly
# regardless of how Streamlit invokes this script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from src.db import init_db, get_all_llm_calls, get_all_allocation_decisions

st.set_page_config(page_title="Industrial Multi-Agent Guardian", layout="wide")

init_db()

st.title("🏭 Industrial Multi-Agent Guardian — Dashboard")
st.caption(
    "Monitoring the LLM Planner/Resource agents and the deterministic, "
    "rule-based Guardrail layer that has final authority over every decision."
)

if st.button("🔄 Refresh"):
    st.rerun()

decisions = get_all_allocation_decisions()
llm_calls = get_all_llm_calls()

decisions_df = pd.DataFrame(decisions)
llm_calls_df = pd.DataFrame(llm_calls)

# --- Top-level metrics --------------------------------------------------

total_decisions = len(decisions_df)
approved_count = int((decisions_df["status"] == "approved").sum()) if total_decisions else 0
rejected_count = total_decisions - approved_count
approval_rate = (approved_count / total_decisions * 100) if total_decisions else 0.0

total_llm_calls = len(llm_calls_df)
total_tokens = (
    int(llm_calls_df["prompt_tokens"].sum() + llm_calls_df["completion_tokens"].sum())
    if total_llm_calls else 0
)
total_cost = float(llm_calls_df["estimated_cost_usd"].sum()) if total_llm_calls else 0.0

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Total Decisions", total_decisions)
col2.metric("Approved", approved_count)
col3.metric("Rejected", rejected_count)
col4.metric("Approval Rate", f"{approval_rate:.1f}%")
col5.metric("LLM Calls", total_llm_calls)
col6.metric("Est. Cost (USD)", f"${total_cost:.6f}")

st.caption(f"Total tokens consumed: {total_tokens:,}")

st.divider()

# --- Approved vs Rejected chart -----------------------------------------

if total_decisions:
    st.subheader("Approved vs Rejected")
    chart_data = pd.DataFrame({
        "status": ["approved", "rejected"],
        "count": [approved_count, rejected_count],
    }).set_index("status")
    st.bar_chart(chart_data)
else:
    st.info("No allocation decisions logged yet. Run `python3 -m src.graph` to generate some.")

st.divider()

# --- Allocation decisions table ------------------------------------------

st.subheader("Guardrail Decisions")
if total_decisions:
    status_filter = st.selectbox("Filter by status", ["all", "approved", "rejected"])
    display_df = decisions_df if status_filter == "all" else decisions_df[decisions_df["status"] == status_filter]
    st.dataframe(display_df, width="stretch")
else:
    st.info("No decisions to display.")

st.divider()

# --- LLM calls table -------------------------------------------------------

st.subheader("LLM Calls (Planner Agent)")
if total_llm_calls:
    st.dataframe(llm_calls_df, width="stretch")
else:
    st.info("No LLM calls logged yet.")
