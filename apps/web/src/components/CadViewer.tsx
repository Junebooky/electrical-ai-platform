"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NormalizedDrawing } from "@/types/cad";
import { ZoomIn, ZoomOut, Maximize2, PlusCircle } from "lucide-react";

export interface ManualMarker {
  id: string;
  x: number;
  y: number;
  item_code: string;
  item_name?: string | null;
  note?: string;
}

interface CadViewerProps {
  drawing: NormalizedDrawing;
  selectedObjectId: string | null;
  highlightedObjectIds?: string[];
  hiddenLayers: Set<string>;
  onSelectObject: (objectId: string | null) => void;
  isAddManualMode?: boolean;
  onAddManualPoint?: (x: number, y: number) => void;
  onOutOfBoundsClick?: (x: number, y: number, maxX: number, maxY: number) => void;
  manualMarkers?: ManualMarker[];
  imageUrl?: string | null;
}

export function CadViewer({
  drawing,
  selectedObjectId,
  highlightedObjectIds = [],
  hiddenLayers,
  onSelectObject,
  isAddManualMode = false,
  onAddManualPoint,
  onOutOfBoundsClick,
  manualMarkers = [],
  imageUrl,
}: CadViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const isImage = drawing.source_type === "IMAGE" || drawing.dxf?.units_name === "PIXEL";
  const imgWidth = drawing.dimensions?.width || (drawing.extents ? drawing.extents.max[0] : 1000);
  const imgHeight = drawing.dimensions?.height || (drawing.extents ? drawing.extents.max[1] : 800);

  // Viewport transform state: [scale, tx, ty]
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [mouseWorld, setMouseWorld] = useState({ x: 0, y: 0 });

  // Compute extents
  const extents = useMemo(() => {
    if (isImage) {
      return { min: [0, 0] as [number, number], max: [imgWidth, imgHeight] as [number, number] };
    }
    if (drawing.extents) return drawing.extents;
    return { min: [0, 0] as [number, number], max: [1000, 1000] as [number, number] };
  }, [drawing.extents, isImage, imgWidth, imgHeight]);

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

    setScale(s);
    if (isImage) {
      setPan({
        x: w / 2 - cx * s,
        y: h / 2 - cy * s,
      });
    } else {
      setPan({
        x: w / 2 - cx * s,
        y: h / 2 + cy * s,
      });
    }
  }, [extents, isImage]);

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
    const worldX = (mouseX - pan.x) / scale;
    const worldY = isImage ? (mouseY - pan.y) / scale : (pan.y - mouseY) / scale;

    const newPanX = mouseX - worldX * newScale;
    const newPanY = isImage ? mouseY - worldY * newScale : mouseY + worldY * newScale;

    setScale(newScale);
    setPan({ x: newPanX, y: newPanY });
  };

  const dragStartPos = useRef<{ clientX: number; clientY: number } | null>(null);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button === 0) {
      const target = e.target as HTMLElement | SVGElement | null;
      if (target?.closest("button, .viewer-controls, [data-interactive='true']")) {
        return;
      }
      dragStartPos.current = { clientX: e.clientX, clientY: e.clientY };
      setIsDragging(true);
      setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const wx = (mouseX - pan.x) / scale;
    const wy = isImage ? (mouseY - pan.y) / scale : (pan.y - mouseY) / scale;
    setMouseWorld({
      x: isImage ? Math.round(wx) : Math.round(wx * 100) / 100,
      y: isImage ? Math.round(wy) : Math.round(wy * 100) / 100,
    });

    if (isDragging) {
      setPan({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    if (dragStartPos.current) {
      const dist = Math.hypot(
        e.clientX - dragStartPos.current.clientX,
        e.clientY - dragStartPos.current.clientY
      );
      // Pure click (distance < 6px) in manual add mode (FR-005, QA-DEF-03)
      if (isAddManualMode && dist < 6 && onAddManualPoint && containerRef.current) {
        const target = e.target as HTMLElement | SVGElement | null;
        const isToolbar = Boolean(target?.closest("button, .viewer-controls, [data-interactive='true']"));
        const isMarker = Boolean(target?.closest("g.cursor-pointer, .interactive-marker"));
        if (!isToolbar && !isMarker) {
          const rect = containerRef.current.getBoundingClientRect();
          const mouseX = e.clientX - rect.left;
          const mouseY = e.clientY - rect.top;
          const wx = (mouseX - pan.x) / scale;
          const wy = isImage ? (mouseY - pan.y) / scale : (pan.y - mouseY) / scale;

          if (isImage) {
            if (wx < 0 || wx > imgWidth || wy < 0 || wy > imgHeight) {
              onOutOfBoundsClick?.(wx, wy, imgWidth, imgHeight);
              setIsDragging(false);
              dragStartPos.current = null;
              return;
            }
          }

          onAddManualPoint(
            isImage ? Math.round(wx) : Math.round(wx * 100) / 100,
            isImage ? Math.round(wy) : Math.round(wy * 100) / 100
          );
        }
      }
    }
    setIsDragging(false);
    dragStartPos.current = null;
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
      <div className="viewer-controls absolute top-4 left-4 z-20 flex items-center gap-1.5 p-1.5 bg-slate-900/90 backdrop-blur border border-slate-800 rounded-lg shadow-xl text-slate-300">
        <button
          onClick={(e) => {
            e.stopPropagation();
            setScale((s) => s * 1.3);
          }}
          onMouseDown={(e) => e.stopPropagation()}
          className="p-1.5 hover:bg-slate-800 hover:text-white rounded transition"
          title="줌 인"
        >
          <ZoomIn size={18} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setScale((s) => s / 1.3);
          }}
          onMouseDown={(e) => e.stopPropagation()}
          className="p-1.5 hover:bg-slate-800 hover:text-white rounded transition"
          title="줌 아웃"
        >
          <ZoomOut size={18} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            fitToScreen();
          }}
          onMouseDown={(e) => e.stopPropagation()}
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
          X: <b className="text-slate-200">{mouseWorld.x}</b>{isImage ? " px" : ""}
        </span>
        <span>
          Y: <b className="text-slate-200">{mouseWorld.y}</b>{isImage ? " px" : ""}
        </span>
        <span className="text-slate-500">|</span>
        <span>{isImage ? "IMAGE (픽셀 좌표계)" : drawing.dxf.units_name}</span>
        {isImage && isAddManualMode && (
          <span className={mouseWorld.x < 0 || mouseWorld.x > imgWidth || mouseWorld.y < 0 || mouseWorld.y > imgHeight ? "text-amber-400 font-semibold" : "text-emerald-400 font-semibold"}>
            {mouseWorld.x < 0 || mouseWorld.x > imgWidth || mouseWorld.y < 0 || mouseWorld.y > imgHeight ? "⚠ 도면 영역 밖 (추가 불가)" : "✓ 도면 내부"}
          </span>
        )}
      </div>

      {/* SVG Canvas */}
      <svg
        className="w-full h-full pointer-events-none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <g transform={`translate(${pan.x}, ${pan.y}) scale(${scale})`}>
          {/* Render Raster Image if Image Drawing */}
          {isImage && imageUrl && (
            <image
              href={imageUrl}
              x={0}
              y={0}
              width={imgWidth}
              height={imgHeight}
              preserveAspectRatio="none"
              className="pointer-events-none select-none"
            />
          )}

          {/* Render Vector Primitives (CAD lines, polylines) */}
          {!isImage &&
            visiblePrimitives.map((prim, idx) => {
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
                const h = prim.height || 10;
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
          {!isImage &&
            visibleObjects.map((obj) => {
              if (!obj.insert_point) return null;
              const [ix, iy] = obj.insert_point;
              const isSelected = obj.id === selectedObjectId;
              const isHighlighted = highlightedSet.has(obj.id);

              // Radius for clickable symbol target (strictly 16 screen pixels regardless of zoom or CAD units)
              const markerRadius = 16 / Math.max(scale, 1e-6);

              return (
                <g
                  key={obj.id}
                  transform={`translate(${ix}, ${-iy})`}
                  className="pointer-events-auto cursor-pointer interactive-marker"
                  onMouseDown={(e) => e.stopPropagation()}
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

          {/* Interactive Manual Markers (Manually Added Objects) */}
          {manualMarkers.map((m) => {
            const isSelected = m.id === selectedObjectId;
            const isHighlighted = highlightedSet.has(m.id);
            const mRadius = 16 / Math.max(scale, 1e-6);
            const markerY = isImage ? m.y : -m.y;

            return (
              <g
                key={m.id}
                data-testid={`manual-marker-${m.id}`}
                transform={`translate(${m.x}, ${markerY})`}
                className="pointer-events-auto cursor-pointer interactive-marker"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectObject(m.id);
                }}
              >
                {isSelected && (
                  <circle
                    cx={0}
                    cy={0}
                    r={mRadius * 1.6}
                    fill="none"
                    stroke="#38bdf8"
                    strokeWidth={4 / scale}
                    className="animate-pulse"
                  />
                )}
                <rect
                  x={-mRadius * 0.75}
                  y={-mRadius * 0.75}
                  width={mRadius * 1.5}
                  height={mRadius * 1.5}
                  transform="rotate(45)"
                  fill={
                    isSelected
                      ? "rgba(56, 189, 248, 0.5)"
                      : isHighlighted
                      ? "rgba(245, 158, 11, 0.6)"
                      : "rgba(245, 158, 11, 0.35)"
                  }
                  stroke="#f59e0b"
                  strokeWidth={2 / scale}
                />
                {/* Short Item Code Label overlay for easy identification */}
                <text
                  x={0}
                  y={mRadius * 1.5}
                  textAnchor="middle"
                  fontSize={10 / Math.max(scale, 1e-6)}
                  fill="#fde68a"
                  className="font-mono font-semibold pointer-events-none select-none"
                  style={{ textShadow: "0 1px 3px rgba(0,0,0,0.8)" }}
                >
                  {m.item_code}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
