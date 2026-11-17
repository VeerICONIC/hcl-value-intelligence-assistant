"""The Streamlit dashboard renders when the backend is down, before a pipeline run, and with a scorecard.

Uses Streamlit's official headless test harness (``streamlit.testing.v1.AppTest``),
which runs the script in-process without a browser. The backend is faked by routing
``httpx.get`` calls to real API responses produced in-process by FastAPI's TestClient.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app.main import create_app

DASHBOARD = str(Path(__file__).resolve().parents[1] / "ui" / "dashboard.py")


def test_dashboard_shows_friendly_error_when_backend_down(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://127.0.0.1:9")  # nothing listens on port 9
    at = AppTest.from_file(DASHBOARD, default_timeout=15).run()
    assert not at.exception
    assert at.title[0].value == "Nimbus Value Intelligence Assistant"
    assert "not reachable" in at.sidebar.error[0].value


@pytest.fixture
def backend(monkeypatch, tmp_path):
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    client = TestClient(create_app())

    def fake_get(url, params=None, timeout=None):
        path = url.split("8000", 1)[-1]
        return client.get(path, params=params)

    monkeypatch.setattr(httpx, "get", fake_get)
    return client


def test_dashboard_before_pipeline_run_asks_to_run_it(backend):
    at = AppTest.from_file(DASHBOARD, default_timeout=30).run()
    assert not at.exception
    assert "API OK" in at.sidebar.success[0].value
    assert any("Run pipeline" in i.value for i in at.info)


def test_dashboard_shows_scorecard_after_run(backend):
    assert backend.post("/pipeline/run").status_code == 200
    at = AppTest.from_file(DASHBOARD, default_timeout=30).run()
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["Initiatives"] == "8" and values["🔴 Red"] == "3" and values["🟢 Green"] == "2"
    assert any(s.value.startswith("4. Data quality") for s in at.subheader)


def test_dashboard_chat_answers_from_scorecard(backend, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "extractive")
    assert backend.post("/pipeline/run").status_code == 200

    def fake_post(url, json=None, timeout=None):
        return backend.post(url.split("8000", 1)[-1], json=json)

    monkeypatch.setattr(httpx, "post", fake_post)
    at = AppTest.from_file(DASHBOARD, default_timeout=30).run()
    at.text_input[0].input("Which initiatives are Red?")
    next(b for b in at.button if b.label == "Ask").click().run()
    assert not at.exception
    assert len(at.chat_message) == 2
    assert any("INIT-004" in m.value for m in at.chat_message[1].markdown)


def test_dashboard_example_button_attention_panel_and_report(backend, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "extractive")
    assert backend.post("/pipeline/run").status_code == 200

    def fake_post(url, json=None, timeout=None):
        return backend.post(url.split("8000", 1)[-1], json=json)

    monkeypatch.setattr(httpx, "post", fake_post)
    at = AppTest.from_file(DASHBOARD, default_timeout=30).run()
    page = " ".join(m.value for m in at.markdown)
    assert "Needs attention" in page and "INIT-004" in page          # attention cards rendered
    next(b for b in at.button if b.label == "Which initiatives need attention?").click().run()
    assert not at.exception
    assert any("INIT-004" in m.value for m in at.chat_message[1].markdown)
    next(b for b in at.button if b.label == "Generate report").click().run()
    assert not at.exception
    report = " ".join(m.value for m in at.markdown)
    assert "Initiatives requiring attention" in report and "\$25,019" in report   # '$' escaped for Streamlit
