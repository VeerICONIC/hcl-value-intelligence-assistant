"""Analytics API: POST /pipeline/run, GET /scorecard, /data-quality, /usage (no AWS involved)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Outputs go to a temp folder so tests never write into data/processed.
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path / "processed"))
    return TestClient(create_app())


@pytest.mark.parametrize("path", ["/scorecard", "/data-quality", "/usage"])
def test_reads_before_a_run_return_409(client, path):
    resp = client.get(path)
    assert resp.status_code == 409
    assert "POST /pipeline/run" in resp.json()["detail"]


def test_run_default_dataset_then_read(client, tmp_path):
    run = client.post("/pipeline/run")
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["raw_dir"] == "data/raw"
    assert body["as_of"] == "2026-11-15"
    assert body["initiative_count"] == 8
    assert body["status_counts"] == {"Green": 2, "Amber": 3, "Red": 3, "Insufficient data": 0}
    assert body["change_count"] > 0 and "UNIT_SCALE" in body["rule_counts"]
    assert (tmp_path / "processed" / "scorecard.csv").is_file()
    version = body["data_version"]

    sc = client.get("/scorecard").json()
    assert sc["data_version"] == version and len(sc["rows"]) == 8
    init4 = next(r for r in sc["rows"] if r["initiative_id"] == "INIT-004")
    assert init4["status"] == "Red" and init4["metrics"]["adoption"]["display"] == "22.0%"
    assert init4["metrics"]["adoption"]["source_refs"]

    dq = client.get("/data-quality").json()
    assert dq["data_version"] == version
    assert len(dq["entries"]) == body["change_count"]
    assert {r["rule_id"] for r in dq["rules"]} == set(body["rule_counts"])
    assert all(r["description"] for r in dq["rules"])

    usage = client.get("/usage").json()
    assert usage["weeks"] == ["2026-10-26", "2026-11-02", "2026-11-09"]
    excluded = [p for p in usage["points"] if not p["included"]]
    assert any(p["initiative_id"] == "INIT-008" and "licensed" in p["note"] for p in excluded)
    assert all(p["source_ref"].startswith("weekly_usage.csv row ") for p in usage["points"])


def test_run_scale_dataset(client):
    run = client.post("/pipeline/run", json={"raw_dir": "data_scale_40/raw"})
    assert run.status_code == 200, run.text
    assert run.json()["initiative_count"] == 40


def test_raw_dir_outside_project_is_rejected(client, tmp_path):
    resp = client.post("/pipeline/run", json={"raw_dir": str(tmp_path)})
    assert resp.status_code == 400
    resp = client.post("/pipeline/run", json={"raw_dir": "../somewhere"})
    assert resp.status_code == 400


def test_missing_folder_is_a_clear_422(client):
    resp = client.post("/pipeline/run", json={"raw_dir": "data/does_not_exist"})
    assert resp.status_code == 422
    assert "not found" in resp.json()["detail"]
