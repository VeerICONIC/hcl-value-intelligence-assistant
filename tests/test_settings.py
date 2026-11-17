"""Settings load with the D2/D3 defaults, accept overrides, and reject bad values clearly."""

from __future__ import annotations

import pytest

from app.core.config import FALLBACK_MESSAGE, Settings, get_settings, load_settings
from app.core.exceptions import ConfigurationError


def test_defaults_match_architecture_d2():
    s = load_settings()
    assert s.aws_region == "ap-south-1"
    assert s.bedrock_embed_model_id == "amazon.titan-embed-text-v2:0"
    assert s.bedrock_embed_dim == 1024
    assert s.bedrock_llm_model_id == "apac.amazon.nova-lite-v1:0"
    assert s.aws_profile is None


def test_env_override(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_EMBED_DIM", "512")
    monkeypatch.setenv("AWS_PROFILE", "   ")  # blank profile means "default chain"
    s = load_settings()
    assert s.aws_region == "us-east-1"
    assert s.bedrock_embed_dim == 512
    assert s.aws_profile is None


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


def test_invalid_titan_dimension_raises_configuration_error():
    with pytest.raises(ConfigurationError, match="BEDROCK_EMBED_DIM"):
        load_settings(bedrock_embed_dim=768)


def test_invalid_log_level_is_reported():
    with pytest.raises(ConfigurationError, match="LOG_LEVEL"):
        load_settings(log_level="loud")


def test_collection_name_encodes_model_and_dimension_d3():
    assert load_settings().chroma_collection == "charters__titan-embed-text-v2__1024"
    assert load_settings(bedrock_embed_dim=256).chroma_collection == "charters__titan-embed-text-v2__256"


def test_no_credential_fields_in_settings_d11():
    forbidden = ("secret", "access_key", "session_token", "password")
    for name in Settings.model_fields:
        assert not any(word in name for word in forbidden), name


def test_fallback_message_is_exact():
    assert FALLBACK_MESSAGE == "I do not have that in the data provided"
