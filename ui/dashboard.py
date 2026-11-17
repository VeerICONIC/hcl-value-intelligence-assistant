"""Nimbus Value Intelligence dashboard (one Streamlit page, architecture.md §3.3).

D13: this file talks ONLY to the FastAPI backend over HTTP. It imports nothing from
``app/``. The backend URL comes from the ``API_BASE_URL`` environment variable.

Top to bottom: sidebar (run pipeline, data version, backend status) -> overview tiles ->
scorecard table -> charts -> data-quality log -> Ask the assistant -> weekly report.
Sections 1-4 never call the LLM (D12).

Run (backend first):  .\\.venv\\Scripts\\python.exe -m streamlit run ui/dashboard.py
"""

from __future__ import annotations

import os

import altair as alt
import httpx
import pandas as pd
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_SECONDS = 5.0
LONG_TIMEOUT = 120.0
DATASETS = {"Demo set (8 initiatives)": "data/raw", "Scale set (40 initiatives)": "data_scale_40/raw"}
STATUS_COLOURS = {"Green": "#2e7d32", "Amber": "#f9a825", "Red": "#c62828", "Insufficient data": "#757575"}
METRIC_COLUMNS = [("adoption", "Adoption"), ("wau_change", "WAU change"), ("roi", "ROI"),
                  ("avg_monthly_benefit", "Avg monthly benefit"), ("payback_months", "Payback"),
                  ("run_rate_vs_plan", "Run-rate vs plan"), ("months_live", "Months live")]


# --- HTTP helpers --------------------------------------------------------------------
def api_get(path: str, **params) -> tuple[dict | None, int | None, str | None]:
    """GET -> (body, status_code, error). Never raises."""
    try:
        resp = httpx.get(f"{API_BASE_URL}{path}", params=params or None, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return None, None, f"Backend not reachable at {API_BASE_URL} ({type(exc).__name__})."
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        return None, resp.status_code, str(detail)
    return resp.json(), 200, None


def api_post(path: str, payload: dict | None = None, timeout: float = LONG_TIMEOUT) -> tuple[dict | None, str | None]:
    try:
        resp = httpx.post(f"{API_BASE_URL}{path}", json=payload or {}, timeout=timeout)
    except httpx.HTTPError as exc:
        return None, f"Backend not reachable at {API_BASE_URL} ({type(exc).__name__})."
    if resp.status_code != 200:
        try:
            return None, str(resp.json().get("detail", resp.text))
        except ValueError:
            return None, resp.text
    return resp.json(), None


def fetch_health(check_aws: bool = False) -> tuple[dict | None, str | None]:
    body, _, err = api_get("/health", check_aws=check_aws)
    return body, err


# --- sidebar -------------------------------------------------------------------------
def render_sidebar() -> bool:
    """Returns True when the backend is reachable."""
    st.sidebar.header("Data")
    label = st.sidebar.selectbox("Dataset", list(DATASETS))
    if st.sidebar.button("Run pipeline", type="primary", use_container_width=True):
        body, err = api_post("/pipeline/run", {"raw_dir": DATASETS[label]})
        if err:
            st.sidebar.error(err)
        else:
            st.session_state["run"] = body
            st.sidebar.success(f"Pipeline run: {body['initiative_count']} initiatives, "
                               f"{body['change_count']} corrections logged")

    st.sidebar.header("Backend status")
    check_aws = st.sidebar.checkbox("Check AWS credentials", value=False,
                                    help="Local check only; no Bedrock model is called.")
    health, error = fetch_health(check_aws)
    if error:
        st.sidebar.error(error)
        st.sidebar.caption("Start it with: python -m uvicorn app.main:app --port 8000")
        return False
    st.sidebar.success(f"API OK - v{health['version']}")
    st.sidebar.caption(f"Answer mode: {health.get('llm_mode', 'bedrock')}")
    st.sidebar.caption(f"Region: {health['aws_region']}")
    st.sidebar.caption(f"Embeddings: {health['embed_model']}")
    st.sidebar.caption(f"LLM: {health['llm_model']}")
    if "aws_credentials" in health:
        if health["aws_credentials"]:
            st.sidebar.info("AWS credentials found")
        else:
            st.sidebar.warning("No AWS credentials (analytics still work; chat runs in extractive mode)")
    return True


# --- analytics sections ----------------------------------------------------------------
def scorecard_frame(rows: list[dict]) -> pd.DataFrame:
    records = []
    for r in rows:
        rec = {"ID": r["initiative_id"], "Initiative": r["name"], "Status": r["status"]}
        for key, label in METRIC_COLUMNS:
            rec[label] = r["metrics"][key]["display"]
        rec["Why"] = r["status_reason"]
        records.append(rec)
    return pd.DataFrame(records)


def render_overview(sc: dict) -> None:
    rows = sc["rows"]
    counts = {s: sum(r["status"] == s for r in rows) for s in STATUS_COLOURS}
    st.subheader("1. Portfolio overview")
    st.caption(f"Data version {sc['data_version']} · as of {sc['as_of']}")
    c = st.columns(4)
    c[0].metric("Initiatives", len(rows))
    c[1].metric("🟢 Green", counts["Green"])
    c[2].metric("🟠 Amber", counts["Amber"])
    c[3].metric("🔴 Red", counts["Red"])
    if counts["Insufficient data"]:
        st.warning(f"{counts['Insufficient data']} initiative(s) have insufficient data for a status.")


def render_scorecard(sc: dict) -> None:
    st.subheader("2. Value scorecard")
    df = scorecard_frame(sc["rows"])
    styled = df.style.map(lambda v: f"background-color: {STATUS_COLOURS.get(v, '')}; color: white"
                          if v in STATUS_COLOURS else "", subset=["Status"])
    st.dataframe(styled, hide_index=True, use_container_width=True)
    with st.expander("How each number was computed (formula, inputs, source rows)"):
        pick = st.selectbox("Initiative", [f"{r['initiative_id']} {r['name']}" for r in sc["rows"]])
        row = next(r for r in sc["rows"] if pick.startswith(r["initiative_id"]))
        st.write(f"**Status: {row['status']}** — {row['status_reason']}")
        st.dataframe(pd.DataFrame([{
            "Metric": label, "Value": row["metrics"][key]["display"], "Formula": row["metrics"][key]["formula"],
            "Inputs": ", ".join(f"{k}={v}" for k, v in row["metrics"][key]["inputs"].items()),
            "Sources": "; ".join(row["metrics"][key]["source_refs"]), "Note": row["metrics"][key]["note"] or "",
        } for key, label in METRIC_COLUMNS]), hide_index=True, use_container_width=True)


def render_charts(sc: dict) -> None:
    st.subheader("3. Charts")
    data = pd.DataFrame([{"Initiative": f"{r['initiative_id']} {r['name']}", "Status": r["status"],
                          "Adoption": r["metrics"]["adoption"]["value"], "ROI": r["metrics"]["roi"]["value"],
                          "Adoption label": r["metrics"]["adoption"]["display"],
                          "ROI label": r["metrics"]["roi"]["display"]} for r in sc["rows"]])
    colour = alt.Color("Status:N", scale=alt.Scale(domain=list(STATUS_COLOURS), range=list(STATUS_COLOURS.values())))
    left, right = st.columns(2)
    with left:
        st.markdown("**Adoption by initiative** (lines at 30% Red and 60% Green thresholds)")
        bars = alt.Chart(data.dropna(subset=["Adoption"])).mark_bar().encode(
            x=alt.X("Adoption:Q", axis=alt.Axis(format="%")), y=alt.Y("Initiative:N", sort=None), color=colour,
            tooltip=["Initiative", "Adoption label", "Status"])
        rules = alt.Chart(pd.DataFrame({"t": [0.30, 0.60]})).mark_rule(strokeDash=[4, 4], color="black").encode(x="t:Q")
        st.altair_chart(bars + rules, use_container_width=True)
    with right:
        st.markdown("**ROI by initiative** (bars around zero)")
        roi = alt.Chart(data.dropna(subset=["ROI"])).mark_bar().encode(
            x=alt.X("ROI:Q", axis=alt.Axis(format="%")), y=alt.Y("Initiative:N", sort=None), color=colour,
            tooltip=["Initiative", "ROI label", "Status"])
        zero = alt.Chart(pd.DataFrame({"t": [0.0]})).mark_rule(color="black").encode(x="t:Q")
        st.altair_chart(roi + zero, use_container_width=True)


def render_data_quality() -> None:
    st.subheader("4. Data quality: change log")
    dq, _, err = api_get("/data-quality")
    if err:
        st.error(err)
        return
    st.caption(f"{len(dq['entries'])} corrections and standardisations applied before scoring.")
    st.dataframe(pd.DataFrame(dq["rules"]), hide_index=True, use_container_width=True)
    entries = pd.DataFrame(dq["entries"])
    rule = st.selectbox("Filter by rule", ["All"] + [r["rule_id"] for r in dq["rules"]])
    if rule != "All":
        entries = entries[entries["rule_id"] == rule]
    st.dataframe(entries, hide_index=True, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Nimbus Value Intelligence", layout="wide")
    st.title("Nimbus Value Intelligence Assistant")
    st.caption("AI portfolio scorecard and grounded assistant. Analytics first, chat second.")
    if not render_sidebar():
        return
    sc, code, err = api_get("/scorecard")
    if code == 409:
        st.info("Choose a dataset and press **Run pipeline** in the sidebar to build the scorecard.")
        return
    if err:
        st.error(err)
        return
    render_overview(sc)
    render_scorecard(sc)
    render_charts(sc)
    render_data_quality()


main()
