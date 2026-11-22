import React, { useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Edges, Html, OrbitControls } from "@react-three/drei";
import * as THREE from "three";

const DIMENSION_COLORS = [
  "#54d2ff",
  "#a58bff",
  "#38d9a9",
  "#ffbd66",
  "#ff7d9d",
  "#80aaff",
  "#d1e56a",
  "#f28cff",
];
const BAR_COLORS = ["#55d5ff", "#9888ff", "#31d6ab", "#ffae62", "#fc7598"];

function DimensionBadge({ dimension, index, active, onSelect }) {
  const mesh = useRef();
  const angle = (index / Math.max(1, dimension.count)) * Math.PI * 2 - Math.PI / 2;
  const radius = 1.18;
  const color = DIMENSION_COLORS[index % DIMENSION_COLORS.length];

  useFrame((_, delta) => {
    if (!mesh.current) return;
    const target = active ? 1.14 : 1;
    mesh.current.scale.lerp(
      new THREE.Vector3(target, target, target),
      1 - Math.exp(-delta * 9),
    );
  });

  return (
    <group
      position={[Math.cos(angle) * radius, Math.sin(angle) * radius, 0.48]}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(dimension.id);
      }}
    >
      <mesh ref={mesh}>
        <boxGeometry args={[0.78, 0.28, 0.1]} />
        <meshStandardMaterial
          color={active ? color : "#172b40"}
          emissive={color}
          emissiveIntensity={active ? 0.42 : 0.08}
          metalness={0.28}
          roughness={0.4}
        />
        <Edges color={color} threshold={15} />
      </mesh>
      <Html
        position={[0, 0, 0.07]}
        transform
        distanceFactor={5}
        pointerEvents="none"
      >
        <span className="cube-label">{dimension.label}</span>
      </Html>
    </group>
  );
}

function CubeBars({ rows, operation, metric, rowDimension }) {
  const series = useMemo(() => {
    return rows.slice(0, 10).map((row, index) => {
      const value =
        operation === "pivot"
          ? Object.entries(row)
              .filter(([key, cell]) => key !== rowDimension && Number.isFinite(Number(cell)))
              .reduce((sum, [, cell]) => sum + Number(cell || 0), 0)
          : Number(row[metric] ?? 0);
      const label =
        row[rowDimension] ??
        Object.entries(row).find(([key]) => key !== metric)?.[1] ??
        `Result ${index + 1}`;
      return { label: String(label), value: Number.isFinite(value) ? value : 0 };
    });
  }, [rows, operation, metric, rowDimension]);

  const maxValue = Math.max(1, ...series.map((item) => item.value));
  const [hovered, setHovered] = useState(null);

  return (
    <group position={[0, -0.02, 0.08]}>
      {series.map((item, index) => {
        const height = 0.12 + (item.value / maxValue) * 0.88;
        const x = series.length === 1 ? 0 : -0.86 + (index * 1.72) / (series.length - 1);
        const color = BAR_COLORS[index % BAR_COLORS.length];
        return (
          <group key={`${item.label}-${index}`} position={[x, -0.45, 0.2]}>
            <AnimatedBar
              height={height}
              color={color}
              label={item.label}
              value={item.value}
              onHover={setHovered}
            />
          </group>
        );
      })}
      {hovered && (
        <Html position={[0, 1.22, 0.7]} center>
          <div className="cube-tooltip">
            <strong>{hovered.label}</strong>
            <span>{hovered.value.toLocaleString()} actual</span>
          </div>
        </Html>
      )}
    </group>
  );
}

function AnimatedBar({ height, color, label, value, onHover }) {
  const mesh = useRef();
  const currentHeight = useRef(0.01);
  useFrame((_, delta) => {
    currentHeight.current = THREE.MathUtils.damp(
      currentHeight.current,
      height,
      7,
      delta,
    );
    if (mesh.current) {
      mesh.current.scale.y = currentHeight.current;
      mesh.current.position.y = currentHeight.current / 2;
    }
  });

  return (
    <mesh
      ref={mesh}
      onPointerOver={(event) => {
        event.stopPropagation();
        onHover({ label, value });
      }}
      onPointerOut={() => onHover(null)}
    >
      <boxGeometry args={[0.105, 1, 0.13]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.24}
        metalness={0.2}
        roughness={0.32}
      />
    </mesh>
  );
}

function Scene({
  dimensions,
  activeDimensions,
  onSelectDimension,
  rows,
  operation,
  metric,
  rowDimension,
  controlsRef,
}) {
  return (
    <>
      <color attach="background" args={["#0c1828"]} />
      <ambientLight intensity={1.35} />
      <directionalLight position={[4, 5, 6]} intensity={2.2} color="#c7e9ff" />
      <pointLight position={[-3, -1, 3]} intensity={30} color="#3977ff" />
      <mesh>
        <boxGeometry args={[2.42, 2.42, 2.42]} />
        <meshPhysicalMaterial
          color="#287da1"
          transparent
          opacity={0.055}
          roughness={0.16}
          metalness={0.12}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
        <Edges color="#5bcdf5" threshold={10} />
      </mesh>
      {dimensions.map((dimension, index) => (
        <DimensionBadge
          key={dimension.id}
          dimension={{ ...dimension, count: dimensions.length }}
          index={index}
          active={activeDimensions.includes(dimension.id)}
          onSelect={onSelectDimension}
        />
      ))}
      <CubeBars
        rows={rows}
        operation={operation}
        metric={metric}
        rowDimension={rowDimension}
      />
      <OrbitControls
        ref={controlsRef}
        enablePan={false}
        enableDamping
        dampingFactor={0.075}
        minDistance={3.2}
        maxDistance={8}
        rotateSpeed={0.72}
      />
    </>
  );
}

export default function AnalyticsCube({ enabled = true, ...props }) {
  return (
    <div className="cube-stage" data-testid="cube-stage">
      <Canvas
        frameloop={enabled ? "always" : "never"}
        camera={{ position: [3.8, 2.8, 4.7], fov: 44 }}
        dpr={[1, 1.8]}
        gl={{ antialias: true, alpha: false }}
      >
        <Scene {...props} />
      </Canvas>
      <div className="cube-controls-hint">
        <span><i className="hint-dot drag" /> drag to rotate</span>
        <span><i className="hint-dot zoom" /> scroll to zoom</span>
      </div>
    </div>
  );
}
