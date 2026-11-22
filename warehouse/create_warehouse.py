"""Build a constrained SQLite warehouse from one completed ETL run."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from config import PROJECT_ROOT, REPORTS_ROOT


AIRBNB_CITIES = ("boston", "seattle")
AIRBNB_KINDS = ("listings", "calendar", "reviews")
TOURISM_METRICS = (
    "latitude", "longitude", "avg_rating", "review_text", "sentiment_score",
    "visitor_count", "avg_cost", "accessibility", "safety_index", "seasonality",
    "popularity_index", "avg_stay_duration", "transport_score", "accommodation_score",
    "cultural_score", "natural_score", "infrastructure_score", "cleanliness_score",
    "season_peak_factor", "return_rate", "review_count", "attractiveness_label",
)


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def table_name_for_file(path: Path) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", path.stem.removeprefix("cleaned_")).strip("_").lower()
    if not name or name[0].isdigit():
        name = f"source_{name}"
    return f"stg_{name}"


def latest_etl_run(processed_root: Path) -> Path:
    runs = sorted(
        (path for path in processed_root.glob("etl_run_*") if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    for run in runs:
        if any(run.glob("cleaned_*.csv")) and (run / "extraction_report.csv").is_file():
            return run
    raise FileNotFoundError(f"No completed ETL run with cleaned CSVs found in {processed_root}")


def _column_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series.dtype) or pd.api.types.is_integer_dtype(series.dtype):
        return "INTEGER"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "REAL"
    return "TEXT"


def _batch_rows(path: Path, chunk_size: int, columns: list[str] | None = None) -> Iterator[pd.DataFrame]:
    reader = pd.read_csv(
        path,
        chunksize=chunk_size,
        low_memory=False,
        usecols=columns,
    )
    with reader:
        yield from reader


def _load_regular_source(
    connection: sqlite3.Connection,
    path: Path,
    table_name: str,
    chunk_size: int,
) -> tuple[int, list[str]]:
    headers = list(pd.read_csv(path, nrows=0).columns)
    if "warehouse_source_row_id" in headers:
        raise ValueError(f"Reserved warehouse field occurs in cleaned source: {path}")
    first_frame = next(_batch_rows(path, chunk_size), None)
    if first_frame is None:
        raise ValueError(f"Cleaned source contains no rows: {path}")

    definitions = ['"warehouse_source_row_id" INTEGER PRIMARY KEY']
    definitions.extend(
        f"{quote_identifier(str(column))} {_column_type(first_frame[column])}"
        for column in headers
    )
    connection.execute(
        f"CREATE TABLE {quote_identifier(table_name)} ({', '.join(definitions)})"
    )
    insert_columns = ["warehouse_source_row_id"] + headers
    placeholders = ", ".join("?" for _ in insert_columns)
    insert_sql = (
        f"INSERT INTO {quote_identifier(table_name)} "
        f"({', '.join(quote_identifier(column) for column in insert_columns)}) "
        f"VALUES ({placeholders})"
    )

    row_id = 0
    for frame in _batch_rows(path, chunk_size):
        values = []
        for row in frame.itertuples(index=False, name=None):
            row_id += 1
            values.append((row_id, *(_sqlite_value(value) for value in row)))
        connection.executemany(insert_sql, values)
    return row_id, headers


def _load_wide_source(
    connection: sqlite3.Connection,
    path: Path,
    table_name: str,
    chunk_size: int,
) -> tuple[int, int, list[str]]:
    headers = list(pd.read_csv(path, nrows=0).columns)
    records_table = f"{table_name}_records"
    attributes_table = f"{table_name}_attributes"
    connection.execute(
        f"CREATE TABLE {quote_identifier(records_table)} ("
        "warehouse_source_row_id INTEGER PRIMARY KEY, etl_source_file TEXT)"
    )
    connection.execute(
        f"CREATE TABLE {quote_identifier(attributes_table)} ("
        "warehouse_source_row_id INTEGER NOT NULL, attribute TEXT NOT NULL, value TEXT, "
        f"PRIMARY KEY (warehouse_source_row_id, attribute), "
        f"FOREIGN KEY (warehouse_source_row_id) REFERENCES {quote_identifier(records_table)}"
        "(warehouse_source_row_id))"
    )
    row_id = 0
    attribute_count = 0
    for frame in _batch_rows(path, chunk_size):
        source_values = (
            frame["etl_source_file"].fillna("").astype(str).tolist()
            if "etl_source_file" in frame.columns
            else [""] * len(frame)
        )
        record_rows = []
        attribute_rows = []
        for offset, row in enumerate(frame.itertuples(index=False, name=None)):
            row_id += 1
            record_rows.append((row_id, source_values[offset]))
            for name, value in zip(headers, row):
                if name == "etl_source_file" or _is_null(value):
                    continue
                attribute_rows.append((row_id, str(name), str(value)))
        connection.executemany(
            f"INSERT INTO {quote_identifier(records_table)} "
            "(warehouse_source_row_id, etl_source_file) VALUES (?, ?)",
            record_rows,
        )
        connection.executemany(
            f"INSERT INTO {quote_identifier(attributes_table)} "
            "(warehouse_source_row_id, attribute, value) VALUES (?, ?, ?)",
            attribute_rows,
        )
        attribute_count += len(attribute_rows)
    return row_id, attribute_count, headers


def _is_null(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _sqlite_value(value: Any) -> Any:
    if _is_null(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, float) and not pd.notna(value):
        return None
    return value


def _insert_manifest(
    connection: sqlite3.Connection,
    source_path: Path,
    output_file: str,
    table_name: str,
    attribute_table_name: str | None,
    rows_loaded: int,
    attribute_values_loaded: int,
    storage_mode: str,
) -> None:
    connection.execute(
        "INSERT INTO warehouse_manifest "
        "(source_file, output_file, table_name, attribute_table_name, rows_loaded, "
        "attribute_values_loaded, storage_mode) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            source_file_for_output(source_path, output_file),
            output_file,
            table_name,
            attribute_table_name,
            rows_loaded,
            attribute_values_loaded,
            storage_mode,
        ),
    )


def source_file_for_output(run_dir: Path, output_file: str) -> str:
    report_path = run_dir / "extraction_report.csv"
    with report_path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if row.get("output_file") == output_file:
                return row.get("source_file", "")
    return ""


def _stage_sources(
    connection: sqlite3.Connection,
    run_dir: Path,
    chunk_size: int,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    output_to_table: dict[str, str] = {}
    source_summaries: list[dict[str, Any]] = []
    cleaned_files = sorted(run_dir.glob("cleaned_*.csv"))
    if not cleaned_files:
        raise FileNotFoundError(f"No cleaned CSV files found in {run_dir}")
    max_columns = int(next(
        (
            option[0].split("=", 1)[1]
            for option in connection.execute("PRAGMA compile_options")
            if option[0].startswith("MAX_COLUMN=")
        ),
        2_000,
    ))
    for path in cleaned_files:
        table_name = table_name_for_file(path)
        if table_name in output_to_table.values():
            raise ValueError(f"Duplicate staging table name for cleaned file {path.name}")
        column_count = len(pd.read_csv(path, nrows=0).columns)
        wide = column_count > min(1_800, max_columns - 16)
        safe_chunk_size = min(chunk_size, max(1, 2_000_000 // max(1, column_count)))
        if wide:
            rows, attribute_count, _ = _load_wide_source(
                connection, path, table_name, safe_chunk_size
            )
            attribute_table = f"{table_name}_attributes"
            row_table = f"{table_name}_records"
            _insert_manifest(
                connection, run_dir, path.name, row_table, attribute_table,
                rows, attribute_count, "sparse_attribute_value",
            )
            output_to_table[path.name] = row_table
            source_summaries.append({
                "output_file": path.name,
                "table_name": row_table,
                "attribute_table_name": attribute_table,
                "rows_loaded": rows,
                "attribute_values_loaded": attribute_count,
                "storage_mode": "sparse_attribute_value",
            })
        else:
            rows, _ = _load_regular_source(connection, path, table_name, safe_chunk_size)
            _insert_manifest(
                connection, run_dir, path.name, table_name, None,
                rows, 0, "columns",
            )
            output_to_table[path.name] = table_name
            source_summaries.append({
                "output_file": path.name,
                "table_name": table_name,
                "attribute_table_name": "",
                "rows_loaded": rows,
                "attribute_values_loaded": 0,
                "storage_mode": "columns",
            })
    return output_to_table, source_summaries


def _parse_iso_date(value: object) -> date | None:
    if _is_null(value):
        return None
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _source_table(output_to_table: dict[str, str], output_file: str) -> str:
    try:
        return output_to_table[output_file]
    except KeyError as error:
        raise ValueError(f"Required cleaned dataset is missing: {output_file}") from error


def _build_date_dimension(
    connection: sqlite3.Connection,
    output_to_table: dict[str, str],
) -> tuple[dict[str, int], dict[str, int]]:
    dates: set[date] = set()
    invalid_counts: dict[str, int] = defaultdict(int)

    def consume(table: str, column: str, label: str) -> None:
        if not _has_column(connection, table, column):
            return
        cursor = connection.execute(
            f"SELECT {quote_identifier(column)} FROM {quote_identifier(table)}"
        )
        for (value,) in cursor:
            parsed = _parse_iso_date(value)
            if parsed is None:
                if not _is_null(value):
                    invalid_counts[label] += 1
            else:
                dates.add(parsed)

    hotel_table = _source_table(output_to_table, "cleaned_hotel.csv")
    for year, month, day_value in connection.execute(
        f"SELECT arrival_date_year, arrival_date_month, arrival_date_day_of_month "
        f"FROM {quote_identifier(hotel_table)}"
    ):
        try:
            parsed = datetime.strptime(
                f"{int(year)} {month} {int(day_value)}", "%Y %B %d"
            ).date()
            dates.add(parsed)
        except (TypeError, ValueError):
            invalid_counts["hotel_arrival_date"] += 1
    consume(hotel_table, "reservation_status_date", "hotel_reservation_status_date")
    consume(_source_table(output_to_table, "cleaned_transport.csv"), "date", "transport_date")
    for city in AIRBNB_CITIES:
        for kind in ("calendar", "reviews"):
            table = _source_table(
                output_to_table,
                f"cleaned_hotel_accomodation_3_{city}_airbnb_open_data_{kind}.csv",
            )
            consume(table, "date", f"{city}_{kind}_date")

    date_lookup: dict[str, int] = {}
    rows = []
    for value in sorted(dates):
        date_text = value.isoformat()
        date_key = value.year * 10000 + value.month * 100 + value.day
        date_lookup[date_text] = date_key
        rows.append((
            date_key, date_text, value.year, (value.month - 1) // 3 + 1,
            value.month, value.day, value.weekday(), value.strftime("%A"),
        ))
    connection.executemany(
        "INSERT INTO dim_date "
        "(date_key, date_value, year, quarter, month, day, weekday, weekday_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return date_lookup, dict(invalid_counts)


def _has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in connection.execute(
        f"PRAGMA table_info({quote_identifier(table)})"
    ))


def _build_hotel_facts(
    connection: sqlite3.Connection,
    output_to_table: dict[str, str],
) -> int:
    table = _source_table(output_to_table, "cleaned_hotel.csv")
    hotels = [
        row[0] for row in connection.execute(
            f"SELECT DISTINCT hotel FROM {quote_identifier(table)} "
            "WHERE hotel IS NOT NULL ORDER BY hotel"
        )
    ]
    connection.executemany(
        "INSERT INTO dim_hotel_type (hotel_type) VALUES (?)",
        ((hotel,) for hotel in hotels),
    )
    hotel_keys = {
        hotel: key for key, hotel in connection.execute(
            "SELECT hotel_key, hotel_type FROM dim_hotel_type"
        )
    }
    rows = []
    cursor = connection.execute(
        f"SELECT warehouse_source_row_id, hotel, is_canceled, lead_time, "
        "arrival_date_year, arrival_date_month, arrival_date_day_of_month, "
        "stays_in_weekend_nights, stays_in_week_nights, adults, children, babies, "
        "previous_cancellations, previous_bookings_not_canceled, booking_changes, "
        "days_in_waiting_list, adr, required_car_parking_spaces, "
        "total_of_special_requests, market_segment, distribution_channel, "
        "customer_type, reservation_status "
        f"FROM {quote_identifier(table)}"
    )
    for row in cursor:
        (
            source_id, hotel, canceled, lead_time, year, month, arrival_day,
            weekend, week_nights, adults, children, babies, previous_cancel,
            previous_bookings, changes, waiting, adr, parking, special,
            market, channel, customer_type, status,
        ) = row
        try:
            arrival = datetime.strptime(
                f"{int(year)} {month} {int(arrival_day)}", "%Y %B %d"
            ).date()
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid booking arrival date at source row {source_id}") from error
        date_key = arrival.year * 10000 + arrival.month * 100 + arrival.day
        rows.append((
            source_id, date_key, hotel_keys[hotel], canceled, lead_time,
            weekend, week_nights, adults, children, babies, previous_cancel,
            previous_bookings, changes, waiting, adr, parking, special,
            market, channel, customer_type, status,
        ))
        if len(rows) >= 10_000:
            connection.executemany(
                "INSERT INTO fact_hotel_booking "
                "(source_row_id, date_key, hotel_key, is_canceled, lead_time, "
                "stays_in_weekend_nights, stays_in_week_nights, adults, children, babies, "
                "previous_cancellations, previous_bookings_not_canceled, booking_changes, "
                "days_in_waiting_list, adr, required_car_parking_spaces, "
                "total_of_special_requests, market_segment, distribution_channel, "
                "customer_type, reservation_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            rows.clear()
    if rows:
        connection.executemany(
            "INSERT INTO fact_hotel_booking "
            "(source_row_id, date_key, hotel_key, is_canceled, lead_time, "
            "stays_in_weekend_nights, stays_in_week_nights, adults, children, babies, "
            "previous_cancellations, previous_bookings_not_canceled, booking_changes, "
            "days_in_waiting_list, adr, required_car_parking_spaces, "
            "total_of_special_requests, market_segment, distribution_channel, "
            "customer_type, reservation_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(hotels)


def _build_airbnb_dimensions(
    connection: sqlite3.Connection,
    output_to_table: dict[str, str],
) -> dict[tuple[str, int], int]:
    listing_keys: dict[tuple[str, int], int] = {}
    for city in AIRBNB_CITIES:
        table = _source_table(
            output_to_table,
            f"cleaned_hotel_accomodation_3_{city}_airbnb_open_data_listings.csv",
        )
        columns = {row[1] for row in connection.execute(
            f"PRAGMA table_info({quote_identifier(table)})"
        )}
        selected = [
            "warehouse_source_row_id", "id", "name", "neighbourhood_cleansed",
            "property_type", "room_type", "accommodates", "bedrooms", "beds",
            "price", "number_of_reviews", "review_scores_rating",
        ]
        missing = [column for column in selected if column not in columns]
        if missing:
            raise ValueError(f"{table} is missing required listing columns: {missing}")
        cursor = connection.execute(
            f"SELECT {', '.join(quote_identifier(column) for column in selected)} "
            f"FROM {quote_identifier(table)}"
        )
        source_count = 0
        for row in cursor:
            (
                source_row_id, listing_id, name, neighbourhood, property_type,
                room_type, accommodates, bedrooms, beds, price, reviews, rating,
            ) = row
            if listing_id is None:
                raise ValueError(f"Null listing id in {table} source row {source_row_id}")
            cursor_insert = connection.execute(
                "INSERT INTO dim_airbnb_listing "
                "(source_city, listing_id, name, neighbourhood_cleansed, property_type, "
                "room_type, accommodates, bedrooms, beds, price, number_of_reviews, "
                "review_scores_rating, boston_source_row_id, seattle_source_row_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    city, listing_id, name, neighbourhood, property_type, room_type,
                    accommodates, bedrooms, beds, price, reviews, rating,
                    source_row_id if city == "boston" else None,
                    source_row_id if city == "seattle" else None,
                ),
            )
            listing_keys[(city, int(listing_id))] = int(cursor_insert.lastrowid)
            source_count += 1
        if source_count == 0:
            raise ValueError(f"No listing records in {table}")
    return listing_keys


def _build_airbnb_facts(
    connection: sqlite3.Connection,
    output_to_table: dict[str, str],
    listing_keys: dict[tuple[str, int], int],
) -> None:
    for city in AIRBNB_CITIES:
        for kind in ("calendar", "reviews"):
            table = _source_table(
                output_to_table,
                f"cleaned_hotel_accomodation_3_{city}_airbnb_open_data_{kind}.csv",
            )
            is_calendar = kind == "calendar"
            fact_table = f"fact_airbnb_{'calendar' if is_calendar else 'review'}_{city}"
            if is_calendar:
                sql = (
                    "SELECT warehouse_source_row_id, listing_id, substr(date, 1, 10), "
                    "available, price FROM "
                ) + quote_identifier(table)
                insert = (
                    f"INSERT INTO {quote_identifier(fact_table)} "
                    "(source_row_id, listing_key, date_key, available, price) "
                    "VALUES (?, ?, ?, ?, ?)"
                )
            else:
                sql = (
                    "SELECT warehouse_source_row_id, listing_id, substr(date, 1, 10), "
                    "id, reviewer_id, reviewer_name, comments FROM "
                ) + quote_identifier(table)
                insert = (
                    f"INSERT INTO {quote_identifier(fact_table)} "
                    "(source_row_id, listing_key, date_key, source_review_id, "
                    "reviewer_id, reviewer_name, comments) VALUES (?, ?, ?, ?, ?, ?, ?)"
                )
            batch = []
            for row in connection.execute(sql):
                source_id, listing_id, date_text, *attributes = row
                if listing_id is None or (city, int(listing_id)) not in listing_keys:
                    raise ValueError(
                        f"Unmatched {city} {kind} listing id {listing_id!r} "
                        f"at source row {source_id}"
                    )
                parsed_date = _parse_iso_date(date_text)
                date_key = (
                    parsed_date.year * 10000 + parsed_date.month * 100 + parsed_date.day
                    if parsed_date
                    else None
                )
                batch.append((
                    source_id, listing_keys[(city, int(listing_id))], date_key, *attributes
                ))
                if len(batch) >= 10_000:
                    connection.executemany(insert, batch)
                    batch.clear()
            if batch:
                connection.executemany(insert, batch)


def _build_tourism_facts(
    connection: sqlite3.Connection,
    output_to_table: dict[str, str],
) -> None:
    table = _source_table(output_to_table, "cleaned_tourism.csv")
    locations = [
        row[0] for row in connection.execute(
            f"SELECT DISTINCT location_name FROM {quote_identifier(table)} "
            "WHERE location_name IS NOT NULL ORDER BY location_name"
        )
    ]
    connection.executemany(
        "INSERT INTO dim_tourism_location (location_name) VALUES (?)",
        ((location,) for location in locations),
    )
    location_keys = {
        name: key for key, name in connection.execute(
            "SELECT location_key, location_name FROM dim_tourism_location"
        )
    }
    selected = ["warehouse_source_row_id", "image_id", "location_name", *TOURISM_METRICS]
    source_columns = {row[1] for row in connection.execute(
        f"PRAGMA table_info({quote_identifier(table)})"
    )}
    missing = [column for column in selected if column not in source_columns]
    if missing:
        raise ValueError(f"Cleaned tourism source is missing fact fields: {missing}")
    sql = (
        f"SELECT {', '.join(quote_identifier(column) for column in selected)} "
        f"FROM {quote_identifier(table)}"
    )
    fact_columns = ["source_row_id", "image_id", "location_key", *TOURISM_METRICS]
    placeholders = ", ".join("?" for _ in fact_columns)
    insert = (
        f"INSERT INTO fact_tourism_observation "
        f"({', '.join(quote_identifier(column) for column in fact_columns)}) "
        f"VALUES ({placeholders})"
    )
    batch = []
    for row in connection.execute(sql):
        source_id, image_id, name, *metrics = row
        if image_id is None or name not in location_keys:
            raise ValueError(f"Unmatched tourism location/image at source row {source_id}")
        batch.append((source_id, image_id, location_keys[name], *metrics))
        if len(batch) >= 10_000:
            connection.executemany(insert, batch)
            batch.clear()
    if batch:
        connection.executemany(insert, batch)


def _inventory_tables(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    tables = [
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    manifest_by_table = {
        row[0]: row[1:] for row in connection.execute(
            "SELECT table_name, source_file, output_file, rows_loaded, "
            "attribute_values_loaded, storage_mode "
            "FROM warehouse_manifest"
        )
    }
    result = []
    for table in tables:
        columns = list(connection.execute(f"PRAGMA table_info({quote_identifier(table)})"))
        row_count = int(connection.execute(
            f"SELECT COUNT(*) FROM {quote_identifier(table)}"
        ).fetchone()[0])
        manifest = manifest_by_table.get(table)
        primary_keys = [column[1] for column in columns if column[5]]
        result.append({
            "table_name": table,
            "table_type": _table_type(table),
            "record_count": row_count,
            "column_count": len(columns),
            "columns": json.dumps(
                [{"name": column[1], "type": column[2], "not_null": bool(column[3])}
                 for column in columns],
                ensure_ascii=False,
            ),
            "primary_key": ", ".join(primary_keys),
            "source_file": manifest[0] if manifest else "",
            "output_file": manifest[1] if manifest else "",
            "storage_mode": manifest[4] if manifest else "",
        })
    return result


def _table_type(table: str) -> str:
    if table.startswith("fact_"):
        return "fact"
    if table.startswith("dim_"):
        return "dimension"
    if table.startswith("stg_"):
        return "source_staging"
    if table == "warehouse_manifest":
        return "metadata"
    if table.endswith("_records"):
        return "source_staging_records"
    if table.endswith("_attributes"):
        return "source_staging_attributes"
    return "other"


def _relationship_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    result = []
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    for table_row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ):
        table = table_row[0]
        for row in connection.execute(f"PRAGMA foreign_key_list({quote_identifier(table)})"):
            _, sequence, parent, child_column, parent_column, on_update, on_delete, _ = row
            parent_count = int(connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(parent)}"
            ).fetchone()[0])
            child_count = int(connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table)} "
                f"WHERE {quote_identifier(child_column)} IS NOT NULL"
            ).fetchone()[0])
            relevant_violations = sum(
                1 for violation in violations
                if violation[0] == table and violation[2] == parent
            )
            result.append({
                "child_table": table,
                "child_column": child_column,
                "parent_table": parent,
                "parent_column": parent_column,
                "child_rows_referencing_parent": child_count,
                "parent_record_count": parent_count,
                "relationship_type": "foreign key",
                "on_update": on_update,
                "on_delete": on_delete,
                "foreign_key_violations": relevant_violations,
                "validation_status": "PASS" if relevant_violations == 0 else "FAIL",
            })
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _unique_report_path(report_root: Path, name: str) -> Path:
    report_root.mkdir(parents=True, exist_ok=True)
    path = report_root / name
    if not path.exists():
        return path
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = report_root / f"{path.stem}_{stamp}{path.suffix}"
    suffix = 1
    while candidate.exists():
        candidate = report_root / f"{path.stem}_{stamp}_{suffix:03d}{path.suffix}"
        suffix += 1
    return candidate


def _write_reports(
    connection: sqlite3.Connection,
    report_root: Path,
    run_dir: Path,
    source_summaries: list[dict[str, Any]],
    invalid_date_counts: dict[str, int],
    database_path: Path,
) -> tuple[Path, Path, Path]:
    table_rows = _inventory_tables(connection)
    table_path = _unique_report_path(report_root, "warehouse_table_inventory.csv")
    _write_csv(
        table_path,
        table_rows,
        [
            "table_name", "table_type", "record_count", "column_count", "columns",
            "primary_key", "source_file", "output_file", "storage_mode",
        ],
    )

    relationship_rows = _relationship_rows(connection)
    relationship_path = _unique_report_path(report_root, "warehouse_relationships.csv")
    _write_csv(
        relationship_path,
        relationship_rows,
        [
            "child_table", "child_column", "parent_table", "parent_column",
            "child_rows_referencing_parent", "parent_record_count", "relationship_type",
            "on_update", "on_delete", "foreign_key_violations", "validation_status",
        ],
    )

    validation_path = _unique_report_path(report_root, "warehouse_validation.txt")
    source_total = sum(int(item["rows_loaded"]) for item in source_summaries)
    source_tables = len(source_summaries)
    database_integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    with validation_path.open("w", encoding="utf-8") as output:
        output.write("TravelIntel SQLite Warehouse Validation\n")
        output.write("=" * 72 + "\n")
        output.write(f"Database: {database_path}\n")
        output.write(f"ETL source run: {run_dir}\n")
        output.write(f"Source datasets staged: {source_tables}\n")
        output.write(f"Source records staged: {source_total}\n")
        output.write(f"Physical SQLite tables: {len(table_rows)}\n")
        output.write(f"Foreign-key constraints: {len(relationship_rows)}\n")
        output.write(f"PRAGMA integrity_check: {database_integrity}\n")
        output.write(f"PRAGMA foreign_key_check violations: {len(fk_errors)}\n")
        output.write(
            "All declared relationship checks: "
            + ("PASS" if not fk_errors else "FAIL")
            + "\n"
        )
        output.write("Source date values not parsed for Dim_Date:\n")
        if invalid_date_counts:
            for label, count in sorted(invalid_date_counts.items()):
                output.write(f"- {label}: {count}\n")
        else:
            output.write("- none\n")
        output.write("\nTable counts:\n")
        for item in table_rows:
            output.write(
                f"- {item['table_name']}: {item['record_count']} records "
                f"({item['table_type']})\n"
            )
        output.write("\nNotes:\n")
        output.write(
            "- Every cleaned source is retained in staging. Very wide reference sources "
            "use normalized record and attribute/value tables.\n"
        )
        output.write(
            "- Hotel, Airbnb, and tourism fact/dimension relationships use source identifiers "
            "validated from the cleaned datasets.\n"
        )
        output.write(
            "- The Indian destination catalog and reviews without a corroborated place/city "
            "key remain separate staging sources; no speculative cross-source joins were made.\n"
        )
    return table_path, relationship_path, validation_path


def build_warehouse(
    run_dir: Path,
    database_path: Path,
    report_root: Path = REPORTS_ROOT,
    schema_path: Path | None = None,
    chunk_size: int = 20_000,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    database_path = database_path.resolve()
    if not run_dir.is_dir():
        raise NotADirectoryError(f"ETL run directory does not exist: {run_dir}")
    if database_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing warehouse: {database_path}")
    schema_path = schema_path or PROJECT_ROOT / "warehouse" / "schema.sql"
    schema_path = schema_path.resolve()
    if not schema_path.is_file():
        raise FileNotFoundError(f"Warehouse schema does not exist: {schema_path}")

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="travelintel_warehouse_", dir=database_path.parent
    ) as temporary_dir:
        build_path = Path(temporary_dir) / database_path.name
        connection = sqlite3.connect(build_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            output_to_table, source_summaries = _stage_sources(
                connection, run_dir, chunk_size
            )
            date_lookup, invalid_date_counts = _build_date_dimension(
                connection, output_to_table
            )
            dim_hotel_count = _build_hotel_facts(connection, output_to_table)
            listing_keys = _build_airbnb_dimensions(connection, output_to_table)
            _build_airbnb_facts(connection, output_to_table, listing_keys)
            _build_tourism_facts(connection, output_to_table)
            connection.commit()

            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_key_errors:
                raise sqlite3.IntegrityError(
                    f"Warehouse validation failed: integrity={integrity}, "
                    f"foreign_key_violations={len(foreign_key_errors)}"
                )
            reports = _write_reports(
                connection,
                report_root,
                run_dir,
                source_summaries,
                invalid_date_counts,
                database_path,
            )
            connection.commit()
        finally:
            connection.close()

        if database_path.exists():
            raise FileExistsError(
                f"Warehouse appeared during build; refusing to overwrite: {database_path}"
            )
        os.rename(build_path, database_path)

    table_path, relationship_path, validation_path = reports
    return {
        "database": database_path,
        "source_datasets": len(source_summaries),
        "source_records": sum(int(item["rows_loaded"]) for item in source_summaries),
        "table_inventory": table_path,
        "relationships": relationship_path,
        "validation": validation_path,
        "table_count": len(_read_csv_rows(table_path)),
        "relationship_count": len(_read_csv_rows(relationship_path)),
        "date_count": len(date_lookup),
        "hotel_dimension_count": dim_hotel_count,
        "airbnb_listing_count": len(listing_keys),
    }


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, default=None)
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "travelintel_warehouse.db",
    )
    parser.add_argument("--reports", type=Path, default=REPORTS_ROOT)
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=20_000,
        help="Rows per CSV ingestion chunk.",
    )
    args = parser.parse_args()
    if args.chunk_size < 1:
        parser.error("--chunk-size must be positive")
    run_dir = args.source_run.resolve() if args.source_run else latest_etl_run(
        PROJECT_ROOT / "Processed Data - 8"
    )
    result = build_warehouse(
        run_dir,
        args.database,
        args.reports,
        chunk_size=args.chunk_size,
    )
    print(f"Warehouse: {result['database']}")
    print(f"Cleaned source datasets staged: {result['source_datasets']}")
    print(f"Source rows staged: {result['source_records']:,}")
    print(f"Physical tables: {result['table_count']}")
    print(f"Declared foreign keys: {result['relationship_count']}")
    print(f"Dates in Dim_Date: {result['date_count']}")
    print(f"Airbnb listing dimension rows: {result['airbnb_listing_count']}")
    print(f"Table inventory: {result['table_inventory']}")
    print(f"Relationships: {result['relationships']}")
    print(f"Validation: {result['validation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
