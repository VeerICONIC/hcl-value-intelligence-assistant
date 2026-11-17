"""Load and validate ``config/*.yaml`` (D10: config-driven loading).

Why typed models instead of raw dicts: a typo in the YAML (a missing key, a unit with
no multiplier, an alias listed under two measures) fails here, at start-up, with one
readable ``ConfigurationError``, instead of as a ``KeyError`` halfway through a pipeline run.

Matching rule used everywhere downstream: header names, metric names, measure names,
units and basis values are compared with ``norm_key`` (case-insensitive, trimmed).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from app.core.exceptions import ConfigurationError

CONFIG_FILES = ("metric_dictionary.yaml", "initiatives.yaml", "status_rules.yaml")
FILE_KEYS = ("initiatives", "weekly_usage", "financials")


def norm_key(text: object) -> str:
    """The one comparison key for names coming from raw files: trimmed, single-spaced, case-folded."""
    return " ".join(str(text).split()).casefold()


# --- metric_dictionary.yaml ------------------------------------------------------
class IdFormat(BaseModel):
    prefix: str
    digits: int


class DateRules(BaseModel):
    day_first: bool = True


class NumberRules(BaseModel):
    currency_symbols: list[str] = ["$"]
    thousands_separator: str = ","
    suffixes: dict[str, float] = {}


class FileSpec(BaseModel):
    filename: str
    sheet: str | None = None
    columns: dict[str, list[str]]          # canonical -> accepted header spellings
    required: list[str]
    defaults: dict[str, str] = {}

    @model_validator(mode="after")
    def _consistent(self) -> "FileSpec":
        unknown = [c for c in [*self.required, *self.defaults] if c not in self.columns]
        if unknown:
            raise ValueError(f"{self.filename}: required/defaults name unknown columns {unknown}")
        both = set(self.required) & set(self.defaults)
        if both:
            raise ValueError(f"{self.filename}: columns {sorted(both)} are both required and defaulted")
        seen: dict[str, str] = {}
        for canonical, aliases in self.columns.items():
            for spelling in [canonical, *aliases]:
                key = norm_key(spelling)
                if key in seen and seen[key] != canonical:
                    raise ValueError(f"{self.filename}: header {spelling!r} maps to both "
                                     f"{seen[key]!r} and {canonical!r}")
                seen[key] = canonical
        return self

    def header_map(self) -> dict[str, str]:
        """norm_key(header spelling) -> canonical column name."""
        return {norm_key(s): c for c, aliases in self.columns.items() for s in [c, *aliases]}


class UsageMetricSpec(BaseModel):
    aliases: list[str] = []


class MeasureSpec(BaseModel):
    role: Literal["benefit", "cost", "check_only"]
    aliases: list[str] = []


class UnitSpec(BaseModel):
    multiplier: float
    kind: Literal["money", "percent"]


class MetricDictionary(BaseModel):
    id_format: IdFormat
    dates: DateRules = DateRules()
    as_of: date | Literal["auto"] = "auto"
    week_length_days: int = 7
    days_per_month: float = 30.44
    numbers: NumberRules = NumberRules()
    allowed_currencies: list[str] = ["USD"]
    files: dict[str, FileSpec]
    usage_metrics: dict[str, UsageMetricSpec]
    financial_measures: dict[str, MeasureSpec]
    units: dict[str, UnitSpec]
    basis_values: list[Literal["cumulative", "monthly"]]
    reported_roi_tolerance_pct_points: float = 0.1

    @field_validator("files")
    @classmethod
    def _all_files(cls, v: dict[str, FileSpec]) -> dict[str, FileSpec]:
        missing = [k for k in FILE_KEYS if k not in v]
        if missing:
            raise ValueError(f"files: missing entries {missing}")
        return v

    @model_validator(mode="after")
    def _aliases_unique(self) -> "MetricDictionary":
        for label, specs in (("usage_metrics", self.usage_metrics), ("financial_measures", self.financial_measures)):
            seen: dict[str, str] = {}
            for canonical, spec in specs.items():
                for spelling in [canonical, *spec.aliases]:
                    key = norm_key(spelling)
                    if key in seen and seen[key] != canonical:
                        raise ValueError(f"{label}: {spelling!r} maps to both {seen[key]!r} and {canonical!r}")
                    seen[key] = canonical
        if self.days_per_month <= 0 or self.week_length_days <= 0:
            raise ValueError("days_per_month and week_length_days must be positive")
        return self

    def usage_metric_map(self) -> dict[str, str]:
        return {norm_key(s): c for c, sp in self.usage_metrics.items() for s in [c, *sp.aliases]}

    def measure_map(self) -> dict[str, str]:
        return {norm_key(s): c for c, sp in self.financial_measures.items() for s in [c, *sp.aliases]}

    def unit_map(self) -> dict[str, tuple[str, UnitSpec]]:
        return {norm_key(name): (name, spec) for name, spec in self.units.items()}


# --- initiatives.yaml ------------------------------------------------------------
class InitiativesConfig(BaseModel):
    canonical_names: dict[str, str] = {}
    name_acronyms: list[str] = []


# --- status_rules.yaml -----------------------------------------------------------
class RedRule(BaseModel):
    adoption_below: float
    roi_below: float


class GreenRule(BaseModel):
    adoption_at_least: float
    roi_above: float


class StatusRules(BaseModel):
    red_if_any: RedRule
    green_if_all: GreenRule


# --- bundle ----------------------------------------------------------------------
class PipelineConfig(BaseModel):
    metric_dictionary: MetricDictionary
    initiatives: InitiativesConfig
    status_rules: StatusRules
    source_files: list[Path]               # the YAML files read (hashed into the data version)


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigurationError(f"Missing configuration file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"{path.name} is not valid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path.name} must contain a mapping at the top level")
    return data


def load_pipeline_config(config_dir: Path) -> PipelineConfig:
    """Read and validate the three pipeline YAML files from ``config_dir``."""
    config_dir = Path(config_dir)
    paths = [config_dir / name for name in CONFIG_FILES]
    raw = [_read_yaml(p) for p in paths]
    models = (MetricDictionary, InitiativesConfig, StatusRules)
    parsed = []
    for path, data, model in zip(paths, raw, models):
        try:
            parsed.append(model.model_validate(data))
        except ValidationError as exc:
            lines = [f"Invalid {path.name}:"]
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"]) or "(top level)"
                lines.append(f"  - {loc}: {err['msg']}")
            raise ConfigurationError("\n".join(lines)) from None
    return PipelineConfig(metric_dictionary=parsed[0], initiatives=parsed[1], status_rules=parsed[2],
                          source_files=paths)
