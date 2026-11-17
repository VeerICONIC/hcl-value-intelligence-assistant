"""Reusable Amazon Bedrock Runtime client (boto3 directly, D2/D4).

* Credentials come from boto3's default provider chain (D11); an optional profile
  *name* may be supplied. Nothing credential-related is stored or logged.
* No AWS call is made at import time or when ``BedrockRuntime`` is constructed;
  the boto3 client is created lazily on first use.
* ``BedrockRuntime`` is a thin wrapper shared by embeddings and generation. It only
  translates errors into actionable ``BedrockError`` subclasses.

Copied from the practice repo (verified against live Bedrock); imports adapted,
``BedrockError`` now derives from the project-wide ``NimbusError``.
"""

from __future__ import annotations

from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    NoRegionError,
    ProfileNotFound,
)

from app.core.config import Settings, get_settings
from app.core.exceptions import NimbusError


class BedrockError(NimbusError):
    """Base class for Bedrock failures. Messages are safe to show to users."""


class CredentialsError(BedrockError):
    """Missing, invalid, or expired AWS credentials / unknown profile."""


class PermissionDeniedError(BedrockError):
    """Credentials are valid but IAM does not allow the action."""


class ModelAccessError(BedrockError):
    """Model access has not been granted for this account/region."""


class ModelNotFoundError(BedrockError):
    """Model ID unsupported, unavailable in the region, or needs an inference profile."""


class RegionError(BedrockError):
    """Region missing/invalid or the Bedrock endpoint is unreachable."""


class ThrottlingError(BedrockError):
    """Request rate or quota exceeded."""


_CRED_CODES = {
    "UnrecognizedClientException", "InvalidSignatureException", "ExpiredTokenException",
    "ExpiredToken", "InvalidClientTokenId", "AuthFailure", "SignatureDoesNotMatch",
}


def translate_error(exc: BaseException, *, model_id: Optional[str] = None,
                    region: Optional[str] = None) -> BedrockError:
    """Map boto3/botocore exceptions to actionable BedrockError subclasses."""
    model = f" '{model_id}'" if model_id else ""
    where = f" in region '{region}'" if region else ""

    if isinstance(exc, ProfileNotFound):
        return CredentialsError(f"AWS profile not found: {exc}. Check AWS_PROFILE.")
    if isinstance(exc, NoCredentialsError):
        return CredentialsError(
            "No AWS credentials found. Sign in (aws login / aws sso login), use environment "
            "credentials or an IAM role; optionally set AWS_PROFILE."
        )
    if isinstance(exc, NoRegionError):
        return RegionError("No AWS region configured. Set AWS_REGION.")
    if isinstance(exc, EndpointConnectionError):
        return RegionError(f"Cannot reach the Bedrock endpoint{where}. Check AWS_REGION and network access.")
    if isinstance(exc, ClientError):
        err = exc.response.get("Error", {})
        code = err.get("Code", "")
        msg = err.get("Message", "")
        low = msg.lower()
        if code in _CRED_CODES:
            return CredentialsError(
                f"AWS rejected the credentials ({code}). They may be invalid or expired; "
                "sign in again (aws login / aws sso login)."
            )
        if "account is currently being verified" in low:
            return PermissionDeniedError(
                f"AWS is still verifying this account, so Bedrock calls are refused{where} (AWS says: {msg}). "
                "This is an account-level hold, not an IAM or model-access problem."
            )
        if code == "AccessDeniedException":
            if "model access" in low or "access to the model" in low or "not enabled" in low:
                return ModelAccessError(
                    f"Model access not granted for{model}{where}. Request access in the Bedrock console."
                )
            return PermissionDeniedError(
                f"IAM permission denied{model}{where}. The identity needs bedrock:InvokeModel "
                f"on the model (and inference profile, if used). AWS says: {msg}"
            )
        if code == "ResourceNotFoundException":
            return ModelNotFoundError(f"Model{model} not found or not available{where}. Check the model ID and region.")
        if code == "ValidationException" and (
            "model identifier is invalid" in low or "on-demand throughput" in low or "inference profile" in low
        ):
            return ModelNotFoundError(
                f"Model ID{model} is invalid for this region, or requires an inference "
                f"profile (e.g. 'apac.' prefix){where}. AWS says: {msg}"
            )
        if code in {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"}:
            return ThrottlingError(f"Bedrock throttled the request ({code}); retry later.")
        return BedrockError(f"Bedrock error {code or 'Unknown'}{model}{where}: {msg}")
    if isinstance(exc, BotoCoreError):
        return BedrockError(f"AWS client error: {exc}")
    return BedrockError(f"Unexpected error: {exc}")


def create_session(settings: Optional[Settings] = None) -> boto3.Session:
    """Create a boto3 session using the default chain and optional profile."""
    s = settings or get_settings()
    try:
        return boto3.Session(profile_name=s.aws_profile, region_name=s.aws_region)
    except ProfileNotFound as exc:
        raise translate_error(exc) from None


def aws_credentials_available(settings: Optional[Settings] = None) -> bool:
    """True if the boto3 chain resolves credentials. Never calls Bedrock and never returns secrets.

    Resolving may read local credential files / the SSO cache (and may refresh an
    expired SSO token), but no model is invoked, so it costs nothing.
    """
    try:
        return create_session(settings).get_credentials() is not None
    except (BedrockError, BotoCoreError):
        return False


def create_bedrock_runtime_client(settings: Optional[Settings] = None, *, verify_credentials: bool = True):
    """Create a ``bedrock-runtime`` boto3 client (no Bedrock API call is made)."""
    s = settings or get_settings()
    session = create_session(s)
    if verify_credentials:
        try:
            creds = session.get_credentials()
        except BotoCoreError as exc:
            raise translate_error(exc, region=s.aws_region) from None
        if creds is None:
            raise translate_error(NoCredentialsError())
    cfg = Config(
        region_name=s.aws_region,
        retries={"max_attempts": 5, "mode": "adaptive"},
        connect_timeout=10,
        read_timeout=60,
    )
    return session.client("bedrock-runtime", config=cfg)


class BedrockRuntime:
    """Thin wrapper over a bedrock-runtime client with unified error translation."""

    def __init__(self, settings: Optional[Settings] = None, client: Any = None):
        self.settings = settings or get_settings()
        self._client = client  # created lazily so construction never touches AWS

    @property
    def client(self):
        if self._client is None:
            self._client = create_bedrock_runtime_client(self.settings)
        return self._client

    def invoke_model(self, model_id: str, body: str | bytes) -> bytes:
        """InvokeModel; returns the raw response body bytes (used for Titan embeddings)."""
        try:
            resp = self.client.invoke_model(
                modelId=model_id, body=body, contentType="application/json", accept="application/json",
            )
            return resp["body"].read()
        except BedrockError:
            raise
        except (ClientError, BotoCoreError) as exc:
            raise translate_error(exc, model_id=model_id, region=self.settings.aws_region) from None

    def converse(self, model_id: str, **kwargs: Any) -> dict:
        """Converse API passthrough (messages, system, inferenceConfig, ...), used for Nova Lite."""
        try:
            return self.client.converse(modelId=model_id, **kwargs)
        except BedrockError:
            raise
        except (ClientError, BotoCoreError) as exc:
            raise translate_error(exc, model_id=model_id, region=self.settings.aws_region) from None
