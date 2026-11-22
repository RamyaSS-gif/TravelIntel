"""Run TravelIntel extraction, cleaning, integration checks, and loading."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config import PROCESSED_ROOT, PROJECT_ROOT, REPORTS_ROOT
from .extract import MetadataOnlySource, discover_sources, iter_source_frames
from .integrate import write_integration_report
from .load import load_cleaned_csvs
from .transform import clean_chunk, missing_counts, output_filename


def _unique_run_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    prefix = datetime.now().strftime("etl_run_%Y%m%d_%H%M%S")
    for suffix in range(1000):
        name = prefix if suffix == 0 else f"{prefix}_{suffix:03d}"
        path = root / name
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue
    raise FileExistsError(f"Unable to create a unique ETL run directory in {root}")


def _unique_report_path(root: Path, filename: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = root / f"{stem}_{stamp}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = root / f"{stem}_{stamp}_{counter:03d}{suffix}"
        counter += 1
    return candidate


def _json_count(values: dict[str, int]) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def _merge_counts(target: Counter[str], values: dict[str, int]) -> None:
    target.update(values)


def _row_hashes(frame: pd.DataFrame) -> pd.Series:
    return pd.util.hash_pandas_object(frame, index=False, categorize=True).map(
        lambda value: f"{int(value):016x}"
    )


def _deduplicate_chunk(
    frame: pd.DataFrame,
    connection: sqlite3.Connection,
    source_id: str,
) -> tuple[pd.DataFrame, int]:
    before = len(frame)
    frame = frame.drop_duplicates(keep="first")
    local_duplicates = before - len(frame)
    if frame.empty:
        return frame, local_duplicates

    hashes = _row_hashes(frame)
    connection.execute("DELETE FROM incoming_hashes")
    connection.executemany(
        "INSERT OR IGNORE INTO incoming_hashes (row_number, row_hash) VALUES (?, ?)",
        ((index, digest) for index, digest in enumerate(hashes)),
    )
    unique_indices = [
        row[0]
        for row in connection.execute(
            "SELECT i.row_number FROM incoming_hashes AS i "
            "LEFT JOIN seen_hashes AS s "
            "ON s.source_id = ? AND s.row_hash = i.row_hash "
            "WHERE s.row_hash IS NULL ORDER BY i.row_number",
            (source_id,),
        )
    ]
    unique_hashes = hashes.iloc[unique_indices]
    connection.executemany(
        "INSERT OR IGNORE INTO seen_hashes (source_id, row_hash) VALUES (?, ?)",
        ((source_id, digest) for digest in unique_hashes),
    )
    result = frame.iloc[unique_indices].copy()
    return result, before - len(result)


def _quality_csv_path(root: Path) -> Path:
    return _unique_report_path(root, "data_quality_report.csv")


def _write_quality_reports(
    report_root: Path,
    summaries: list[dict[str, Any]],
    column_rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    summary_path = _quality_csv_path(report_root)
    fields = [
        "source_file", "output_file", "status", "rows_before", "rows_after",
        "columns_before", "columns_after", "duplicates_removed",
        "missing_values_before", "missing_values_after", "invalid_values",
        "date_parse_failures", "numeric_conversion_failures", "details",
    ]
    with summary_path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in summaries:
            writer.writerow({
                **row,
                "missing_values_before": _json_count(row["missing_values_before"]),
                "missing_values_after": _json_count(row["missing_values_after"]),
                "invalid_values": _json_count(row["invalid_values"]),
            })

    column_path = _unique_report_path(report_root, "data_quality_columns.csv")
    column_fields = [
        "source_file", "column_name", "missing_before", "missing_after",
        "data_type_after",
    ]
    with column_path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=column_fields)
        writer.writeheader()
        writer.writerows(column_rows)
    return summary_path, column_path


def _process_source(
    source: Path,
    run_dir: Path,
    root: Path,
    connection: sqlite3.Connection,
) -> tuple[dict[str, Any], dict[str, Path] | None, list[dict[str, Any]]]:
    relative = source.relative_to(root)
    source_key = str(relative)
    output_name = output_filename(source, relative)
    output_path = run_dir / output_name
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output_path}")

    summary: dict[str, Any] = {
        "source_file": source_key,
        "output_file": "",
        "status": "in_progress",
        "rows_before": 0,
        "rows_after": 0,
        "columns_before": 0,
        "columns_after": 0,
        "duplicates_removed": 0,
        "missing_values_before": Counter(),
        "missing_values_after": Counter(),
        "invalid_values": Counter(),
        "date_parse_failures": 0,
        "numeric_conversion_failures": 0,
        "details": "",
    }
    column_types: dict[str, str] = {}
    wrote_header = False
    source_id = source_key
    try:
        for raw_frame in iter_source_frames(source):
            summary["rows_before"] += len(raw_frame)
            summary["columns_before"] = max(summary["columns_before"], len(raw_frame.columns))
            _merge_counts(summary["missing_values_before"], missing_counts(raw_frame))

            cleaned, transform_metrics = clean_chunk(raw_frame, source_key)
            summary["date_parse_failures"] += transform_metrics["date_parse_failures"]
            summary["numeric_conversion_failures"] += transform_metrics["numeric_conversion_failures"]
            _merge_counts(summary["invalid_values"], transform_metrics["invalid_values"])
            summary["columns_after"] = max(summary["columns_after"], len(cleaned.columns))
            for name, dtype in cleaned.dtypes.items():
                column_types[str(name)] = str(dtype)

            unique, duplicate_count = _deduplicate_chunk(cleaned, connection, source_id)
            summary["duplicates_removed"] += duplicate_count
            if not unique.empty:
                _merge_counts(summary["missing_values_after"], missing_counts(unique))
                unique.to_csv(
                    output_path,
                    mode="a",
                    index=False,
                    header=not wrote_header,
                    encoding="utf-8",
                    na_rep="",
                )
                wrote_header = True
                summary["rows_after"] += len(unique)
        if not wrote_header:
            summary["status"] = "empty"
            summary["details"] = "No data rows were produced; no cleaned CSV was written."
            return summary, None, []

        summary["status"] = "success"
        summary["output_file"] = output_name
        columns = [
            {
                "source_file": source_key,
                "column_name": name,
                "missing_before": summary["missing_values_before"].get(name, 0),
                "missing_after": summary["missing_values_after"].get(name, 0),
                "data_type_after": column_types.get(name, "unknown"),
            }
            for name in sorted(
                set(summary["missing_values_before"]) | set(summary["missing_values_after"]) | set(column_types)
            )
        ]
        return summary, {output_name: output_path}, columns
    except MetadataOnlySource as error:
        summary["status"] = "metadata_only"
        summary["details"] = str(error)
        return summary, None, []
    except Exception as error:
        summary["status"] = "error"
        summary["details"] = f"{type(error).__name__}: {error}"
        return summary, None, []


def _write_extraction_report(path: Path, summaries: list[dict[str, Any]]) -> None:
    fields = ["source_file", "status", "rows_before", "columns_before", "output_file", "details"]
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in summaries)


def _write_summary(
    path: Path,
    root: Path,
    run_dir: Path,
    source_count: int,
    summaries: list[dict[str, Any]],
    database_path: Path | None,
    database_tables: int,
    database_error: str,
    integration_summary: str,
    report_paths: list[Path],
) -> None:
    statuses = Counter(str(row["status"]) for row in summaries)
    with path.open("w", encoding="utf-8") as output:
        output.write("TravelIntel ETL Run Summary\n")
        output.write("=" * 72 + "\n")
        output.write(f"Run timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        output.write(f"Source root: {root}\n")
        output.write(f"Output directory: {run_dir}\n")
        output.write(f"Source files discovered: {source_count}\n")
        output.write(f"Successful cleaned datasets: {statuses.get('success', 0)}\n")
        output.write(f"Metadata-only sources: {statuses.get('metadata_only', 0)}\n")
        output.write(f"Empty sources: {statuses.get('empty', 0)}\n")
        output.write(f"Failed sources: {statuses.get('error', 0)}\n\n")
        output.write("Per-source results\n")
        output.write("-" * 72 + "\n")
        for row in summaries:
            output.write(
                f"{row['source_file']}: {row['status']}; {row['rows_before']} input rows; "
                f"{row['rows_after']} output rows; {row['duplicates_removed']} duplicates removed.\n"
            )
            if row["details"]:
                output.write(f"  Details: {row['details']}\n")
        output.write("\nLoading\n")
        output.write("-" * 72 + "\n")
        if database_path:
            output.write(f"SQLite database: {database_path}\n")
            output.write(f"Cleaned tables loaded: {database_tables}\n")
            if database_error:
                output.write(f"SQLite load failed; the incomplete database was preserved: {database_error}\n")
        else:
            output.write("SQLite database was not created.\n")
            if database_error:
                output.write(f"SQLite load error: {database_error}\n")
        output.write("\nIntegration decision\n")
        output.write("-" * 72 + "\n")
        output.write(integration_summary + "\n")
        output.write("\nReports\n")
        for report in report_paths:
            output.write(f"- {report}\n")


def run_pipeline(root: Path = PROJECT_ROOT) -> int:
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Source root is not a directory: {root}")
    sources = discover_sources(root)
    if not sources:
        raise FileNotFoundError(f"No supported source files found in {root}")

    run_dir = _unique_run_directory(PROCESSED_ROOT)
    with tempfile.TemporaryDirectory(prefix="travelintel_etl_") as temporary_dir:
        connection = sqlite3.connect(Path(temporary_dir) / "dedup.sqlite")
        connection.execute(
            "CREATE TABLE seen_hashes (source_id TEXT NOT NULL, row_hash TEXT NOT NULL, "
            "PRIMARY KEY (source_id, row_hash))"
        )
        connection.execute(
            "CREATE TEMP TABLE incoming_hashes (row_number INTEGER PRIMARY KEY, row_hash TEXT UNIQUE)"
        )
        summaries: list[dict[str, Any]] = []
        output_files: dict[str, Path] = {}
        column_rows: list[dict[str, Any]] = []
        for index, source in enumerate(sources, start=1):
            summary, outputs, columns = _process_source(source, run_dir, root, connection)
            summaries.append(summary)
            column_rows.extend(columns)
            if outputs:
                output_files.update(outputs)
            print(
                f"[{index}/{len(sources)}] {summary['source_file']}: "
                f"{summary['status']} ({summary['rows_before']} rows)"
            )
        connection.close()

    extraction_path = run_dir / "extraction_report.csv"
    _write_extraction_report(extraction_path, summaries)
    integration_path, integration_summary = write_integration_report(run_dir, output_files)
    quality_path, column_quality_path = _write_quality_reports(REPORTS_ROOT, summaries, column_rows)

    successful = [item for item in summaries if item["status"] == "success"]
    failed = [item for item in summaries if item["status"] == "error"]
    database_path: Path | None = None
    database_tables = 0
    database_error = ""
    if successful:
        candidate_database_path = run_dir / "travelintel_warehouse.db"
        try:
            database_tables = load_cleaned_csvs(
                run_dir,
                candidate_database_path,
                summaries,
                list(output_files.values()),
            )
            database_path = candidate_database_path
        except Exception as error:
            database_error = f"{type(error).__name__}: {error}"
            print(f"SQLite load failed: {database_error}")
            failed.append({"source_file": "SQLite load", "details": database_error})
            if candidate_database_path.exists():
                database_path = candidate_database_path

    report_paths = [extraction_path, integration_path, quality_path, column_quality_path]
    summary_path = _unique_report_path(REPORTS_ROOT, "etl_summary.txt")
    _write_summary(
        summary_path,
        root,
        run_dir,
        len(sources),
        summaries,
        database_path,
        database_tables,
        database_error,
        integration_summary,
        report_paths,
    )
    print(f"\nETL output directory: {run_dir}")
    print(f"Quality report: {quality_path}")
    print(f"ETL summary: {summary_path}")
    if database_path:
        print(f"SQLite database: {database_path} ({database_tables} tables)")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    return run_pipeline(args.source)


if __name__ == "__main__":
    raise SystemExit(main())
