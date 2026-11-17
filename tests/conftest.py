"""Shared test fixtures. No test in the default run touches AWS (live tests are marked ``live``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings, get_settings

# Every env var our Settings reads; cleared so the developer's shell/.env can't change results.
SETTING_VARS = [name.upper() for name in Settings.model_fields]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isolate each test from the developer's environment and any local .env file."""
    for var in SETTING_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(Path(__file__).parent)  # tests/ has no .env, so only defaults apply
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Default settings with Chroma pointed at a throwaway directory."""
    return Settings(chroma_path=tmp_path / "chroma")
