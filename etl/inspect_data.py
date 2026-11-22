"""Build a memory-conscious inventory of the source archive."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


SUPPORTED_EXTENSIONS = {
    ".csv", ".xlsx", ".xls", ".json", ".jsonl", ".parquet", ".txt", ".ipynb"
}
CHUNK_SIZE = 50_000
SAMPLE_LIMIT = 5
EXCLUDED_ROOT_DIRECTORIES = {
    "etl", "warehouse", "olap", "analysis", "reports",
    "08_processed_data", "09_olap_outputs",
    "processed data - 8", "olap outputs - 9", "travelintel_project",
}


def json_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, str) and len(value) > 300:
        return value[:297] + "..."
    return value


def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def row_digest(values: Iterable[Any]) -> str:
    payload = encode_json([json_value(value) for value in values])
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def object_digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def insert_hashes(connection: sqlite3.Connection, source_id: str, digests: list[str]) -> None:
    connection.executemany(
        "INSERT OR IGNORE INTO row_hashes (source_id, digest) VALUES (?, ?)",
        ((source_id, digest) for digest in digests),
    )


def base_entry(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root)
    return {
        "dataset_name": relative.parent.name or root.name,
        "file_name": path.name,
        "relative_path": str(relative),
        "file_format": path.suffix.lower().lstrip(".") or "no extension",
        "file_size_bytes": path.stat().st_size,
        "record_count": None,
        "column_count": None,
        "column_names": [],
        "data_types": {},
        "missing_values": {},
        "duplicate_records": None,
        "sample_records": [],
        "inspection_status": "not inspected",
        "details": "",
    }


def inspect_tabular_rows(
    rows: Iterable[Iterable[Any]],
    headers: list[str],
    entry: dict[str, Any],
    connection: sqlite3.Connection,
    source_id: str,
) -> None:
    entry["column_names"] = headers
    entry["column_count"] = len(headers)
    entry["missing_values"] = dict.fromkeys(headers, 0)
    types: dict[str, set[str]] = defaultdict(set)
    samples: list[dict[str, Any]] = []
    row_count = 0
    batch: list[str] = []
    for row in rows:
        values = list(row[:len(headers)])
        if len(values) < len(headers):
            values.extend([None] * (len(headers) - len(values)))
        row_count += 1
        batch.append(row_digest(values))
        for index, name in enumerate(headers):
            value = values[index]
            if value is None or value == "":
                entry["missing_values"][name] += 1
            else:
                types[name].add(type(value).__name__)
        if len(samples) < SAMPLE_LIMIT:
            samples.append({name: json_value(values[index]) for index, name in enumerate(headers)})
        if len(batch) >= CHUNK_SIZE:
            insert_hashes(connection, source_id, batch)
            batch.clear()
    if batch:
        insert_hashes(connection, source_id, batch)
    entry["record_count"] = row_count
    entry["data_types"] = {
        name: "|".join(sorted(type_names)) if type_names else "unknown"
        for name, type_names in types.items()
    }
    entry["sample_records"] = samples
    unique_count = connection.execute(
        "SELECT COUNT(*) FROM row_hashes WHERE source_id = ?", (source_id,)
    ).fetchone()[0]
    entry["duplicate_records"] = row_count - unique_count
    entry["inspection_status"] = "ok"


def inspect_csv(path: Path, entry: dict[str, Any], connection: sqlite3.Connection, source_id: str) -> None:
    with path.open("rb") as file:
        prefix = file.read(256 * 1024)
    try:
        prefix.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        try:
            from charset_normalizer import from_bytes

            match = from_bytes(prefix).best()
            encoding = match.encoding if match else "cp1252"
        except ImportError:
            encoding = "cp1252"
        entry["details"] = f"Detected text encoding: {encoding}."

    samples: list[dict[str, Any]] = []
    missing: dict[str, int] = {}
    types: dict[str, set[str]] = defaultdict(set)
    records = 0
    for chunk in pd.read_csv(path, chunksize=CHUNK_SIZE, low_memory=False, encoding=encoding):
        headers = [str(column) for column in chunk.columns]
        if not missing:
            missing = dict.fromkeys(headers, 0)
            entry["column_names"] = headers
            entry["column_count"] = len(headers)
        missing_chunk = chunk.isna().sum()
        for name in headers:
            missing[name] += int(missing_chunk[name])
            types[name].add(str(chunk[name].dtype))
        if len(samples) < SAMPLE_LIMIT:
            remaining = SAMPLE_LIMIT - len(samples)
            samples.extend(
                {
                    str(name): json_value(value)
                    for name, value in sample.items()
                }
                for sample in chunk.head(remaining).to_dict(orient="records")
            )
        hashes = [
            row_digest(row)
            for row in chunk.itertuples(index=False, name=None)
        ]
        insert_hashes(connection, source_id, hashes)
        records += len(chunk)
    if not entry["column_names"]:
        header = pd.read_csv(path, nrows=0)
        entry["column_names"] = [str(column) for column in header.columns]
        entry["column_count"] = len(entry["column_names"])
        missing = dict.fromkeys(entry["column_names"], 0)
    entry["record_count"] = records
    entry["missing_values"] = missing
    entry["data_types"] = {
        name: "|".join(sorted(type_names)) if type_names else "unknown"
        for name, type_names in types.items()
    }
    entry["sample_records"] = samples
    unique_count = connection.execute(
        "SELECT COUNT(*) FROM row_hashes WHERE source_id = ?", (source_id,)
    ).fetchone()[0]
    entry["duplicate_records"] = records - unique_count
    entry["inspection_status"] = "ok"


def inspect_json(path: Path, entry: dict[str, Any], connection: sqlite3.Connection, source_id: str) -> None:
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = next(
            (data[key] for key in ("data", "records", "items", "results", "destinations", "places")
             if isinstance(data.get(key), list)),
            None,
        )
        if records is None:
            records = [data]
            entry["details"] = "JSON object treated as one record; nested structures are preserved."
    else:
        records = [data]
        entry["details"] = "Top-level JSON scalar treated as one record."

    if records and all(isinstance(record, dict) for record in records[:SAMPLE_LIMIT]):
        headers = sorted({str(key) for record in records[:1000] for key in record})
        rows = ([record.get(name) for name in headers] for record in records)
        inspect_tabular_rows(rows, headers, entry, connection, source_id)
        if entry["record_count"] != len(records):
            entry["record_count"] = len(records)
    else:
        entry["record_count"] = len(records)
        entry["column_count"] = 1 if records else 0
        entry["column_names"] = ["value"] if records else []
        entry["data_types"] = {
            "value": "|".join(sorted({type(value).__name__ for value in records[:1000]}))
        }
        entry["missing_values"] = {"value": sum(value is None for value in records)}
        for value in records:
            insert_hashes(connection, source_id, [row_digest([value])])
        entry["duplicate_records"] = len(records) - connection.execute(
            "SELECT COUNT(*) FROM row_hashes WHERE source_id = ?", (source_id,)
        ).fetchone()[0]
        entry["sample_records"] = [{"value": json_value(value)} for value in records[:SAMPLE_LIMIT]]
        entry["inspection_status"] = "ok"


def inspect_jsonl(path: Path, entry: dict[str, Any], connection: sqlite3.Connection, source_id: str) -> None:
    headers: list[str] = []
    samples: list[dict[str, Any]] = []
    types: dict[str, set[str]] = defaultdict(set)
    non_missing: dict[str, int] = defaultdict(int)
    count = 0
    batch: list[str] = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            count += 1
            if isinstance(record, dict):
                for key in record:
                    if key not in headers:
                        headers.append(str(key))
                for key, value in record.items():
                    if value is not None:
                        non_missing[str(key)] += 1
                        types[str(key)].add(type(value).__name__)
                batch.append(object_digest(record))
                if len(samples) < SAMPLE_LIMIT:
                    samples.append({str(key): json_value(value) for key, value in record.items()})
            else:
                if not headers:
                    headers = ["value"]
                types["value"].add(type(record).__name__)
                non_missing["value"] += int(record is not None)
                batch.append(object_digest(record))
                if len(samples) < SAMPLE_LIMIT:
                    samples.append({"value": json_value(record)})
            if len(batch) >= CHUNK_SIZE:
                insert_hashes(connection, source_id, batch)
                batch.clear()
    if batch:
        insert_hashes(connection, source_id, batch)
    entry["record_count"] = count
    entry["column_names"] = headers
    entry["column_count"] = len(headers)
    entry["data_types"] = {
        name: "|".join(sorted(type_names)) if type_names else "unknown"
        for name, type_names in types.items()
    }
    entry["missing_values"] = {
        name: count - non_missing[name]
        for name in headers
    }
    entry["sample_records"] = samples
    unique_count = connection.execute(
        "SELECT COUNT(*) FROM row_hashes WHERE source_id = ?", (source_id,)
    ).fetchone()[0]
    entry["duplicate_records"] = count - unique_count
    entry["inspection_status"] = "ok"


def inspect_text(path: Path, entry: dict[str, Any]) -> None:
    samples: list[dict[str, str]] = []
    records = 0
    with path.open("r", encoding="utf-8-sig", errors="replace") as file:
        for line in file:
            records += 1
            if len(samples) < SAMPLE_LIMIT:
                samples.append({"line": line.rstrip("\r\n")[:300]})
    entry.update({
        "record_count": records,
        "column_count": 1,
        "column_names": ["line"],
        "data_types": {"line": "string"},
        "missing_values": {},
        "duplicate_records": None,
        "sample_records": samples,
        "inspection_status": "ok",
        "details": "Plain-text line count; duplicate-row analysis is not applicable.",
    })


def inspect_notebook(path: Path, entry: dict[str, Any]) -> None:
    with path.open("r", encoding="utf-8-sig") as file:
        notebook = json.load(file)
    cells = notebook.get("cells", [])
    code = [cell for cell in cells if cell.get("cell_type") == "code"]
    snippets = []
    for cell in code:
        source = cell.get("source", [])
        text = "".join(source) if isinstance(source, list) else str(source)
        if text.strip() and len(snippets) < SAMPLE_LIMIT:
            snippets.append({"code": text[:300] + ("..." if len(text) > 300 else "")})
    metadata = notebook.get("metadata", {})
    entry.update({
        "record_count": None,
        "column_count": None,
        "column_names": [],
        "data_types": {"notebook": "Jupyter notebook"},
        "missing_values": {},
        "duplicate_records": None,
        "sample_records": snippets,
        "inspection_status": "ok",
        "details": (
            f"Notebook metadata keys: {', '.join(sorted(metadata.keys()))}; "
            f"{len(cells)} cells ({len(code)} code). Source inspected only; code was not executed."
        ),
    })


def inspect_excel(path: Path, entry: dict[str, Any], connection: sqlite3.Connection,
                  source_id: str) -> list[dict[str, Any]]:
    sheets: list[dict[str, Any]] = []
    if path.suffix.lower() == ".xlsx":
        try:
            import openpyxl
        except ImportError as error:
            entry["inspection_status"] = "error"
            entry["details"] = f"Cannot inspect XLSX worksheets: openpyxl is not installed ({error})."
            return [entry]
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for sheet_name in workbook.sheetnames:
            sheet_entry = dict(entry)
            sheet_entry["dataset_name"] = f"{entry['dataset_name']} / {sheet_name}"
            sheet_entry["details"] = f"Worksheet: {sheet_name}"
            rows = workbook[sheet_name].iter_rows(values_only=True)
            first = next(rows, ())
            headers = [str(value) if value is not None else f"column_{index + 1}"
                       for index, value in enumerate(first)]
            inspect_tabular_rows(rows, headers, sheet_entry, connection, f"{source_id}:{sheet_name}")
            sheets.append(sheet_entry)
        workbook.close()
        return sheets
    try:
        import xlrd
    except ImportError as error:
        entry["inspection_status"] = "error"
        entry["details"] = f"Cannot inspect XLS worksheets: xlrd is not installed ({error})."
        return [entry]
    workbook = xlrd.open_workbook(path, on_demand=True)
    for sheet in workbook.sheets():
        sheet_entry = dict(entry)
        sheet_entry["dataset_name"] = f"{entry['dataset_name']} / {sheet.name}"
        sheet_entry["details"] = f"Worksheet: {sheet.name}"
        headers = [str(value) for value in sheet.row_values(0)] if sheet.nrows else []
        rows = (sheet.row_values(index) for index in range(1, sheet.nrows))
        inspect_tabular_rows(rows, headers, sheet_entry, connection, f"{source_id}:{sheet.name}")
        sheets.append(sheet_entry)
    workbook.release_resources()
    return sheets


def inspect_parquet(path: Path, entry: dict[str, Any], connection: sqlite3.Connection,
                    source_id: str) -> None:
    try:
        import pyarrow.parquet as parquet
    except ImportError as error:
        entry["inspection_status"] = "error"
        entry["details"] = f"Cannot inspect Parquet row groups: pyarrow is not installed ({error})."
        return
    file = parquet.ParquetFile(path)
    headers = file.schema_arrow.names
    entry["column_names"] = headers
    entry["column_count"] = len(headers)
    entry["data_types"] = {field.name: str(field.type) for field in file.schema_arrow}
    entry["missing_values"] = dict.fromkeys(headers, 0)
    samples: list[dict[str, Any]] = []
    count = 0
    for batch in file.iter_batches(batch_size=CHUNK_SIZE):
        frame = batch.to_pandas()
        count += len(frame)
        for name, value in frame.isna().sum().items():
            entry["missing_values"][name] += int(value)
        if len(samples) < SAMPLE_LIMIT:
            samples.extend(json.loads(frame.head(SAMPLE_LIMIT - len(samples)).to_json(
                orient="records", date_format="iso", force_ascii=False
            )))
        insert_hashes(connection, source_id, [row_digest(row) for row in frame.itertuples(index=False, name=None)])
    unique_count = connection.execute(
        "SELECT COUNT(*) FROM row_hashes WHERE source_id = ?", (source_id,)
    ).fetchone()[0]
    entry["record_count"] = count
    entry["duplicate_records"] = count - unique_count
    entry["sample_records"] = samples
    entry["inspection_status"] = "ok"


def inspect_file(path: Path, root: Path, connection: sqlite3.Connection, source_id: str) -> list[dict[str, Any]]:
    entry = base_entry(path, root)
    extension = path.suffix.lower()
    try:
        if extension == ".csv":
            inspect_csv(path, entry, connection, source_id)
        elif extension == ".json":
            inspect_json(path, entry, connection, source_id)
        elif extension == ".jsonl":
            inspect_jsonl(path, entry, connection, source_id)
        elif extension == ".txt":
            inspect_text(path, entry)
        elif extension == ".ipynb":
            inspect_notebook(path, entry)
        elif extension in {".xlsx", ".xls"}:
            return inspect_excel(path, entry, connection, source_id)
        elif extension == ".parquet":
            inspect_parquet(path, entry, connection, source_id)
        else:
            entry["inspection_status"] = "unsupported"
            entry["details"] = "Non-tabular asset; file is listed but not parsed as a dataset."
    except Exception as error:
        entry["inspection_status"] = "error"
        entry["details"] = f"{type(error).__name__}: {error}"
    return [entry]


def write_reports(entries: list[dict[str, Any]], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / "dataset_inventory.csv"
    fields = [
        "dataset_name", "file_name", "relative_path", "file_format", "file_size_bytes",
        "record_count", "column_count", "column_names", "data_types", "missing_values",
        "duplicate_records", "sample_records", "inspection_status", "details",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for entry in entries:
            writer.writerow({
                key: encode_json(entry[key]) if isinstance(entry.get(key), (dict, list)) else entry.get(key)
                for key in fields
            })

    txt_path = report_dir / "dataset_inventory.txt"
    with txt_path.open("w", encoding="utf-8") as file:
        file.write("TravelIntel Dataset Inventory\n")
        file.write("=" * 80 + "\n")
        file.write(f"Files inventoried: {len(entries)}\n")
        file.write(f"Successfully inspected: {sum(item['inspection_status'] == 'ok' for item in entries)}\n")
        file.write(f"Unsupported non-tabular assets: {sum(item['inspection_status'] == 'unsupported' for item in entries)}\n")
        file.write(f"Inspection errors: {sum(item['inspection_status'] == 'error' for item in entries)}\n\n")
        for entry in entries:
            file.write(f"Dataset: {entry['dataset_name']}\n")
            file.write(f"File: {entry['relative_path']}\n")
            file.write(f"Format: {entry['file_format']} | Size: {entry['file_size_bytes']:,} bytes\n")
            file.write(
                f"Records: {entry['record_count']} | Columns: {entry['column_count']} "
                f"| Duplicates: {entry['duplicate_records']}\n"
            )
            file.write(f"Columns: {encode_json(entry['column_names'])}\n")
            file.write(f"Data types: {encode_json(entry['data_types'])}\n")
            file.write(f"Missing values: {encode_json(entry['missing_values'])}\n")
            file.write(f"Sample records: {encode_json(entry['sample_records'])}\n")
            file.write(f"Status: {entry['inspection_status']}")
            if entry["details"]:
                file.write(f" | {entry['details']}")
            file.write("\n" + "-" * 80 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    project_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--source", type=Path, default=project_root)
    parser.add_argument(
        "--reports", type=Path,
        default=project_root / "reports",
    )
    args = parser.parse_args()
    root = args.source.resolve()
    if not root.is_dir():
        parser.error(f"Source archive does not exist or is not a directory: {root}")

    files = sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and (path.relative_to(root).parts[0].casefold() not in EXCLUDED_ROOT_DIRECTORIES)
    )
    entries: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="travelintel_inventory_") as temporary_dir:
        connection = sqlite3.connect(os.path.join(temporary_dir, "row_hashes.sqlite"))
        connection.execute(
            "CREATE TABLE row_hashes (source_id TEXT NOT NULL, digest TEXT NOT NULL, "
            "PRIMARY KEY (source_id, digest))"
        )
        for index, path in enumerate(files):
            source_id = str(index)
            records = inspect_file(path, root, connection, source_id)
            entries.extend(records)
            print(f"[{index + 1}/{len(files)}] {path.relative_to(root)}: {records[0]['inspection_status']}")
        connection.close()

    write_reports(entries, args.reports.resolve())
    print(f"\nCSV report: {args.reports.resolve() / 'dataset_inventory.csv'}")
    print(f"TXT report: {args.reports.resolve() / 'dataset_inventory.txt'}")
    print(f"Inspected {len(entries)} inventory entries from {len(files)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
