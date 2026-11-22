"""Tests for warehouse keys, relationships, and source preservation."""

from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from warehouse.create_warehouse import _stage_sources, build_warehouse
from warehouse.build_dimensional_schemas import build_dimensional_schemas


def write_source(run_dir: Path, filename: str, frame: pd.DataFrame) -> None:
    frame.to_csv(run_dir / filename, index=False)


class WarehouseBuildTests(unittest.TestCase):
    def test_builds_fact_dimensions_and_valid_foreign_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "etl_run_test"
            run_dir.mkdir()
            report_dir = root / "reports"

            hotel = pd.DataFrame([{
                "hotel": "City Hotel",
                "is_canceled": 0,
                "lead_time": 10,
                "arrival_date_year": 2016,
                "arrival_date_month": "January",
                "arrival_date_day_of_month": 3,
                "stays_in_weekend_nights": 1,
                "stays_in_week_nights": 2,
                "adults": 2,
                "children": 0,
                "babies": 0,
                "previous_cancellations": 0,
                "previous_bookings_not_canceled": 0,
                "booking_changes": 0,
                "days_in_waiting_list": 0,
                "adr": 120.5,
                "required_car_parking_spaces": 0,
                "total_of_special_requests": 1,
                "market_segment": "Direct",
                "distribution_channel": "Direct",
                "customer_type": "Transient",
                "reservation_status": "Check-Out",
                "reservation_status_date": "2016-01-03",
                "etl_source_file": "hotel_bookings.csv",
            }])
            write_source(run_dir, "cleaned_hotel.csv", hotel)
            write_source(run_dir, "cleaned_transport.csv", pd.DataFrame({
                "date": ["2016-01-03"], "distance": [5.0],
                "etl_source_file": ["travel-times.csv"],
            }))

            for city, identifier in (("boston", 101), ("seattle", 202)):
                prefix = f"cleaned_hotel_accomodation_3_{city}_airbnb_open_data_"
                listings = pd.DataFrame([{
                    "id": identifier,
                    "name": f"{city} home",
                    "neighbourhood_cleansed": "Central",
                    "property_type": "Apartment",
                    "room_type": "Entire home/apt",
                    "accommodates": 2,
                    "bedrooms": 1,
                    "beds": 1,
                    "price": "$100.00",
                    "number_of_reviews": 1,
                    "review_scores_rating": 95.0,
                    "etl_source_file": f"{city}_listings.csv",
                }])
                write_source(run_dir, prefix + "listings.csv", listings)
                write_source(run_dir, prefix + "calendar.csv", pd.DataFrame([{
                    "listing_id": identifier, "date": "2016-01-03",
                    "available": "t", "price": "$100.00",
                    "etl_source_file": f"{city}_calendar.csv",
                }]))
                write_source(run_dir, prefix + "reviews.csv", pd.DataFrame([{
                    "listing_id": identifier, "id": identifier + 1,
                    "date": "2016-01-03", "reviewer_id": 1,
                    "reviewer_name": "Guest", "comments": "Good stay",
                    "etl_source_file": f"{city}_reviews.csv",
                }]))

            from warehouse.create_warehouse import TOURISM_METRICS

            tourism = {
                "image_id": [1],
                "location_name": ["Test Place"],
                "etl_source_file": ["tourism_dataset.csv"],
            }
            for metric in TOURISM_METRICS:
                if metric in {"review_text", "attractiveness_label"}:
                    tourism[metric] = ["A sample" if metric == "review_text" else "Popular"]
                else:
                    tourism[metric] = [1]
            write_source(run_dir, "cleaned_tourism.csv", pd.DataFrame(tourism))

            output_files = sorted(path.name for path in run_dir.glob("cleaned_*.csv"))
            with (run_dir / "extraction_report.csv").open(
                "w", newline="", encoding="utf-8"
            ) as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=["source_file", "status", "rows_before", "columns_before", "output_file", "details"],
                )
                writer.writeheader()
                for filename in output_files:
                    writer.writerow({
                        "source_file": filename.removeprefix("cleaned_"),
                        "status": "success",
                        "rows_before": 1,
                        "columns_before": 1,
                        "output_file": filename,
                        "details": "",
                    })

            database = root / "travelintel_warehouse.db"
            result = build_warehouse(
                run_dir,
                database,
                report_dir,
                chunk_size=1,
            )
            self.assertTrue(database.is_file())
            self.assertEqual(result["source_datasets"], len(output_files))

            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                for table in (
                    "fact_hotel_booking",
                    "fact_airbnb_calendar_boston",
                    "fact_airbnb_calendar_seattle",
                    "fact_airbnb_review_boston",
                    "fact_airbnb_review_seattle",
                    "fact_tourism_observation",
                ):
                    self.assertEqual(
                        connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                        1,
                    )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM dim_airbnb_listing").fetchone()[0],
                    2,
                )
            finally:
                connection.close()

            dimensional = build_dimensional_schemas(database, report_dir)
            self.assertEqual(dimensional["star_tables"], 10)
            self.assertEqual(dimensional["snowflake_tables"], 15)
            self.assertEqual(dimensional["star_relationships"], 19)
            self.assertEqual(dimensional["snowflake_relationships"], 25)
            self.assertEqual(dimensional["star_fact_rows"], dimensional["snowflake_fact_rows"])
            self.assertEqual(dimensional["foreign_key_violations"], 0)
            self.assertEqual(dimensional["integrity"], "ok")
            self.assertEqual(len(dimensional["sample_joins"]), 6)
            self.assertTrue(dimensional["reports"]["star_inventory"].is_file())
            self.assertTrue(dimensional["reports"]["snowflake_relationships"].is_file())
            with self.assertRaises(FileExistsError):
                build_dimensional_schemas(database, report_dir)

            with self.assertRaises(FileExistsError):
                build_warehouse(run_dir, database, report_dir)

    def test_wide_source_records_keep_row_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "etl_run_test"
            run_dir.mkdir()
            wide = pd.DataFrame({
                f"field_{index}": ["value" if index == 0 else None]
                for index in range(1_805)
            })
            wide["etl_source_file"] = "references.jsonl"
            write_source(run_dir, "cleaned_wide_reference.csv", wide)
            with (run_dir / "extraction_report.csv").open(
                "w", newline="", encoding="utf-8"
            ) as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=["source_file", "status", "rows_before", "columns_before", "output_file", "details"],
                )
                writer.writeheader()
                writer.writerow({
                    "source_file": "references.jsonl",
                    "status": "success",
                    "rows_before": 1,
                    "columns_before": 1_806,
                    "output_file": "cleaned_wide_reference.csv",
                    "details": "",
                })

            database = root / "wide.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "CREATE TABLE warehouse_manifest ("
                    "source_file TEXT PRIMARY KEY, output_file TEXT NOT NULL, "
                    "table_name TEXT NOT NULL, attribute_table_name TEXT, rows_loaded INTEGER, "
                    "attribute_values_loaded INTEGER, storage_mode TEXT)"
                )
                output_map, summaries = _stage_sources(connection, run_dir, chunk_size=1)
                connection.commit()
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM stg_wide_reference_records"
                    ).fetchone()[0],
                    1,
                )
                value = connection.execute(
                    "SELECT value FROM stg_wide_reference_attributes "
                    "WHERE attribute = 'field_0'"
                ).fetchone()[0]
                self.assertEqual(value, "value")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                connection.close()
            self.assertEqual(output_map["cleaned_wide_reference.csv"], "stg_wide_reference_records")
            self.assertEqual(summaries[0]["rows_loaded"], 1)


if __name__ == "__main__":
    unittest.main()
