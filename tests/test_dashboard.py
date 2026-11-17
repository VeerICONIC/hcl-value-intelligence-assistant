"""The Streamlit dashboard renders both when the backend is down and when it is up.

Uses Streamlit's official headless test harness (``streamlit.testing.v1.AppTest``),
which runs the script in-process without a browser.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

DASHBOARD = str(Path(__file__).resolve().parents[1] / "ui" / "dashboard.py")


def test_dashboard_shows_friendly_error_when_backend_down(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://127.0.0.1:9")  # nothing listens on port 9
    at = AppTest.from_file(DASHBOARD, default_timeout=15).run()
    assert not at.exception
    assert at.title[0].value == "Nimbus Value Intelligence Assistant"
    assert "not reachable" in at.sidebar.error[0].value


def test_dashboard_shows_backend_status_when_up(monkeypatch):
    payload = {"status": "ok", "app": "x", "version": "0.1.0", "aws_region": "ap-south-1",
               "embed_model": "amazon.titan-embed-text-v2:0", "llm_model": "apac.amazon.nova-lite-v1:0",
               "chroma_collection": "charters__titan-embed-text-v2__1024"}

    def fake_get(url, params=None, timeout=None):
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    at = AppTest.from_file(DASHBOARD, default_timeout=15).run()
    assert not at.exception
    assert "API OK" in at.sidebar.success[0].value
