"""FastAPI application. FastAPI owns all logic; the Streamlit dashboard only calls it (D13).

Run:  .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import data_quality, health, pipeline, scorecard, usage
from app.core.config import APP_NAME, APP_VERSION, get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    """Build the app. A factory keeps tests free to create fresh instances.

    Each instance holds its own latest pipeline result on ``app.state.pipeline_result``.
    """
    configure_logging(get_settings().log_level)
    app = FastAPI(title=APP_NAME, version=APP_VERSION)
    app.state.pipeline_result = None
    for module in (health, pipeline, scorecard, data_quality, usage):
        app.include_router(module.router)
    # Later steps add: ask (Step 7), report (Step 9).
    return app


app = create_app()
