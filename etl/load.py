"""Load cleaned CSVs into a new SQLite staging warehouse without overwriting."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from config import ETL_CHUNK_SIZE
from .transform import table_name_from_output

WIDE_TABLE_THRESHOLD = 1800


def _load_wide_chunk(
    frame: pd.DataFrame,
    connection: sqlite3.Connection,
    table_name: str,
    row_offset: int,
    create_table: bool,
) -> None:
    """Store sparse, high-dimensional records as (record, attribute, value) rows."""
    source_column = "etl_source_file" if "etl_source_file" in frame.columns else None
    value_columns = [column for column in frame.columns if column != source_column]
    if create_table:
        connection.execute(
            f'CREATE TABLE "{table_name}" ('
            "source_record_id INTEGER NOT NULL, attribute TEXT NOT NULL, "
            "value TEXT, etl_source_file TEXT NOT NULL)"
        )
    matrix = frame[value_columns].to_numpy(dtype=object, copy=False)
    row_positions, column_positions = pd.notna(matrix).nonzero()
    if len(row_positions) == 0:
        return
    if source_column:
        source_file = str(frame[source_column].iloc[0])
    else:
        source_file = ""
    long_frame = pd.DataFrame({
        "source_record_id": row_offset + row_positions,
        "attribute": pd.Index(value_columns).take(column_positions),
        "value": matrix[row_positions, column_positions].astype(str),
        "etl_source_file": source_file,
    })
    long_frame.to_sql(
        table_name,
        connection,
        if_exists="append",
        index=False,
        chunksize=5_000,
    )

def load_cleaned_csvs(
    run_dir: Path,
    database_path: Path,
    manifest: list[dict[str, object]],
    cleaned_files: list[Path] | None = None,
) -> int:
    """Create a SQLite database with one traceable table per cleaned source file."""
    if database_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {database_path}")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_files = sorted(cleaned_files or run_dir.glob("cleaned_*.csv"))
    if not cleaned_files:
        raise ValueError(f"No cleaned CSVs found in {run_dir}")

    connection = sqlite3.connect(database_path)
    manifest_columns = connection.execute("PRAGMA compile_options").fetchall()
    sqlite_column_limit = next(
        (
            int(option[0].split("=", 1)[1])
            for option in manifest_columns
            if option[0].startswith("MAX_COLUMN=")
        ),
        2_000,
    )
    wide_threshold = min(WIDE_TABLE_THRESHOLD, sqlite_column_limit - 16)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "CREATE TABLE etl_manifest ("
            "table_name TEXT PRIMARY KEY, source_file TEXT NOT NULL, "
            "output_file TEXT NOT NULL, rows_loaded INTEGER NOT NULL, "
            "storage_mode TEXT NOT NULL)"
        )
        for path in cleaned_files:
            table_name = table_name_from_output(path)
            rows_loaded = 0
            first_chunk = True
            storage_mode = ""
            column_count = len(pd.read_csv(path, nrows=0).columns)
            read_chunk_size = min(
                ETL_CHUNK_SIZE,
                max(1, 2_000_000 // max(1, column_count)),
            )
            with pd.read_csv(path, chunksize=read_chunk_size, low_memory=False) as reader:
                for frame in reader:
                    wide = len(frame.columns) > wide_threshold
                    if first_chunk:
                        storage_mode = "sparse_attribute_value" if wide else "columns"
                    if wide:
                        _load_wide_chunk(
                            frame,
                            connection,
                            table_name,
                            rows_loaded,
                            create_table=first_chunk,
                        )
                    else:
                        frame.to_sql(
                            table_name,
                            connection,
                            if_exists="fail" if first_chunk else "append",
                            index=False,
                            chunksize=5_000,
                        )
                    first_chunk = False
                    rows_loaded += len(frame)
            if first_chunk:
                raise ValueError(f"Cleaned file has no records and cannot be loaded: {path}")
            source_file = next(
                (
                    str(item.get("source_file", ""))
                    for item in manifest
                    if item.get("output_file") == path.name
                ),
                "",
            )
            connection.execute(
                "INSERT INTO etl_manifest "
                "(table_name, source_file, output_file, rows_loaded, storage_mode) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    table_name,
                    source_file,
                    path.name,
                    rows_loaded,
                    storage_mode,
                ),
            )
        connection.commit()
        return len(cleaned_files)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
