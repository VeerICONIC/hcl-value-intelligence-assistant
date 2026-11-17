"""Project exception hierarchy.

Every error we raise on purpose derives from ``NimbusError``, so the API layer can
catch "our" errors with one ``except`` and turn them into clean HTTP responses,
while genuine bugs (TypeError, KeyError, ...) still surface loudly.

Messages are written to be safe to show to a user: no credentials, no stack data.
Bedrock-specific errors live in ``app.core.bedrock`` (they subclass ``NimbusError``).
"""

from __future__ import annotations


class NimbusError(Exception):
    """Base class for all expected, user-explainable failures in this project."""


class ConfigurationError(NimbusError):
    """Settings are missing or invalid. The message lists every bad field."""


class DataValidationError(NimbusError):
    """A raw data file is missing, unreadable or lacks required columns. Message names the file."""


# --- Charter parsing --------------------------------------------------------
class DocumentParseError(NimbusError):
    """A charter file could not be parsed. Carries the filename and a user-safe reason."""

    code = "parse_error"

    def __init__(self, filename: str, reason: str):
        super().__init__(f"{filename}: {reason}")
        self.filename = filename
        self.reason = reason


class EmptyDocumentError(DocumentParseError):
    code = "empty_document"


class CorruptDocumentError(DocumentParseError):
    code = "corrupt_document"


class EncryptedDocumentError(DocumentParseError):
    code = "encrypted_document"


class OcrRequiredError(DocumentParseError):
    code = "ocr_required"


class UnsupportedEncodingError(DocumentParseError):
    code = "unsupported_encoding"


# --- Vector store -----------------------------------------------------------
class VectorStoreError(NimbusError):
    """A ChromaDB operation failed. Message is user-safe."""
