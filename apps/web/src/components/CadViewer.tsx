"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NormalizedDrawing } from "@/types/cad";
import { ZoomIn, ZoomOut, Maximize2, PlusCircle } from "lucide-react";

interface CadViewerProps {
  drawing: NormalizedDrawing;
  selectedObjectId: string | null;
  highlightedObjectIds?: string[];
  hiddenLayers: Set<string>;
  onSelectObject: (objectId: string | null) => void;
  isAddManualMode?: boolean;
  onAddManualPoint?: (x: number, y: number) => void;
}

export function CadViewer({
  drawing,
  selectedObjectId,
  highlightedObjectIds = [],
  hiddenLayers,
  onSelectObject,
  isAddManualMode = false,
  onAddManualPoint,
}: CadViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Viewport transform state: [scale, tx, ty]
  // In CAD, +Y is UP, but in SVG +Y is DOWN. We invert Y coordinates in world space.
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [mouseWorld, setMouseWorld] = useState({ x: 0, y: 0 });

  // Compute extents
  const extents = useMemo(() => {
    if (drawing.extents) return drawing.extents;
    return { min: [0, 0] as [number, number], max: [1000, 1000] as [number, number] };
  }, [drawing.extents]);

  const fitToScreen = useCallback(() => {
    if (!containerRef.current) return;
    const { clientWidth: w, clientHeight: h } = containerRef.current;
    if (w <= 0 || h <= 0) return;

    const [minX, minY] = extents.min;
    const [maxX, maxY] = extents.max;
    const dx = Math.max(maxX - minX, 100);
    const dy = Math.max(maxY - minY, 100);

    const padding = 60;
    const sx = (w - padding * 2) / dx;
    const sy = (h - padding * 2) / dy;
    const s = Math.min(sx, sy, 5.0);

    // Center of drawing in world coords
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;

    // We map world (cx, cy) to screen (w/2, h/2)
    // screenX = w/2 + (worldX - cx) * s
    // screenY = h/2 - (worldY - cy) * s  (inverted Y)
    setScale(s);
    setPan({
      x: w / 2 - cx * s,
      y: h / 2 + cy * s,
    });
  }, [extents]);

  useEffect(() => {
    fitToScreen();
  }, [fitToScreen]);

  // Handle zoom with mouse wheel
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const zoomFactor = e.deltaY < 0 ? 1.2 : 0.833;
    const newScale = Math.max(Math.min(scale * zoomFactor, 200), 0.001);

    // Zoom centered on cursor
    // mouseX = pan.x + worldX * scale => worldX = (mouseX - pan.x) / scale
    const worldX = (mouseX - pan.x) / scale;
    const worldY = (pan.y - mouseY) / scale;

    const newPanX = mouseX - worldX * newScale;
    const newPanY = mouseY + worldY * newScale;

    setScale(newScale);
    setPan({ x: newPanX, y: newPanY });
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button === 0) {
      if (isAddManualMode) {
        if (onAddManualPoint) {
          onAddManualPoint(mouseWorld.x, mouseWorld.y);
        }
        return;
      }
      setIsDragging(true);
      setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    // Invert screen to CAD world coordinates
    const wx = (mouseX - pan.x) / scale;
    const wy = (pan.y - mouseY) / scale;
    setMouseWorld({ x: Math.round(wx * 100) / 100, y: Math.round(wy * 100) / 100 });

    if (isDragging) {
      setPan({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const highlightedSet = useMemo(() => new Set(highlightedObjectIds), [highlightedObjectIds]);

  // Filter visible primitives
  const visiblePrimitives = useMemo(() => {
    return drawing.primitives.filter((p) => !hiddenLayers.has(p.layer));
  }, [drawing.primitives, hiddenLayers]);

  // Filter visible CAD count objects (INSERT markers)
  const visibleObjects = useMemo(() => {
    return drawing.objects.filter(
      (o) => o.entity_type === "INSERT" && !hiddenLayers.has(o.layer)
    );
  }, [drawing.objects, hiddenLayers]);

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-full overflow-hidden bg-slate-950 select-none ${
        isAddManualMode ? "cursor-crosshair" : isDragging ? "cursor-grabbing" : "cursor-grab"
      }`}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {/* CAD Floating Toolbar */}
      <div className="absolute top-4 left-4 z-20 flex items-center gap-1.5 p-1.5 bg-slate-900/90 backdrop-blur border border-slate-800 rounded-lg shadow-xl text-slate-300">
        <button
          onClick={() => setScale((s) => s * 1.3)}
          className="p-1.5 hover:bg-slate-800 hover:text-white rounded transition"
          title="줌 인"
        >
          <ZoomIn size={18} />
        </button>
        <button
          onClick={() => setScale((s) => s / 1.3)}
          className="p-1.5 hover:bg-slate-800 hover:text-white rounded transition"
          title="줌 아웃"
        >
          <ZoomOut size={18} />
        </button>
        <button
          onClick={fitToScreen}
          className="p-1.5 hover:bg-slate-800 hover:text-white rounded transition"
          title="화면 맞춤"
        >
          <Maximize2 size={18} />
        </button>
        <div className="w-[1px] h-4 bg-slate-800 my-auto" />
        <div className="px-2 text-xs font-mono text-slate-400">
          {(scale * 100).toFixed(0)}%
        </div>
      </div>

      {/* Mode Banner if in Manual Add */}
      {isAddManualMode && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-4 py-2 bg-amber-500/90 text-slate-950 font-medium rounded-full shadow-lg text-sm animate-pulse">
          <PlusCircle size={16} />
          <span>도면을 클릭하여 누락 기구 좌표를 지정하세요</span>
        </div>
      )}

      {/* Coordinate & Unit status overlay at bottom */}
      <div className="absolute bottom-3 left-4 z-20 flex items-center gap-4 text-xs font-mono text-slate-400 bg-slate-900/80 px-3 py-1.5 rounded border border-slate-800 pointer-events-none">
        <span>
          X: <b className="text-slate-200">{mouseWorld.x}</b>
        </span>
        <span>
          Y: <b className="text-slate-200">{mouseWorld.y}</b>
        </span>
        <span className="text-slate-500">|</span>
        <span>{drawing.dxf.units_name}</span>
      </div>

      {/* SVG Canvas */}
      <svg
        className="w-full h-full pointer-events-none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <g transform={`translate(${pan.x}, ${pan.y}) scale(${scale})`}>
          {/* Render Vector Primitives (CAD lines, polylines) */}
          {visiblePrimitives.map((prim, idx) => {
            if (prim.kind === "polyline") {
              if (prim.points.length === 0) return null;
              if (prim.points.length === 1) {
                const [px, py] = prim.points[0];
                return (
                  <circle
                    key={idx}
                    cx={px}
                    cy={-py}
                    r={2 / scale}
                    fill={prim.color || "#94a3b8"}
                  />
                );
              }
              const d = prim.points
                .map((pt, i) => `${i === 0 ? "M" : "L"} ${pt[0]} ${-pt[1]}`)
                .join(" ");
              return (
                <path
                  key={idx}
                  d={prim.closed ? `${d} Z` : d}
                  fill="none"
                  stroke={prim.color || "#64748b"}
                  strokeWidth={1 / scale}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                />
              );
            }
            if (prim.kind === "text" && prim.text && prim.points.length > 0) {
              const [tx, ty] = prim.points[0];
              const h = (prim.height || 10);
              return (
                <text
                  key={idx}
                  x={tx}
                  y={-ty}
                  fontSize={h}
                  fill={prim.color || "#cbd5e1"}
                  transform={
                    prim.rotation_deg
                      ? `rotate(${-prim.rotation_deg}, ${tx}, ${-ty})`
                      : undefined
                  }
                  style={{
                    fontFamily: "monospace",
                    pointerEvents: "none",
                  }}
                >
                  {prim.text}
                </text>
              );
            }
            return null;
          })}

          {/* Interactive Block Markers (Clickable CAD Objects) */}
          {visibleObjects.map((obj) => {
            if (!obj.insert_point) return null;
            const [ix, iy] = obj.insert_point;
            const isSelected = obj.id === selectedObjectId;
            const isHighlighted = highlightedSet.has(obj.id);

            // Radius for clickable symbol target
            const markerRadius = Math.max(120, 16 / scale);

            return (
              <g
                key={obj.id}
                transform={`translate(${ix}, ${-iy})`}
                className="pointer-events-auto cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectObject(obj.id);
                }}
              >
                {/* Outer Glow for Selected / Highlighted */}
                {isSelected && (
                  <circle
                    cx={0}
                    cy={0}
                    r={markerRadius * 1.5}
                    fill="none"
                    stroke="#38bdf8"
                    strokeWidth={4 / scale}
                    className="animate-pulse"
                  />
                )}
                {isHighlighted && !isSelected && (
                  <circle
                    cx={0}
                    cy={0}
                    r={markerRadius * 1.3}
                    fill="none"
                    stroke="#f59e0b"
                    strokeWidth={2 / scale}
                    strokeDasharray={`${4 / scale},${4 / scale}`}
                  />
                )}

                {/* Interactive Hit Area Circle */}
                <circle
                  cx={0}
                  cy={0}
                  r={markerRadius}
                  fill={
                    isSelected
                      ? "rgba(56, 189, 248, 0.35)"
                      : isHighlighted
                      ? "rgba(245, 158, 11, 0.25)"
                      : "rgba(148, 163, 184, 0.08)"
                  }
                  stroke={
                    isSelected
                      ? "#38bdf8"
                      : isHighlighted
                      ? "#f59e0b"
                      : "rgba(148, 163, 184, 0.3)"
                  }
                  strokeWidth={1.5 / scale}
                />
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
