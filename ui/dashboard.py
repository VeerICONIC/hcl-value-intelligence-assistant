"""Nimbus Value Intelligence dashboard (one Streamlit page, architecture.md §3.3).

D13: this file talks ONLY to the FastAPI backend over HTTP. It imports nothing from
``app/``. The backend URL comes from the ``API_BASE_URL`` environment variable.

Step 1 shell: page header + sidebar backend status. Later steps add, top to bottom:
overview tiles, scorecard table, charts, data quality (Step 4), the Ask panel
(Step 8) and the weekly report (Step 9).

Run (backend first):  .\\.venv\\Scripts\\python.exe -m streamlit run ui/dashboard.py
"""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_SECONDS = 5.0


def fetch_health(check_aws: bool = False) -> tuple[dict | None, str | None]:
    """Call GET /health. Returns (body, None) on success or (None, error message)."""
    try:
        resp = httpx.get(f"{API_BASE_URL}/health", params={"check_aws": check_aws}, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json(), None
    except httpx.HTTPError as exc:
        return None, f"Backend not reachable at {API_BASE_URL} ({type(exc).__name__})."


def render_sidebar() -> None:
    st.sidebar.header("Backend status")
    check_aws = st.sidebar.checkbox("Check AWS credentials", value=False,
                                    help="Local check only; no Bedrock model is called.")
    health, error = fetch_health(check_aws)
    if error:
        st.sidebar.error(error)
        st.sidebar.caption("Start it with: python -m uvicorn app.main:app --port 8000")
        return
    st.sidebar.success(f"API OK - v{health['version']}")
    st.sidebar.caption(f"Region: {health['aws_region']}")
    st.sidebar.caption(f"Embeddings: {health['embed_model']}")
    st.sidebar.caption(f"LLM: {health['llm_model']}")
    if "aws_credentials" in health:
        if health["aws_credentials"]:
            st.sidebar.info("AWS credentials found")
        else:
            st.sidebar.warning("No AWS credentials (analytics still work; chat needs Bedrock)")


def main() -> None:
    st.set_page_config(page_title="Nimbus Value Intelligence", layout="wide")
    st.title("Nimbus Value Intelligence Assistant")
    st.caption("AI portfolio scorecard and grounded assistant. Analytics first, chat second.")
    render_sidebar()
    st.info("The portfolio scorecard, charts and data-quality log arrive in Step 4.")


main()
