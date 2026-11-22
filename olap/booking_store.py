"""Central persistence for customer booking requests.

Booking requests are deliberately separate from the analytical warehouse facts.
They represent customer intent only; this module never creates supplier or
payment confirmations.
"""

from __future__ import annotations

import json
import math
import re
import secrets
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT
from olap.olap_operations import OLAPError


DATABASE_PATH = PROJECT_ROOT / "travelintel_warehouse.db"
BOOKING_TYPES = {"hotel", "bus", "train", "flight", "rental", "taxi", "trip plan"}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
BOOKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS customer_bookings (
    booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_reference TEXT NOT NULL UNIQUE,
    customer_name TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    booking_type TEXT NOT NULL,
    origin TEXT,
    destination TEXT,
    travel_date TEXT NOT NULL,
    return_date TEXT,
    passenger_details TEXT NOT NULL,
    price_breakdown TEXT NOT NULL,
    payment_status TEXT NOT NULL DEFAULT 'not_processed',
    booking_status TEXT NOT NULL DEFAULT 'planning_request',
    request_details TEXT NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_customer_bookings_email
    ON customer_bookings(customer_email);
CREATE INDEX IF NOT EXISTS idx_customer_bookings_created
    ON customer_bookings(created_at);
"""


def _connection(database: Path | str | sqlite3.Connection) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, sqlite3.Connection):
        database.row_factory = sqlite3.Row
        return database, False
    connection = sqlite3.connect(Path(database).resolve())
    connection.row_factory = sqlite3.Row
    return connection, True


def ensure_booking_table(database: Path | str | sqlite3.Connection = DATABASE_PATH) -> None:
    connection, owned = _connection(database)
    try:
        connection.executescript(BOOKING_TABLE_SQL)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(customer_bookings)")
        }
        if "client_request_id" not in columns:
            connection.execute(
                "ALTER TABLE customer_bookings ADD COLUMN client_request_id TEXT"
            )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_bookings_request_id "
            "ON customer_bookings(client_request_id) WHERE client_request_id IS NOT NULL"
        )
        connection.commit()
    finally:
        if owned:
            connection.close()


def _required_text(payload: dict[str, Any], field: str, maximum: int) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise OLAPError(f"{field} is required.")
    value = value.strip()
    if len(value) > maximum:
        raise OLAPError(f"{field} must be no longer than {maximum} characters.")
    return value


def _optional_text(payload: dict[str, Any], field: str, maximum: int) -> str | None:
    value = payload.get(field)
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise OLAPError(f"{field} must be text no longer than {maximum} characters.")
    return value.strip() or None


def _json_object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field, {})
    if not isinstance(value, dict):
        raise OLAPError(f"{field} must be an object.")
    try:
        json.dumps(value)
    except (TypeError, ValueError) as error:
        raise OLAPError(f"{field} contains values that cannot be stored.") from error
    return value


def _row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for field in ("passenger_details", "price_breakdown", "request_details"):
        try:
            result[field] = json.loads(result[field])
        except (TypeError, json.JSONDecodeError):
            result[field] = {}
    result["customerName"] = result.pop("customer_name")
    result["email"] = result.pop("customer_email")
    result["reference"] = result.pop("booking_reference")
    result["bookingType"] = result.pop("booking_type")
    result["travelDate"] = result.pop("travel_date")
    result["returnDate"] = result.pop("return_date")
    result["passengerDetails"] = result.pop("passenger_details")
    result["priceBreakdown"] = result.pop("price_breakdown")
    result["paymentStatus"] = result.pop("payment_status")
    result["bookingStatus"] = result.pop("booking_status")
    result["requestDetails"] = result.pop("request_details")
    result["createdAt"] = result.pop("created_at")
    result["requestId"] = result.pop("client_request_id")
    return result


def create_booking(
    payload: dict[str, Any],
    database: Path | str | sqlite3.Connection = DATABASE_PATH,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise OLAPError("Request body must be a JSON object.")
    customer_name = _required_text(payload, "customerName", 200)
    email = _required_text(payload, "email", 320).lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise OLAPError("Enter a valid email address.")
    booking_type = _required_text(payload, "bookingType", 40).lower()
    if booking_type not in BOOKING_TYPES:
        raise OLAPError("Unsupported booking type.")
    travel_date = _required_text(payload, "travelDate", 10)
    try:
        date.fromisoformat(travel_date)
    except ValueError as error:
        raise OLAPError("travelDate must use YYYY-MM-DD format.") from error
    if travel_date < date.today().isoformat():
        raise OLAPError("travelDate cannot be in the past.")
    return_date = _optional_text(payload, "returnDate", 10)
    if return_date:
        try:
            date.fromisoformat(return_date)
        except ValueError as error:
            raise OLAPError("returnDate must use YYYY-MM-DD format.") from error
        if return_date < travel_date:
            raise OLAPError("returnDate cannot be before travelDate.")
    origin = _optional_text(payload, "origin", 300)
    destination = _optional_text(payload, "destination", 300)
    passenger_details = _json_object(payload, "passengerDetails")
    passengers = passenger_details.get("passengers")
    if (
        isinstance(passengers, bool)
        or not isinstance(passengers, int)
        or passengers < 1
        or passengers > 20
    ):
        raise OLAPError("passengerDetails.passengers must be a whole number from 1 to 20.")
    supplied_price_breakdown = _json_object(payload, "priceBreakdown")
    customer_estimate = supplied_price_breakdown.get("customerEstimate")
    if customer_estimate is not None:
        if (
            isinstance(customer_estimate, bool)
            or not isinstance(customer_estimate, (int, float))
            or not math.isfinite(customer_estimate)
            or customer_estimate < 0
            or customer_estimate > 1_000_000_000
        ):
            raise OLAPError("customerEstimate must be a non-negative number up to 1,000,000,000.")
    estimate_currency = supplied_price_breakdown.get("currency")
    if customer_estimate is not None:
        if (
            not isinstance(estimate_currency, str)
            or estimate_currency not in {"INR", "USD", "EUR", "GBP"}
        ):
            raise OLAPError("Estimate currency must be INR, USD, EUR, or GBP.")
    else:
        estimate_currency = None
    historical_rate = supplied_price_breakdown.get("historicalNightlyRate")
    if historical_rate is not None and (
        not isinstance(historical_rate, str) or len(historical_rate) > 100
    ):
        raise OLAPError("historicalNightlyRate must be text no longer than 100 characters.")
    price_breakdown = {
        "supplierQuote": None,
        "taxes": None,
        "actualTotal": None,
        "customerEstimate": customer_estimate,
        "currency": estimate_currency,
        "historicalNightlyRate": historical_rate,
        "note": "No supplier quote or payable total has been verified.",
    }
    request_details = _json_object(payload, "requestDetails")
    request_id = _optional_text(payload, "requestId", 100)
    reference = f"TI-REQ-{secrets.token_hex(5).upper()}"
    created_at = datetime.now(timezone.utc).isoformat()
    connection, owned = _connection(database)
    try:
        ensure_booking_table(connection)
        if request_id:
            existing = connection.execute(
                "SELECT * FROM customer_bookings WHERE client_request_id = ?",
                (request_id,),
            ).fetchone()
            if existing:
                if existing["customer_email"] != email:
                    raise OLAPError("This request identifier is already in use.")
                return _row(existing)
        try:
            connection.execute(
                """
                INSERT INTO customer_bookings (
                    booking_reference, customer_name, customer_email, booking_type,
                    origin, destination, travel_date, return_date, passenger_details,
                    price_breakdown, payment_status, booking_status, request_details,
                    created_at, client_request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_processed',
                          'planning_request', ?, ?, ?)
                """,
                (
                    reference, customer_name, email, booking_type, origin, destination,
                    travel_date, return_date, json.dumps(passenger_details),
                    json.dumps(price_breakdown), json.dumps(request_details), created_at,
                    request_id,
                ),
            )
        except sqlite3.IntegrityError:
            if request_id:
                existing = connection.execute(
                    "SELECT * FROM customer_bookings WHERE client_request_id = ?",
                    (request_id,),
                ).fetchone()
                if existing and existing["customer_email"] == email:
                    return _row(existing)
            raise
        connection.commit()
        row = connection.execute(
            "SELECT * FROM customer_bookings WHERE booking_reference = ?",
            (reference,),
        ).fetchone()
        return _row(row)
    finally:
        if owned:
            connection.close()


def list_bookings(
    database: Path | str | sqlite3.Connection = DATABASE_PATH,
    *,
    email: str | None = None,
    travel_date: str | None = None,
    booking_type: str | None = None,
    booking_status: str | None = None,
) -> list[dict[str, Any]]:
    connection, owned = _connection(database)
    try:
        ensure_booking_table(connection)
        conditions = []
        parameters: list[Any] = []
        if email is not None:
            normalized = _required_text({"email": email}, "email", 320).lower()
            if not EMAIL_PATTERN.fullmatch(normalized):
                raise OLAPError("Enter a valid email address.")
            conditions.append("customer_email = ?")
            parameters.append(normalized)
        if travel_date:
            try:
                date.fromisoformat(travel_date)
            except ValueError as error:
                raise OLAPError("date must use YYYY-MM-DD format.") from error
            conditions.append("travel_date = ?")
            parameters.append(travel_date)
        if booking_type:
            if booking_type not in BOOKING_TYPES:
                raise OLAPError("Unsupported booking type filter.")
            conditions.append("booking_type = ?")
            parameters.append(booking_type)
        if booking_status:
            if booking_status not in {"planning_request", "cancelled_request"}:
                raise OLAPError("Unsupported booking status filter.")
            conditions.append("booking_status = ?")
            parameters.append(booking_status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = connection.execute(
            "SELECT * FROM customer_bookings " + where
            + " ORDER BY created_at DESC, booking_id DESC",
            parameters,
        ).fetchall()
        return [_row(row) for row in rows]
    finally:
        if owned:
            connection.close()


def cancel_booking(
    reference: str,
    email: str,
    database: Path | str | sqlite3.Connection = DATABASE_PATH,
) -> dict[str, Any]:
    if not reference or not isinstance(reference, str):
        raise OLAPError("A booking reference is required.")
    normalized_email = _required_text({"email": email}, "email", 320).lower()
    connection, owned = _connection(database)
    try:
        ensure_booking_table(connection)
        cursor = connection.execute(
            "UPDATE customer_bookings SET booking_status = 'cancelled_request' "
            "WHERE booking_reference = ? AND customer_email = ?",
            (reference, normalized_email),
        )
        if cursor.rowcount == 0:
            raise OLAPError("Booking request was not found for this customer.")
        connection.commit()
        row = connection.execute(
            "SELECT * FROM customer_bookings WHERE booking_reference = ?",
            (reference,),
        ).fetchone()
        return _row(row)
    finally:
        if owned:
            connection.close()
