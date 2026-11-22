import React, { useEffect, useMemo, useState } from "react";

const EMPTY_DATA = { tourism: [], hotels: [], reviews: [], calendars: {} };

async function queryWarehouse(fact, measures, groupBy) {
  const response = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      schema: "star",
      fact,
      operation: "roll_up",
      group_by: groupBy,
      measures,
    }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
  return result.rows;
}

function formatNumber(value, digits = 0) {
  return Number.isFinite(Number(value))
    ? Number(value).toLocaleString(undefined, { maximumFractionDigits: digits })
    : "—";
}

function StatCard({ label, value, note, icon }) {
  return (
    <article className="portal-stat-card">
      <div className="portal-stat-top"><span>{label}</span><b aria-hidden="true">{icon}</b></div>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function BarList({ rows, labelKey, valueKey, empty, suffix = "" }) {
  const max = Math.max(1, ...rows.map((row) => Number(row[valueKey]) || 0));
  if (!rows.length) return <div className="portal-empty">{empty}</div>;
  return (
    <div className="portal-bar-list">
      {rows.map((row, index) => {
        const value = Number(row[valueKey]) || 0;
        return (
          <div className="portal-bar-row" key={`${row[labelKey]}-${index}`}>
            <div className="portal-bar-copy">
              <span title={String(row[labelKey] ?? "Unknown")}>{row[labelKey] ?? "Unknown"}</span>
              <b>{formatNumber(value, 2)}{suffix}</b>
            </div>
            <div className="portal-bar-track">
              <i style={{ width: `${Math.max(2, (value / max) * 100)}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ErrorMessage({ children }) {
  return children ? <div className="portal-error" role="alert">{children}</div> : null;
}

function Dashboard({ data, errors, loading, onNavigate }) {
  const tourismTotal = data.tourism.reduce((sum, row) => sum + (Number(row.fact_rows) || 0), 0);
  const bookingTotal = data.hotels.reduce((sum, row) => sum + (Number(row.fact_rows) || 0), 0);
  const reviewTotal = data.reviews.reduce((sum, row) => sum + (Number(row.fact_rows) || 0), 0);
  const destinations = data.tourism.length;
  const sortedTourism = [...data.tourism]
    .sort((a, b) => (Number(b.recorded_visitors) || 0) - (Number(a.recorded_visitors) || 0))
    .slice(0, 6);

  return (
    <>
      <section className="portal-welcome">
        <div>
          <p className="eyebrow">TRAVEL INTELLIGENCE · LIVE WAREHOUSE</p>
          <h1>Tourism, seen clearly.</h1>
          <p>Explore destination observations and accommodation data from your connected TravelIntel warehouse.</p>
        </div>
        <button className="portal-primary" onClick={() => onNavigate("tourism")}>Explore tourism data <span>→</span></button>
      </section>
      <ErrorMessage>{errors.general || [errors.tourism, errors.hotels, errors.reviews].filter(Boolean).join(" · ")}</ErrorMessage>
      <div className="portal-stat-grid">
        <StatCard label="Tourism observations" value={loading ? "…" : errors.tourism ? "Unavailable" : formatNumber(tourismTotal)} note="Verified destination records" icon="◈" />
        <StatCard label="Destinations observed" value={loading ? "…" : errors.tourism ? "Unavailable" : formatNumber(destinations)} note="Locations in tourism fact data" icon="⌖" />
        <StatCard label="Hotel bookings" value={loading ? "…" : errors.hotels ? "Unavailable" : formatNumber(bookingTotal)} note="Records in the hotel fact table" icon="▤" />
        <StatCard label="Airbnb reviews" value={loading ? "…" : errors.reviews ? "Unavailable" : formatNumber(reviewTotal)} note="Boston + Seattle review records" icon="✳" />
      </div>
      <div className="portal-section-heading">
        <div><p className="eyebrow">FROM THE WAREHOUSE</p><h2>Destination pulse</h2></div>
        <span className="portal-live-tag"><i /> Actual query results</span>
      </div>
      <div className="portal-content-grid">
        <article className="portal-panel">
          <div className="portal-panel-heading"><div><h3>Recorded visitors</h3><span>By destination · top 6</span></div><b>01</b></div>
          <ErrorMessage>{errors.tourism}</ErrorMessage>
          <BarList rows={sortedTourism} labelKey="location" valueKey="recorded_visitors" empty={loading ? "Loading destination data…" : "No tourism results are available."} />
        </article>
        <article className="portal-panel portal-summary-panel">
          <p className="eyebrow">DATA COVERAGE</p>
          <h3>Evidence over estimates.</h3>
          <p>Each metric on this dashboard is queried from a fact table in the existing Star Schema. Traveller survey data is not modeled as a warehouse fact, so no traveller totals are shown.</p>
          <div className="portal-summary-pills"><span>Star + Snowflake</span><span>5 OLAP operations</span><span>Read-only queries</span></div>
          <button className="portal-text-button" onClick={() => onNavigate("warehouse")}>View warehouse details <span>→</span></button>
        </article>
      </div>
    </>
  );
}

function WarehousePage({ catalog, data, errors, loading }) {
  const factCounts = {
    tourism_observation: data.tourism.reduce((sum, row) => sum + (Number(row.fact_rows) || 0), 0),
    hotel_booking: data.hotels.reduce((sum, row) => sum + (Number(row.fact_rows) || 0), 0),
    airbnb_review_boston: Number(data.reviews.find((row) => row.source === "Boston")?.fact_rows) || 0,
    airbnb_review_seattle: Number(data.reviews.find((row) => row.source === "Seattle")?.fact_rows) || 0,
  };
  const unavailable = (factId) => (
    factId === "tourism_observation" && errors.tourism ||
    factId === "hotel_booking" && errors.hotels ||
    factId.startsWith("airbnb_review") && errors.reviews ||
    factId.startsWith("airbnb_calendar") && errors.calendars
  );
  return (
    <>
      <div className="portal-page-heading"><p className="eyebrow">DATA FOUNDATION</p><h1>Data warehouse</h1><p>Explore the existing ETL outputs and dimensional models powering TravelIntel.</p></div>
      <ErrorMessage>{errors.general}</ErrorMessage>
      <div className="portal-stat-grid portal-stat-grid-three">
        <StatCard label="Dimensional models" value={catalog ? "2" : "—"} note="Star Schema · Snowflake Schema" icon="◇" />
        <StatCard label="OLAP fact datasets" value={catalog ? formatNumber(catalog.facts.length) : "—"} note="Discovered from the API catalog" icon="▦" />
        <StatCard label="ETL / source data" value="Existing" note="Processed outputs preserved in workspace" icon="↻" />
      </div>
      <article className="portal-panel portal-table-panel">
        <div className="portal-panel-heading"><div><h3>OLAP-ready fact datasets</h3><span>Mapped from the live API catalog</span></div><span className="portal-live-tag"><i /> {catalog ? "Connected" : "Unavailable"}</span></div>
        {catalog ? (
          <div className="portal-data-list">
            {catalog.facts.map((fact) => {
              const model = catalog.models?.star?.[fact.id];
              return (
                <div className="portal-data-row" key={fact.id}>
                  <span className="portal-data-icon">▤</span>
                  <div><b>{fact.label}</b><small><code>{model?.table ?? "Table mapping unavailable"}</code></small></div>
                  <span className="portal-data-count">
                    {loading ? "Querying…" : unavailable(fact.id) ? "Unavailable" : factCounts[fact.id] !== undefined ? `${formatNumber(factCounts[fact.id])} rows` : data.calendars[fact.id] !== undefined ? `${formatNumber(data.calendars[fact.id])} rows` : "In catalog"}
                  </span>
                </div>
              );
            })}
          </div>
        ) : <p className="portal-empty">Start the existing API to discover warehouse datasets.</p>}
        <ErrorMessage>{errors.general || [errors.tourism, errors.hotels, errors.reviews, errors.calendars].filter(Boolean).join(" · ")}</ErrorMessage>
      </article>
      <div className="portal-info-strip"><b>Pipeline status</b><span>The existing ETL pipeline and SQLite warehouse are unchanged. This website reads the Star Schema through the current read-only API.</span></div>
    </>
  );
}

function TourismPage({ data, errors, loading }) {
  const visitorRows = [...data.tourism].sort((a, b) => (Number(b.recorded_visitors) || 0) - (Number(a.recorded_visitors) || 0));
  const ratingRows = [...data.tourism].sort((a, b) => (Number(b.average_rating) || 0) - (Number(a.average_rating) || 0)).slice(0, 8);
  return (
    <>
      <div className="portal-page-heading"><p className="eyebrow">OBSERVATIONS · TRENDS · REVIEWS</p><h1>Tourism analytics</h1><p>Explore recorded visitor counts, ratings, costs and sentiment in the tourism observation fact.</p></div>
      <ErrorMessage>{errors.tourism}</ErrorMessage>
      <div className="portal-content-grid">
        <article className="portal-panel"><div className="portal-panel-heading"><div><h3>Recorded visitors</h3><span>Destination ranking · source values</span></div></div><BarList rows={visitorRows.slice(0, 10)} labelKey="location" valueKey="recorded_visitors" empty={loading ? "Loading actual results…" : "No results available."} /></article>
        <article className="portal-panel"><div className="portal-panel-heading"><div><h3>Average destination rating</h3><span>Highest observed averages</span></div></div><BarList rows={ratingRows} labelKey="location" valueKey="average_rating" empty={loading ? "Loading actual results…" : "No results available."} suffix=" / 5" /></article>
      </div>
      <article className="portal-panel portal-table-panel">
        <div className="portal-panel-heading"><div><h3>Destination analysis</h3><span>Grouped directly from tourism_observation</span></div><span className="portal-live-tag"><i /> Actual data</span></div>
        {data.tourism.length ? (
          <div className="portal-table-scroll"><table className="portal-table"><thead><tr><th>Destination</th><th>Records</th><th>Visitors</th><th>Avg. rating</th><th>Avg. cost</th><th>Sentiment</th></tr></thead>
            <tbody>{data.tourism.map((row, index) => <tr key={`${row.location}-${index}`}><td>{row.location ?? "—"}</td><td>{formatNumber(row.fact_rows)}</td><td>{formatNumber(row.recorded_visitors)}</td><td>{formatNumber(row.average_rating, 2)}</td><td>{formatNumber(row.average_cost, 2)}</td><td>{formatNumber(row.average_sentiment_score, 3)}</td></tr>)}</tbody>
          </table></div>
        ) : <p className="portal-empty">{loading ? "Loading destination data…" : "No tourism results are available."}</p>}
        <p className="portal-footnote">Rating and sentiment are fields from the tourism observation dataset, not sentiment analysis of the separate review sources.</p>
      </article>
      <article className="portal-panel portal-review-panel"><div className="portal-panel-heading"><div><h3>Accommodation review coverage</h3><span>Review fact records · comments are not re-scored</span></div></div>
        <ErrorMessage>{errors.reviews}</ErrorMessage>
        <div className="portal-review-counts">{data.reviews.map((row) => <div key={row.source}><span>{row.source}</span><b>{formatNumber(row.fact_rows)}</b><small>reviews · {formatNumber(row.comments_present)} with comments</small></div>)}</div>
      </article>
    </>
  );
}

function RecommendationsPage({ data, errors, loading }) {
  const [basis, setBasis] = useState("recorded_visitors");
  const recommendations = useMemo(() => [...data.tourism]
    .filter((row) => Number.isFinite(Number(row[basis])))
    .sort((a, b) => Number(b[basis]) - Number(a[basis]))
    .slice(0, 8), [data.tourism, basis]);
  const basisLabel = {
    recorded_visitors: "highest recorded visitor count",
    average_rating: "highest observed average rating",
    average_sentiment_score: "highest observed sentiment score",
  }[basis];
  return (
    <>
      <div className="portal-page-heading"><p className="eyebrow">DATA-LED DISCOVERY</p><h1>Travel recommendations</h1><p>Explore destinations ranked by observed tourism indicators. These are descriptive rankings, not personalized predictions.</p></div>
      <article className="portal-panel portal-recommend-controls">
        <label className="field"><span>Rank destinations by</span><select value={basis} onChange={(event) => setBasis(event.target.value)}><option value="recorded_visitors">Recorded visitors</option><option value="average_rating">Average rating</option><option value="average_sentiment_score">Average sentiment score</option></select></label>
        <div><b>Recommendation basis</b><p>Destinations are ordered by {basisLabel} in the existing tourism observation records. No traveler profile or predictive model is used.</p></div>
      </article>
      <ErrorMessage>{errors.tourism}</ErrorMessage>
      {loading ? <div className="portal-empty portal-loading">Loading actual destination results…</div> : recommendations.length ? (
        <div className="portal-recommend-grid">{recommendations.map((row, index) => <article className="portal-recommend-card" key={`${row.location}-${index}`}>
          <div className="portal-recommend-rank">0{index + 1}</div><div><p className="eyebrow">OBSERVED DESTINATION</p><h3>{row.location ?? "Unknown destination"}</h3><span>{formatNumber(row.fact_rows)} tourism records</span></div>
          <div className="portal-recommend-metric"><b>{formatNumber(row[basis], basis === "recorded_visitors" ? 0 : 3)}</b><small>{basis === "recorded_visitors" ? "recorded visitors" : basis === "average_rating" ? "average rating" : "sentiment score"}</small></div>
        </article>)}</div>
      ) : <div className="portal-empty">No actual destination results are available for this ranking.</div>}
    </>
  );
}

function AboutPage() {
  const modules = [
    ["01", "Data preparation", "ETL, validation and source lineage"],
    ["02", "Warehouse", "SQLite staging and dimensional data"],
    ["03", "Analytics", "Star and Snowflake schemas with five OLAP operations"],
    ["04", "Exploration", "Interactive 3D cube and schema explorer"],
  ];
  return (
    <>
      <section className="portal-about-hero"><p className="eyebrow">COLLEGE PROJECT · TOURISM DATA INTELLIGENCE</p><h1>TravelIntel</h1><p>A tourism analytics project that brings multiple data sources into a validated warehouse, then makes the results explorable through dimensional models and interactive OLAP.</p></section>
      <div className="portal-content-grid portal-about-grid">
        <article className="portal-panel"><p className="eyebrow">PROJECT OBJECTIVES</p><h3>From raw sources to useful insight.</h3><ul className="portal-objectives"><li>Prepare and preserve source data through a traceable ETL pipeline.</li><li>Model verified relationships in Star and Snowflake schemas.</li><li>Enable roll-up, drill-down, slice, dice and pivot analysis.</li><li>Present findings without inventing unsupported cross-source joins.</li></ul></article>
        <article className="portal-panel"><p className="eyebrow">TECHNOLOGIES</p><h3>Built with existing project tools.</h3><div className="portal-tech-tags"><span>React</span><span>Vite</span><span>Three.js</span><span>Python</span><span>SQLite</span><span>OLAP</span></div><p className="portal-footnote">Analytics continue to use read-only OLAP queries. Customer planning requests are stored separately in the central SQLite booking table and do not change ETL or analytical facts.</p></article>
      </div>
      <div className="portal-module-grid">{modules.map(([number, title, description]) => <article key={number}><b>{number}</b><h3>{title}</h3><p>{description}</p></article>)}</div>
    </>
  );
}

export default function PortalPages({ page, catalog, onNavigate }) {
  const [data, setData] = useState(EMPTY_DATA);
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    const jobs = [
      queryWarehouse("tourism_observation", ["fact_rows", "average_rating", "recorded_visitors", "average_cost", "average_sentiment_score"], ["location"]),
      queryWarehouse("hotel_booking", ["fact_rows", "canceled_bookings", "average_adr"], ["hotel_type"]),
      queryWarehouse("airbnb_review_boston", ["fact_rows", "comments_present"], []),
      queryWarehouse("airbnb_review_seattle", ["fact_rows", "comments_present"], []),
      queryWarehouse("airbnb_calendar_boston", ["fact_rows"], []),
      queryWarehouse("airbnb_calendar_seattle", ["fact_rows"], []),
    ];
    Promise.allSettled(jobs).then((results) => {
      if (!active) return;
      const nextErrors = {};
      const tourism = results[0].status === "fulfilled" ? results[0].value : (nextErrors.tourism = results[0].reason.message, []);
      const hotels = results[1].status === "fulfilled" ? results[1].value : (nextErrors.hotels = results[1].reason.message, []);
      const boston = results[2].status === "fulfilled" ? results[2].value[0] : (nextErrors.reviews = results[2].reason.message, null);
      const seattle = results[3].status === "fulfilled" ? results[3].value[0] : (nextErrors.reviews = [nextErrors.reviews, results[3].reason.message].filter(Boolean).join(" · "), null);
      const bostonCalendar = results[4].status === "fulfilled" ? results[4].value[0] : (nextErrors.calendars = results[4].reason.message, null);
      const seattleCalendar = results[5].status === "fulfilled" ? results[5].value[0] : (nextErrors.calendars = [nextErrors.calendars, results[5].reason.message].filter(Boolean).join(" · "), null);
      setData({
        tourism,
        hotels,
        reviews: [boston && { ...boston, source: "Boston" }, seattle && { ...seattle, source: "Seattle" }].filter(Boolean),
        calendars: {
          ...(bostonCalendar ? { airbnb_calendar_boston: bostonCalendar.fact_rows } : {}),
          ...(seattleCalendar ? { airbnb_calendar_seattle: seattleCalendar.fact_rows } : {}),
        },
      });
      setErrors(nextErrors);
      setLoading(false);
    });
    return () => { active = false; };
  }, []);

  const pageTitles = {
    dashboard: "Dashboard",
    warehouse: "Data warehouse",
    tourism: "Tourism analytics",
    recommendations: "Travel recommendations",
    about: "About TravelIntel",
  };
  return (
    <section className="portal-page">
      <div className="portal-page-topline"><span>TRAVELINTEL / {pageTitles[page]?.toUpperCase()}</span><span>LIVE · READ-ONLY DATA</span></div>
      {page === "dashboard" && <Dashboard data={data} errors={errors} loading={loading} onNavigate={onNavigate} />}
      {page === "warehouse" && <WarehousePage catalog={catalog} data={data} errors={errors} loading={loading} />}
      {page === "tourism" && <TourismPage data={data} errors={errors} loading={loading} />}
      {page === "recommendations" && <RecommendationsPage data={data} errors={errors} loading={loading} />}
      {page === "about" && <AboutPage />}
    </section>
  );
}
