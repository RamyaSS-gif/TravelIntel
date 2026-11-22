import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AnalyticsCube from "./AnalyticsCube.jsx";
import CustomerPortal from "./CustomerPortal.jsx";
import PortalPages from "./PortalPages.jsx";
import SchemaExplorer from "./SchemaExplorer.jsx";
import AuthGate from "./AuthGate.jsx";

const OPERATION_LABELS = {
  roll_up: "Roll-up",
  drill_down: "Drill-down",
  slice: "Slice",
  dice: "Dice",
  pivot: "Pivot",
};

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status}).`);
  }
  return payload;
}

function dimensionLabel(metadata, id) {
  return metadata?.dimensions.find((dimension) => dimension.id === id)?.label ?? id;
}

function resultMetric(row, metadata) {
  return metadata.measures.find((measure) => typeof row[measure.id] === "number")?.id;
}

function makeSeries(rows, operation, measure, rowDimension) {
  return rows.map((row, index) => {
    const value =
      operation === "pivot"
        ? Object.entries(row)
            .filter(([key, cell]) => key !== rowDimension && Number.isFinite(Number(cell)))
            .reduce((sum, [, cell]) => sum + Number(cell || 0), 0)
        : Number(row[measure] ?? 0);
    const label =
      row[rowDimension] ??
      Object.entries(row).find(([key]) => key !== measure)?.[1] ??
      `Result ${index + 1}`;
    return { label: String(label), value: Number.isFinite(value) ? value : 0 };
  });
}

function ResultsChart({ rows, operation, measure, rowDimension }) {
  const points = useMemo(
    () => makeSeries(rows, operation, measure, rowDimension).slice(0, 16),
    [rows, operation, measure, rowDimension],
  );
  const max = Math.max(1, ...points.map((point) => point.value));
  const chartWidth = Math.max(420, points.length * 52);
  const chartHeight = 208;
  const gap = 12;
  const barWidth = Math.min(34, (chartWidth - gap * (points.length + 1)) / points.length);

  if (!points.length) {
    return <div className="empty-chart">No rows returned for this selection.</div>;
  }

  return (
    <div className="chart-scroll">
      <svg
        className="result-chart"
        role="img"
        aria-label="Chart of actual OLAP query results"
        viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        width={chartWidth}
        height={chartHeight}
      >
        <line x1="0" y1="174" x2={chartWidth} y2="174" className="chart-axis" />
        {points.map((point, index) => {
          const height = (point.value / max) * 138;
          const x = gap + index * (barWidth + gap);
          const y = 174 - height;
          return (
            <g key={`${point.label}-${index}`}>
              <title>{`${point.label}: ${point.value.toLocaleString()}`}</title>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={height}
                rx="5"
                className="chart-bar"
                style={{ animationDelay: `${index * 28}ms` }}
              />
              <text
                x={x + barWidth / 2}
                y="194"
                textAnchor="middle"
                className="chart-label"
              >
                {point.label.length > 8 ? `${point.label.slice(0, 7)}…` : point.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function ResultTable({ rows }) {
  const columns = rows.length ? Object.keys(rows[0]) : [];
  return (
    <div className="table-scroll">
      <table className="result-table">
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 100).map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column}>
                  {typeof row[column] === "number"
                    ? row[column].toLocaleString()
                    : row[column] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 100 && (
        <div className="table-note">Showing 100 of {rows.length.toLocaleString()} grouped rows.</div>
      )}
    </div>
  );
}

function SelectField({ label, value, onChange, options, disabled, testId }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select
        data-testid={testId}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled || options.length === 0}
      >
        {options.map((option) => (
          <option key={option.id ?? String(option.value)} value={option.id ?? option.value}>
            {option.label ?? String(option.value)}
          </option>
        ))}
      </select>
    </label>
  );
}

function DimensionChecks({ dimensions, selected, onToggle, title }) {
  return (
    <fieldset className="dimension-picker">
      <legend>{title}</legend>
      <div className="dimension-checks">
        {dimensions.map((dimension, index) => (
          <label className="check-chip" key={dimension.id}>
            <input
              type="checkbox"
              checked={selected.includes(dimension.id)}
              onChange={() => onToggle(dimension.id)}
            />
            <span className="dimension-swatch" style={{ "--swatch": `var(--dim-${index % 8})` }} />
            {dimension.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: "⌂" },
  { id: "bookings", label: "Bookings", icon: "▤" },
  { id: "warehouse", label: "Data Warehouse", icon: "▦" },
  { id: "olap", label: "OLAP Analytics", icon: "◇" },
  { id: "schema", label: "Schema Explorer", icon: "⌘" },
  { id: "tourism", label: "Tourism Analytics", icon: "⌖" },
  { id: "recommendations", label: "Travel Recommendations", icon: "✧" },
  { id: "about", label: "About Project", icon: "ⓘ" },
];

function AdminBookings() {
  const [bookings, setBookings] = useState([]);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [travelDate, setTravelDate] = useState("");
  const [category, setCategory] = useState("");
  const [bookingStatus, setBookingStatus] = useState("");

  const refreshBookings = useCallback(() => {
    setStatus("loading");
    const query = new URLSearchParams();
    if (travelDate) query.set("date", travelDate);
    if (category) query.set("category", category);
    if (bookingStatus) query.set("status", bookingStatus);
    requestJson(`/api/admin/bookings${query.size ? `?${query}` : ""}`)
      .then((result) => {
        setBookings(result.bookings);
        setStatus("connected");
        setError("");
      })
      .catch((cause) => {
        setError(cause.message);
        setStatus("error");
      });
  }, [travelDate, category, bookingStatus]);

  useEffect(() => {
    refreshBookings();
    const onFocus = () => {
      if (document.visibilityState === "visible") refreshBookings();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refreshBookings]);

  return (
    <section className="view-panel">
      <div className="page-heading">
        <div>
          <p className="eyebrow">CENTRAL BOOKING STORAGE</p>
          <h1>Customer booking requests</h1>
          <p className="page-subtitle">Requests saved in the shared TravelIntel database. No supplier or payment confirmation is implied.</p>
        </div>
        <div className="detail-actions">
          <span className={`connection-status ${status}`}><i /> {status === "connected" ? "DATABASE CONNECTED" : status === "error" ? "UNAVAILABLE" : "LOADING"}</span>
          <button className="customer-button subtle" onClick={refreshBookings} disabled={status === "loading"}>Refresh records</button>
        </div>
      </div>
      {error && <div className="customer-error" role="alert">{error}</div>}
      <div className="browse-tools">
        <label className="customer-input"><span>Travel date</span><input type="date" value={travelDate} onChange={(event) => setTravelDate(event.target.value)} /></label>
        <label className="customer-input"><span>Category</span><select value={category} onChange={(event) => setCategory(event.target.value)}><option value="">All categories</option>{["hotel", "bus", "train", "flight", "taxi", "rental", "trip plan"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="customer-input"><span>Request status</span><select value={bookingStatus} onChange={(event) => setBookingStatus(event.target.value)}><option value="">All statuses</option><option value="planning_request">Planning request</option><option value="cancelled_request">Cancelled request</option></select></label>
        <button className="customer-button" onClick={refreshBookings} disabled={status === "loading"}>Apply filters</button>
      </div>
      <section className="portal-panel portal-table-panel">
        {bookings.length ? (
          <div className="portal-table-scroll"><table className="portal-table"><thead><tr><th>Reference</th><th>Customer</th><th>Type</th><th>Route / destination</th><th>Travel dates</th><th>Passengers / room</th><th>Amount</th><th>Payment</th><th>Status</th></tr></thead>
            <tbody>{bookings.map((booking) => {
              const actual = booking.priceBreakdown?.actualTotal;
              const estimate = booking.priceBreakdown?.customerEstimate;
              const amount = actual != null
                ? `${actual} ${booking.priceBreakdown?.currency || ""} · actual`
                : estimate != null
                  ? `${estimate} ${booking.priceBreakdown?.currency || ""} · customer estimate`
                  : "Unavailable";
              return <tr key={booking.reference}><td><code>{booking.reference}</code></td><td>{booking.customerName}<br /><small>{booking.email}</small></td><td>{booking.bookingType}</td><td>{booking.origin || "—"} → {booking.destination || "—"}</td><td>{booking.travelDate}{booking.returnDate ? ` to ${booking.returnDate}` : ""}</td><td>{booking.passengerDetails?.passengers ?? "—"} / {booking.passengerDetails?.rooms ?? "—"}</td><td>{amount}</td><td>{booking.paymentStatus}</td><td>{booking.bookingStatus}</td></tr>;
            })}</tbody>
          </table></div>
        ) : <p className="portal-empty">{status === "loading" ? "Loading booking requests…" : "No customer booking requests have been saved."}</p>}
      </section>
    </section>
  );
}

function AdminAnalytics({ onExit, onLogout, user }) {
  const [catalog, setCatalog] = useState(null);
  const [activeView, setActiveView] = useState("dashboard");
  const [schema, setSchema] = useState("star");
  const [fact, setFact] = useState("tourism_observation");
  const [operation, setOperation] = useState("roll_up");
  const [selectedDimensions, setSelectedDimensions] = useState([]);
  const [fromDimensions, setFromDimensions] = useState([]);
  const [filters, setFilters] = useState([]);
  const [filterValues, setFilterValues] = useState({});
  const [filterOptions, setFilterOptions] = useState({});
  const [rowDimension, setRowDimension] = useState("");
  const [columnDimension, setColumnDimension] = useState("");
  const [selectedMeasures, setSelectedMeasures] = useState([]);
  const [pivotMeasure, setPivotMeasure] = useState("");
  const [rows, setRows] = useState([]);
  const [resultInfo, setResultInfo] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controlsRef = useRef();

  useEffect(() => {
    let active = true;
    Promise.all([
      requestJson("/api/catalog"),
      requestJson("/api/health"),
    ])
      .then(([data]) => {
        if (!active) return;
        setCatalog(data);
        setStatus("connected");
      })
      .catch((cause) => {
        if (!active) return;
        setStatus("offline");
        setError(cause.message);
      });
    return () => { active = false; };
  }, []);

  const metadata = catalog?.models?.[schema]?.[fact];
  const dimensions = metadata?.dimensions ?? [];
  const measures = metadata?.measures ?? [];
  const facts = catalog?.facts ?? [];

  useEffect(() => {
    if (!metadata) return;
    setSelectedDimensions(metadata.default_groups);
    setFromDimensions(metadata.default_groups.slice(0, 1));
    setSelectedMeasures(metadata.default_measures);
    setRowDimension(metadata.dimensions[0]?.id ?? "");
    setColumnDimension(metadata.dimensions[1]?.id ?? "");
    setPivotMeasure(metadata.default_measures[0] ?? metadata.measures[0]?.id ?? "");
    setFilters([]);
    setFilterValues({});
    setFilterOptions({});
    setRows([]);
    setResultInfo(null);
    setError("");
  }, [schema, fact, catalog]);

  const toggleItem = useCallback((setter, current, item) => {
    setter(current.includes(item) ? current.filter((value) => value !== item) : [...current, item]);
  }, []);

  const selectedIds = useMemo(
    () => new Set([...selectedDimensions, ...filters, rowDimension, columnDimension].filter(Boolean)),
    [selectedDimensions, filters, rowDimension, columnDimension],
  );

  const toggleDimensionFromCube = (dimensionId) => {
    setSelectedDimensions((current) =>
      current.includes(dimensionId)
        ? current.filter((item) => item !== dimensionId)
        : [...current, dimensionId],
    );
  };

  const loadFilterOptions = useCallback(async (dimensionId) => {
    if (!dimensionId || filterOptions[dimensionId]) return;
    try {
      const query = new URLSearchParams({ schema, fact, dimension: dimensionId });
      const response = await requestJson(`/api/dimension-values?${query}`);
      setFilterOptions((current) => ({ ...current, [dimensionId]: response.values }));
      if (response.values.length) {
        setFilterValues((current) => ({
          ...current,
          [dimensionId]: current[dimensionId] ?? response.values[0],
        }));
      }
    } catch (cause) {
      setError(cause.message);
    }
  }, [schema, fact, filterOptions]);

  useEffect(() => {
    filters.forEach((dimensionId) => { void loadFilterOptions(dimensionId); });
  }, [filters, loadFilterOptions]);

  const toggleFilter = (dimensionId) => {
    setFilters((current) => {
      if (operation === "slice") {
        return current.includes(dimensionId) ? [] : [dimensionId];
      }
      const next = current.includes(dimensionId)
        ? current.filter((item) => item !== dimensionId)
        : [...current, dimensionId];
      return next;
    });
    void loadFilterOptions(dimensionId);
  };

  const queryPayload = () => {
    const groupBy = selectedDimensions;
    const activeFilters = Object.fromEntries(
      filters
        .filter((dimensionId) => filterValues[dimensionId] !== undefined)
        .map((dimensionId) => [dimensionId, filterValues[dimensionId]]),
    );
    const base = { schema, fact, operation, measures: selectedMeasures };
    if (operation === "roll_up") return { ...base, group_by: groupBy };
    if (operation === "drill_down") {
      const fine = selectedDimensions;
      const coarse = fromDimensions.filter((item) => fine.includes(item));
      return { ...base, from_group_by: coarse, group_by: fine };
    }
    if (operation === "slice") {
      const [dimension] = filters;
      return {
        ...base,
        dimension,
        filters: dimension ? { [dimension]: filterValues[dimension] } : {},
        group_by: groupBy.filter((item) => item !== dimension),
      };
    }
    if (operation === "dice") return { ...base, filters: activeFilters, group_by: groupBy };
    return {
      schema,
      fact,
      operation,
      row_dimension: rowDimension,
      column_dimension: columnDimension,
      measure: pivotMeasure,
      filters: activeFilters,
    };
  };

  const runOperation = async () => {
    setBusy(true);
    setError("");
    try {
      const request = queryPayload();
      const result = await requestJson("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      setRows(result.rows);
      setResultInfo({ ...result, request });
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  };

  const resetCube = () => controlsRef.current?.reset();
  const resultMetadata = resultInfo
    ? catalog?.models?.[resultInfo.schema]?.[resultInfo.fact]
    : metadata;
  const resultRequest = resultInfo?.request;
  const resultDimensions = resultRequest?.operation === "pivot"
    ? [resultRequest.row_dimension, resultRequest.column_dimension]
    : resultRequest?.group_by ?? [];
  const resultDimensionLabels = resultDimensions.map((id) =>
    dimensionLabel(resultMetadata, id),
  );
  const resultFilters = Object.entries(resultRequest?.filters ?? {}).map(
    ([id, value]) => `${dimensionLabel(resultMetadata, id)} = ${value}`,
  );
  const activeMetric = resultInfo
    ? resultInfo.operation === "pivot"
      ? resultRequest.measure
      : resultMetric(rows[0] ?? {}, {
          measures: (resultRequest.measures ?? []).map((id) => ({ id })),
        })
    : operation === "pivot"
      ? pivotMeasure
      : resultMetric(rows[0] ?? {}, metadata ?? { measures: [] });
  const displayOperation = resultInfo?.operation ?? operation;
  const displayRowDimension = resultRequest?.row_dimension ?? rowDimension;
  const filterableDimensions = dimensions.filter(
    (dimension) => !filters.includes(dimension.id) || operation === "slice",
  );
  const filtersReady = filters.every((dimensionId) => filterValues[dimensionId] !== undefined);
  const changeOperation = (nextOperation) => {
    setOperation(nextOperation);
    if (nextOperation === "drill_down" && metadata) {
      const coarse = metadata.default_groups.slice(0, 1);
      const fine = [...metadata.default_groups];
      if (fine.length <= coarse.length) {
        const nextDetail = dimensions.find((dimension) => !fine.includes(dimension.id));
        if (nextDetail) fine.push(nextDetail.id);
      }
      setFromDimensions(coarse);
      setSelectedDimensions(fine);
    }
    if (nextOperation === "slice" && dimensions[0]) {
      setFilters([dimensions[0].id]);
    }
    if (nextOperation === "dice") {
      const defaults = [...(metadata?.default_groups ?? [])];
      for (const dimension of dimensions) {
        if (defaults.length >= 2) break;
        if (!defaults.includes(dimension.id)) defaults.push(dimension.id);
      }
      setFilters(defaults.slice(0, 2));
    }
  };

  return (
    <div className="site-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark" aria-hidden="true"><span /><span /><span /></div>
          <div><div className="brand-name">TRAVEL<span>INTEL</span></div><div className="brand-caption">TOURISM INTELLIGENCE</div></div>
        </div>
        <p className="sidebar-section-label">WORKSPACE</p>
        <nav className="sidebar-nav" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={activeView === item.id ? "active" : ""}
              onClick={() => setActiveView(item.id)}
              aria-current={activeView === item.id ? "page" : undefined}
            >
              <span className="sidebar-nav-icon" aria-hidden="true">{item.icon}</span>
              <span>{item.label}</span>
              {activeView === item.id && <i />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-demo-card"><span className="demo-label"><i /> DEMO ACCESS</span><p>Read-only project workspace</p></div>
          <button className="sidebar-signout" onClick={onLogout}><span aria-hidden="true">↪</span> Log out</button>
          <button className="sidebar-signout" onClick={onExit}><span aria-hidden="true">←</span> Travel website</button>
          <span className="sidebar-version">TRAVELINTEL · COLLEGE PROJECT</span>
        </div>
      </aside>
      <main className="app-shell">
      <header className="topbar">
        <div className="topbar-title"><span>{NAV_ITEMS.find((item) => item.id === activeView)?.label}</span><small>TravelIntel analytics workspace</small></div>
        <div className="topbar-right">
          <span className={`connection-status ${status}`} data-testid="connection-status">
            <i /> {status === "connected" ? "DATABASE CONNECTED" : status === "offline" ? "API OFFLINE" : "CONNECTING"}
          </span>
          <span className="topbar-demo-chip"><i /> DEMO</span>
          <span className="topbar-user-chip">{user.name}</span>
          <button className="admin-exit-link" onClick={onLogout}>Log out</button>
          <button className="admin-exit-link" onClick={onExit}>Travel website <span>↗</span></button>
        </div>
      </header>

      <div className={!["olap", "schema", "bookings"].includes(activeView) ? "portal-view" : "portal-view is-hidden"}>
        <PortalPages page={activeView} catalog={catalog} onNavigate={setActiveView} />
      </div>
      <div className={activeView === "bookings" ? "portal-view" : "portal-view is-hidden"}>
        <AdminBookings />
      </div>
      <div className={activeView === "olap" ? "view-panel" : "view-panel is-hidden"}>
      <section className="page-heading">
        <div>
          <p className="eyebrow">INTERACTIVE ANALYTICS</p>
          <h1>Tourism analytics cube</h1>
          <p className="page-subtitle">Explore verified warehouse facts through live OLAP queries.</p>
        </div>
        <div className="schema-switch" role="group" aria-label="Schema model">
          {["star", "snowflake"].map((item) => (
            <button
              key={item}
              className={schema === item ? "active" : ""}
              onClick={() => setSchema(item)}
              disabled={!catalog}
            >
              {item === "star" ? "Star schema" : "Snowflake"}
            </button>
          ))}
        </div>
      </section>

      {error && <div className="notice error-notice" role="alert">{error}</div>}

      <section className="workspace-grid">
        <article className="panel cube-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">LIVE DIMENSION SPACE</p>
              <h2>TRAVELINTEL_TOURISM_ANALYTICS_CUBE</h2>
            </div>
            <button className="icon-button" onClick={resetCube} aria-label="Reset camera" title="Reset camera">
              <span className="reset-icon">↺</span>
            </button>
          </div>
          <AnalyticsCube
            enabled={activeView === "olap"}
            dimensions={dimensions}
            activeDimensions={[...selectedIds]}
            onSelectDimension={toggleDimensionFromCube}
            rows={rows}
            operation={displayOperation}
            metric={activeMetric}
            rowDimension={displayRowDimension}
            controlsRef={controlsRef}
          />
          <div className="cube-legend">
            <span><i className="legend-cube" /> Warehouse dimensions</span>
            <span><i className="legend-bars" /> Query result magnitude</span>
            <span className="legend-note">Click dimension tags to select</span>
          </div>
          <div className="dimension-legend">
            {dimensions.map((dimension, index) => (
              <button
                key={dimension.id}
                className={selectedIds.has(dimension.id) ? "legend-dimension selected" : "legend-dimension"}
                style={{ "--dimension-color": `var(--dim-${index % 8})` }}
                onClick={() => toggleDimensionFromCube(dimension.id)}
                title={`Toggle ${dimension.label}`}
              >
                <i />{dimension.label}
              </button>
            ))}
          </div>
        </article>

        <aside className="panel controls-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">QUERY BUILDER</p>
              <h2>Configure analysis</h2>
            </div>
            <span className="read-only-badge">READ ONLY</span>
          </div>

          <div className="control-grid">
            <SelectField
              label="Fact table"
              value={fact}
              onChange={setFact}
              options={facts}
              disabled={!catalog}
              testId="fact-select"
            />
            <SelectField
              label="OLAP operation"
              value={operation}
              onChange={changeOperation}
              options={Object.entries(OPERATION_LABELS).map(([id, label]) => ({ id, label }))}
              disabled={!catalog}
              testId="operation-select"
            />
          </div>

          {operation === "roll_up" && (
            <DimensionChecks
              dimensions={dimensions}
              selected={selectedDimensions}
              onToggle={(id) => toggleItem(setSelectedDimensions, selectedDimensions, id)}
              title="Aggregate by"
            />
          )}

          {operation === "drill_down" && (
            <>
              <DimensionChecks
                dimensions={dimensions}
                selected={fromDimensions}
                onToggle={(id) => toggleItem(setFromDimensions, fromDimensions, id)}
                title="Summary level"
              />
              <DimensionChecks
                dimensions={dimensions}
                selected={selectedDimensions}
                onToggle={(id) => toggleItem(setSelectedDimensions, selectedDimensions, id)}
                title="Detail level (includes summary dimensions)"
              />
            </>
          )}

          {(operation === "slice" || operation === "dice") && (
            <div className="filter-builder">
              <div className="subheading">
                <span>{operation === "slice" ? "Choose one slice" : "Choose two or more dice filters"}</span>
                <small>{filters.length} selected</small>
              </div>
              <div className="filter-list">
                {filterableDimensions.map((dimension) => (
                  <div className="filter-row" key={dimension.id}>
                    <label className="filter-check">
                      <input
                        type="checkbox"
                        checked={filters.includes(dimension.id)}
                        onChange={() => toggleFilter(dimension.id)}
                      />
                      <span>{dimension.label}</span>
                    </label>
                    {filters.includes(dimension.id) && (
                      <select
                        aria-label={`${dimension.label} filter value`}
                        data-testid={`filter-${dimension.id}`}
                        value={String(filterValues[dimension.id] ?? "")}
                        onChange={(event) => {
                          const option = (filterOptions[dimension.id] ?? []).find(
                            (value) => String(value) === event.target.value,
                          );
                          setFilterValues((current) => ({ ...current, [dimension.id]: option }));
                        }}
                      >
                        {(filterOptions[dimension.id] ?? []).map((value) => (
                          <option key={String(value)} value={String(value)}>{String(value)}</option>
                        ))}
                      </select>
                    )}
                  </div>
                ))}
              </div>
              <DimensionChecks
                dimensions={dimensions.filter((dimension) => !filters.includes(dimension.id))}
                selected={selectedDimensions.filter((dimension) => !filters.includes(dimension))}
                onToggle={(id) => toggleItem(setSelectedDimensions, selectedDimensions, id)}
                title="Group results by"
              />
            </div>
          )}

          {operation === "pivot" && (
            <div className="control-grid pivot-fields">
              <SelectField
                label="Rows"
                value={rowDimension}
                onChange={setRowDimension}
                options={dimensions}
              />
              <SelectField
                label="Columns"
                value={columnDimension}
                onChange={setColumnDimension}
                options={dimensions.filter((item) => item.id !== rowDimension)}
              />
              <SelectField
                label="Measure"
                value={pivotMeasure}
                onChange={setPivotMeasure}
                options={measures}
              />
            </div>
          )}

          {operation !== "pivot" && (
            <fieldset className="dimension-picker measure-picker">
              <legend>Measures</legend>
              <div className="measure-list">
                {measures.map((measure) => (
                  <label className="check-chip" key={measure.id}>
                    <input
                      type="checkbox"
                      checked={selectedMeasures.includes(measure.id)}
                      onChange={() => toggleItem(setSelectedMeasures, selectedMeasures, measure.id)}
                    />
                    {measure.label}
                  </label>
                ))}
              </div>
            </fieldset>
          )}

          <button
            className="run-button"
            data-testid="run-query"
            onClick={runOperation}
            disabled={
              !catalog ||
              busy ||
              (operation === "slice" && (filters.length !== 1 || !filtersReady)) ||
              (operation === "dice" && (filters.length < 2 || !filtersReady)) ||
              (operation === "drill_down" &&
                (!fromDimensions.length ||
                  fromDimensions.some((dimension) => !selectedDimensions.includes(dimension)) ||
                  selectedDimensions.length <= fromDimensions.length)) ||
              (operation !== "pivot" && selectedMeasures.length === 0)
            }
          >
            {busy ? <><span className="spinner" /> Querying warehouse…</> : <><span>▶</span> Run {OPERATION_LABELS[operation]}</>}
          </button>
          <p className="control-footnote">
            Queries execute against <code>{metadata?.table ?? "verified fact table"}</code>; no warehouse data is changed.
          </p>
        </aside>
      </section>

      <section className="results-section">
        <div className="results-heading">
          <div>
            <p className="eyebrow">QUERY OUTPUT</p>
            <h2>Analytical results</h2>
            <p className="page-subtitle">
              {resultInfo
                ? `${OPERATION_LABELS[resultInfo.operation]} · ${resultInfo.table} · ${rows.length.toLocaleString()} grouped rows`
                : "Run an OLAP operation to load live results from SQLite."}
            </p>
            {resultInfo && (
              <p className="page-subtitle">
                Dimensions: {resultDimensionLabels.length ? resultDimensionLabels.join(", ") : "Grand total"}
                {resultFilters.length > 0 && ` · Filters: ${resultFilters.join(", ")}`}
              </p>
            )}
          </div>
          {resultInfo && (
            <span className="actual-data-badge"><i /> ACTUAL WAREHOUSE DATA</span>
          )}
        </div>
        <div className="results-grid">
          <article className="panel chart-panel">
            <div className="results-card-heading">
              <div><h3>Result profile</h3><span>Actual query values · top 16 groups</span></div>
            </div>
            <ResultsChart
              rows={rows}
              operation={displayOperation}
              measure={activeMetric}
              rowDimension={displayRowDimension}
            />
          </article>
          <article className="panel table-panel">
            <div className="results-card-heading">
              <div><h3>Result table</h3><span>{resultInfo ? `Source: ${resultInfo.table}` : "No query executed yet"}</span></div>
            </div>
            {rows.length ? <ResultTable rows={rows} /> : <div className="empty-table">Query results will appear here.</div>}
          </article>
        </div>
      </section>

      <footer className="app-footer">
        <span>TRAVELINTEL <b>·</b> STAGE 07</span>
        <span>Dimensions and measures are discovered from the selected warehouse fact.</span>
      </footer>
      </div>
      <div className={activeView === "schema" ? "view-panel" : "view-panel is-hidden"}>
        <SchemaExplorer
          enabled={activeView === "schema"}
          schema={schema}
          onSchemaChange={setSchema}
        />
      </div>
      </main>
    </div>
  );
}

export default function App() {
  const [portal, setPortal] = useState(() => (
    window.location.pathname.replace(/\/+$/, "") === "/admin" ? "admin" : "customer"
  ));

  useEffect(() => {
    const syncPortal = () => {
      setPortal(window.location.pathname.replace(/\/+$/, "") === "/admin" ? "admin" : "customer");
    };
    window.addEventListener("popstate", syncPortal);
    return () => window.removeEventListener("popstate", syncPortal);
  }, []);

  const navigatePortal = (nextPortal) => {
    const path = nextPortal === "admin" ? "/admin" : "/customer";
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
    setPortal(nextPortal);
  };

  return (
    <AuthGate key={portal} portal={portal}>
      {(user, onLogout) => portal === "admin"
        ? <AdminAnalytics
            user={user}
            onLogout={() => { navigatePortal("customer"); onLogout(); }}
            onExit={() => navigatePortal("customer")}
          />
        : <CustomerPortal
            user={user}
            onLogout={onLogout}
            onAdmin={() => navigatePortal("admin")}
          />}
    </AuthGate>
  );
}
