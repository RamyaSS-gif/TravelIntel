# TravelIntel

TravelIntel is a multi-source tourism data warehouse and analysis project. The
current implementation completes the first ETL pass over the source files in
this workspace. Original source datasets are read-only inputs.

## Run the ETL

From this directory, run:

```powershell
python -m etl.pipeline
```

The pipeline discovers supported files below the workspace, excluding project
and generated-output folders. It processes delimited text in chunks, cleans
column names and whitespace, standardizes parseable dates and numeric fields,
preserves missing values, validates selected ranges, and removes duplicate
records. Each output row includes `etl_source_file` lineage.

Every run creates a new, timestamped directory under `Processed Data - 8`.
Existing outputs are not overwritten. The run contains cleaned CSVs,
`extraction_report.csv`, `integration_report.csv`, and
`travelintel_warehouse.db`. The SQLite database includes one table per cleaned
source plus `etl_manifest`. Very wide, sparse reference tables are stored as
`source_record_id`, `attribute`, and `value` rows to stay within SQLite's
column limit; the manifest records this storage mode.

Quality summary and per-column reports and an ETL summary are written under
`reports`. If a report name already exists, a timestamped name is used instead.
The inventory report from Stage 1 is retained.

## Current source findings

- The archive contains 29 tabular source files and two metadata-only files.
- The Jupyter notebook's metadata and code cells are inventoried, but notebook
  code is never executed by the ETL.
- No safe cross-source join was found for the tourism dataset, hotel bookings,
  weather series, or commute data. Seven review-place names match the
  destination catalog, but city context does not reliably corroborate those
  matches. Accordingly, no `integrated_tourism.csv` is fabricated; cleaned
  sources remain separate and the candidate checks are documented.
- No XLS, XLSX, or Parquet sources were present in this archive. The ETL has
  readers for these formats; their parsing libraries are optional dependencies.

## Validation status

The ETL unit suite is:

```powershell
python -m unittest etl.test_etl -v
```

The full archive run completed with 29 cleaned tables loaded into SQLite,
two metadata-only sources, zero source-level errors, and a passing SQLite
integrity check. Review the most recent ETL summary and quality report in
`reports` for per-source counts and quality metrics.

## SQLite warehouse (Stage 4)

Build the warehouse from the most recent ETL run with:

```powershell
python -m warehouse.create_warehouse
```

The builder creates `travelintel_warehouse.db` in the workspace and refuses to
overwrite an existing database. It stages every cleaned CSV, assigning a
warehouse row identifier for traceability. The wide reference datasets use a
record table and an attribute/value table so the complete set of source fields
can be stored within SQLite's column limit.

The current warehouse includes `dim_date`, `dim_hotel_type`,
`dim_airbnb_listing`, and `dim_tourism_location`, with booking, Airbnb
availability/review, and tourism observation fact tables. Foreign keys connect
facts to their applicable source rows and dimensions. Other datasets remain
separate staging tables where a defensible fact/dimension join is unavailable.
Review the `warehouse/` folder for the schema and builder, and the
`reports/warehouse_table_inventory.csv`,
`reports/warehouse_relationships.csv`, and
`reports/warehouse_validation.txt` files for the generated inventory and
validation evidence.

Warehouse tests:

```powershell
python -m unittest warehouse.test_create_warehouse -v
```

## Star and Snowflake schemas (Stage 5)

After building the warehouse, add both dimensional models without replacing
staging or Stage 4 tables:

```powershell
python -m warehouse.build_dimensional_schemas
```

The command is additive and refuses to recreate existing `star_` or
`snowflake_` tables. Both models are stored in the workspace-level
`travelintel_warehouse.db`.

The Star Schema has denormalized date, hotel type, Airbnb listing, and tourism
location dimensions, with separate facts for hotel bookings, Boston and Seattle
Airbnb calendar/review events, and tourism observations. Snowflake normalizes
the date dimension into date and calendar-month tables and the Airbnb listing
dimension into city, observed neighbourhood, property-type, and room-type
tables. No additional geography hierarchy is inferred. Each fact row retains a
foreign key to its source staging row.

The builder checks fact-row parity against the existing warehouse facts,
executes and compares representative JOINs for both models, and validates
SQLite integrity and foreign keys. Generated reports include
`star_schema_table_inventory.csv`, `star_schema_relationships.csv`,
`snowflake_schema_table_inventory.csv`,
`snowflake_schema_relationships.csv`, both schema sample JOIN reports, and
`schema_comparison.txt`.

Tests:

```powershell
python -m unittest warehouse.test_create_warehouse -v
```

## Functional OLAP operations (Stage 6)

Run the read-only OLAP demonstrations against the existing warehouse:

```powershell
python -m olap.olap_operations
python -m unittest olap.test_olap_operations -v
```

`olap/olap_operations.py` supports roll-up, drill-down, slice, dice, and pivot
over each of the six separate Star and Snowflake fact tables. Dimension names
and measures are validated per fact; unsupported fields raise a clear error.
Queries use parameterized filter values and do not write to the warehouse.
Five real-data examples and a direct record-count validation report are saved
to `OLAP Outputs - 9`. Airbnb prices remain text and are not averaged. The
tourism observation fact has no date key, so its drill-down uses the available
location and attractiveness-label categories instead of an invented time
hierarchy.

## Interactive 3D OLAP cube (Stage 7)

The React/Three.js application in `frontend/` connects to the existing SQLite
warehouse through a local read-only API. Start the API from the workspace root:

```powershell
python -m olap.api_server
```

In a second terminal, start the frontend:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The cube supports mouse-drag rotation, scroll
zoom, clickable dimension selectors, and camera reset. Its query builder invokes
the Stage 6 OLAP engine for roll-up, drill-down, slice, dice, and pivot, then
renders actual query rows in the cube, chart, and results table. Available
dimensions and measures are discovered from the selected fact table. Traveller,
transport, and weather are not dimensions in either existing dimensional
schema, so they are not offered. Airbnb prices remain text and are not treated
as numeric measures.

Run the API and OLAP tests with:

```powershell
python -m unittest olap.test_olap_operations olap.test_api_server -v
```

## Interactive schema explorer (Stage 8)

Use the Stage 7 API and frontend commands above, then select **Schema explorer**
in the application header. The Star and Snowflake views discover their table
columns, primary keys, foreign keys, row counts, and sample records directly
from SQLite metadata and read-only queries. Their 3D connectors represent
declared foreign keys between displayed model tables; ETL lineage foreign keys
to staging tables are shown in the selected table's inspector. Drag to rotate,
scroll to zoom, right-drag to pan, and use the reset button to restore the
camera.

Validate the read-only schema endpoints and existing OLAP behavior with:

```powershell
python -m unittest olap.test_olap_operations olap.test_api_server -v
```

## TravelIntel customer portal

The default frontend is a customer-facing destination discovery and trip
planning demo. It includes destination search and profiles, MoodMatch,
destination comparison and alternatives, trip drafts, historical
accommodation/weather/review information, a transport data notice, and
browser-local demo booking requests. **Admin Analytics** opens the existing
dashboard, warehouse views, OLAP cube, and Star/Snowflake Schema Explorer.

The `/admin` login is separate from customer accounts. Configure the admin
credentials in the environment of the API process before starting it; the API
does not accept customer registrations as administrator credentials:

```powershell
$env:TRAVELINTEL_ADMIN_EMAIL = "<your-admin-email>"
$env:TRAVELINTEL_ADMIN_PASSWORD = "<your-admin-password>"
python -m olap.api_server
```

Start the app from the workspace root in two terminals:

```powershell
python -m olap.api_server
```

```powershell
Set-Location frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development server proxies `/api` to the
read-only API at `http://127.0.0.1:8765`. The API reads the existing
`travelintel_warehouse.db`; run the ETL and warehouse/schema steps above if
that database is not present.

The portal describes dataset boundaries in the UI: destination profiles,
Airbnb snapshots, commute records, weather observations, and reviews are
separate historical sources without a defensible universal join. They are not
live availability, prices, tourist routes, or forecasts. Demo booking requests
are stored only in the current browser's local storage; they do not reserve
travel, contact providers, or write to the warehouse. No production
authentication, booking provider, or hosted deployment is configured.

Build the static frontend bundle with:

```powershell
Set-Location frontend
npm run build
```

Serving the production bundle requires a host for `frontend/dist` and a
separately reachable Python API configured for the deployment environment.
