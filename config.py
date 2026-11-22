"""TravelIntel project paths and ETL defaults."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT
PROCESSED_ROOT = PROJECT_ROOT / "Processed Data - 8"
REPORTS_ROOT = PROJECT_ROOT / "reports"
ETL_CHUNK_SIZE = 50_000

EXCLUDED_ROOT_DIRECTORIES = {
    "etl",
    "warehouse",
    "olap",
    "analysis",
    "reports",
    "08_processed_data",
    "09_olap_outputs",
    "processed data - 8",
    "olap outputs - 9",
    "travelintel_project",
}

SUPPORTED_SOURCE_EXTENSIONS = {
    ".csv",
    ".xlsx",
    ".xls",
    ".json",
    ".jsonl",
    ".parquet",
    ".txt",
    ".ipynb",
}
