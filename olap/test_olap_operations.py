"""Tests for OLAP operations against small Star and Snowflake fixtures."""

from __future__ import annotations

import sqlite3
import unittest

from olap.olap_operations import FACTS, OLAPEngine, OLAPError


def create_hotel_fixture(connection: sqlite3.Connection, prefix: str) -> None:
    if prefix == "star_":
        connection.executescript(
            """
            CREATE TABLE star_dim_date (
                date_key INTEGER PRIMARY KEY, year INTEGER, quarter INTEGER, month INTEGER
            );
            CREATE TABLE star_dim_hotel_type (
                hotel_key INTEGER PRIMARY KEY, hotel_type TEXT
            );
            CREATE TABLE star_fact_hotel_booking (
                booking_fact_id INTEGER PRIMARY KEY, date_key INTEGER, hotel_key INTEGER,
                is_canceled INTEGER, adr REAL, lead_time INTEGER, market_segment TEXT,
                customer_type TEXT, reservation_status TEXT
            );
            INSERT INTO star_dim_date VALUES (1, 2024, 1, 1), (2, 2024, 1, 2), (3, 2025, 1, 1);
            INSERT INTO star_dim_hotel_type VALUES (1, 'City Hotel'), (2, 'Resort Hotel');
            INSERT INTO star_fact_hotel_booking VALUES
                (1, 1, 1, 0, 100.0, 10, 'Online', 'Transient', 'Check-Out'),
                (2, 2, 1, 1, 200.0, 20, 'Online', 'Transient', 'Canceled'),
                (3, 3, 2, 0, 150.0, 30, 'Direct', 'Contract', 'Check-Out');
            """
        )
    else:
        connection.executescript(
            """
            CREATE TABLE snowflake_dim_calendar_month (
                month_key INTEGER PRIMARY KEY, year INTEGER, quarter INTEGER, month INTEGER
            );
            CREATE TABLE snowflake_dim_date (
                date_key INTEGER PRIMARY KEY, month_key INTEGER
            );
            CREATE TABLE snowflake_dim_hotel_type (
                hotel_key INTEGER PRIMARY KEY, hotel_type TEXT
            );
            CREATE TABLE snowflake_fact_hotel_booking (
                booking_fact_id INTEGER PRIMARY KEY, date_key INTEGER, hotel_key INTEGER,
                is_canceled INTEGER, adr REAL, lead_time INTEGER, market_segment TEXT,
                customer_type TEXT, reservation_status TEXT
            );
            INSERT INTO snowflake_dim_calendar_month VALUES
                (1, 2024, 1, 1), (2, 2024, 1, 2), (3, 2025, 1, 1);
            INSERT INTO snowflake_dim_date VALUES (1, 1), (2, 2), (3, 3);
            INSERT INTO snowflake_dim_hotel_type VALUES (1, 'City Hotel'), (2, 'Resort Hotel');
            INSERT INTO snowflake_fact_hotel_booking VALUES
                (1, 1, 1, 0, 100.0, 10, 'Online', 'Transient', 'Check-Out'),
                (2, 2, 1, 1, 200.0, 20, 'Online', 'Transient', 'Canceled'),
                (3, 3, 2, 0, 150.0, 30, 'Direct', 'Contract', 'Check-Out');
            """
        )


class OLAPOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        create_hotel_fixture(self.connection, "star_")
        create_hotel_fixture(self.connection, "snowflake_")
        self.engine = OLAPEngine(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_roll_up_matches_direct_sql(self) -> None:
        actual = self.engine.roll_up(
            "hotel_booking", group_by=("year",),
            measures=("fact_rows", "canceled_bookings"),
        )
        direct = self.connection.execute(
            """
            SELECT d.year, COUNT(*), SUM(CASE WHEN f.is_canceled=1 THEN 1 ELSE 0 END)
            FROM star_fact_hotel_booking f
            JOIN star_dim_date d ON d.date_key=f.date_key
            GROUP BY d.year ORDER BY d.year
            """
        ).fetchall()
        self.assertEqual(
            [(row["year"], row["fact_rows"], row["canceled_bookings"]) for row in actual],
            direct,
        )

    def test_drill_down_matches_direct_sql(self) -> None:
        actual = self.engine.drill_down(
            "hotel_booking", ("year",), ("year", "month"),
            measures=("fact_rows",),
        )
        direct = self.connection.execute(
            """
            SELECT d.year, d.month, COUNT(*)
            FROM star_fact_hotel_booking f
            JOIN star_dim_date d ON d.date_key=f.date_key
            GROUP BY d.year, d.month ORDER BY d.year, d.month
            """
        ).fetchall()
        self.assertEqual(
            [(row["year"], row["month"], row["fact_rows"]) for row in actual],
            direct,
        )

    def test_slice_matches_direct_sql_and_uses_snowflake_dates(self) -> None:
        actual = self.engine.slice(
            "hotel_booking", "hotel_type", "City Hotel",
            group_by=("year",), measures=("fact_rows",),
        )
        direct = self.connection.execute(
            """
            SELECT d.year, COUNT(*)
            FROM star_fact_hotel_booking f
            JOIN star_dim_date d ON d.date_key=f.date_key
            JOIN star_dim_hotel_type h ON h.hotel_key=f.hotel_key
            WHERE h.hotel_type=?
            GROUP BY d.year ORDER BY d.year
            """,
            ("City Hotel",),
        ).fetchall()
        self.assertEqual([(row["year"], row["fact_rows"]) for row in actual], direct)

        snowflake = self.engine.roll_up(
            "hotel_booking", "snowflake", group_by=("year", "month"),
            measures=("fact_rows",),
        )
        self.assertEqual(sum(row["fact_rows"] for row in snowflake), 3)

    def test_dice_matches_direct_sql(self) -> None:
        actual = self.engine.dice(
            "hotel_booking",
            {"year": 2024, "market_segment": "Online"},
            group_by=("month",), measures=("fact_rows",),
        )
        direct = self.connection.execute(
            """
            SELECT d.month, COUNT(*)
            FROM star_fact_hotel_booking f
            JOIN star_dim_date d ON d.date_key=f.date_key
            WHERE d.year=? AND f.market_segment=?
            GROUP BY d.month ORDER BY d.month
            """,
            (2024, "Online"),
        ).fetchall()
        self.assertEqual([(row["month"], row["fact_rows"]) for row in actual], direct)

    def test_pivot_matches_direct_sql(self) -> None:
        actual = self.engine.pivot(
            "hotel_booking", "year", "hotel_type", "fact_rows"
        )
        self.assertEqual(
            actual,
            [
                {"year": 2024, "City Hotel": 2, "Resort Hotel": None},
                {"year": 2025, "City Hotel": None, "Resort Hotel": 1},
            ],
        )
        direct = self.connection.execute(
            """
            SELECT d.year, h.hotel_type, COUNT(*)
            FROM star_fact_hotel_booking f
            JOIN star_dim_date d ON d.date_key=f.date_key
            JOIN star_dim_hotel_type h ON h.hotel_key=f.hotel_key
            GROUP BY d.year, h.hotel_type
            """
        ).fetchall()
        self.assertEqual(
            sum(value or 0 for row in actual for key, value in row.items() if key != "year"),
            sum(row[2] for row in direct),
        )

    def test_unsupported_dimensions_and_invalid_drill_down_are_explicit(self) -> None:
        with self.assertRaisesRegex(OLAPError, "Available dimensions"):
            self.engine.slice("hotel_booking", "destination", "Nowhere")
        with self.assertRaisesRegex(OLAPError, "Drill-down requires"):
            self.engine.drill_down(
                "hotel_booking", ("year",), ("month",),
                measures=("fact_rows",),
            )
        with self.assertRaisesRegex(OLAPError, "at least two"):
            self.engine.dice("hotel_booking", {"year": 2024})

    def test_all_six_fact_tables_are_supported_separately(self) -> None:
        self.assertEqual(
            set(FACTS),
            {
                "hotel_booking",
                "airbnb_calendar_boston",
                "airbnb_calendar_seattle",
                "airbnb_review_boston",
                "airbnb_review_seattle",
                "tourism_observation",
            },
        )


if __name__ == "__main__":
    unittest.main()
