"""Add Star and Snowflake schema models to an existing TravelIntel warehouse."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT, REPORTS_ROOT


STAR_TABLES = (
    "star_dim_date",
    "star_dim_hotel_type",
    "star_dim_airbnb_listing",
    "star_dim_tourism_location",
    "star_fact_hotel_booking",
    "star_fact_airbnb_calendar_boston",
    "star_fact_airbnb_calendar_seattle",
    "star_fact_airbnb_review_boston",
    "star_fact_airbnb_review_seattle",
    "star_fact_tourism_observation",
)

SNOWFLAKE_TABLES = (
    "snowflake_dim_calendar_month",
    "snowflake_dim_date",
    "snowflake_dim_hotel_type",
    "snowflake_dim_airbnb_city",
    "snowflake_dim_airbnb_neighbourhood",
    "snowflake_dim_airbnb_property_type",
    "snowflake_dim_airbnb_room_type",
    "snowflake_dim_airbnb_listing",
    "snowflake_dim_tourism_location",
    "snowflake_fact_hotel_booking",
    "snowflake_fact_airbnb_calendar_boston",
    "snowflake_fact_airbnb_calendar_seattle",
    "snowflake_fact_airbnb_review_boston",
    "snowflake_fact_airbnb_review_seattle",
    "snowflake_fact_tourism_observation",
)


STAR_SAMPLE_QUERIES = {
    "hotel_bookings_by_month_and_type": """
        SELECT d.year, d.month, h.hotel_type, COUNT(*) AS booking_rows,
               ROUND(AVG(f.adr), 2) AS average_adr
        FROM star_fact_hotel_booking AS f
        JOIN star_dim_date AS d ON d.date_key = f.date_key
        JOIN star_dim_hotel_type AS h ON h.hotel_key = f.hotel_key
        GROUP BY d.year, d.month, h.hotel_type
        ORDER BY d.year, d.month, h.hotel_type
        LIMIT 12
    """,
    "airbnb_calendar_by_city": """
        SELECT l.source_city,
               COUNT(*) AS calendar_rows,
               SUM(CASE WHEN lower(f.available) = 't' THEN 1 ELSE 0 END) AS marked_available
        FROM star_fact_airbnb_calendar_boston AS f
        JOIN star_dim_airbnb_listing AS l ON l.listing_key = f.listing_key
        GROUP BY l.source_city
        UNION ALL
        SELECT l.source_city,
               COUNT(*) AS calendar_rows,
               SUM(CASE WHEN lower(f.available) = 't' THEN 1 ELSE 0 END) AS marked_available
        FROM star_fact_airbnb_calendar_seattle AS f
        JOIN star_dim_airbnb_listing AS l ON l.listing_key = f.listing_key
        GROUP BY l.source_city
        ORDER BY source_city
    """,
    "tourism_by_location": """
        SELECT l.location_name, COUNT(*) AS observations,
               ROUND(AVG(f.avg_rating), 3) AS average_rating,
               SUM(f.visitor_count) AS recorded_visitors
        FROM star_fact_tourism_observation AS f
        JOIN star_dim_tourism_location AS l ON l.location_key = f.location_key
        GROUP BY l.location_name
        ORDER BY l.location_name
        LIMIT 10
    """,
}

SNOWFLAKE_SAMPLE_QUERIES = {
    "hotel_bookings_by_month_and_type": """
        SELECT m.year, m.month, h.hotel_type, COUNT(*) AS booking_rows,
               ROUND(AVG(f.adr), 2) AS average_adr
        FROM snowflake_fact_hotel_booking AS f
        JOIN snowflake_dim_date AS d ON d.date_key = f.date_key
        JOIN snowflake_dim_calendar_month AS m ON m.month_key = d.month_key
        JOIN snowflake_dim_hotel_type AS h ON h.hotel_key = f.hotel_key
        GROUP BY m.year, m.month, h.hotel_type
        ORDER BY m.year, m.month, h.hotel_type
        LIMIT 12
    """,
    "airbnb_calendar_by_city": """
        SELECT c.city_name AS source_city,
               COUNT(*) AS calendar_rows,
               SUM(CASE WHEN lower(f.available) = 't' THEN 1 ELSE 0 END) AS marked_available
        FROM snowflake_fact_airbnb_calendar_boston AS f
        JOIN snowflake_dim_airbnb_listing AS l ON l.listing_key = f.listing_key
        JOIN snowflake_dim_airbnb_city AS c ON c.city_key = l.city_key
        GROUP BY c.city_name
        UNION ALL
        SELECT c.city_name AS source_city,
               COUNT(*) AS calendar_rows,
               SUM(CASE WHEN lower(f.available) = 't' THEN 1 ELSE 0 END) AS marked_available
        FROM snowflake_fact_airbnb_calendar_seattle AS f
        JOIN snowflake_dim_airbnb_listing AS l ON l.listing_key = f.listing_key
        JOIN snowflake_dim_airbnb_city AS c ON c.city_key = l.city_key
        GROUP BY c.city_name
        ORDER BY source_city
    """,
    "tourism_by_location": """
        SELECT l.location_name, COUNT(*) AS observations,
               ROUND(AVG(f.avg_rating), 3) AS average_rating,
               SUM(f.visitor_count) AS recorded_visitors
        FROM snowflake_fact_tourism_observation AS f
        JOIN snowflake_dim_tourism_location AS l ON l.location_key = f.location_key
        GROUP BY l.location_name
        ORDER BY l.location_name
        LIMIT 10
    """,
}


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def unique_report_path(report_root: Path, name: str) -> Path:
    report_root.mkdir(parents=True, exist_ok=True)
    candidate = report_root / name
    if not candidate.exists():
        return candidate
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = report_root / f"{candidate.stem}_{stamp}{candidate.suffix}"
    suffix = 1
    while candidate.exists():
        candidate = report_root / f"{candidate.stem}_{suffix:03d}{candidate.suffix}"
        suffix += 1
    return candidate


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _copy_star_schema(connection: sqlite3.Connection) -> None:
    copies = (
        ("star_dim_date", "dim_date", "date_key, date_value, year, quarter, month, day, weekday, weekday_name"),
        ("star_dim_hotel_type", "dim_hotel_type", "hotel_key, hotel_type"),
        (
            "star_dim_airbnb_listing",
            "dim_airbnb_listing",
            "listing_key, source_city, listing_id, name, neighbourhood_cleansed, "
            "property_type, room_type, accommodates, bedrooms, beds, price, "
            "number_of_reviews, review_scores_rating, boston_source_row_id, "
            "seattle_source_row_id",
        ),
        ("star_dim_tourism_location", "dim_tourism_location", "location_key, location_name"),
    )
    for target, source, columns in copies:
        connection.execute(
            f"INSERT INTO {quote_identifier(target)} ({columns}) "
            f"SELECT {columns} FROM {quote_identifier(source)}"
        )

    hotel_columns = (
        "booking_fact_id, source_row_id, date_key, hotel_key, is_canceled, lead_time, "
        "stays_in_weekend_nights, stays_in_week_nights, adults, children, babies, "
        "previous_cancellations, previous_bookings_not_canceled, booking_changes, "
        "days_in_waiting_list, adr, required_car_parking_spaces, "
        "total_of_special_requests, market_segment, distribution_channel, "
        "customer_type, reservation_status"
    )
    connection.execute(
        f"INSERT INTO star_fact_hotel_booking ({hotel_columns}) "
        f"SELECT {hotel_columns} FROM fact_hotel_booking"
    )

    for city in ("boston", "seattle"):
        for kind, primary_key, columns in (
            (
                "calendar",
                "calendar_fact_id",
                "source_row_id, listing_key, date_key, available, price",
            ),
            (
                "review",
                "review_fact_id",
                "source_row_id, listing_key, date_key, source_review_id, "
                "reviewer_id, reviewer_name, comments",
            ),
        ):
            target = f"star_fact_airbnb_{kind}_{city}"
            source = f"fact_airbnb_{kind}_{city}"
            connection.execute(
                f"INSERT INTO {quote_identifier(target)} ({columns}) "
                f"SELECT {columns} FROM {quote_identifier(source)}"
            )

    tourism_columns = (
        "tourism_fact_id, source_row_id, image_id, location_key, latitude, longitude, "
        "avg_rating, review_text, sentiment_score, visitor_count, avg_cost, accessibility, "
        "safety_index, seasonality, popularity_index, avg_stay_duration, transport_score, "
        "accommodation_score, cultural_score, natural_score, infrastructure_score, "
        "cleanliness_score, season_peak_factor, return_rate, review_count, attractiveness_label"
    )
    connection.execute(
        f"INSERT INTO star_fact_tourism_observation ({tourism_columns}) "
        f"SELECT {tourism_columns} FROM fact_tourism_observation"
    )


def _build_snowflake_dimensions(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO snowflake_dim_calendar_month "
        "(month_key, year, quarter, month) "
        "SELECT DISTINCT year * 100 + month, year, quarter, month "
        "FROM dim_date ORDER BY year, month"
    )
    connection.execute(
        "INSERT INTO snowflake_dim_date "
        "(date_key, date_value, day, weekday, weekday_name, month_key) "
        "SELECT date_key, date_value, day, weekday, weekday_name, year * 100 + month "
        "FROM dim_date"
    )
    connection.execute(
        "INSERT INTO snowflake_dim_hotel_type (hotel_key, hotel_type) "
        "SELECT hotel_key, hotel_type FROM dim_hotel_type"
    )
    connection.execute(
        "INSERT INTO snowflake_dim_airbnb_city (city_name) "
        "SELECT DISTINCT source_city FROM dim_airbnb_listing "
        "WHERE source_city IS NOT NULL ORDER BY source_city"
    )

    connection.execute(
        "INSERT INTO snowflake_dim_airbnb_neighbourhood "
        "(city_key, neighbourhood_name) "
        "SELECT DISTINCT c.city_key, l.neighbourhood_cleansed "
        "FROM dim_airbnb_listing AS l "
        "JOIN snowflake_dim_airbnb_city AS c ON c.city_name = l.source_city "
        "WHERE l.neighbourhood_cleansed IS NOT NULL "
        "ORDER BY c.city_key, l.neighbourhood_cleansed"
    )
    connection.execute(
        "INSERT INTO snowflake_dim_airbnb_property_type (property_type) "
        "SELECT DISTINCT property_type FROM dim_airbnb_listing "
        "WHERE property_type IS NOT NULL ORDER BY property_type"
    )
    connection.execute(
        "INSERT INTO snowflake_dim_airbnb_room_type (room_type) "
        "SELECT DISTINCT room_type FROM dim_airbnb_listing "
        "WHERE room_type IS NOT NULL ORDER BY room_type"
    )
    connection.execute(
        "INSERT INTO snowflake_dim_airbnb_listing ("
        "listing_key, city_key, listing_id, neighbourhood_key, property_type_key, "
        "room_type_key, name, accommodates, bedrooms, beds, price, number_of_reviews, "
        "review_scores_rating, boston_source_row_id, seattle_source_row_id) "
        "SELECT l.listing_key, c.city_key, l.listing_id, n.neighbourhood_key, "
        "p.property_type_key, r.room_type_key, l.name, l.accommodates, l.bedrooms, "
        "l.beds, l.price, l.number_of_reviews, l.review_scores_rating, "
        "l.boston_source_row_id, l.seattle_source_row_id "
        "FROM dim_airbnb_listing AS l "
        "JOIN snowflake_dim_airbnb_city AS c ON c.city_name = l.source_city "
        "LEFT JOIN snowflake_dim_airbnb_neighbourhood AS n "
        "ON n.city_key = c.city_key AND n.neighbourhood_name = l.neighbourhood_cleansed "
        "LEFT JOIN snowflake_dim_airbnb_property_type AS p "
        "ON p.property_type = l.property_type "
        "LEFT JOIN snowflake_dim_airbnb_room_type AS r ON r.room_type = l.room_type"
    )
    connection.execute(
        "INSERT INTO snowflake_dim_tourism_location (location_key, location_name) "
        "SELECT location_key, location_name FROM dim_tourism_location"
    )


def _copy_snowflake_facts(connection: sqlite3.Connection) -> None:
    hotel_columns = (
        "booking_fact_id, source_row_id, date_key, hotel_key, is_canceled, lead_time, "
        "stays_in_weekend_nights, stays_in_week_nights, adults, children, babies, "
        "previous_cancellations, previous_bookings_not_canceled, booking_changes, "
        "days_in_waiting_list, adr, required_car_parking_spaces, "
        "total_of_special_requests, market_segment, distribution_channel, "
        "customer_type, reservation_status"
    )
    connection.execute(
        f"INSERT INTO snowflake_fact_hotel_booking ({hotel_columns}) "
        f"SELECT {hotel_columns} FROM fact_hotel_booking"
    )
    for city in ("boston", "seattle"):
        for kind, columns in (
            (
                "calendar",
                "calendar_fact_id, source_row_id, listing_key, date_key, available, price",
            ),
            (
                "review",
                "review_fact_id, source_row_id, listing_key, date_key, source_review_id, "
                "reviewer_id, reviewer_name, comments",
            ),
        ):
            connection.execute(
                f"INSERT INTO snowflake_fact_airbnb_{kind}_{city} ({columns}) "
                f"SELECT {columns} FROM fact_airbnb_{kind}_{city}"
            )
    tourism_columns = (
        "tourism_fact_id, source_row_id, image_id, location_key, latitude, longitude, "
        "avg_rating, review_text, sentiment_score, visitor_count, avg_cost, accessibility, "
        "safety_index, seasonality, popularity_index, avg_stay_duration, transport_score, "
        "accommodation_score, cultural_score, natural_score, infrastructure_score, "
        "cleanliness_score, season_peak_factor, return_rate, review_count, attractiveness_label"
    )
    connection.execute(
        f"INSERT INTO snowflake_fact_tourism_observation ({tourism_columns}) "
        f"SELECT {tourism_columns} FROM fact_tourism_observation"
    )


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(table)}"
    ).fetchone()[0])


def _schema_inventory(
    connection: sqlite3.Connection,
    tables: tuple[str, ...],
    schema_type: str,
) -> list[dict[str, Any]]:
    result = []
    for table in tables:
        if not _table_exists(connection, table):
            raise sqlite3.DatabaseError(f"Expected schema table was not created: {table}")
        info = list(connection.execute(f"PRAGMA table_info({quote_identifier(table)})"))
        result.append({
            "schema": schema_type,
            "table_name": table,
            "table_type": "fact" if "_fact_" in table else "dimension",
            "record_count": _count(connection, table),
            "column_count": len(info),
            "columns": json.dumps(
                [
                    {
                        "name": row[1],
                        "type": row[2],
                        "not_null": bool(row[3]),
                        "primary_key_order": row[5],
                    }
                    for row in info
                ],
                ensure_ascii=False,
            ),
            "primary_key": ", ".join(row[1] for row in info if row[5]),
        })
    return result


def _schema_relationships(
    connection: sqlite3.Connection,
    tables: tuple[str, ...],
    schema_type: str,
) -> list[dict[str, Any]]:
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    result = []
    for table in tables:
        groups: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in connection.execute(f"PRAGMA foreign_key_list({quote_identifier(table)})"):
            groups[row[0]].append(row)
        for foreign_key_id, rows in groups.items():
            rows.sort(key=lambda item: item[1])
            parent_table = rows[0][2]
            child_columns = [row[3] for row in rows]
            parent_columns = [row[4] for row in rows]
            on_update = rows[0][5]
            on_delete = rows[0][6]
            child_predicate = " AND ".join(
                f"{quote_identifier(column)} IS NOT NULL" for column in child_columns
            )
            child_references = int(connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table)} "
                f"WHERE {child_predicate}"
            ).fetchone()[0])
            parent_rows = _count(connection, parent_table)
            table_violations = sum(
                1 for violation in violations
                if violation[0] == table and violation[3] == foreign_key_id
            )
            result.append({
                "schema": schema_type,
                "child_table": table,
                "child_column": ", ".join(child_columns),
                "parent_table": parent_table,
                "parent_column": ", ".join(parent_columns),
                "child_rows_referencing_parent": child_references,
                "parent_record_count": parent_rows,
                "foreign_key_violations": table_violations,
                "validation_status": "PASS" if table_violations == 0 else "FAIL",
                "on_update": on_update,
                "on_delete": on_delete,
            })
    return result


def _write_rows(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _execute_samples(
    connection: sqlite3.Connection,
    queries: dict[str, str],
    schema_type: str,
) -> list[dict[str, Any]]:
    results = []
    for name, sql in queries.items():
        rows = [dict(row) for row in connection.execute(sql).fetchall()]
        if not rows:
            raise AssertionError(f"{schema_type} sample join returned no rows: {name}")
        results.append({
            "schema": schema_type,
            "query_name": name,
            "sql": " ".join(sql.split()),
            "result_rows": len(rows),
            "sample_result": json.dumps(rows, ensure_ascii=False, default=str),
        })
    return results


def _validate_models(connection: sqlite3.Connection) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    fact_pairs = (
        ("hotel_bookings", "star_fact_hotel_booking", "snowflake_fact_hotel_booking"),
        ("airbnb_calendar_boston", "star_fact_airbnb_calendar_boston", "snowflake_fact_airbnb_calendar_boston"),
        ("airbnb_calendar_seattle", "star_fact_airbnb_calendar_seattle", "snowflake_fact_airbnb_calendar_seattle"),
        ("airbnb_reviews_boston", "star_fact_airbnb_review_boston", "snowflake_fact_airbnb_review_boston"),
        ("airbnb_reviews_seattle", "star_fact_airbnb_review_seattle", "snowflake_fact_airbnb_review_seattle"),
        ("tourism_observations", "star_fact_tourism_observation", "snowflake_fact_tourism_observation"),
    )
    for label, star_table, snowflake_table in fact_pairs:
        source_count = _count(
            connection,
            {
                "hotel_bookings": "fact_hotel_booking",
                "airbnb_calendar_boston": "fact_airbnb_calendar_boston",
                "airbnb_calendar_seattle": "fact_airbnb_calendar_seattle",
                "airbnb_reviews_boston": "fact_airbnb_review_boston",
                "airbnb_reviews_seattle": "fact_airbnb_review_seattle",
                "tourism_observations": "fact_tourism_observation",
            }[label],
        )
        star_count = _count(connection, star_table)
        snowflake_count = _count(connection, snowflake_table)
        if source_count != star_count or source_count != snowflake_count:
            raise AssertionError(
                f"{label} row mismatch: source={source_count}, star={star_count}, "
                f"snowflake={snowflake_count}"
            )
        comparisons.append({
            "fact": label,
            "source_rows": source_count,
            "star_rows": star_count,
            "snowflake_rows": snowflake_count,
            "status": "PASS",
        })

    star_joins = _execute_samples(connection, STAR_SAMPLE_QUERIES, "star")
    snowflake_joins = _execute_samples(connection, SNOWFLAKE_SAMPLE_QUERIES, "snowflake")
    for star, snowflake in zip(star_joins, snowflake_joins):
        if star["query_name"] != snowflake["query_name"]:
            raise AssertionError("Star and Snowflake sample query order differs.")
        if star["sample_result"] != snowflake["sample_result"]:
            raise AssertionError(
                f"Equivalent query results differ for {star['query_name']}"
            )
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok" or foreign_key_errors:
        raise sqlite3.IntegrityError(
            f"Dimensional schema validation failed: integrity={integrity}, "
            f"foreign_key_violations={len(foreign_key_errors)}"
        )
    return {
        "fact_comparisons": comparisons,
        "star_joins": star_joins,
        "snowflake_joins": snowflake_joins,
        "integrity": integrity,
        "foreign_key_violations": len(foreign_key_errors),
    }


def _generate_reports(
    connection: sqlite3.Connection,
    report_root: Path,
    validation: dict[str, Any],
) -> dict[str, Path]:
    star_inventory = _schema_inventory(connection, STAR_TABLES, "star")
    snowflake_inventory = _schema_inventory(connection, SNOWFLAKE_TABLES, "snowflake")
    star_relationships = _schema_relationships(connection, STAR_TABLES, "star")
    snowflake_relationships = _schema_relationships(connection, SNOWFLAKE_TABLES, "snowflake")

    paths = {
        "star_inventory": unique_report_path(report_root, "star_schema_table_inventory.csv"),
        "star_relationships": unique_report_path(report_root, "star_schema_relationships.csv"),
        "snowflake_inventory": unique_report_path(report_root, "snowflake_schema_table_inventory.csv"),
        "snowflake_relationships": unique_report_path(report_root, "snowflake_schema_relationships.csv"),
        "star_samples": unique_report_path(report_root, "star_schema_sample_joins.csv"),
        "snowflake_samples": unique_report_path(report_root, "snowflake_schema_sample_joins.csv"),
        "comparison": unique_report_path(report_root, "schema_comparison.txt"),
    }
    inventory_fields = [
        "schema", "table_name", "table_type", "record_count", "column_count",
        "columns", "primary_key",
    ]
    relationship_fields = [
        "schema", "child_table", "child_column", "parent_table", "parent_column",
        "child_rows_referencing_parent", "parent_record_count",
        "foreign_key_violations", "validation_status", "on_update", "on_delete",
    ]
    sample_fields = ["schema", "query_name", "sql", "result_rows", "sample_result"]
    _write_rows(paths["star_inventory"], star_inventory, inventory_fields)
    _write_rows(paths["snowflake_inventory"], snowflake_inventory, inventory_fields)
    _write_rows(paths["star_relationships"], star_relationships, relationship_fields)
    _write_rows(paths["snowflake_relationships"], snowflake_relationships, relationship_fields)
    _write_rows(paths["star_samples"], validation["star_joins"], sample_fields)
    _write_rows(paths["snowflake_samples"], validation["snowflake_joins"], sample_fields)

    total_facts = sum(row["source_rows"] for row in validation["fact_comparisons"])
    with paths["comparison"].open("w", encoding="utf-8") as output:
        output.write("TravelIntel Star and Snowflake Schema Comparison\n")
        output.write("=" * 72 + "\n")
        output.write(f"Star schema tables: {len(STAR_TABLES)}\n")
        output.write(f"Snowflake schema tables: {len(SNOWFLAKE_TABLES)}\n")
        output.write(f"Fact rows represented in each model: {total_facts:,}\n")
        output.write(
            f"Star foreign-key constraints: {len(star_relationships)} "
            f"(all {'PASS' if all(r['validation_status'] == 'PASS' for r in star_relationships) else 'NOT PASS'})\n"
        )
        output.write(
            f"Snowflake foreign-key constraints: {len(snowflake_relationships)} "
            f"(all {'PASS' if all(r['validation_status'] == 'PASS' for r in snowflake_relationships) else 'NOT PASS'})\n"
        )
        output.write(f"Database integrity check: {validation['integrity']}\n")
        output.write(f"Foreign-key violations: {validation['foreign_key_violations']}\n\n")
        output.write("Fact grain and row-count comparisons\n")
        output.write("-" * 72 + "\n")
        grains = {
            "hotel_bookings": "One source hotel-booking record per fact row.",
            "airbnb_calendar_boston": "One Boston listing-calendar date record per fact row.",
            "airbnb_calendar_seattle": "One Seattle listing-calendar date record per fact row.",
            "airbnb_reviews_boston": "One Boston Airbnb review record per fact row.",
            "airbnb_reviews_seattle": "One Seattle Airbnb review record per fact row.",
            "tourism_observations": "One tourism_dataset image/observation record per fact row.",
        }
        for row in validation["fact_comparisons"]:
            output.write(
                f"- {row['fact']}: {row['source_rows']:,} rows; "
                f"grain: {grains[row['fact']]} {row['status']}\n"
            )
        output.write("\nStructure comparison\n")
        output.write("-" * 72 + "\n")
        output.write(
            "Star dimensions are denormalized: date attributes, Airbnb listing attributes, "
            "and location labels live on dimensions directly referenced by facts.\n"
        )
        output.write(
            "Snowflake dimensions normalize calendar date to calendar month and Airbnb listing "
            "to city, neighbourhood, property-type, and room-type lookup tables. "
            "The neighbourhood-to-city and date-to-month relationships use observed source "
            "labels and calendar values.\n"
        )
        output.write(
            "Hotel type and tourism location remain single dimensions because the sources "
            "do not provide a defensible further hierarchy for them.\n"
        )
        output.write("\nExecuted sample JOIN comparisons\n")
        output.write("-" * 72 + "\n")
        for star, snowflake in zip(validation["star_joins"], validation["snowflake_joins"]):
            output.write(
                f"- {star['query_name']}: Star returned {star['result_rows']} rows; "
                f"Snowflake returned {snowflake['result_rows']} rows; "
                f"result sets {'match' if star['sample_result'] == snowflake['sample_result'] else 'DIFFER'}.\n"
            )
        output.write("\nLimitations\n")
        output.write("-" * 72 + "\n")
        output.write(
            "- Hotel bookings have no destination identifier and remain a separate subject area.\n"
        )
        output.write(
            "- Indian destination and review sources were not added to these facts because "
            "no sufficiently corroborated shared key was established.\n"
        )
        output.write(
            "- Airbnb prices remain text because the source price values do not supply a "
            "confirmed common currency/normalization rule.\n"
        )
    return paths


def build_dimensional_schemas(
    database_path: Path,
    report_root: Path = REPORTS_ROOT,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"Existing warehouse database not found: {database_path}")
    schema_path = schema_path or PROJECT_ROOT / "warehouse" / "dimensional_schema.sql"
    schema_path = schema_path.resolve()
    if not schema_path.is_file():
        raise FileNotFoundError(f"Dimensional schema SQL not found: {schema_path}")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise sqlite3.IntegrityError("SQLite foreign key enforcement could not be enabled.")
        existing = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name LIKE 'star_%' OR name LIKE 'snowflake_%')"
            )
        ]
        if existing:
            raise FileExistsError(
                "Dimensional schema tables already exist; refusing to recreate or replace them: "
                + ", ".join(sorted(existing))
            )

        schema_sql = schema_path.read_text(encoding="utf-8")
        schema_sql = schema_sql.replace(
            "PRAGMA foreign_keys = ON;",
            "BEGIN IMMEDIATE;",
            1,
        )
        try:
            connection.executescript(schema_sql)
            _copy_star_schema(connection)
            _build_snowflake_dimensions(connection)
            _copy_snowflake_facts(connection)
            validation = _validate_models(connection)
            paths = _generate_reports(connection, report_root.resolve(), validation)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        table_counts = {
            table: _count(connection, table)
            for table in STAR_TABLES + SNOWFLAKE_TABLES
        }
        return {
            "star_tables": len(STAR_TABLES),
            "snowflake_tables": len(SNOWFLAKE_TABLES),
            "star_fact_rows": sum(
                table_counts[table] for table in STAR_TABLES if "_fact_" in table
            ),
            "snowflake_fact_rows": sum(
                table_counts[table] for table in SNOWFLAKE_TABLES if "_fact_" in table
            ),
            "star_relationships": len(_schema_relationships(connection, STAR_TABLES, "star")),
            "snowflake_relationships": len(
                _schema_relationships(connection, SNOWFLAKE_TABLES, "snowflake")
            ),
            "integrity": validation["integrity"],
            "foreign_key_violations": validation["foreign_key_violations"],
            "table_counts": table_counts,
            "reports": paths,
            "fact_comparisons": validation["fact_comparisons"],
            "sample_joins": validation["star_joins"] + validation["snowflake_joins"],
        }
    finally:
        connection.close()


def refresh_schema_reports(
    database_path: Path,
    report_root: Path = REPORTS_ROOT,
) -> dict[str, Any]:
    """Revalidate existing dimensional tables and write fresh, non-overwriting reports."""
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"Existing warehouse database not found: {database_path}")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for table in STAR_TABLES + SNOWFLAKE_TABLES:
            if not _table_exists(connection, table):
                raise sqlite3.DatabaseError(
                    f"Cannot refresh dimensional reports; required table is missing: {table}"
                )
        validation = _validate_models(connection)
        paths = _generate_reports(connection, report_root.resolve(), validation)
        return {
            "star_relationships": len(_schema_relationships(connection, STAR_TABLES, "star")),
            "snowflake_relationships": len(
                _schema_relationships(connection, SNOWFLAKE_TABLES, "snowflake")
            ),
            "integrity": validation["integrity"],
            "foreign_key_violations": validation["foreign_key_violations"],
            "reports": paths,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "travelintel_warehouse.db",
    )
    parser.add_argument("--reports", type=Path, default=REPORTS_ROOT)
    parser.add_argument(
        "--reports-only",
        action="store_true",
        help="Revalidate existing schema tables and refresh reports without creating tables.",
    )
    args = parser.parse_args()
    if args.reports_only:
        result = refresh_schema_reports(args.database, args.reports)
        print(f"Existing schema tables preserved in: {args.database.resolve()}")
    else:
        result = build_dimensional_schemas(args.database, args.reports)
    print(f"Database: {args.database.resolve()}")
    if not args.reports_only:
        print(f"Star schema tables created: {result['star_tables']}")
        print(f"Snowflake schema tables created: {result['snowflake_tables']}")
        print(f"Star fact rows loaded: {result['star_fact_rows']:,}")
        print(f"Snowflake fact rows loaded: {result['snowflake_fact_rows']:,}")
    print(f"Star relationships verified: {result['star_relationships']}")
    print(f"Snowflake relationships verified: {result['snowflake_relationships']}")
    print(f"Database integrity: {result['integrity']}")
    print(f"Foreign-key violations: {result['foreign_key_violations']}")
    for name, path in result["reports"].items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
