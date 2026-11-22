"""Focused tests for ETL behavior and safety guarantees."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from etl.extract import discover_sources, iter_source_frames
from etl.load import load_cleaned_csvs
from etl.pipeline import _deduplicate_chunk, run_pipeline
from etl.transform import clean_chunk


class ExtractionTests(unittest.TestCase):
    def test_discovers_sources_but_excludes_processed_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Tourism").mkdir()
            (root / "Processed Data - 8").mkdir()
            (root / "Tourism" / "places.csv").write_text("Name\nA\n", encoding="utf-8")
            (root / "Processed Data - 8" / "cleaned.csv").write_text("Name\nA\n", encoding="utf-8")

            self.assertEqual([path.name for path in discover_sources(root)], ["places.csv"])

    def test_jsonl_extracts_records_without_losing_sparse_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "records.jsonl"
            path.write_text('{"place":"A","score":1}\n{"place":"B","other":"x"}\n', encoding="utf-8")

            frames = list(iter_source_frames(path, chunk_size=1))
            combined = pd.concat(frames, ignore_index=True)

            self.assertEqual(list(combined.columns), ["other", "place", "score"])
            self.assertEqual(len(combined), 2)


class TransformationTests(unittest.TestCase):
    def test_standardizes_values_and_keeps_missing_rows(self) -> None:
        source = pd.DataFrame({
            "City Name": ["  Jaipur  ", "Pune"],
            "Avg Rating": ["5", "6"],
            "Reservation Date": ["2024-01-02", "2024-01-03"],
            "Optional": ["", None],
        })

        cleaned, metrics = clean_chunk(source, "reviews.csv")

        self.assertEqual(cleaned.loc[0, "city_name"], "Jaipur")
        self.assertEqual(cleaned.loc[0, "reservation_date"], "2024-01-02")
        self.assertTrue(pd.isna(cleaned.loc[0, "optional"]))
        self.assertEqual(metrics["invalid_values"]["avg_rating"], 1)
        self.assertEqual(len(cleaned), len(source))
        self.assertTrue((cleaned["etl_source_file"] == "reviews.csv").all())


class DuplicateSafetyTests(unittest.TestCase):
    def test_removes_duplicates_across_chunks(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE seen_hashes (source_id TEXT NOT NULL, row_hash TEXT NOT NULL, "
            "PRIMARY KEY (source_id, row_hash))"
        )
        connection.execute(
            "CREATE TEMP TABLE incoming_hashes (row_number INTEGER PRIMARY KEY, row_hash TEXT UNIQUE)"
        )
        first, first_removed = _deduplicate_chunk(
            pd.DataFrame({"place": ["A", "B"]}), connection, "source"
        )
        second, second_removed = _deduplicate_chunk(
            pd.DataFrame({"place": ["B", "C"]}), connection, "source"
        )
        connection.close()

        self.assertEqual(first["place"].tolist(), ["A", "B"])
        self.assertEqual(first_removed, 0)
        self.assertEqual(second["place"].tolist(), ["C"])
        self.assertEqual(second_removed, 1)


class SQLiteLoadingTests(unittest.TestCase):
    def test_sparse_storage_handles_wide_reference_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            run_dir.mkdir()
            values = {
                f"field_{index}": [f"value_{index}", None]
                for index in range(1_805)
            }
            values["etl_source_file"] = ["references.jsonl", "references.jsonl"]
            pd.DataFrame(values).to_csv(run_dir / "cleaned_wide.csv", index=False)
            database = run_dir / "travelintel_warehouse.db"

            tables = load_cleaned_csvs(
                run_dir,
                database,
                [{"source_file": "references.jsonl", "output_file": "cleaned_wide.csv"}],
                [run_dir / "cleaned_wide.csv"],
            )
            connection = sqlite3.connect(database)
            try:
                row_count = connection.execute(
                    "SELECT COUNT(*) FROM wide"
                ).fetchone()[0]
                row = connection.execute(
                    "SELECT attribute, value FROM wide WHERE source_record_id = 0 "
                    "AND attribute = 'field_1'"
                ).fetchone()
                storage_mode = connection.execute(
                    "SELECT storage_mode FROM etl_manifest WHERE table_name = 'wide'"
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(tables, 1)
            self.assertEqual(row_count, 1_805)
            self.assertEqual(row, ("field_1", "value_1"))
            self.assertEqual(storage_mode, "sparse_attribute_value")


class PipelineTests(unittest.TestCase):
    def test_runs_extract_transform_integration_and_sqlite_load(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "Tourism"
            source_dir.mkdir()
            source_file = source_dir / "tourism_dataset.csv"
            source_file.write_text(
                "Location Name,Avg Rating,Visitor Count\n"
                "  Jaipur ,4.5,10\n"
                "Jaipur,4.5,10\n"
                "Pune,5.0,20\n",
                encoding="utf-8",
            )
            processed = root / "Processed Data - 8"
            reports = root / "reports"

            with patch("etl.pipeline.PROCESSED_ROOT", processed), patch(
                "etl.pipeline.REPORTS_ROOT", reports
            ):
                exit_code = run_pipeline(root)

            self.assertEqual(exit_code, 0)
            run_dir = next(processed.iterdir())
            cleaned = pd.read_csv(run_dir / "cleaned_tourism.csv")
            self.assertEqual(cleaned["location_name"].tolist(), ["Jaipur", "Pune"])
            self.assertEqual(len(cleaned), 2)
            connection = sqlite3.connect(run_dir / "travelintel_warehouse.db")
            try:
                count = connection.execute("SELECT COUNT(*) FROM tourism").fetchone()[0]
                manifest_count = connection.execute("SELECT COUNT(*) FROM etl_manifest").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 2)
            self.assertEqual(manifest_count, 1)
            self.assertTrue((run_dir / "integration_report.csv").is_file())
            self.assertTrue((reports / "data_quality_report.csv").is_file())
            self.assertTrue((reports / "etl_summary.txt").is_file())


if __name__ == "__main__":
    unittest.main()
