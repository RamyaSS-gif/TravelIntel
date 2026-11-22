"""Narrow, read-only data access for the TravelIntel customer portal."""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from config import PROJECT_ROOT
from olap.olap_operations import OLAPError


DATABASE_PATH = PROJECT_ROOT / "travelintel_warehouse.db"
WEATHER_TABLES = {
    "bengaluru": "stg_weather_bengaluru",
    "bombay": "stg_weather_bombay",
    "delhi": "stg_weather_delhi",
    "hyderabad": "stg_weather_hyderabad",
    "jaipur": "stg_weather_jaipur",
    "kanpur": "stg_weather_kanpur",
    "nagpur": "stg_weather_nagpur",
    "pune": "stg_weather_pune",
}
DESTINATION_FIELDS = (
    "id",
    "destination_name",
    "state",
    "district",
    "region",
    "coordinates_latitude",
    "coordinates_longitude",
    "popularity_score",
    "accessibility",
    "road_connectivity",
    "trip_types",
    "primary_attractions",
    "activities_available",
    "unique_experiences",
    "hidden_gems",
    "best_seasons",
    "avoid_seasons",
    "peak_tourist_season",
    "off_season",
    "rainfall_pattern",
    "ideal_for",
    "special_considerations",
    "minimum_days",
    "ideal_days",
    "maximum_days",
    "suggested_itinerary",
    "accommodation_types",
    "safety_rating",
    "safety_notes",
    "user_reviews_summary",
    "sustainability_notes",
    "nearest_airport_name",
    "nearest_airport_distance_km",
    "nearest_railway_station_name",
    "nearest_railway_station_distance_km",
    "nearest_major_city_name",
    "nearest_major_city_distance_km",
    "budget_category_total_daily_range",
    "mid_range_category_total_daily_range",
    "luxury_category_total_daily_range",
    "average_temperature_winter",
    "average_temperature_summer",
    "average_temperature_monsoon",
)
DESTINATION_LIST_FIELDS = {
    "trip_types",
    "primary_attractions",
    "activities_available",
    "hidden_gems",
    "best_seasons",
    "avoid_seasons",
    "ideal_for",
}
DESTINATION_RANGE_FIELDS = {
    "budget_category_total_daily_range": "budget",
    "mid_range_category_total_daily_range": "mid_range",
    "luxury_category_total_daily_range": "luxury",
}


@contextmanager
def _connection(database: Path | str | sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    if isinstance(database, sqlite3.Connection):
        yield database
        return

    path = Path(database).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Warehouse database not found: {path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _source_array(value: Any) -> list[str]:
    if not value:
        return []
    text = str(value).strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    return next(csv.reader([text], skipinitialspace=True), [])


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def destinations(database: Path | str | sqlite3.Connection = DATABASE_PATH) -> list[dict[str, Any]]:
    columns = ", ".join(f'"{field}"' for field in DESTINATION_FIELDS)
    with _connection(database) as connection:
        rows = connection.execute(
            f'SELECT {columns} FROM "stg_destinations" '
            'ORDER BY CAST("popularity_score" AS REAL) DESC, "destination_name"'
        ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for field in DESTINATION_LIST_FIELDS:
            item[field] = _json_value(item[field]) or []
        item["budgets"] = {
            key: _json_value(item.pop(field))
            for field, key in DESTINATION_RANGE_FIELDS.items()
        }
        for field in (
            "id",
            "popularity_score",
            "minimum_days",
            "ideal_days",
            "maximum_days",
            "safety_rating",
            "coordinates_latitude",
            "coordinates_longitude",
            "nearest_airport_distance_km",
            "nearest_railway_station_distance_km",
            "nearest_major_city_distance_km",
        ):
            item[field] = _number(item[field])
        result.append(item)
    return result


def accommodations(
    database: Path | str | sqlite3.Connection = DATABASE_PATH,
    *,
    city: str = "",
    search: str = "",
    limit: int = 60,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 100:
        raise OLAPError("Accommodation result limit must be between 1 and 100.")
    city_value = city.strip().lower()
    search_value = f"%{search.strip().lower()}%"
    source_tables = (
        ("Boston", "stg_hotel_accomodation_3_boston_airbnb_open_data_listings"),
        ("Seattle", "stg_hotel_accomodation_3_seattle_airbnb_open_data_listings"),
    )
    selects = []
    parameters: list[Any] = []
    for source_city, table in source_tables:
        selects.append(
            f"""
            SELECT
                CAST("id" AS TEXT) AS id,
                "name" AS name,
                "summary" AS summary,
                "description" AS description,
                "picture_url" AS image_url,
                "neighbourhood_cleansed" AS neighbourhood,
                "property_type" AS property_type,
                "room_type" AS room_type,
                "accommodates" AS accommodates,
                "bedrooms" AS bedrooms,
                "beds" AS beds,
                "amenities" AS amenities,
                "price" AS historical_price,
                "last_scraped" AS snapshot_date,
                "number_of_reviews" AS review_count,
                "review_scores_rating" AS rating,
                "availability_30" AS snapshot_availability_30,
                "cancellation_policy" AS snapshot_cancellation_policy,
                "minimum_nights" AS snapshot_minimum_nights,
                ? AS city
            FROM "{table}"
            WHERE (? = '' OR lower(?) = lower(?))
              AND (? = '' OR lower("name") LIKE ?
                   OR lower("neighbourhood_cleansed") LIKE ?
                   OR lower(?) LIKE ?)
            """
        )
        parameters.extend(
            [
                source_city,
                city_value,
                city_value,
                source_city,
                search.strip(),
                search_value,
                search_value,
                source_city,
                search_value,
            ]
        )
    sql = (
        "SELECT * FROM (" + " UNION ALL ".join(selects) + ") "
        "ORDER BY CAST(rating AS REAL) DESC, CAST(review_count AS INTEGER) DESC LIMIT ?"
    )
    parameters.append(limit)
    with _connection(database) as connection:
        rows = connection.execute(sql, parameters).fetchall()
    result = [dict(row) for row in rows]
    for row in result:
        row["amenities"] = _source_array(row["amenities"])
    return result


def transport_records(
    database: Path | str | sqlite3.Connection = DATABASE_PATH,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 100:
        raise OLAPError("Transport result limit must be between 1 and 100.")
    with _connection(database) as connection:
        rows = connection.execute(
            """
            SELECT "date", "day_of_week", "going_to", "distance",
                   "avg_speed", "total_time", "moving_time", "comments"
            FROM "stg_transport"
            ORDER BY "date" DESC, "start_time" DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def weather_history(
    city: str,
    database: Path | str | sqlite3.Connection = DATABASE_PATH,
) -> dict[str, Any]:
    table = WEATHER_TABLES.get(city.strip().lower())
    if table is None:
        raise OLAPError(
            f"Unsupported weather location. Choose from: {', '.join(WEATHER_TABLES)}."
        )
    with _connection(database) as connection:
        date_range = connection.execute(
            f'SELECT MIN("date_time"), MAX("date_time") FROM "{table}"'
        ).fetchone()
        months = connection.execute(
            f"""
            SELECT
                CAST(substr("date_time", 6, 2) AS INTEGER) AS month,
                ROUND(AVG(CAST("mintemp_c" AS REAL)), 1) AS average_min_c,
                ROUND(AVG(CAST("maxtemp_c" AS REAL)), 1) AS average_max_c,
                ROUND(AVG(CAST("precip_mm" AS REAL)), 1) AS average_precip_mm,
                ROUND(AVG(CAST("humidity" AS REAL)), 1) AS average_humidity,
                COUNT(*) AS observations
            FROM "{table}"
            WHERE "date_time" IS NOT NULL
            GROUP BY substr("date_time", 6, 2)
            ORDER BY month
            """
        ).fetchall()
    return {
        "city": city.title(),
        "historical": True,
        "date_range": list(date_range) if date_range else [None, None],
        "monthly_averages": [dict(row) for row in months],
    }


def review_insights(
    database: Path | str | sqlite3.Connection = DATABASE_PATH,
    *,
    limit: int = 12,
) -> dict[str, Any]:
    if limit < 1 or limit > 50:
        raise OLAPError("Review sample limit must be between 1 and 50.")
    with _connection(database) as connection:
        tourism_summary = connection.execute(
            """
            SELECT
                COUNT(*) AS review_count,
                ROUND(AVG(CAST("rating" AS REAL)), 2) AS average_rating,
                SUM(CASE WHEN CAST("rating" AS REAL) >= 4 THEN 1 ELSE 0 END) AS high_rated,
                SUM(CASE WHEN CAST("rating" AS REAL) <= 2 THEN 1 ELSE 0 END) AS low_rated
            FROM "stg_reviews"
            WHERE CAST("rating" AS REAL) BETWEEN 1 AND 5
            """
        ).fetchone()
        rating_bands = connection.execute(
            """
            SELECT CAST("rating" AS INTEGER) AS rating, COUNT(*) AS records
            FROM "stg_reviews"
            WHERE CAST("rating" AS REAL) BETWEEN 1 AND 5
            GROUP BY CAST("rating" AS INTEGER)
            ORDER BY rating
            """
        ).fetchall()
        frequent_places = connection.execute(
            """
            SELECT "city", "place", COUNT(*) AS review_count,
                   ROUND(AVG(CAST("rating" AS REAL)), 2) AS average_rating
            FROM "stg_reviews"
            WHERE "place" IS NOT NULL AND trim("place") <> ''
              AND CAST("rating" AS REAL) BETWEEN 1 AND 5
            GROUP BY "city", "place"
            ORDER BY review_count DESC
            LIMIT 10
            """
        ).fetchall()
        samples = connection.execute(
            """
            SELECT "city", "place", CAST("rating" AS REAL) AS rating,
                   substr("raw_review", 1, 1200) AS review
            FROM "stg_reviews"
            WHERE "raw_review" IS NOT NULL AND trim("raw_review") <> ''
              AND CAST("rating" AS REAL) BETWEEN 1 AND 5
            ORDER BY "warehouse_source_row_id" DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        hotel_summary = connection.execute(
            """
            SELECT COUNT(*) AS review_count,
                   ROUND(AVG(CAST("rating" AS REAL)), 2) AS average_rating
            FROM "stg_tripadvisor_hotel_reviews"
            WHERE CAST("rating" AS REAL) BETWEEN 1 AND 5
            """
        ).fetchone()
    return {
        "tourism_reviews": dict(tourism_summary),
        "rating_bands": [dict(row) for row in rating_bands],
        "frequent_places": [dict(row) for row in frequent_places],
        "samples": [dict(row) for row in samples],
        "hotel_review_summary": dict(hotel_summary),
        "analysis_note": (
            "High/low groups are based only on numeric ratings (4–5 and 1–2). "
            "Review text is not sentiment-classified."
        ),
    }
