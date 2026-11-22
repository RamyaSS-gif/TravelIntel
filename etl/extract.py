"""Read supported source datasets without changing their original files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pandas as pd

from config import ETL_CHUNK_SIZE, EXCLUDED_ROOT_DIRECTORIES, SUPPORTED_SOURCE_EXTENSIONS


class MetadataOnlySource(Exception):
    """Raised when a supported file is metadata/code rather than tabular data."""


def discover_sources(root: Path) -> list[Path]:
    """Find supported source files while excluding project and output directories."""
    root = root.resolve()
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS
        and path.relative_to(root).parts
        and path.relative_to(root).parts[0].casefold() not in EXCLUDED_ROOT_DIRECTORIES
    )


def _csv_encoding(path: Path) -> str:
    with path.open("rb") as source:
        sample = source.read(256 * 1024)
    try:
        sample.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        try:
            from charset_normalizer import from_bytes
        except ImportError:
            return "cp1252"
        match = from_bytes(sample).best()
        return match.encoding if match else "cp1252"


def _records_from_json(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("data", "records", "items", "results", "destinations", "places"):
            if isinstance(value.get(key), list):
                return value[key]
        return [value]
    return [value]


def _flatten_record(record: object) -> dict[str, object]:
    if isinstance(record, dict):
        return pd.json_normalize(record, sep="_").to_dict(orient="records")[0]
    return {"value": record}


def _jsonl_columns(path: Path) -> list[str]:
    """Discover the union of JSONL fields before chunking sparse, wide records."""
    columns: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            columns.update(_flatten_record(record).keys())
    return sorted(columns)


def _read_jsonl(path: Path, chunk_size: int) -> Iterator[pd.DataFrame]:
    columns = _jsonl_columns(path)
    if not columns:
        yield pd.DataFrame()
        return
    effective_chunk_size = min(chunk_size, max(1, 2_000_000 // len(columns)))
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            rows.append(_flatten_record(json.loads(line)))
            if len(rows) >= effective_chunk_size:
                yield pd.DataFrame.from_records(rows, columns=columns)
                rows.clear()
        if rows:
            yield pd.DataFrame.from_records(rows, columns=columns)


def iter_source_frames(path: Path, chunk_size: int = ETL_CHUNK_SIZE) -> Iterator[pd.DataFrame]:
    """Yield DataFrame chunks for a source file; notebooks are never executed."""
    extension = path.suffix.lower()
    if extension == ".csv":
        encoding = _csv_encoding(path)
        reader = pd.read_csv(
            path,
            chunksize=chunk_size,
            low_memory=False,
            encoding=encoding,
        )
        yield from reader
        return

    if extension == ".jsonl":
        yield from _read_jsonl(path, chunk_size)
        return

    if extension == ".json":
        with path.open("r", encoding="utf-8-sig") as source:
            value = json.load(source)
        if isinstance(value, dict) and "$schema" in value and (
            "properties" in value or ("items" in value and "type" in value)
        ):
            raise MetadataOnlySource("JSON Schema document; not a data table.")
        records = [_flatten_record(record) for record in _records_from_json(value)]
        frame = pd.DataFrame.from_records(records)
        for start in range(0, len(frame), chunk_size):
            yield frame.iloc[start:start + chunk_size].copy()
        if frame.empty:
            yield frame
        return

    if extension == ".txt":
        lines: list[str] = []
        with path.open("r", encoding="utf-8-sig", errors="replace") as source:
            for line in source:
                lines.append(line.rstrip("\r\n"))
                if len(lines) >= chunk_size:
                    yield pd.DataFrame({"line": lines})
                    lines.clear()
        if lines:
            yield pd.DataFrame({"line": lines})
        elif path.stat().st_size == 0:
            yield pd.DataFrame({"line": pd.Series(dtype="string")})
        return

    if extension == ".ipynb":
        with path.open("r", encoding="utf-8-sig") as source:
            notebook = json.load(source)
        cells = notebook.get("cells", [])
        code_cells = sum(cell.get("cell_type") == "code" for cell in cells)
        raise MetadataOnlySource(
            f"Notebook metadata inspected ({len(cells)} cells, {code_cells} code cells); "
            "code was not executed."
        )

    if extension in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(path)
        for sheet_name in workbook.sheet_names:
            frame = pd.read_excel(workbook, sheet_name=sheet_name)
            frame["etl_source_sheet"] = sheet_name
            for start in range(0, len(frame), chunk_size):
                yield frame.iloc[start:start + chunk_size].copy()
            if frame.empty:
                yield frame
        return

    if extension == ".parquet":
        frame = pd.read_parquet(path)
        for start in range(0, len(frame), chunk_size):
            yield frame.iloc[start:start + chunk_size].copy()
        if frame.empty:
            yield frame
        return

    raise ValueError(f"Unsupported source format: {path.suffix or '(no extension)'}")
