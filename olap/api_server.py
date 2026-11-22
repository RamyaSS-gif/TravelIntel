"""Local HTTP API for the TravelIntel OLAP cube and customer booking requests."""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from config import PROJECT_ROOT
from olap.customer_data import (
    accommodations as customer_accommodations,
    destinations as customer_destinations,
    review_insights,
    transport_records,
    weather_history,
)
from olap.booking_store import (
    cancel_booking,
    create_booking,
    list_bookings,
)
from olap.olap_operations import FACTS, OLAPEngine, OLAPError, SCHEMAS


DATABASE_PATH = PROJECT_ROOT / "travelintel_warehouse.db"
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8765))
MAX_REQUEST_BYTES = 1_000_000
DIMENSION_LABELS = {
    "year": "Year",
    "quarter": "Quarter",
    "month": "Month",
    "hotel_type": "Hotel type",
    "market_segment": "Market segment",
    "customer_type": "Customer type",
    "reservation_status": "Reservation status",
    "city": "City",
    "neighbourhood": "Neighbourhood",
    "property_type": "Property type",
    "room_type": "Room type",
    "available": "Availability",
    "location": "Destination / location",
    "attractiveness_label": "Attractiveness",
}
MEASURE_LABELS = {
    "fact_rows": "Total records",
    "canceled_bookings": "Canceled bookings",
    "average_adr": "Average daily rate (ADR)",
    "average_lead_time": "Average lead time",
    "available_rows": "Available calendar rows",
    "unavailable_rows": "Unavailable calendar rows",
    "comments_present": "Reviews with comments",
    "average_rating": "Average rating",
    "recorded_visitors": "Recorded visitors",
    "average_cost": "Average cost",
    "average_sentiment_score": "Average sentiment score",
}
FACT_LABELS = {
    "hotel_booking": "Hotel bookings",
    "airbnb_calendar_boston": "Boston Airbnb calendar",
    "airbnb_calendar_seattle": "Seattle Airbnb calendar",
    "airbnb_review_boston": "Boston Airbnb reviews",
    "airbnb_review_seattle": "Seattle Airbnb reviews",
    "tourism_observation": "Tourism observations",
}
OPERATIONS = ("roll_up", "drill_down", "slice", "dice", "pivot")
ADMIN_EMAIL_ENV = "TRAVELINTEL_ADMIN_EMAIL"
ADMIN_PASSWORD_ENV = "TRAVELINTEL_ADMIN_PASSWORD"


def verify_admin_credentials(payload: Any) -> bool:
    expected_email = os.environ.get(ADMIN_EMAIL_ENV, "").strip().lower()
    expected_password = os.environ.get(ADMIN_PASSWORD_ENV, "")
    if not expected_email or not expected_password or not isinstance(payload, dict):
        return False

    email = payload.get("email")
    password = payload.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return False

    return (
        hmac.compare_digest(
            email.strip().lower().encode("utf-8"),
            expected_email.encode("utf-8"),
        )
        and hmac.compare_digest(
            password.encode("utf-8"),
            expected_password.encode("utf-8"),
        )
    )


def _label(name: str, labels: dict[str, str]) -> str:
    return labels.get(name, name.replace("_", " ").title())


def build_catalog(database: Path | str = DATABASE_PATH) -> dict[str, Any]:
    catalog: dict[str, Any] = {
        "schemas": list(SCHEMAS),
        "operations": list(OPERATIONS),
        "facts": [
            {"id": key, "label": FACT_LABELS[key]}
            for key in FACTS
        ],
        "models": {},
    }
    with OLAPEngine(database) as engine:
        for schema in SCHEMAS:
            catalog["models"][schema] = {}
            for fact in FACTS:
                plan = engine._plan(fact, schema)
                catalog["models"][schema][fact] = {
                    "table": plan["table"],
                    "default_groups": list(plan["default_groups"]),
                    "default_measures": list(plan["default_measures"]),
                    "dimensions": [
                        {"id": field, "label": _label(field, DIMENSION_LABELS)}
                        for field in plan["dimensions"]
                    ],
                    "measures": [
                        {"id": field, "label": _label(field, MEASURE_LABELS)}
                        for field in plan["measures"]
                    ],
                }
    return catalog


def dimension_values(
    schema: str,
    fact: str,
    dimension: str,
    database: Path | str = DATABASE_PATH,
    limit: int = 250,
) -> list[Any]:
    if limit < 1 or limit > 500:
        raise OLAPError("Dimension value limit must be between 1 and 500.")
    with OLAPEngine(database) as engine:
        plan = engine._plan(fact, schema)
        if dimension not in plan["dimensions"]:
            available = ", ".join(plan["dimensions"])
            raise OLAPError(
                f"Dimension {dimension!r} is unavailable for {fact!r}. "
                f"Available dimensions: {available}."
            )
        expression = plan["dimensions"][dimension]
        sql = (
            f'SELECT DISTINCT {expression} AS value FROM "{plan["table"]}" AS f'
            + plan["joins"]
            + f" WHERE {expression} IS NOT NULL ORDER BY {expression} LIMIT ?"
        )
        return [
            row[0]
            for row in engine.connection.execute(sql, (limit,)).fetchall()
        ]


def schema_catalog(
    schema: str,
    database: Path | str = DATABASE_PATH,
) -> dict[str, Any]:
    if schema not in SCHEMAS:
        raise OLAPError("Unsupported schema; choose 'star' or 'snowflake'.")

    prefix = SCHEMAS[schema]
    with OLAPEngine(database) as engine:
        tables = [
            row[0]
            for row in engine.connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND substr(name, 1, ?) = ? ORDER BY name",
                (len(prefix), prefix),
            )
        ]
        table_names = set(tables)
        table_details = []
        relationships = []

        for table in tables:
            metadata = _schema_table_metadata(engine, prefix, table)
            for foreign_key in metadata["foreign_keys"]:
                target = foreign_key["table"]
                if target in table_names:
                    relationships.append(
                        {
                            "from_table": table,
                            "to_table": target,
                            "columns": foreign_key["columns"],
                            "kind": (
                                "hierarchy"
                                if table.startswith(prefix + "dim_")
                                and target.startswith(prefix + "dim_")
                                else "relationship"
                            ),
                        }
                    )
            table_details.append(metadata)

        return {
            "schema": schema,
            "tables": table_details,
            "relationships": relationships,
        }


def _schema_table_metadata(
    engine: OLAPEngine,
    prefix: str,
    table: str,
) -> dict[str, Any]:
    if not table.startswith(prefix):
        raise OLAPError(f"Table {table!r} is unavailable in the selected schema.")
    exists = engine.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if exists is None:
        raise OLAPError(f"Table {table!r} is unavailable in the selected schema.")

    quoted_table = '"' + table.replace('"', '""') + '"'
    columns = [
        {
            "name": row[1],
            "type": row[2],
            "not_null": bool(row[3]),
            "default": row[4],
            "primary_key_order": row[5],
        }
        for row in engine.connection.execute(f"PRAGMA table_info({quoted_table})")
    ]
    grouped_foreign_keys: dict[int, dict[str, Any]] = {}
    for row in engine.connection.execute(
        f"PRAGMA foreign_key_list({quoted_table})"
    ):
        key = grouped_foreign_keys.setdefault(
            row[0],
            {"table": row[2], "columns": []},
        )
        key["columns"].append({"from": row[3], "to": row[4]})

    row_count = engine.connection.execute(
        f"SELECT COUNT(*) FROM {quoted_table}"
    ).fetchone()[0]
    return {
        "name": table,
        "kind": "fact" if table.startswith(prefix + "fact_") else "dimension",
        "columns": columns,
        "foreign_keys": list(grouped_foreign_keys.values()),
        "row_count": row_count,
    }


def schema_table(
    schema: str,
    table: str,
    database: Path | str = DATABASE_PATH,
    limit: int = 5,
) -> dict[str, Any]:
    if limit < 1 or limit > 25:
        raise OLAPError("Sample row limit must be between 1 and 25.")
    if schema not in SCHEMAS:
        raise OLAPError("Unsupported schema; choose 'star' or 'snowflake'.")

    with OLAPEngine(database) as engine:
        metadata = _schema_table_metadata(engine, SCHEMAS[schema], table)
        quoted_table = '"' + table.replace('"', '""') + '"'
        cursor = engine.connection.execute(
            f"SELECT * FROM {quoted_table} LIMIT ?", (limit,)
        )
        names = [column[0] for column in cursor.description]
        rows = [
            dict(zip(names, row))
            for row in cursor.fetchall()
        ]
    return {**metadata, "rows": rows}


def execute_request(
    payload: dict[str, Any],
    database: Path | str = DATABASE_PATH,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise OLAPError("Request body must be a JSON object.")
    schema = payload.get("schema", "star")
    fact = payload.get("fact")
    operation = payload.get("operation")
    if not isinstance(schema, str) or not isinstance(fact, str):
        raise OLAPError("Both schema and fact identifiers are required.")
    if operation not in OPERATIONS:
        raise OLAPError(f"Unsupported operation {operation!r}.")

    with OLAPEngine(database) as engine:
        plan = engine._plan(fact, schema)
        dimensions = plan["dimensions"]
        measures = plan["measures"]
        filters = payload.get("filters", {})
        if not isinstance(filters, dict):
            raise OLAPError("filters must be an object mapping dimensions to values.")
        selected_measures = payload.get("measures", plan["default_measures"])
        if operation != "pivot" and (
            not isinstance(selected_measures, list)
            or not all(isinstance(item, str) for item in selected_measures)
        ):
            raise OLAPError("measures must be an array of measure identifiers.")

        if operation in {"roll_up", "drill_down", "slice", "dice"}:
            group_by = payload.get("group_by", list(plan["default_groups"]))
            if not isinstance(group_by, list) or not all(
                isinstance(item, str) for item in group_by
            ):
                raise OLAPError("group_by must be an array of dimension identifiers.")

        if operation == "roll_up":
            rows = engine.roll_up(
                fact, schema, group_by, filters=filters, measures=selected_measures
            )
        elif operation == "drill_down":
            coarse = payload.get("from_group_by")
            if not isinstance(coarse, list) or not all(
                isinstance(item, str) for item in coarse
            ):
                raise OLAPError("from_group_by must be an array of dimensions.")
            rows = engine.drill_down(
                fact,
                coarse,
                group_by,
                schema,
                filters=filters,
                measures=selected_measures,
            )
        elif operation == "slice":
            dimension = payload.get("dimension")
            if not isinstance(dimension, str) or dimension not in dimensions:
                raise OLAPError(
                    "Choose one available dimension for the slice operation."
                )
            if dimension not in filters or len(filters) != 1:
                raise OLAPError(
                    "Slice requires exactly one filter value for the selected dimension."
                )
            rows = engine.slice(
                fact,
                dimension,
                filters[dimension],
                schema,
                group_by=group_by,
                measures=selected_measures,
            )
        elif operation == "dice":
            rows = engine.dice(
                fact,
                filters,
                schema,
                group_by=group_by,
                measures=selected_measures,
            )
        else:
            row_dimension = payload.get("row_dimension")
            column_dimension = payload.get("column_dimension")
            measure = payload.get("measure")
            if not all(
                isinstance(value, str)
                for value in (row_dimension, column_dimension, measure)
            ):
                raise OLAPError(
                    "Pivot requires row_dimension, column_dimension, and measure."
                )
            rows = engine.pivot(
                fact,
                row_dimension,
                column_dimension,
                measure,
                schema,
                filters=filters,
            )

        return {
            "schema": schema,
            "fact": fact,
            "operation": operation,
            "table": plan["table"],
            "dimensions": list(dimensions),
            "measures": list(measures),
            "filters": filters,
            "rows": rows,
        }


class APIHandler(BaseHTTPRequestHandler):
    server_version = "TravelIntelCube/1.0"

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"[cube-api] {self.address_string()} {format_string % args}")

    def _send_json(self, status: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request = urlparse(self.path)
        try:
            if request.path == "/api/health":
                with OLAPEngine(self.server.database_path) as engine:
                    engine.connection.execute("SELECT 1").fetchone()
                self._send_json(200, {"status": "ok", "database": "connected"})
            elif request.path == "/api/catalog":
                self._send_json(200, build_catalog(self.server.database_path))
            elif request.path == "/api/dimension-values":
                query = parse_qs(request.query)
                values = dimension_values(
                    _one_query_value(query, "schema"),
                    _one_query_value(query, "fact"),
                    _one_query_value(query, "dimension"),
                    self.server.database_path,
                )
                self._send_json(200, {"values": values})
            elif request.path == "/api/schema":
                query = parse_qs(request.query)
                self._send_json(
                    200,
                    schema_catalog(
                        _one_query_value(query, "schema"),
                        self.server.database_path,
                    ),
                )
            elif request.path == "/api/schema-table":
                query = parse_qs(request.query)
                self._send_json(
                    200,
                    schema_table(
                        _one_query_value(query, "schema"),
                        _one_query_value(query, "table"),
                        self.server.database_path,
                    ),
                )
            elif request.path == "/api/customer/destinations":
                self._send_json(
                    200,
                    {"destinations": customer_destinations(self.server.database_path)},
                )
            elif request.path == "/api/customer/accommodations":
                query = parse_qs(request.query)
                self._send_json(
                    200,
                    {
                        "accommodations": customer_accommodations(
                            self.server.database_path,
                            city=_optional_query_value(query, "city"),
                            search=_optional_query_value(query, "search"),
                            limit=_query_limit(query, 60, 100),
                        )
                    },
                )
            elif request.path == "/api/customer/transport":
                query = parse_qs(request.query)
                self._send_json(
                    200,
                    {
                        "records": transport_records(
                            self.server.database_path,
                            limit=_query_limit(query, 30, 100),
                        ),
                        "notice": (
                            "Historical commute-time records only; no tourist "
                            "routes, live schedules, or ticket inventory are available."
                        ),
                    },
                )
            elif request.path == "/api/customer/weather":
                query = parse_qs(request.query)
                self._send_json(
                    200,
                    weather_history(
                        _one_query_value(query, "city"),
                        self.server.database_path,
                    ),
                )
            elif request.path == "/api/customer/reviews":
                query = parse_qs(request.query)
                self._send_json(
                    200,
                    review_insights(
                        self.server.database_path,
                        limit=_query_limit(query, 12, 50),
                    ),
                )
            elif request.path == "/api/customer/bookings":
                query = parse_qs(request.query)
                self._send_json(
                    200,
                    {
                        "bookings": list_bookings(
                            self.server.database_path,
                            email=_one_query_value(query, "email"),
                        )
                    },
                )
            elif request.path == "/api/admin/bookings":
                query = parse_qs(request.query)
                self._send_json(
                    200,
                    {
                        "bookings": list_bookings(
                            self.server.database_path,
                            travel_date=_optional_query_value(query, "date") or None,
                            booking_type=_optional_query_value(query, "category") or None,
                            booking_status=_optional_query_value(query, "status") or None,
                        )
                    },
                )
            else:
                self._send_json(404, {"error": "API route not found."})
        except (OLAPError, KeyError) as error:
            self._send_json(400, {"error": str(error)})
        except (sqlite3.Error, FileNotFoundError) as error:
            self._send_json(500, {"error": f"Database query failed: {error}"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 1 or content_length > MAX_REQUEST_BYTES:
                self._send_json(413, {"error": "Request body is empty or too large."})
                return
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if path == "/api/query":
                self._send_json(
                    200, execute_request(payload, self.server.database_path)
                )
                return
            if path == "/api/admin/login":
                if (
                    not os.environ.get(ADMIN_EMAIL_ENV, "").strip()
                    or not os.environ.get(ADMIN_PASSWORD_ENV, "")
                ):
                    self._send_json(
                        503,
                        {
                            "error": (
                                "Admin login is not configured. Set "
                                f"{ADMIN_EMAIL_ENV} and {ADMIN_PASSWORD_ENV}."
                            )
                        },
                    )
                    return
                if not verify_admin_credentials(payload):
                    self._send_json(401, {"error": "Admin email or password is incorrect."})
                    return
                self._send_json(
                    200,
                    {
                        "role": "admin",
                        "email": os.environ[ADMIN_EMAIL_ENV].strip().lower(),
                    },
                )
                return
            if path == "/api/customer/bookings":
                booking = create_booking(payload, self.server.database_path)
                self._send_json(201, {"booking": booking})
                return
            if path.startswith("/api/customer/bookings/") and path.endswith("/cancel"):
                reference = path[len("/api/customer/bookings/"):-len("/cancel")].strip("/")
                email = payload.get("email") if isinstance(payload, dict) else None
                if not isinstance(email, str):
                    raise OLAPError("Customer email is required to cancel a request.")
                self._send_json(
                    200,
                    {"booking": cancel_booking(reference, email, self.server.database_path)},
                )
                return
            self._send_json(404, {"error": "API route not found."})
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self._send_json(400, {"error": f"Invalid JSON request: {error}"})
        except (OLAPError, KeyError, ValueError) as error:
            self._send_json(400, {"error": str(error)})
        except (sqlite3.Error, FileNotFoundError) as error:
            self._send_json(500, {"error": f"Database query failed: {error}"})


def _one_query_value(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name)
    if not values or not values[0]:
        raise OLAPError(f"Missing required query parameter: {name}.")
    return values[0]


def _optional_query_value(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name)
    return values[0] if values else ""


def _query_limit(query: dict[str, list[str]], default: int, maximum: int) -> int:
    value = _optional_query_value(query, "limit")
    if not value:
        return default
    try:
        limit = int(value)
    except ValueError as error:
        raise OLAPError("The limit parameter must be an integer.") from error
    if limit < 1 or limit > maximum:
        raise OLAPError(f"The limit parameter must be between 1 and {maximum}.")
    return limit


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), APIHandler)
    server.database_path = DATABASE_PATH
    print(f"TravelIntel cube API: http://{HOST}:{PORT}/api/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping TravelIntel cube API.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
