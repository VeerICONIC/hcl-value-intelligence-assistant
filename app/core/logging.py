"""Logging setup: one format for the whole app, configured once.

Modules just do ``logger = logging.getLogger(__name__)``; only entry points
(FastAPI startup, scripts) call ``configure_logging``.

Note: this file is ``app/core/logging.py``. Inside it, ``import logging`` still
gets the standard library, because Python 3 imports are absolute. Our module is only
reachable as ``app.core.logging``.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_HANDLER_NAME = "nimbus-console"

# Third-party loggers that are noisy at INFO/DEBUG.
_QUIET = ("botocore", "boto3", "urllib3", "chromadb", "httpx", "httpcore")


def configure_logging(level: str = "INFO") -> None:
    """Attach one stdout handler to the root logger. Safe to call repeatedly."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    if not any(getattr(h, "name", None) == _HANDLER_NAME for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
