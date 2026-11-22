"""Tourism dataset cleaning and normalization helpers."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


NUMERIC_NAME_PATTERN = re.compile(
    r"(^|_)(latitude|longitude|rating|score|count|price|cost|"
    r"duration|distance|speed|temperature|humidity|rainfall|"
    r"altitude|visitors|budget|amount|adr|year|month|day|"
    r"nights|adults|children|babies|lead_time|index)(_|$)"
)
DATE_NAME_PATTERN = re.compile(r"(^date$|_date$|date_time|datetime)")
RATING_COLUMNS = {"rating", "avg_rating", "average_rating"}
COORDINATE_LIMITS = {"latitude": (-90, 90), "longitude": (-180, 180)}


def standardize_column_name(name: object) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "column"


def _unique_column_names(names: list[str]) -> list[str]:
    seen: Counter[str] = Counter()
    result = []
    for name in names:
        seen[name] += 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result


def _is_missing(series: pd.Series) -> pd.Series:
    missing = series.isna()
    if pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype):
        missing = missing | series.astype("string").str.strip().eq("").fillna(False)
    return missing


def missing_counts(frame: pd.DataFrame) -> dict[str, int]:
    names = _unique_column_names([standardize_column_name(name) for name in frame.columns])
    return {
        name: int(_is_missing(frame[original_name]).sum())
        for original_name, name in zip(frame.columns, names)
    }


def _clean_nested_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, str):
        value = value.strip()
        return pd.NA if not value else value
    return value


def _standardize_dates(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    failures = 0
    for name in frame.columns:
        if not DATE_NAME_PATTERN.search(name):
            continue
        series = frame[name]
        if not (
            pd.api.types.is_object_dtype(series.dtype)
            or pd.api.types.is_string_dtype(series.dtype)
        ):
            continue
        non_missing = ~_is_missing(series)
        if not non_missing.any():
            continue
        source = series[non_missing].astype("string")
        parsed = pd.to_datetime(source, errors="coerce", format="mixed")
        success = parsed.notna()
        if success.mean() < 0.85:
            continue
        failures += int((~success).sum())
        converted = pd.Series(pd.NA, index=frame.index, dtype="string")
        has_time = bool(source.str.contains(r"\d{1,2}:\d{2}").any())
        date_format = "%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d"
        converted.loc[non_missing[non_missing].index] = parsed.dt.strftime(date_format).to_numpy()
        frame[name] = converted
    return frame, failures


def _standardize_numerics(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    failures = 0
    for name in frame.columns:
        if not NUMERIC_NAME_PATTERN.search(name):
            continue
        series = frame[name]
        if pd.api.types.is_numeric_dtype(series.dtype):
            continue
        non_missing = ~_is_missing(series)
        if not non_missing.any():
            continue
        converted = pd.to_numeric(series, errors="coerce")
        failed = non_missing & converted.isna()
        if converted.notna().sum() / int(non_missing.sum()) >= 0.85:
            failures += int(failed.sum())
            frame[name] = converted
    return frame, failures


def invalid_value_counts(frame: pd.DataFrame) -> dict[str, int]:
    invalid: dict[str, int] = {}
    for name in frame.columns:
        series = frame[name]
        if name in RATING_COLUMNS:
            numeric = pd.to_numeric(series, errors="coerce")
            count = int((numeric.notna() & ~numeric.between(1, 5)).sum())
            if count:
                invalid[name] = count
        if name in COORDINATE_LIMITS:
            numeric = pd.to_numeric(series, errors="coerce")
            lower, upper = COORDINATE_LIMITS[name]
            count = int((numeric.notna() & ~numeric.between(lower, upper)).sum())
            if count:
                invalid[name] = count
        if name in {"visitor_count", "review_count", "lead_time"}:
            numeric = pd.to_numeric(series, errors="coerce")
            count = int((numeric.notna() & (numeric < 0)).sum())
            if count:
                invalid[name] = count
    return invalid


def clean_chunk(frame: pd.DataFrame, source_relative_path: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalize names, whitespace, parsable dates/numbers, and source lineage."""
    result = frame.copy()
    result.columns = _unique_column_names(
        [standardize_column_name(column) for column in result.columns]
    )
    for name in result.select_dtypes(include=["object", "string"]).columns:
        result[name] = result[name].map(_clean_nested_value)
    result, date_failures = _standardize_dates(result)
    result, numeric_failures = _standardize_numerics(result)
    invalid = invalid_value_counts(result)
    result["etl_source_file"] = source_relative_path
    return result, {
        "date_parse_failures": date_failures,
        "numeric_conversion_failures": numeric_failures,
        "invalid_values": invalid,
    }


def output_filename(source_path: Path, relative_path: Path) -> str:
    """Use clear canonical names for primary sources and unique names otherwise."""
    name = source_path.name.casefold()
    if name == "tourism_dataset.csv":
        return "cleaned_tourism.csv"
    if name == "india_tourism_dataset.json":
        return "cleaned_destinations.csv"
    if name == "hotel_bookings.csv":
        return "cleaned_hotel.csv"
    if name == "review_db.csv":
        return "cleaned_reviews.csv"
    if name == "tripadvisor_hotel_reviews.csv":
        return "cleaned_tripadvisor_hotel_reviews.csv"
    if name == "travel-times.csv":
        return "cleaned_transport.csv"
    if source_path.parent.name.casefold() == "weather data - 7":
        city = standardize_column_name(source_path.stem)
        return f"cleaned_weather_{city}.csv"
    parts = [standardize_column_name(part) for part in relative_path.with_suffix("").parts]
    return "cleaned_" + "_".join(parts) + ".csv"


def table_name_from_output(output_path: Path) -> str:
    return standardize_column_name(output_path.stem.removeprefix("cleaned_"))
