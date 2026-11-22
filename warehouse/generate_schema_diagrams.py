"""Render database-verified Star and Snowflake schema diagrams as PNGs."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path
from textwrap import wrap
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

from config import PROJECT_ROOT


STAR_TABLES = (
    "star_dim_date",
    "star_dim_hotel_type",
    "star_dim_airbnb_listing",
    "star_dim_tourism_location",
    "star_fact_hotel_booking",
    "star_fact_airbnb_calendar_boston",
    "star_fact_airbnb_calendar_seattle",
    "star_fact_airbnb_review_boston",
    "star_fact_airbnb_review_seattle",
    "star_fact_tourism_observation",
)

SNOWFLAKE_TABLES = (
    "snowflake_dim_calendar_month",
    "snowflake_dim_date",
    "snowflake_dim_hotel_type",
    "snowflake_dim_airbnb_city",
    "snowflake_dim_airbnb_neighbourhood",
    "snowflake_dim_airbnb_property_type",
    "snowflake_dim_airbnb_room_type",
    "snowflake_dim_airbnb_listing",
    "snowflake_dim_tourism_location",
    "snowflake_fact_hotel_booking",
    "snowflake_fact_airbnb_calendar_boston",
    "snowflake_fact_airbnb_calendar_seattle",
    "snowflake_fact_airbnb_review_boston",
    "snowflake_fact_airbnb_review_seattle",
    "snowflake_fact_tourism_observation",
)

ATTRIBUTE_PRIORITIES = {
    "star_dim_date": ("date_value", "year", "quarter", "month", "day", "weekday_name"),
    "star_dim_hotel_type": ("hotel_type",),
    "star_dim_airbnb_listing": (
        "source_city", "listing_id", "name", "neighbourhood_cleansed",
        "property_type", "room_type", "accommodates", "price",
    ),
    "star_dim_tourism_location": ("location_name",),
    "star_fact_hotel_booking": (
        "is_canceled", "lead_time", "stays_in_week_nights", "adr", "reservation_status",
    ),
    "star_fact_airbnb_calendar_boston": ("available", "price"),
    "star_fact_airbnb_calendar_seattle": ("available", "price"),
    "star_fact_airbnb_review_boston": ("source_review_id", "reviewer_id", "comments"),
    "star_fact_airbnb_review_seattle": ("source_review_id", "reviewer_id", "comments"),
    "star_fact_tourism_observation": (
        "image_id", "avg_rating", "visitor_count", "avg_cost",
        "popularity_index", "attractiveness_label",
    ),
    "snowflake_dim_calendar_month": ("year", "quarter", "month"),
    "snowflake_dim_date": ("date_value", "day", "weekday_name"),
    "snowflake_dim_hotel_type": ("hotel_type",),
    "snowflake_dim_airbnb_city": ("city_name",),
    "snowflake_dim_airbnb_neighbourhood": ("neighbourhood_name",),
    "snowflake_dim_airbnb_property_type": ("property_type",),
    "snowflake_dim_airbnb_room_type": ("room_type",),
    "snowflake_dim_airbnb_listing": (
        "listing_id", "name", "accommodates", "bedrooms", "price",
        "review_scores_rating",
    ),
    "snowflake_dim_tourism_location": ("location_name",),
    "snowflake_fact_hotel_booking": (
        "is_canceled", "lead_time", "stays_in_week_nights", "adr", "reservation_status",
    ),
    "snowflake_fact_airbnb_calendar_boston": ("available", "price"),
    "snowflake_fact_airbnb_calendar_seattle": ("available", "price"),
    "snowflake_fact_airbnb_review_boston": ("source_review_id", "reviewer_id", "comments"),
    "snowflake_fact_airbnb_review_seattle": ("source_review_id", "reviewer_id", "comments"),
    "snowflake_fact_tourism_observation": (
        "image_id", "avg_rating", "visitor_count", "avg_cost",
        "popularity_index", "attractiveness_label",
    ),
}

COLORS = {
    "fact": "#F4A261",
    "dimension": "#2A9D8F",
    "panel": "#F4F7FB",
    "ink": "#18324B",
    "edge": "#526779",
    "muted": "#627789",
    "white": "#FFFFFF",
}


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def load_schema_metadata(
    connection: sqlite3.Connection,
    table_names: tuple[str, ...],
    relationship_report: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    existing_tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = sorted(set(table_names) - existing_tables)
    if missing:
        raise ValueError(f"Schema tables missing from database: {', '.join(missing)}")

    tables: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for table in table_names:
        columns = list(connection.execute(
            f"PRAGMA table_info({quote_identifier(table)})"
        ))
        column_names = {row[1] for row in columns}
        primary_keys = [
            row[1] for row in sorted(columns, key=lambda value: value[5]) if row[5]
        ]
        if not primary_keys:
            raise ValueError(f"Displayed table has no primary key: {table}")

        grouped: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in connection.execute(
            f"PRAGMA foreign_key_list({quote_identifier(table)})"
        ):
            grouped[row[0]].append(row)

        foreign_keys: list[dict[str, Any]] = []
        for rows in grouped.values():
            rows.sort(key=lambda value: value[1])
            parent_table = rows[0][2]
            parent_columns = [row[4] for row in rows]
            edge = {
                "child_table": table,
                "child_columns": [row[3] for row in rows],
                "parent_table": parent_table,
                "parent_columns": parent_columns,
            }
            if not set(edge["child_columns"]).issubset(column_names):
                raise ValueError(f"Foreign key columns missing from {table}: {edge}")
            foreign_keys.append(edge)
            if parent_table in table_names:
                parent_info = list(connection.execute(
                    f"PRAGMA table_info({quote_identifier(parent_table)})"
                ))
                parent_column_names = {row[1] for row in parent_info}
                if not set(parent_columns).issubset(parent_column_names):
                    raise ValueError(f"Foreign key parent columns missing: {edge}")
                edges.append(edge)

        tables[table] = {
            "columns": [row[1] for row in columns],
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys,
        }

    if not relationship_report.is_file():
        raise FileNotFoundError(f"Validated relationship report not found: {relationship_report}")
    with relationship_report.open(encoding="utf-8-sig", newline="") as source:
        report_rows = list(csv.DictReader(source))
    if any(row.get("validation_status") != "PASS" for row in report_rows):
        raise sqlite3.IntegrityError(
            f"Relationship report contains a failed relationship: {relationship_report}"
        )
    validated = {
        (
            row.get("child_table", ""),
            _normalize_column_list(row.get("child_column", "")),
            row.get("parent_table", ""),
            _normalize_column_list(row.get("parent_column", "")),
        )
        for row in report_rows
    }
    for edge in edges:
        key = (
            edge["child_table"],
            _normalize_column_list(", ".join(edge["child_columns"])),
            edge["parent_table"],
            _normalize_column_list(", ".join(edge["parent_columns"])),
        )
        if key not in validated:
            raise sqlite3.IntegrityError(
                f"Foreign key is declared but has no passing validation report: {edge}"
            )
    return tables, edges


def _normalize_column_list(value: str) -> str:
    return ",".join(part.strip() for part in value.split(","))


def _attributes(table: str, metadata: dict[str, Any], limit: int = 4) -> list[str]:
    key_columns = set(metadata["primary_keys"])
    for foreign_key in metadata["foreign_keys"]:
        key_columns.update(foreign_key["child_columns"])
    actual = metadata["columns"]
    priorities = ATTRIBUTE_PRIORITIES.get(table, ())
    chosen = [column for column in priorities if column in actual and column not in key_columns]
    chosen = list(dict.fromkeys(chosen))[:limit]
    remaining = [
        column for column in actual
        if column not in key_columns and column not in chosen
    ]
    chosen.extend(remaining[:max(0, limit - len(chosen))])
    return chosen


def _text_for_box(
    table: str,
    metadata: dict[str, Any],
    in_schema_tables: set[str],
) -> list[tuple[str, str]]:
    lines = [
        ("PK", ", ".join(metadata["primary_keys"])),
    ]
    internal_columns: list[str] = []
    lineage_columns: list[str] = []
    for foreign_key in metadata["foreign_keys"]:
        if foreign_key["parent_table"] in in_schema_tables:
            internal_columns.extend(foreign_key["child_columns"])
        else:
            lineage_columns.extend(foreign_key["child_columns"])
    if internal_columns:
        lines.append(("FK", ", ".join(dict.fromkeys(internal_columns))))
    if lineage_columns:
        lines.append(("FK · ETL lineage", ", ".join(dict.fromkeys(lineage_columns))))
    attributes = _attributes(
        table,
        metadata,
        limit=3 if "_fact_" in table else 4,
    )
    if attributes:
        lines.append(("ATTR", ", ".join(attributes)))
    hidden = len(metadata["columns"]) - len(
        metadata["primary_keys"]
        + [
            column
            for foreign_key in metadata["foreign_keys"]
            for column in foreign_key["child_columns"]
        ]
        + attributes
    )
    if hidden > 0:
        lines.append(("MORE", f"{hidden} additional source columns"))
    return lines


def draw_diagram(
    schema_name: str,
    tables: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    positions: dict[str, tuple[float, float, float, float]],
    output_path: Path,
    subtitle: str,
    canvas_size: tuple[float, float] = (24, 16),
) -> None:
    figure, axis = plt.subplots(figsize=canvas_size)
    figure.patch.set_facecolor("#FFFFFF")
    axis.set_facecolor("#FFFFFF")
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")

    axis.text(
        0.035, 0.965, schema_name, transform=axis.transAxes,
        fontsize=25, fontweight="bold", color=COLORS["ink"], va="top",
    )
    axis.text(
        0.037, 0.923, subtitle, transform=axis.transAxes,
        fontsize=11, color=COLORS["muted"], va="top",
    )

    panels = [
        (0.025, 0.545, 0.455, 0.34, "HOTEL BOOKINGS"),
        (0.505, 0.545, 0.47, 0.34, "TOURISM OBSERVATIONS"),
        (0.025, 0.035, 0.95, 0.47, "AIRBNB LISTINGS · CALENDAR · REVIEWS"),
    ]
    for x, y, width, height, title in panels:
        panel = FancyBboxPatch(
            (x, y), width, height,
            boxstyle="round,pad=0.008,rounding_size=0.015",
            transform=axis.transAxes,
            facecolor=COLORS["panel"],
            edgecolor="#D5DFE8",
            linewidth=1.1,
            zorder=0,
        )
        axis.add_patch(panel)
        axis.text(
            x + 0.014, y + height - 0.025, title,
            transform=axis.transAxes,
            fontsize=10, fontweight="bold", color=COLORS["muted"], va="top",
        )

    table_set = set(tables)
    for edge in edges:
        child = edge["child_table"]
        parent = edge["parent_table"]
        if child not in positions or parent not in positions:
            continue
        sx, sy, sw, sh = positions[child]
        tx, ty, tw, th = positions[parent]
        source = (sx + sw / 2, sy + sh / 2)
        target = (tx + tw / 2, ty + th / 2)
        dx, dy = target[0] - source[0], target[1] - source[1]
        if dx == 0 and dy == 0:
            continue
        source_scale = min(
            (sw / 2) / abs(dx) if dx else float("inf"),
            (sh / 2) / abs(dy) if dy else float("inf"),
        )
        target_scale = min(
            (tw / 2) / abs(dx) if dx else float("inf"),
            (th / 2) / abs(dy) if dy else float("inf"),
        )
        start = (source[0] + dx * source_scale, source[1] + dy * source_scale)
        end = (target[0] - dx * target_scale, target[1] - dy * target_scale)
        axis.add_patch(FancyArrowPatch(
            start,
            end,
            transform=axis.transAxes,
            arrowstyle="-|>",
            mutation_scale=11,
            linewidth=1.25,
            color=COLORS["edge"],
            connectionstyle="arc3,rad=0.035",
            zorder=1,
        ))

    for table, (x, y, width, height) in positions.items():
        if table not in table_set:
            raise ValueError(f"Layout references an unverified table: {table}")
        is_fact = "_fact_" in table
        color = COLORS["fact"] if is_fact else COLORS["dimension"]
        box = FancyBboxPatch(
            (x, y), width, height,
            boxstyle="round,pad=0.005,rounding_size=0.008",
            transform=axis.transAxes,
            facecolor=COLORS["white"],
            edgecolor=color,
            linewidth=1.5,
            zorder=2,
        )
        axis.add_patch(box)
        header_height = min(0.037, height * 0.28)
        header = Rectangle(
            (x, y + height - header_height), width, header_height,
            transform=axis.transAxes,
            facecolor=color,
            edgecolor=color,
            zorder=3,
        )
        axis.add_patch(header)
        axis.text(
            x + 0.009, y + height - header_height / 2,
            table, transform=axis.transAxes,
            fontsize=7.6 if width < 0.23 else 8.5,
            fontweight="bold", color=COLORS["white"], va="center",
            zorder=4,
        )

        lines = _text_for_box(table, tables[table], table_set)
        content_top = y + height - header_height - 0.012
        available_height = max(0.04, height - header_height - 0.025)
        wrapped_lines: list[tuple[str, str]] = []
        wrap_width = max(30, int(width * 190))
        for tag, text in lines:
            prefix = "" if tag == "MORE" else f"{tag}: "
            chunks = wrap(
                prefix + text,
                width=wrap_width,
                subsequent_indent="   " if prefix else "",
                break_long_words=False,
                break_on_hyphens=False,
            ) or [prefix + text]
            wrapped_lines.extend((tag, chunk) for chunk in chunks)
        line_height = min(0.032, available_height / max(1, len(wrapped_lines)))
        font_size = 7.1 if width < 0.23 else 7.7
        for index, (tag, display) in enumerate(wrapped_lines):
            line_y = content_top - index * line_height
            if tag in {"PK", "FK", "FK · ETL lineage"}:
                label_color = "#8B4F00" if tag == "PK" else "#155E75"
                weight = "bold"
            elif tag == "MORE":
                label_color = COLORS["muted"]
                weight = "normal"
            else:
                label_color = COLORS["ink"]
                weight = "normal"
            axis.text(
                x + 0.009, line_y, display,
                transform=axis.transAxes,
                fontsize=font_size, color=label_color, fontweight=weight,
                va="top", clip_on=True, zorder=4,
            )

    legend_y = 0.012
    for index, (label, color) in enumerate(
        (("Fact table", COLORS["fact"]), ("Dimension table", COLORS["dimension"]))
    ):
        x = 0.04 + index * 0.17
        axis.add_patch(FancyBboxPatch(
            (x, legend_y), 0.018, 0.018,
            boxstyle="round,pad=0.002,rounding_size=0.004",
            transform=axis.transAxes, facecolor=color, edgecolor=color,
        ))
        axis.text(
            x + 0.024, legend_y + 0.009, label,
            transform=axis.transAxes, fontsize=8.5, color=COLORS["ink"], va="center",
        )
    axis.text(
        0.48, legend_y + 0.009,
        "Arrows show verified in-schema foreign keys; ETL lineage FKs are listed in boxes.",
        transform=axis.transAxes, fontsize=8, color=COLORS["muted"], va="center",
    )

    figure.savefig(
        output_path,
        dpi=240,
        bbox_inches="tight",
        facecolor=figure.get_facecolor(),
        metadata={"Title": schema_name, "Description": subtitle},
    )
    plt.close(figure)


def star_positions() -> dict[str, tuple[float, float, float, float]]:
    return {
        "star_dim_hotel_type": (0.285, 0.705, 0.17, 0.13),
        "star_fact_hotel_booking": (0.13, 0.565, 0.25, 0.12),
        "star_dim_tourism_location": (0.655, 0.705, 0.20, 0.13),
        "star_fact_tourism_observation": (0.60, 0.565, 0.31, 0.12),
        "star_dim_date": (0.40, 0.515, 0.18, 0.105),
        "star_dim_airbnb_listing": (0.37, 0.315, 0.24, 0.14),
        "star_fact_airbnb_calendar_boston": (0.05, 0.09, 0.205, 0.17),
        "star_fact_airbnb_calendar_seattle": (0.285, 0.09, 0.205, 0.17),
        "star_fact_airbnb_review_boston": (0.52, 0.09, 0.205, 0.17),
        "star_fact_airbnb_review_seattle": (0.755, 0.09, 0.205, 0.17),
    }


def snowflake_positions() -> dict[str, tuple[float, float, float, float]]:
    return {
        "snowflake_dim_hotel_type": (0.055, 0.705, 0.17, 0.13),
        "snowflake_fact_hotel_booking": (0.13, 0.565, 0.25, 0.12),
        "snowflake_dim_tourism_location": (0.655, 0.705, 0.20, 0.13),
        "snowflake_fact_tourism_observation": (0.60, 0.565, 0.31, 0.12),
        "snowflake_dim_calendar_month": (0.055, 0.345, 0.16, 0.12),
        "snowflake_dim_date": (0.255, 0.345, 0.17, 0.12),
        "snowflake_dim_airbnb_listing": (0.48, 0.33, 0.20, 0.15),
        "snowflake_dim_airbnb_city": (0.77, 0.36, 0.16, 0.11),
        "snowflake_dim_airbnb_neighbourhood": (0.77, 0.20, 0.18, 0.12),
        "snowflake_dim_airbnb_property_type": (0.51, 0.17, 0.17, 0.11),
        "snowflake_dim_airbnb_room_type": (0.30, 0.17, 0.17, 0.11),
        "snowflake_fact_airbnb_calendar_boston": (0.035, 0.045, 0.205, 0.11),
        "snowflake_fact_airbnb_calendar_seattle": (0.275, 0.045, 0.205, 0.11),
        "snowflake_fact_airbnb_review_boston": (0.515, 0.045, 0.205, 0.11),
        "snowflake_fact_airbnb_review_seattle": (0.755, 0.045, 0.205, 0.11),
    }


def _unique_paths(output_dir: Path, overwrite: bool = False) -> tuple[Path, Path]:
    star = output_dir / "star_schema_diagram.png"
    snowflake = output_dir / "snowflake_schema_diagram.png"
    existing = [path for path in (star, snowflake) if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "Refusing to overwrite existing diagram(s): "
            + ", ".join(str(path) for path in existing)
        )
    return star, snowflake


def generate_diagrams(
    database_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"SQLite warehouse does not exist: {database_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    star_path, snowflake_path = _unique_paths(output_dir, overwrite)

    report_root = output_dir.parent
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        star_tables, star_edges = load_schema_metadata(
            connection,
            STAR_TABLES,
            _latest_report(report_root, "star_schema_relationships"),
        )
        snowflake_tables, snowflake_edges = load_schema_metadata(
            connection,
            SNOWFLAKE_TABLES,
            _latest_report(report_root, "snowflake_schema_relationships"),
        )
    finally:
        connection.close()

    draw_diagram(
        "TRAVELINTEL · STAR SCHEMA",
        star_tables,
        star_edges,
        star_positions(),
        star_path,
        "Verified warehouse facts and denormalized dimensions · actual database PKs and FKs",
    )
    draw_diagram(
        "TRAVELINTEL · SNOWFLAKE SCHEMA",
        snowflake_tables,
        snowflake_edges,
        snowflake_positions(),
        snowflake_path,
        "Verified warehouse facts and normalized date / Airbnb dimensions · actual database PKs and FKs",
    )
    return star_path, snowflake_path


def _latest_report(report_root: Path, stem: str) -> Path:
    matches = sorted(report_root.glob(f"{stem}*.csv"))
    if not matches:
        raise FileNotFoundError(f"No schema relationship reports found for {stem} in {report_root}")
    return matches[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "travelintel_warehouse.db",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "reports" / "diagrams",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the two required diagram PNGs if they already exist.",
    )
    args = parser.parse_args()
    star_path, snowflake_path = generate_diagrams(
        args.database, args.output_dir, overwrite=args.overwrite
    )
    for path in (star_path, snowflake_path):
        with path.open("rb") as image:
            if image.read(8) != b"\x89PNG\r\n\x1a\n":
                raise OSError(f"Generated file is not a valid PNG: {path}")
        print(f"{path} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
