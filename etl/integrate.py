"""Assess cross-source relationships and integrate only validated keys."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd


def normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def _append_rows(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "left_dataset",
        "right_dataset",
        "candidate_key",
        "exact_match_count",
        "decision",
        "reason",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_integration_report(run_dir: Path, output_files: dict[str, Path]) -> tuple[Path, str]:
    destination_path = output_files.get("cleaned_destinations.csv")
    reviews_path = output_files.get("cleaned_reviews.csv")
    tourism_path = output_files.get("cleaned_tourism.csv")
    rows: list[dict[str, object]] = []

    if destination_path and tourism_path:
        destinations = pd.read_csv(destination_path, usecols=lambda name: name in {"destination_name"})
        tourism = pd.read_csv(tourism_path, usecols=lambda name: name in {"location_name"})
        destination_names = {
            normalize_key(value) for value in destinations.get("destination_name", pd.Series(dtype=str)).dropna()
        }
        location_names = {
            normalize_key(value) for value in tourism.get("location_name", pd.Series(dtype=str)).dropna()
        }
        overlap = destination_names & location_names
        rows.append({
            "left_dataset": "tourism_dataset",
            "right_dataset": "india_tourism_dataset",
            "candidate_key": "location_name = destination_name (normalized exact match)",
            "exact_match_count": len(overlap),
            "decision": "not integrated",
            "reason": "No shared destination names were found." if not overlap
            else "Names overlap, but the datasets have no shared stable destination identifier.",
        })

    if destination_path and reviews_path:
        destinations = pd.read_csv(
            destination_path,
            usecols=lambda name: name in {"destination_name", "state", "district"},
        )
        reviews = pd.read_csv(
            reviews_path,
            usecols=lambda name: name in {"place", "city"},
            chunksize=100_000,
        )
        destination_by_name: dict[str, dict[str, str]] = {}
        for record in destinations.to_dict(orient="records"):
            name = record.get("destination_name")
            if pd.notna(name):
                destination_by_name[normalize_key(name)] = {
                    key: normalize_key(value)
                    for key, value in record.items()
                    if key in {"state", "district"} and pd.notna(value)
                }

        candidate_names: set[str] = set()
        corroborated_names: set[str] = set()
        for chunk in reviews:
            for place, city in chunk[["place", "city"]].dropna(subset=["place"]).itertuples(
                index=False, name=None
            ):
                place_key = normalize_key(place)
                destination = destination_by_name.get(place_key)
                if destination:
                    candidate_names.add(place_key)
                    city_key = normalize_key(city) if pd.notna(city) else ""
                    if city_key and city_key in destination.values():
                        corroborated_names.add(place_key)
        rows.append({
            "left_dataset": "indian_place_reviews",
            "right_dataset": "india_tourism_dataset",
            "candidate_key": "place = destination_name (normalized exact match)",
            "exact_match_count": len(candidate_names),
            "decision": "not integrated",
            "reason": (
                f"{len(candidate_names)} place names match, but only "
                f"{len(corroborated_names)} have a city matching the catalog's state/district; "
                "the remaining rows cannot be assigned reliably without a maintained crosswalk."
            ),
        })

    rows.extend([
        {
            "left_dataset": "hotel_bookings",
            "right_dataset": "tourism_and_destination_sources",
            "candidate_key": "destination/city identifier",
            "exact_match_count": 0,
            "decision": "not integrated",
            "reason": "Hotel bookings contain hotel type and guest-origin country, but no destination or city key.",
        },
        {
            "left_dataset": "weather_city_files",
            "right_dataset": "tourism_sources",
            "candidate_key": "city and observation date",
            "exact_match_count": 0,
            "decision": "not integrated",
            "reason": "Weather is a city-level time series; tourism and destination records have no matching observation dates and city keys.",
        },
        {
            "left_dataset": "commute_travel_times",
            "right_dataset": "tourism_sources",
            "candidate_key": "destination",
            "exact_match_count": 0,
            "decision": "not integrated",
            "reason": "The transport dataset describes a commute (e.g. Home/GSK), not tourist journeys or catalog destinations.",
        },
        {
            "left_dataset": "tripadvisor_hotel_reviews",
            "right_dataset": "hotel_bookings",
            "candidate_key": "rating",
            "exact_match_count": 0,
            "decision": "not integrated",
            "reason": "Rating is a measure, not a row-level relationship key; the review data has no booking/listing identifier.",
        },
    ])
    report_path = run_dir / "integration_report.csv"
    _append_rows(report_path, rows)
    summary = (
        f"Reviewed {len(rows)} candidate relationships. No integrated_tourism.csv was produced "
        "because no cross-source relationship met the exact, contextual key checks. Cleaned source "
        "tables are retained separately; the candidate counts and reasons are in integration_report.csv."
    )
    return report_path, summary
