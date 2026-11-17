"""Assistant end to end through POST /ask, offline (LLM_MODE=extractive, BM25): routing, templates, guards, fallback."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.charters.chunker import chunk_folder
from app.core.config import FALLBACK_MESSAGE, PROJECT_ROOT
from app.main import create_app
from app.orchestration.guards import has_digit
from app.orchestration.router import route

NAMES = {"INIT-004": "Contract Review Assistant", "INIT-005": "Customer Service Chatbot", "INIT-003": "Sales Forecast Model"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LLM_MODE", "extractive")
    mp.setenv("PROCESSED_DIR", str(tmp_path_factory.mktemp("processed")))
    from app.core.config import get_settings
    get_settings.cache_clear()
    c = TestClient(create_app())
    assert c.post("/pipeline/run").status_code == 200
    yield c
    mp.undo()


@pytest.fixture(autouse=True)
def clean_env():      # override conftest's per-test env reset: this module keeps one configured client
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield


def ask(client, q):
    resp = client.post("/ask", json={"question": q})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_chunks_have_metadata_and_injection_flag():
    chunks = chunk_folder(PROJECT_ROOT / "data" / "charters")
    assert {c.initiative_id for c in chunks} == {f"INIT-00{i}" for i in range(1, 9)}
    assert [c.chunk_id for c in chunks if c.injection_flag] == ["INIT-005:risks-and-mitigations"]
    assert not any(c.initiative_id == "INIT-003" and "Risk" in c.section for c in chunks)
    assert {c.source_file for c in chunks if c.initiative_id == "INIT-006"} == {"invoice_anomaly_detector_charter.docx"}


@pytest.mark.parametrize("q, kind", [
    ("What is the adoption of the Contract Review Assistant?", "metric"),
    ("Which initiatives are Red?", "metric"),
    ("What are the risks of INIT-005?", "narrative"),
    ("Why is INIT-004 Red?", "mixed"),
    ("What is the portfolio average ROI?", "unsupported"),
    ("Tell me a joke", "unsupported"),
])
def test_router(q, kind):
    assert route(q, NAMES).kind == kind


def test_metric_lookup_is_template_with_scorecard_source(client):
    r = ask(client, "What is the adoption of the Contract Review Assistant?")
    assert r["route"] == "metric" and "22.0%" in r["answer"] and "Red" in r["answer"]
    assert r["scorecard_sources"][0]["metric"] == "adoption"


def test_rank_and_count(client):
    assert "INIT-002" in ask(client, "Which initiative has the highest ROI?")["answer"]
    assert ask(client, "How many initiatives are Red?")["answer"].startswith("3 Red")


def test_narrative_has_citation_and_no_digits(client):
    r = ask(client, "What are the objectives of INIT-002?")
    assert r["route"] == "narrative" and r["status"] == "answered"
    assert "it_helpdesk_bot_charter.md" in r["answer"] and not has_digit(r["answer"])
    assert r["charter_sources"][0]["section"] == "Objectives"


def test_injection_is_ignored(client):
    r = ask(client, "What are the risks of the Customer Service Chatbot?")
    assert "ignore all previous instructions" not in r["answer"].lower()
    assert "250" not in r["answer"] and "Green" not in r["answer"]
    assert any("Injection guard" in n for n in r["guard_notes"])
    s = ask(client, "What is the status of INIT-005?")
    assert "Red" in s["answer"] and "Green" not in s["answer"] and "250" not in s["answer"]


def test_missing_section_gives_exact_fallback(client):
    r = ask(client, "What are the risks of INIT-003?")
    assert r["status"] == "no_evidence" and r["answer"] == FALLBACK_MESSAGE


def test_personal_data_refused(client):
    r = ask(client, "What is the email address of the INIT-001 sponsor?")
    assert r["status"] == "refused"


def test_undefined_aggregate_gives_fallback(client):
    assert ask(client, "What is the portfolio average ROI?")["answer"] == FALLBACK_MESSAGE


def test_mixed_combines_both(client):
    r = ask(client, "Why is INIT-004 Red?")
    assert r["route"] == "mixed" and "22.0%" in r["answer"] and "contract_review_assistant_charter.md" in r["answer"]
    assert r["scorecard_sources"] and r["charter_sources"]


def test_ask_before_pipeline_is_409(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "extractive")
    assert TestClient(create_app()).post("/ask", json={"question": "Which initiatives are Red?"}).status_code == 409


def test_index_endpoint(client):
    body = client.post("/charters/index").json()
    assert body["chunks"] == 63 and body["injection_flagged"] == ["INIT-005:risks-and-mitigations"]
    assert body["retrieval"] == "bm25"


def test_weekly_report_is_deterministic_and_cited(client):
    body = client.post("/report/weekly").json()
    md = body["markdown"]
    assert "Initiatives requiring attention" in md and "| INIT-004 Contract Review Assistant | 🔴 Red |" in md
    # Red first, then Amber
    assert md.index("INIT-004 Contract Review Assistant (Red)") < md.index("INIT-003 Sales Forecast Model (Amber)")
    assert "[C1] contract_review_assistant_charter.md, Risks and Mitigations" in md
    assert "ignore all previous instructions" not in md.lower()
    assert "INIT-003 Sales Forecast Model (Amber)" in md and "no Risks and Mitigations section" in md
    assert "involve planners in validation" in md          # PDF line fragments joined
    again = client.post("/report/weekly").json()["markdown"]
    strip = lambda t: "\n".join(l for l in t.splitlines() if not l.startswith("**Generated:**"))
    assert strip(again) == strip(md)
