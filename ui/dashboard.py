"""
Nimbus Value Intelligence Assistant: one-page dashboard.
Analytics first (no LLM), then the assistant chat on the same page, then the weekly report.

Run:  streamlit run ui/dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from nimbus import llm  # noqa: E402
from nimbus.pipeline import METRIC_LABELS, fmt_metric  # noqa: E402
from nimbus.service import Service  # noqa: E402

st.set_page_config(page_title="Nimbus Value Intelligence", page_icon="📊", layout="wide")
STATUS_COLOR = {"Green": "#2e7d32", "Amber": "#f9a825", "Red": "#c62828", "Insufficient data": "#757575"}


@st.cache_resource
def get_service() -> Service:
    return Service()


svc = get_service()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Data")
    options = [p.name for p in sorted(ROOT.iterdir()) if p.is_dir() and (p / "raw").is_dir()]
    dataset = st.selectbox("Dataset", options, index=options.index("data") if "data" in options else 0)
    if st.button("▶ Run pipeline", type="primary", width="stretch"):
        with st.spinner("Cleaning data, computing scorecard, indexing charters..."):
            st.session_state["run_info"] = svc.run(str(ROOT / dataset))
            st.session_state["chat"] = []
    if svc.ready:
        info = st.session_state.get("run_info", {})
        st.success("Pipeline ready")
        st.caption(f"Data version `{svc.result.data_version}`  \nAs of {svc.result.as_of}  \n"
                   f"Charters: {info.get('charters', {}).get('charters', '?')} files, "
                   f"{info.get('charters', {}).get('chunks', '?')} chunks  \n"
                   f"Embeddings: {svc.index.mode}")
    st.divider()
    s = llm.status()
    st.caption(f"Bedrock region {s['region']}  \nLLM: {s['llm']}  \nEmbeddings: {s['embeddings']}" + (f"  \n{s['note']}" if s["note"] else ""))

st.title("📊 Nimbus Group: AI Portfolio Value Intelligence")
st.caption("Code for numbers · retrieval for charter evidence · the language model only for explanation")

if not svc.ready:
    st.info("Choose a dataset and click **Run pipeline** in the sidebar to clean the data and build the scorecard.")
    st.stop()

r = svc.result
sc = r.scorecard.copy()

# ------------------------------------------------------------------ 1. overview
counts = sc.status.value_counts().to_dict()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Initiatives", len(sc))
c2.metric("🟢 Green", counts.get("Green", 0))
c3.metric("🟠 Amber", counts.get("Amber", 0))
c4.metric("🔴 Red", counts.get("Red", 0))
c5.metric("Data corrections", len(r.changes))

# ------------------------------------------------------------------ 2. scorecard
st.subheader("Governed scorecard")
cols = ["adoption", "wau_change", "roi", "avg_monthly_benefit", "payback_months", "run_rate_vs_plan"]
view = pd.DataFrame({"ID": sc.initiative_id, "Initiative": sc["name"], "Status": sc.status,
                     **{METRIC_LABELS[c]: [fmt_metric(c, v) for v in sc[c]] for c in cols},
                     "Why": sc.status_reason})


def _color(v):
    return f"background-color: {STATUS_COLOR.get(v, '')}; color: white; font-weight: 600" if v in STATUS_COLOR else ""


st.dataframe(view.style.map(_color, subset=["Status"]), width="stretch", hide_index=True,
             height=min(420, 40 + 35 * len(view)))
with st.expander("How each metric is calculated (governed formulas)"):
    st.markdown("""
| Metric | Formula |
|---|---|
| Adoption | latest-week active users ÷ licensed users |
| WAU change | (latest-week − first-week active users) ÷ first-week active users |
| ROI | (benefit to date − cost to date) ÷ cost to date |
| Avg monthly benefit | benefit to date ÷ months live |
| Payback | cost to date ÷ avg monthly benefit |
| Run-rate vs plan | avg monthly benefit × 12 ÷ planned annual benefit |
| Status | Red if adoption < 30% or ROI < 0; else Green if adoption ≥ 60% and ROI > 0; else Amber |
""")
    pick = st.selectbox("Inputs for initiative", sc.initiative_id)
    row = sc.set_index("initiative_id").loc[pick]
    st.write({k: fmt_metric(k, row[k]) for k in ["licensed_users", "wau_first", "wau_latest", "benefit_to_date",
                                                 "cost_to_date", "planned_annual_benefit", "months_live"]})

# ------------------------------------------------------------------ 3. charts
st.subheader("Adoption and value")
ch1, ch2 = st.columns(2)
plot = sc.dropna(subset=["adoption"]).assign(adoption_pct=lambda d: d.adoption * 100, roi_pct=lambda d: d.roi * 100)
color = alt.Color("status:N", scale=alt.Scale(domain=list(STATUS_COLOR), range=list(STATUS_COLOR.values())), legend=None)
bars = alt.Chart(plot).mark_bar().encode(
    y=alt.Y("name:N", sort="-x", title=None), x=alt.X("adoption_pct:Q", title="Adoption (%)"), color=color,
    tooltip=["name", alt.Tooltip("adoption_pct:Q", format=".1f", title="Adoption %"), "status"])
rules = alt.Chart(pd.DataFrame({"x": [30, 60], "label": ["Red below 30%", "Green from 60%"]})).mark_rule(strokeDash=[4, 4]).encode(x="x:Q")
ch1.altair_chart((bars + rules).properties(title="Adoption by initiative (thresholds 30% / 60%)", height=max(260, 22 * len(plot))), width="stretch")
roi = alt.Chart(plot).mark_bar().encode(
    y=alt.Y("name:N", sort="-x", title=None), x=alt.X("roi_pct:Q", title="ROI (%)"), color=color,
    tooltip=["name", alt.Tooltip("roi_pct:Q", format="+.1f", title="ROI %"), "status"])
zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule().encode(x="x:Q")
ch2.altair_chart((roi + zero).properties(title="ROI by initiative", height=max(260, 22 * len(plot))), width="stretch")

u = r.usage[r.usage.included].merge(sc[["initiative_id", "name"]], on="initiative_id")
if len(sc) <= 12:
    st.altair_chart(alt.Chart(u).mark_line(point=True).encode(
        x=alt.X("week_start:T", title="Week starting"), y=alt.Y("value:Q", title="Weekly active users"),
        color=alt.Color("name:N", title=None), tooltip=["name", "week_start", "value"]).properties(
        title="Weekly active users over the reporting period", height=280), width="stretch")

# ------------------------------------------------------------------ 4. data quality
st.subheader("Data quality: change log")
chg = r.changes
st.caption(f"{len(chg)} corrections and flags. Every change records the rule, the source row, old and new values, the reason and its effect.")
st.bar_chart(chg.rule.value_counts(), horizontal=True, height=260)
st.dataframe(chg[["rule", "file", "row", "initiative_id", "column", "old", "new", "reason", "effect"]],
             width="stretch", hide_index=True, height=300)

# ------------------------------------------------------------------ 5. assistant
st.divider()
st.subheader("💬 Ask the assistant")
st.caption("Metric questions are answered from the scorecard above (no LLM). Narrative questions use the charters, with citations. "
           "If the data doesn't support an answer you'll see: *I do not have that in the data provided*.")
examples = ["Which initiatives need attention?", "What is the ROI of the Customer Service Chatbot?",
            "Why is the Customer Service Chatbot red?", "What are the risks of the Sales Forecast Model?",
            "What is the phone number of the HR Policy Copilot sponsor?"]
ex_cols = st.columns(len(examples))
clicked = None
for col, ex in zip(ex_cols, examples):
    if col.button(ex, width="stretch"):
        clicked = ex

st.session_state.setdefault("chat", [])
for turn in st.session_state["chat"]:
    with st.chat_message("user"):
        st.write(turn["q"])
    with st.chat_message("assistant"):
        st.markdown(turn["a"]["answer"])
        st.caption(f"Route: **{turn['a']['route']}** · status: {turn['a']['status']} · data version {r.data_version}")
        if turn["a"]["scorecard_sources"] or turn["a"]["charter_sources"]:
            with st.expander("Sources"):
                for i, s_ in enumerate(turn["a"]["scorecard_sources"], 1):
                    st.markdown(f"**[S{i}] Scorecard:** " + ", ".join(f"{k}: {v}" for k, v in s_.items()))
                for s_ in turn["a"]["charter_sources"]:
                    st.markdown(f"**[{s_['ref']}] {s_['source_file']}, {s_['section']}**")
                    st.caption(s_["excerpt"])
        if turn["a"]["guard_notes"]:
            st.caption("🛡️ " + " · ".join(turn["a"]["guard_notes"]))

question = st.chat_input("Ask about adoption, value, status, risks, objectives...") or clicked
if question:
    ans = svc.assistant.ask(question)
    st.session_state["chat"].append({"q": question, "a": ans.__dict__})
    st.rerun()

# ------------------------------------------------------------------ 6. weekly report
st.divider()
st.subheader("🗂️ Weekly executive report")
if st.button("Generate weekly report"):
    st.session_state["report"] = svc.report()
if "report" in st.session_state:
    st.download_button("Download report (Markdown)", st.session_state["report"], file_name=f"weekly_report_{r.as_of}.md")
    with st.container(border=True):
        st.markdown(st.session_state["report"])
