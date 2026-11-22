import React, { useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { Edges, Line, OrbitControls } from "@react-three/drei";
import * as THREE from "three";

const EMPTY_SCHEMA = { tables: [], relationships: [] };

async function requestJson(url) {
  const response = await fetch(url);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`The API returned an invalid response (${response.status}).`);
  }
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status}).`);
  }
  return payload;
}

function getSharedRequest(cache, key, url) {
  const cached = cache.get(key);
  if (cached) return cached;

  const request = requestJson(url).catch((error) => {
    if (cache.get(key) === request) cache.delete(key);
    throw error;
  });
  cache.set(key, request);
  return request;
}

function arrangeTables(tables) {
  const facts = tables.filter((table) => table.kind === "fact");
  const dimensions = tables.filter((table) => table.kind === "dimension");
  const positions = new Map();

  const ring = (items, radius, phase) => {
    items.forEach((table, index) => {
      const angle = (index / Math.max(1, items.length)) * Math.PI * 2 + phase;
      positions.set(table.name, [
        Math.cos(angle) * radius,
        Math.sin(angle) * radius,
        ((index % 3) - 1) * 0.12,
      ]);
    });
  };

  ring(facts, 2.75, -Math.PI / 2);
  ring(dimensions, 3.8, -Math.PI / 2);
  return positions;
}

function SchemaEdge({ relationship, positions }) {
  const source = positions.get(relationship.from_table);
  const target = positions.get(relationship.to_table);
  if (!source || !target) return null;
  const color = relationship.kind === "hierarchy" ? "#b29aff" : "#6c8ba7";
  return (
    <Line
      points={[source, target]}
      color={color}
      lineWidth={relationship.kind === "hierarchy" ? 1.8 : 1}
      transparent
      opacity={relationship.kind === "hierarchy" ? 0.9 : 0.58}
    />
  );
}

function makeTableLabelTexture(table) {
  const canvas = document.createElement("canvas");
  canvas.width = 1024;
  canvas.height = 144;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Unable to create the schema label canvas.");

  const color = table.kind === "fact" ? "#f3a15e" : "#32b49a";
  context.fillStyle = "rgba(9, 24, 39, 0.94)";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = color;
  context.lineWidth = 4;
  context.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "#edf7ff";
  context.font = "600 42px Consolas, monospace";
  context.fillText(table.name, canvas.width / 2, 48, canvas.width - 20);
  context.fillStyle = "#9ab0c3";
  context.font = "30px Segoe UI, sans-serif";
  context.fillText(
    `${table.columns.length} columns · ${table.row_count.toLocaleString()} rows`,
    canvas.width / 2,
    104,
    canvas.width - 20,
  );

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function SchemaNodeLabel({ table }) {
  const texture = useMemo(
    () => makeTableLabelTexture(table),
    [table.kind, table.name, table.columns.length, table.row_count],
  );
  useEffect(() => () => texture.dispose(), [texture]);

  return (
    <mesh position={[0, 0.02, 0.155]} renderOrder={1}>
      <planeGeometry args={[2.4, 0.42]} />
      <meshBasicMaterial
        map={texture}
        transparent
        side={THREE.DoubleSide}
        toneMapped={false}
      />
    </mesh>
  );
}

function SchemaNode({ table, position, selected, onSelect }) {
  const color = table.kind === "fact" ? "#f3a15e" : "#32b49a";
  return (
    <group
      position={position}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(table.name);
      }}
    >
      <mesh>
        <boxGeometry args={[2.6, 1, 0.28]} />
        <meshStandardMaterial
          color={selected ? color : "#10283b"}
          emissive={color}
          emissiveIntensity={selected ? 0.3 : 0.08}
          metalness={0.22}
          roughness={0.38}
        />
        <Edges color={color} threshold={12} />
      </mesh>
      <SchemaNodeLabel table={table} />
    </group>
  );
}

function SchemaScene({ catalog, selectedTable, onSelect, controlsRef }) {
  const positions = useMemo(() => arrangeTables(catalog.tables), [catalog.tables]);
  return (
    <>
      <color attach="background" args={["#0c1828"]} />
      <ambientLight intensity={1.3} />
      <directionalLight position={[4, 5, 6]} intensity={1.8} color="#c7e9ff" />
      <pointLight position={[-3, -1, 3]} intensity={18} color="#3977ff" />
      {catalog.relationships.map((relationship, index) => (
        <SchemaEdge
          key={`${relationship.from_table}-${relationship.to_table}-${index}`}
          relationship={relationship}
          positions={positions}
        />
      ))}
      {catalog.tables.map((table) => (
        <SchemaNode
          key={table.name}
          table={table}
          position={positions.get(table.name)}
          selected={selectedTable === table.name}
          onSelect={onSelect}
        />
      ))}
      <OrbitControls
        ref={controlsRef}
        enablePan
        enableDamping
        dampingFactor={0.08}
        minDistance={6}
        maxDistance={20}
        target={[0, 0, 0]}
      />
    </>
  );
}

function ColumnList({ table }) {
  const foreignKeyColumns = new Set(
    table.foreign_keys.flatMap((foreignKey) =>
      foreignKey.columns.map((column) => column.from),
    ),
  );
  return (
    <div className="schema-column-list">
      {table.columns.map((column) => (
        <div className="schema-column" key={column.name}>
          <code>{column.name}</code>
          <span>{column.type || "—"}</span>
          <div className="schema-key-tags">
            {column.primary_key_order > 0 && <b className="key-tag primary">PK</b>}
            {foreignKeyColumns.has(column.name) && <b className="key-tag foreign">FK</b>}
            {column.not_null && <small>NOT NULL</small>}
          </div>
        </div>
      ))}
    </div>
  );
}

function SampleRows({ table }) {
  const columns = table.columns.map((column) => column.name);
  if (!table.rows.length) {
    return <p className="schema-empty">This table currently has no records.</p>;
  }
  return (
    <div className="schema-sample-scroll">
      <table className="schema-sample-table">
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {table.rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column} title={row[column] == null ? "" : String(row[column])}>
                  {row[column] == null ? "—" : String(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SchemaExplorer({ enabled, schema, onSchemaChange }) {
  const [catalogs, setCatalogs] = useState({});
  const [selectedTable, setSelectedTable] = useState("");
  const [details, setDetails] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const controlsRef = useRef();
  const catalogRequests = useRef(new Map());
  const detailRequests = useRef(new Map());
  const catalog = catalogs[schema] ?? null;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setDetails(null);
    const query = new URLSearchParams({ schema });
    getSharedRequest(
      catalogRequests.current,
      schema,
      `/api/schema?${query}`,
    )
      .then((data) => {
        if (!active) return;
        setCatalogs((current) => ({ ...current, [schema]: data }));
        setSelectedTable((current) => (
          data.tables.some((table) => table.name === current)
            ? current
            : data.tables.find((table) => table.kind === "fact")?.name ??
              data.tables[0]?.name ??
              ""
        ));
      })
      .catch((cause) => {
        if (active) setError(cause.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [schema]);

  useEffect(() => {
    if (!selectedTable || !selectedTable.startsWith(`${schema}_`)) {
      setDetails(null);
      setDetailsLoading(false);
      return undefined;
    }
    let active = true;
    setDetails(null);
    setDetailsLoading(true);
    setError("");
    const query = new URLSearchParams({ schema, table: selectedTable });
    getSharedRequest(
      detailRequests.current,
      `${schema}:${selectedTable}`,
      `/api/schema-table?${query}`,
    )
      .then((data) => {
        if (active) setDetails(data);
      })
      .catch((cause) => {
        if (active) setError(cause.message);
      })
      .finally(() => {
        if (active) setDetailsLoading(false);
      });
    return () => { active = false; };
  }, [schema, selectedTable]);

  const hierarchies = useMemo(
    () => catalog?.relationships.filter((relationship) => relationship.kind === "hierarchy") ?? [],
    [catalog],
  );
  const modelTables = new Set(catalog?.tables.map((table) => table.name) ?? []);

  return (
    <section className="schema-page">
      <div className="page-heading schema-page-heading">
        <div>
          <p className="eyebrow">DATABASE STRUCTURE · STAGE 08</p>
          <h1>Schema explorer</h1>
          <p className="page-subtitle">
            Explore verified tables, keys, and relationships from the read-only SQLite warehouse.
          </p>
        </div>
        <div className="schema-switch" role="group" aria-label="Schema model">
          {["star", "snowflake"].map((item) => (
            <button
              key={item}
              className={schema === item ? "active" : ""}
              onClick={() => onSchemaChange(item)}
            >
              {item === "star" ? "Star schema" : "Snowflake"}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="notice error-notice" role="alert">{error}</div>}

      <div className="schema-workspace">
        <article className="panel schema-visual-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">LIVE SQLITE MODEL</p>
              <h2>{schema === "star" ? "Star schema" : "Snowflake schema"} · {catalog?.tables.length ?? "…"} tables</h2>
            </div>
            <button
              className="icon-button"
              onClick={() => controlsRef.current?.reset()}
              aria-label="Reset camera"
              title="Reset camera"
            >
              <span className="reset-icon">↺</span>
            </button>
          </div>
          <div className="schema-canvas-stage" data-testid="schema-canvas">
            <Canvas
              frameloop={enabled ? "always" : "never"}
              camera={{ position: [0, 0, 14.5], fov: 44 }}
              dpr={[1, 1.6]}
              gl={{ antialias: true, alpha: false }}
            >
              <SchemaScene
                catalog={catalog ?? EMPTY_SCHEMA}
                selectedTable={selectedTable}
                onSelect={setSelectedTable}
                controlsRef={controlsRef}
              />
            </Canvas>
            {loading && <div className="schema-canvas-message">Reading SQLite schema…</div>}
            {!loading && catalog && catalog.tables.length === 0 && (
              <div className="schema-canvas-message">No tables found for this schema.</div>
            )}
            <div className="cube-controls-hint">
              <span><i className="hint-dot drag" /> drag to rotate</span>
              <span><i className="hint-dot zoom" /> scroll to zoom</span>
              <span><i className="hint-dot pan" /> right-drag to pan</span>
            </div>
          </div>
          <div className="schema-legend">
            <span><i className="legend-fact" /> Fact table</span>
            <span><i className="legend-dimension" /> Dimension table</span>
            <span><i className="legend-relationship" /> Foreign-key relationship</span>
            {schema === "snowflake" && <span><i className="legend-hierarchy" /> Dimension hierarchy</span>}
          </div>
          <p className="schema-explanation">
            {schema === "star"
              ? `${(catalog?.tables.filter((table) => table.kind === "fact") ?? []).length} actual fact tables sit inside the dimension ring. Connectors are declared SQLite foreign keys; ETL lineage keys are listed in table details.`
              : `Snowflake dimensions are normalized into linked tables. ${hierarchies.length} dimension-to-dimension foreign-key relationships are highlighted.`}
          </p>
        </article>

        <aside className="panel schema-details-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">TABLE INSPECTOR</p>
              <h2>{details?.name ?? (loading ? "Loading table…" : "Select a table")}</h2>
            </div>
            {details && <span className={`table-kind-badge ${details.kind}`}>{details.kind}</span>}
          </div>
          {catalog && (
            <label className="field schema-table-select">
              <span>Inspect table</span>
              <select
                aria-label="Inspect table"
                value={selectedTable}
                onChange={(event) => setSelectedTable(event.target.value)}
              >
                {catalog.tables.map((table) => (
                  <option key={table.name} value={table.name}>{table.name}</option>
                ))}
              </select>
            </label>
          )}
          {detailsLoading && <p className="schema-empty">Loading table details…</p>}
          {!detailsLoading && catalog && selectedTable && !details && !error && (
            <p className="schema-empty">No table details are available.</p>
          )}
          {details && (
            <>
              <div className="schema-table-stats">
                <span><b>{details.row_count.toLocaleString()}</b> records</span>
                <span><b>{details.columns.length}</b> columns</span>
              </div>
              <h3 className="schema-section-title">Columns and keys</h3>
              <ColumnList table={details} />
              <h3 className="schema-section-title">Foreign-key references</h3>
              {details.foreign_keys.length ? (
                <div className="schema-fk-list">
                  {details.foreign_keys.map((foreignKey, index) => (
                    <div className="schema-fk-item" key={`${foreignKey.table}-${index}`}>
                      <code>{foreignKey.columns.map((column) => column.from).join(", ")}</code>
                      <span>→</span>
                      <strong>{foreignKey.table}</strong>
                      {!modelTables.has(foreignKey.table) && <small>ETL lineage</small>}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="schema-empty">No foreign keys declared.</p>
              )}
              <h3 className="schema-section-title">Sample records · first 5</h3>
              <SampleRows table={details} />
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
