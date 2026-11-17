"""One shared application state used by both the API and the dashboard."""

from __future__ import annotations

from pathlib import Path

from nimbus.assistant import Assistant
from nimbus.charters import CharterIndex
from nimbus.pipeline import PipelineResult, run_pipeline
from nimbus.report import weekly_report


class Service:
    def __init__(self) -> None:
        self.result: PipelineResult | None = None
        self.index: CharterIndex | None = None
        self.assistant: Assistant | None = None
        self.index_info: dict = {}

    def run(self, dataset_dir: str = "data") -> dict:
        d = Path(dataset_dir)
        result = run_pipeline(d / "raw")
        index = CharterIndex()
        info = index.build(d / "charters")
        assistant = Assistant(result, index)
        # publish only when every step succeeded, so the app is never half-initialised
        self.result, self.index, self.index_info, self.assistant = result, index, info, assistant
        sc = self.result.scorecard
        return {"dataset": dataset_dir, "data_version": self.result.data_version, "as_of": self.result.as_of.isoformat(),
                "initiatives": len(sc), "status_counts": sc.status.value_counts().to_dict(),
                "changes": len(self.result.changes), "charters": self.index_info}

    @property
    def ready(self) -> bool:
        return self.result is not None and self.assistant is not None

    def report(self) -> str:
        return weekly_report(self.result, self.index)


SERVICE = Service()
