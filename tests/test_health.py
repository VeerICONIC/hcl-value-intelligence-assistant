"""GET /health returns 200 and never needs AWS."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core import bedrock
from app.main import create_app


def test_health_ok_without_aws(monkeypatch):
    def _must_not_be_called(*a, **k):
        raise AssertionError("plain /health must not touch AWS")

    monkeypatch.setattr(bedrock, "aws_credentials_available", _must_not_be_called)
    resp = TestClient(create_app()).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["aws_region"] == "ap-south-1"
    assert body["chroma_collection"] == "charters__titan-embed-text-v2__1024"
    assert "aws_credentials" not in body


def test_health_check_aws_reports_credentials(monkeypatch):
    monkeypatch.setattr(bedrock, "aws_credentials_available", lambda settings=None: False)
    resp = TestClient(create_app()).get("/health", params={"check_aws": True})
    assert resp.status_code == 200
    assert resp.json()["aws_credentials"] is False
