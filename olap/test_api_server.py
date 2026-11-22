"""Tests for OLAP cube API request validation and dispatch."""

from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from olap.api_server import (
    dimension_values,
    execute_request,
    schema_catalog,
    schema_table,
    verify_admin_credentials,
)
from olap.olap_operations import OLAPError
from olap.test_olap_operations import create_hotel_fixture


class CubeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        create_hotel_fixture(self.connection, "star_")

    def tearDown(self) -> None:
        self.connection.close()

    def test_admin_login_accepts_only_configured_admin_credentials(self) -> None:
        credentials = {
            "TRAVELINTEL_ADMIN_EMAIL": "ops@example.test",
            "TRAVELINTEL_ADMIN_PASSWORD": "admin-secret",
        }
        with patch.dict("os.environ", credentials, clear=True):
            self.assertTrue(
                verify_admin_credentials(
                    {"email": " OPS@example.test ", "password": "admin-secret"}
                )
            )
            self.assertFalse(
                verify_admin_credentials(
                    {"email": "customer@example.test", "password": "customer-secret"}
                )
            )

    def test_admin_login_fails_closed_when_credentials_are_unconfigured(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(
                verify_admin_credentials(
                    {"email": "ops@example.test", "password": "admin-secret"}
                )
            )

    def test_dimension_values_come_from_fixture_database(self) -> None:
        self.assertEqual(
            dimension_values(
                "star", "hotel_booking", "hotel_type", self.connection
            ),
            ["City Hotel", "Resort Hotel"],
        )

    def test_api_dispatches_all_five_real_olap_operations(self) -> None:
        cases = [
            {
                "operation": "roll_up",
                "group_by": ["year"],
                "measures": ["fact_rows"],
            },
            {
                "operation": "drill_down",
                "from_group_by": ["year"],
                "group_by": ["year", "month"],
                "measures": ["fact_rows"],
            },
            {
                "operation": "slice",
                "dimension": "hotel_type",
                "filters": {"hotel_type": "City Hotel"},
                "group_by": ["year"],
                "measures": ["fact_rows"],
            },
            {
                "operation": "dice",
                "filters": {"year": 2024, "market_segment": "Online"},
                "group_by": ["month"],
                "measures": ["fact_rows"],
            },
            {
                "operation": "pivot",
                "row_dimension": "year",
                "column_dimension": "hotel_type",
                "measure": "fact_rows",
            },
        ]
        for case in cases:
            with self.subTest(operation=case["operation"]):
                result = execute_request(
                    {"schema": "star", "fact": "hotel_booking", **case},
                    self.connection,
                )
                self.assertEqual(result["operation"], case["operation"])
                self.assertTrue(result["rows"])

    def test_api_rejects_unavailable_dimensions(self) -> None:
        with self.assertRaisesRegex(OLAPError, "Available dimensions"):
            execute_request(
                {
                    "schema": "star",
                    "fact": "hotel_booking",
                    "operation": "roll_up",
                    "group_by": ["destination"],
                    "measures": ["fact_rows"],
                },
                self.connection,
            )

    def test_schema_metadata_and_sample_records_come_from_sqlite(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.executescript(
            """
            CREATE TABLE star_dim_sample (
                sample_key INTEGER PRIMARY KEY,
                sample_name TEXT NOT NULL
            );
            CREATE TABLE star_fact_sample (
                fact_key INTEGER PRIMARY KEY,
                sample_key INTEGER NOT NULL,
                FOREIGN KEY (sample_key) REFERENCES star_dim_sample(sample_key)
            );
            INSERT INTO star_dim_sample VALUES (7, 'Actual dimension');
            INSERT INTO star_fact_sample VALUES (11, 7);
            """
        )
        try:
            catalog = schema_catalog("star", connection)
            fact = next(
                item for item in catalog["tables"]
                if item["name"] == "star_fact_sample"
            )
            self.assertEqual(fact["row_count"], 1)
            self.assertEqual(
                catalog["relationships"],
                [
                    {
                        "from_table": "star_fact_sample",
                        "to_table": "star_dim_sample",
                        "columns": [{"from": "sample_key", "to": "sample_key"}],
                        "kind": "relationship",
                    }
                ],
            )

            details = schema_table("star", "star_fact_sample", connection)
            self.assertEqual(
                [column["name"] for column in details["columns"]],
                ["fact_key", "sample_key"],
            )
            self.assertEqual(details["columns"][0]["primary_key_order"], 1)
            self.assertEqual(details["rows"], [{"fact_key": 11, "sample_key": 7}])
        finally:
            connection.close()

    def test_schema_table_rejects_tables_outside_selected_model(self) -> None:
        with self.assertRaisesRegex(OLAPError, "unavailable"):
            schema_table("star", "snowflake_dim_date", self.connection)

    def test_schema_table_rejects_missing_tables_with_valid_prefix(self) -> None:
        with self.assertRaisesRegex(OLAPError, "unavailable"):
            schema_table("star", "star_fact_missing", self.connection)


if __name__ == "__main__":
    unittest.main()
