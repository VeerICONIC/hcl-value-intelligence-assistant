"""Read the raw files exactly as supplied (FR-02, D10).

Design choices:
- **Everything is read as text** (``dtype=str``, no NA guessing). pandas would otherwise
  silently turn "1,000" into a string but 1000 into an int, read "07/09/2026" month-first,
  or turn "NA" into NaN. The cleaning rules decide how to read each cell, and log it.
- **Headers are mapped through config** (``files.<name>.columns`` in metric_dictionary.yaml),
  so a renamed column in the real data is a YAML edit, not a code change.
- **Every row keeps its source position** in ``_row`` (spreadsheet row number: the header
  is row 1, the first data row is row 2), so each change-log entry and each metric input
  points back to the exact cell an evaluator can open.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.core.exceptions import DataValidationError
from app.core.yaml_config import FileSpec, MetricDictionary, norm_key

logger = logging.getLogger(__name__)

ROW_COL = "_row"


@dataclass
class RawTable:
    """One raw file after header mapping. ``df`` holds canonical columns (all text) + ``_row``."""

    key: str            # "initiatives" | "weekly_usage" | "financials"
    filename: str
    path: Path
    df: pd.DataFrame


def _read(path: Path, spec: FileSpec) -> pd.DataFrame:
    if not path.is_file():
        raise DataValidationError(f"Missing data file: {path.name} (expected in {path.parent})")
    try:
        if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
            sheet = spec.sheet if spec.sheet is not None else 0
            df = pd.read_excel(path, sheet_name=sheet, dtype=str, keep_default_na=False)
        else:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        raise DataValidationError(f"Cannot read {path.name}: {exc}") from None
    return df.fillna("").astype(str)


def _map_headers(df: pd.DataFrame, spec: FileSpec) -> pd.DataFrame:
    header_map = spec.header_map()
    rename: dict[str, str] = {}
    ignored: list[str] = []
    for col in df.columns:
        canonical = header_map.get(norm_key(col))
        if canonical is None:
            ignored.append(str(col))
        elif canonical in rename.values():
            raise DataValidationError(
                f"{spec.filename}: more than one column maps to {canonical!r} (check columns in metric_dictionary.yaml)")
        else:
            rename[col] = canonical
    missing = [c for c in spec.required if c not in rename.values()]
    if missing:
        raise DataValidationError(
            f"{spec.filename}: missing required column(s) {missing}. Found {list(map(str, df.columns))}. "
            "Add the header spelling to files.<file>.columns in config/metric_dictionary.yaml.")
    if ignored:
        logger.info("%s: ignoring columns not in the metric dictionary: %s", spec.filename, ignored)
    out = df[list(rename)].rename(columns=rename)
    for col, default in spec.defaults.items():
        if col not in out.columns:
            out[col] = default
    return out


def load_table(raw_dir: Path, key: str, md: MetricDictionary) -> RawTable:
    spec = md.files[key]
    path = Path(raw_dir) / spec.filename
    df = _map_headers(_read(path, spec), spec)
    df = df.reset_index(drop=True)
    df[ROW_COL] = df.index + 2          # header is row 1
    return RawTable(key=key, filename=spec.filename, path=path, df=df)


def load_raw_tables(raw_dir: Path, md: MetricDictionary) -> dict[str, RawTable]:
    """Load initiatives, weekly usage and financials from ``raw_dir``."""
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        raise DataValidationError(f"Raw data folder not found: {raw_dir}")
    return {key: load_table(raw_dir, key, md) for key in ("initiatives", "weekly_usage", "financials")}
