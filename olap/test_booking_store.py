"""Tests for persistent customer booking request records."""

from __future__ import annotations

import sqlite3
import unittest
from datetime import date, timedelta

from olap.booking_store import (
    cancel_booking,
    create_booking,
    ensure_booking_table,
    list_bookings,
)
from olap.olap_operations import OLAPError


class BookingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.payload = {
            "customerName": "Travel Customer",
            "email": "travel@example.com",
            "requestId": "request-unique-001",
            "bookingType": "hotel",
            "origin": "Seattle",
            "destination": "Boston",
            "travelDate": (date.today() + timedelta(days=30)).isoformat(),
            "returnDate": (date.today() + timedelta(days=32)).isoformat(),
            "passengerDetails": {"passengers": 2, "rooms": 1},
            "priceBreakdown": {"actualTotal": None},
            "requestDetails": {"hotel": {"roomType": "Private room"}},
        }

    def tearDown(self) -> None:
        self.connection.close()

    def test_create_is_persistent_and_never_confirms_payment_or_booking(self) -> None:
        created = create_booking(self.payload, self.connection)
        loaded = list_bookings(self.connection, email=self.payload["email"])
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["reference"], created["reference"])
        self.assertEqual(created["paymentStatus"], "not_processed")
        self.assertEqual(created["bookingStatus"], "planning_request")

    def test_client_cannot_set_paid_confirmed_or_actual_price(self) -> None:
        payload = {
            **self.payload,
            "paymentStatus": "paid",
            "bookingStatus": "confirmed",
            "priceBreakdown": {
                "customerEstimate": 1250,
                "currency": "INR",
                "supplierQuote": 1250,
                "actualTotal": 1250,
            },
        }
        booking = create_booking(payload, self.connection)
        self.assertEqual(booking["paymentStatus"], "not_processed")
        self.assertEqual(booking["bookingStatus"], "planning_request")
        self.assertIsNone(booking["priceBreakdown"]["supplierQuote"])
        self.assertIsNone(booking["priceBreakdown"]["actualTotal"])
        self.assertEqual(booking["priceBreakdown"]["customerEstimate"], 1250)

    def test_repeated_request_id_does_not_create_duplicate(self) -> None:
        first = create_booking(self.payload, self.connection)
        retry = create_booking(self.payload, self.connection)
        self.assertEqual(first["reference"], retry["reference"])
        self.assertEqual(len(list_bookings(self.connection)), 1)

    def test_cancel_requires_matching_customer_email(self) -> None:
        booking = create_booking(self.payload, self.connection)
        with self.assertRaises(OLAPError):
            cancel_booking(booking["reference"], "other@example.com", self.connection)
        cancelled = cancel_booking(
            booking["reference"], self.payload["email"], self.connection
        )
        self.assertEqual(cancelled["bookingStatus"], "cancelled_request")
        self.assertEqual(
            list_bookings(self.connection, email=self.payload["email"])[0]["bookingStatus"],
            "cancelled_request",
        )

    def test_invalid_date_and_passenger_count_are_rejected(self) -> None:
        invalid_date = {**self.payload, "travelDate": "not-a-date"}
        invalid_passengers = {
            **self.payload,
            "passengerDetails": {"passengers": 0},
        }
        with self.assertRaises(OLAPError):
            create_booking(invalid_date, self.connection)
        with self.assertRaises(OLAPError):
            create_booking(invalid_passengers, self.connection)

    def test_customer_estimate_rejects_invalid_currency_and_amount(self) -> None:
        invalid_currency = {
            **self.payload,
            "priceBreakdown": {"customerEstimate": 100, "currency": []},
        }
        invalid_amount = {
            **self.payload,
            "priceBreakdown": {"customerEstimate": -1, "currency": "USD"},
        }
        with self.assertRaises(OLAPError):
            create_booking(invalid_currency, self.connection)
        with self.assertRaises(OLAPError):
            create_booking(invalid_amount, self.connection)

    def test_admin_filters_by_date_category_and_status(self) -> None:
        booking = create_booking(self.payload, self.connection)
        self.assertEqual(
            len(list_bookings(
                self.connection,
                travel_date=booking["travelDate"],
                booking_type="hotel",
                booking_status="planning_request",
            )),
            1,
        )
        self.assertEqual(
            list_bookings(self.connection, booking_type="train"),
            [],
        )

    def test_migrates_existing_phase_one_table(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE customer_bookings (
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
                payment_status TEXT NOT NULL,
                booking_status TEXT NOT NULL,
                request_details TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        ensure_booking_table(self.connection)
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(customer_bookings)")
        }
        self.assertIn("client_request_id", columns)


if __name__ == "__main__":
    unittest.main()
