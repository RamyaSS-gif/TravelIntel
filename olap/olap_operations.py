"""Parameterized OLAP operations over the verified TravelIntel schemas."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from config import PROJECT_ROOT


FACTS = {
    "hotel_booking": {
        "table": "fact_hotel_booking",
        "family": "hotel",
        "default_groups": ("year", "month", "hotel_type"),
        "default_measures": ("fact_rows", "canceled_bookings", "average_adr"),
    },
    "airbnb_calendar_boston": {
        "table": "fact_airbnb_calendar_boston",
        "family": "calendar",
        "default_groups": ("year", "month", "city"),
        "default_measures": ("fact_rows", "available_rows"),
    },
    "airbnb_calendar_seattle": {
        "table": "fact_airbnb_calendar_seattle",
        "family": "calendar",
        "default_groups": ("year", "month", "city"),
        "default_measures": ("fact_rows", "available_rows"),
    },
    "airbnb_review_boston": {
        "table": "fact_airbnb_review_boston",
        "family": "review",
        "default_groups": ("year", "city"),
        "default_measures": ("fact_rows", "comments_present"),
    },
    "airbnb_review_seattle": {
        "table": "fact_airbnb_review_seattle",
        "family": "review",
        "default_groups": ("year", "city"),
        "default_measures": ("fact_rows", "comments_present"),
    },
    "tourism_observation": {
        "table": "fact_tourism_observation",
        "family": "tourism",
        "default_groups": ("location",),
        "default_measures": ("fact_rows", "average_rating", "recorded_visitors"),
    },
}

SCHEMAS = {"star": "star_", "snowflake": "snowflake_"}


class OLAPError(ValueError):
    """Raised when an OLAP request is not supported by the selected fact."""


class OLAPEngine:
    """Run OLAP queries against one existing SQLite database."""

    def __init__(self, database: Path | str | sqlite3.Connection):
        self._owns_connection = not isinstance(database, sqlite3.Connection)
        if self._owns_connection:
            path = Path(database).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Warehouse database not found: {path}")
            self.connection = sqlite3.connect(
                f"file:{path.as_posix()}?mode=ro", uri=True
            )
        else:
            self.connection = database

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def __enter__(self) -> "OLAPEngine":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _plan(self, fact: str, schema: str) -> dict[str, Any]:
        if schema not in SCHEMAS:
            raise OLAPError(f"Unsupported schema {schema!r}; use 'star' or 'snowflake'.")
        if fact not in FACTS:
            raise OLAPError(
                f"Unsupported fact {fact!r}; choose one of: {', '.join(FACTS)}."
            )

        prefix = SCHEMAS[schema]
        fact_table = prefix + FACTS[fact]["table"]
        if not self._table_exists(fact_table):
            raise OLAPError(f"Fact table {fact_table!r} is unavailable.")

        family = FACTS[fact]["family"]
        if family == "hotel":
            date_table = prefix + "dim_date"
            hotel_table = prefix + "dim_hotel_type"
            joins = (
                f' LEFT JOIN "{date_table}" AS d ON d.date_key = f.date_key'
                f' LEFT JOIN "{hotel_table}" AS h ON h.hotel_key = f.hotel_key'
            )
            if schema == "snowflake":
                month_table = prefix + "dim_calendar_month"
                joins += (
                    f' LEFT JOIN "{month_table}" AS m ON m.month_key = d.month_key'
                )
                year_expr, month_expr, quarter_expr = "m.year", "m.month", "m.quarter"
            else:
                year_expr, month_expr, quarter_expr = (
                    "d.year",
                    "d.month",
                    "d.quarter",
                )
            dimensions = {
                "year": year_expr,
                "quarter": quarter_expr,
                "month": month_expr,
                "hotel_type": "h.hotel_type",
                "market_segment": "f.market_segment",
                "customer_type": "f.customer_type",
                "reservation_status": "f.reservation_status",
            }
            measures = {
                "fact_rows": "COUNT(*)",
                "canceled_bookings": (
                    "SUM(CASE WHEN f.is_canceled = 1 THEN 1 ELSE 0 END)"
                ),
                "average_adr": "ROUND(AVG(f.adr), 2)",
                "average_lead_time": "ROUND(AVG(f.lead_time), 2)",
            }
        elif family in {"calendar", "review"}:
            date_table = prefix + "dim_date"
            listing_table = prefix + "dim_airbnb_listing"
            fact_date_column = "date_key"
            fact_listing_column = "listing_key"
            joins = (
                f' LEFT JOIN "{date_table}" AS d ON d.date_key = f.{fact_date_column}'
                f' LEFT JOIN "{listing_table}" AS l '
                f"ON l.listing_key = f.{fact_listing_column}"
            )
            if schema == "star":
                year_expr, month_expr = "d.year", "d.month"
                city_expr = "l.source_city"
                neighbourhood_expr = "l.neighbourhood_cleansed"
                property_expr, room_expr = "l.property_type", "l.room_type"
            else:
                month_table = prefix + "dim_calendar_month"
                city_table = prefix + "dim_airbnb_city"
                neighbourhood_table = prefix + "dim_airbnb_neighbourhood"
                property_table = prefix + "dim_airbnb_property_type"
                room_table = prefix + "dim_airbnb_room_type"
                joins += (
                    f' LEFT JOIN "{month_table}" AS m ON m.month_key = d.month_key'
                    f' LEFT JOIN "{city_table}" AS c ON c.city_key = l.city_key'
                    f' LEFT JOIN "{neighbourhood_table}" AS n '
                    "ON n.city_key = l.city_key "
                    "AND n.neighbourhood_key = l.neighbourhood_key"
                    f' LEFT JOIN "{property_table}" AS p '
                    "ON p.property_type_key = l.property_type_key"
                    f' LEFT JOIN "{room_table}" AS r ON r.room_type_key = l.room_type_key'
                )
                year_expr, month_expr = "m.year", "m.month"
                city_expr = "c.city_name"
                neighbourhood_expr = "n.neighbourhood_name"
                property_expr, room_expr = "p.property_type", "r.room_type"
            dimensions = {
                "year": year_expr,
                "month": month_expr,
                "city": city_expr,
                "neighbourhood": neighbourhood_expr,
                "property_type": property_expr,
                "room_type": room_expr,
            }
            if family == "calendar":
                dimensions["available"] = "f.available"
                measures = {
                    "fact_rows": "COUNT(*)",
                    "available_rows": (
                        "SUM(CASE WHEN lower(f.available) = 't' THEN 1 ELSE 0 END)"
                    ),
                    "unavailable_rows": (
                        "SUM(CASE WHEN lower(f.available) = 'f' THEN 1 ELSE 0 END)"
                    ),
                }
            else:
                measures = {
                    "fact_rows": "COUNT(*)",
                    "comments_present": (
                        "SUM(CASE WHEN f.comments IS NOT NULL "
                        "AND trim(f.comments) <> '' THEN 1 ELSE 0 END)"
                    ),
                }
        else:
            location_table = prefix + "dim_tourism_location"
            joins = (
                f' LEFT JOIN "{location_table}" AS l '
                "ON l.location_key = f.location_key"
            )
            dimensions = {
                "location": "l.location_name",
                "attractiveness_label": "f.attractiveness_label",
            }
            measures = {
                "fact_rows": "COUNT(*)",
                "average_rating": "ROUND(AVG(f.avg_rating), 3)",
                "recorded_visitors": "SUM(f.visitor_count)",
                "average_cost": "ROUND(AVG(f.avg_cost), 2)",
                "average_sentiment_score": "ROUND(AVG(f.sentiment_score), 3)",
            }

        return {
            "table": fact_table,
            "joins": joins,
            "dimensions": dimensions,
            "measures": measures,
            "default_groups": FACTS[fact]["default_groups"],
            "default_measures": FACTS[fact]["default_measures"],
        }

    def _table_exists(self, table: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    @staticmethod
    def _validate_fields(
        plan: dict[str, Any],
        group_by: Iterable[str],
        filters: dict[str, Any] | None,
        measures: Iterable[str],
    ) -> tuple[list[str], dict[str, Any], list[str]]:
        groups = list(group_by)
        filter_values = filters or {}
        measure_names = list(measures)
        if len(set(groups)) != len(groups):
            raise OLAPError("Group-by dimensions must not be repeated.")
        for field in groups + list(filter_values):
            if field not in plan["dimensions"]:
                raise OLAPError(
                    f"Dimension {field!r} is unavailable for this fact. "
                    f"Available dimensions: {', '.join(plan['dimensions'])}."
                )
        for measure in measure_names:
            if measure not in plan["measures"]:
                raise OLAPError(
                    f"Measure {measure!r} is unavailable for this fact. "
                    f"Available measures: {', '.join(plan['measures'])}."
                )
        if not measure_names:
            raise OLAPError("At least one valid measure is required.")
        return groups, filter_values, measure_names

    def _aggregate(
        self,
        fact: str,
        schema: str,
        group_by: Iterable[str],
        *,
        filters: dict[str, Any] | None = None,
        measures: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        plan = self._plan(fact, schema)
        measure_names = list(measures or plan["default_measures"])
        groups, filter_values, measure_names = self._validate_fields(
            plan, group_by, filters, measure_names
        )

        selected = [
            f'{plan["dimensions"][field]} AS "{field}"' for field in groups
        ] + [
            f'{plan["measures"][measure]} AS "{measure}"'
            for measure in measure_names
        ]
        sql = f'SELECT {", ".join(selected)} FROM "{plan["table"]}" AS f'
        sql += plan["joins"]
        parameters: list[Any] = []
        if filter_values:
            conditions = []
            for field, value in filter_values.items():
                expression = plan["dimensions"][field]
                if value is None:
                    conditions.append(f"{expression} IS NULL")
                else:
                    conditions.append(f"{expression} = ?")
                    parameters.append(value)
            sql += " WHERE " + " AND ".join(conditions)
        if groups:
            group_expressions = ", ".join(
                plan["dimensions"][field] for field in groups
            )
            sql += f" GROUP BY {group_expressions}"
            sql += " ORDER BY " + ", ".join(
                f"{plan['dimensions'][field]} IS NULL, {plan['dimensions'][field]}"
                for field in groups
            )
        cursor = self.connection.execute(sql, parameters)
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def roll_up(
        self,
        fact: str,
        schema: str = "star",
        group_by: Iterable[str] | None = None,
        *,
        filters: dict[str, Any] | None = None,
        measures: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate the selected fact at actual dimension levels."""
        plan = self._plan(fact, schema)
        return self._aggregate(
            fact,
            schema,
            group_by if group_by is not None else plan["default_groups"],
            filters=filters,
            measures=measures,
        )

    def drill_down(
        self,
        fact: str,
        from_group_by: Iterable[str],
        to_group_by: Iterable[str],
        schema: str = "star",
        *,
        filters: dict[str, Any] | None = None,
        measures: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Expand a valid summary to a finer grouping of available dimensions."""
        plan = self._plan(fact, schema)
        coarse, fine = list(from_group_by), list(to_group_by)
        if not coarse or len(fine) <= len(coarse) or not set(coarse).issubset(fine):
            raise OLAPError(
                "Drill-down requires a non-empty coarse grouping contained in "
                "a strictly more detailed grouping."
            )
        return self._aggregate(
            fact,
            schema,
            fine,
            filters=filters,
            measures=measures,
        )

    def slice(
        self,
        fact: str,
        dimension: str,
        value: Any,
        schema: str = "star",
        *,
        group_by: Iterable[str] | None = None,
        measures: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter by one dimension value, then aggregate."""
        plan = self._plan(fact, schema)
        groups = (
            list(group_by)
            if group_by is not None
            else [field for field in plan["default_groups"] if field != dimension]
        )
        return self._aggregate(
            fact,
            schema,
            groups,
            filters={dimension: value},
            measures=measures,
        )

    def dice(
        self,
        fact: str,
        filters: dict[str, Any],
        schema: str = "star",
        *,
        group_by: Iterable[str] | None = None,
        measures: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter by two or more dimension values, then aggregate."""
        if len(filters) < 2:
            raise OLAPError("Dice requires at least two dimension filters.")
        plan = self._plan(fact, schema)
        groups = (
            list(group_by)
            if group_by is not None
            else [field for field in plan["default_groups"] if field not in filters]
        )
        return self._aggregate(
            fact,
            schema,
            groups,
            filters=filters,
            measures=measures,
        )

    def pivot(
        self,
        fact: str,
        row_dimension: str,
        column_dimension: str,
        measure: str,
        schema: str = "star",
        *,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Pivot one actual measure into rows and observed dimension columns."""
        if row_dimension == column_dimension:
            raise OLAPError("Pivot row and column dimensions must be different.")
        aggregated = self._aggregate(
            fact,
            schema,
            (row_dimension, column_dimension),
            filters=filters,
            measures=(measure,),
        )
        column_values = list(
            dict.fromkeys(
                "(missing)" if row[column_dimension] is None
                else str(row[column_dimension])
                for row in aggregated
            )
        )
        pivoted: dict[Any, dict[str, Any]] = {}
        for row in aggregated:
            row_value = row[row_dimension]
            row_record = pivoted.setdefault(row_value, {row_dimension: row_value})
            column_value = (
                "(missing)"
                if row[column_dimension] is None
                else str(row[column_dimension])
            )
            row_record[column_value] = row[measure]
        return [
            {row_dimension: row_value, **{
                column: pivoted[row_value].get(column)
                for column in column_values
            }}
            for row_value in pivoted
        ]

    def example_dimension_values(
        self, fact: str, schema: str, fields: Iterable[str]
    ) -> dict[str, Any]:
        """Return values from the first source fact row for reproducible examples."""
        plan = self._plan(fact, schema)
        requested = list(fields)
        for field in requested:
            if field not in plan["dimensions"]:
                raise OLAPError(f"Dimension {field!r} is unavailable for {fact!r}.")
        expressions = [
            f'{plan["dimensions"][field]} AS "{field}"' for field in requested
        ]
        sql = f'SELECT {", ".join(expressions)} FROM "{plan["table"]}" AS f'
        sql += plan["joins"] + " LIMIT 1"
        row = self.connection.execute(sql).fetchone()
        if row is None:
            raise OLAPError(f"Fact table {plan['table']!r} contains no rows.")
        values = dict(zip(requested, row))
        missing = [key for key, value in values.items() if value is None]
        if missing:
            raise OLAPError(
                f"Cannot demonstrate filters with NULL values in {', '.join(missing)}."
            )
        return values


def _unique_output_path(directory: Path, stem: str, suffix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = directory / f"{stem}_{stamp}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{stamp}_{counter:03d}{suffix}"
        counter += 1
    return candidate


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    if not fields:
        fields = ["result"]
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _direct_filtered_count(
    engine: OLAPEngine, fact: str, schema: str, filters: dict[str, Any] | None
) -> int:
    plan = engine._plan(fact, schema)
    sql = f'SELECT COUNT(*) FROM "{plan["table"]}" AS f' + plan["joins"]
    parameters: list[Any] = []
    if filters:
        conditions = []
        for field, value in filters.items():
            expression = plan["dimensions"][field]
            if value is None:
                conditions.append(f"{expression} IS NULL")
            else:
                conditions.append(f"{expression} = ?")
                parameters.append(value)
        sql += " WHERE " + " AND ".join(conditions)
    return int(engine.connection.execute(sql, parameters).fetchone()[0])


def run_live_examples(
    database: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Execute five demonstrations and write result CSVs plus a validation report."""
    database_path = Path(database) if database else PROJECT_ROOT / "travelintel_warehouse.db"
    destination = Path(output_dir) if output_dir else PROJECT_ROOT / "OLAP Outputs - 9"
    destination.mkdir(parents=True, exist_ok=True)

    examples = (
        ("roll_up", "hotel_booking", "star"),
        ("drill_down", "hotel_booking", "snowflake"),
        ("slice", "airbnb_calendar_boston", "star"),
        ("dice", "airbnb_review_seattle", "snowflake"),
        ("pivot", "tourism_observation", "star"),
    )
    report_lines = [
        "TravelIntel OLAP execution and direct-count validation",
        f"Database: {database_path.resolve()}",
        f"Output folder: {destination.resolve()}",
        "All six fact families are supported independently in both schemas.",
        "",
    ]
    results: list[dict[str, Any]] = []
    with OLAPEngine(database_path) as engine:
        for operation, fact, schema in examples:
            plan = engine._plan(fact, schema)
            filters: dict[str, Any] = {}
            if operation == "roll_up":
                rows = engine.roll_up(fact, schema)
            elif operation == "drill_down":
                rows = engine.drill_down(
                    fact, ("year",), ("year", "month"), schema,
                    measures=("fact_rows", "average_adr"),
                )
            elif operation == "slice":
                values = engine.example_dimension_values(fact, schema, ("year",))
                filters = values
                rows = engine.slice(
                    fact, "year", values["year"], schema,
                    measures=("fact_rows", "available_rows"),
                )
            elif operation == "dice":
                values = engine.example_dimension_values(fact, schema, ("year", "city"))
                filters = values
                rows = engine.dice(
                    fact, filters, schema, measures=("fact_rows", "comments_present")
                )
            else:
                rows = engine.pivot(
                    fact,
                    "location",
                    "attractiveness_label",
                    "fact_rows",
                    schema,
                )

            for row in rows:
                for field, value in filters.items():
                    row.setdefault(field, value)
            reported_rows = sum(
                int(row.get("fact_rows") or 0) for row in rows
            )
            if operation == "pivot":
                # Pivot columns are dynamic; sum their observed numeric values.
                reported_rows = sum(
                    int(value or 0)
                    for row in rows
                    for key, value in row.items()
                    if key != "location"
                )
            expected_rows = _direct_filtered_count(engine, fact, schema, filters)
            passed = reported_rows == expected_rows
            filter_note = (
                ", ".join(f"{field}={value!r}" for field, value in filters.items())
                if filters
                else "none"
            )
            output_path = _unique_output_path(
                destination, f"olap_{schema}_{operation}_{fact}", ".csv"
            )
            _write_csv(output_path, rows)
            report_lines.append(
                f"{operation.upper()} | {schema} | {plan['table']} | "
                f"{len(rows)} result rows | fact records {reported_rows} "
                f"(direct SQL {expected_rows}) | filters: {filter_note} | "
                f"{'PASS' if passed else 'FAIL'} | "
                f"{output_path.name}"
            )
            if not passed:
                raise RuntimeError(
                    f"{operation} result count {reported_rows} did not match "
                    f"direct SQL count {expected_rows}."
                )
            results.append({
                "operation": operation,
                "schema": schema,
                "fact": fact,
                "table": plan["table"],
                "result_rows": len(rows),
                "fact_rows": reported_rows,
                "validated": passed,
                "csv": output_path,
            })

        report_lines.extend(("", "Supported fact tables and actual record counts:"))
        for fact, definition in FACTS.items():
            table = "star_" + definition["table"]
            if not engine._table_exists(table):
                raise OLAPError(f"Expected Star Schema fact table {table!r} is missing.")
            count = int(
                engine.connection.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
            )
            report_lines.append(f"- {table}: {count:,} records")

    report_path = _unique_output_path(
        destination, "olap_execution_report", ".txt"
    )
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return {
        "results": results,
        "report": report_path,
        "output_dir": destination,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "travelintel_warehouse.db",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "OLAP Outputs - 9",
    )
    args = parser.parse_args()
    result = run_live_examples(args.database, args.output_dir)
    for item in result["results"]:
        print(
            f"{item['operation']}: {item['table']} -> {item['csv']} "
            f"({item['fact_rows']:,} records; PASS)"
        )
    print(f"Report: {result['report']}")


if __name__ == "__main__":
    main()
