"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import {
  NormalizedDrawing,
  ProjectMetadata,
  ItemMappingRule,
  TakeoffResult,
  SourceObject,
  TakeoffEvidenceRow,
} from "@/types/cad";
import { CadViewer } from "@/components/CadViewer";
import { MappingPanel } from "@/components/MappingPanel";
import { TakeoffTable } from "@/components/TakeoffTable";
import { ReviewDrawer } from "@/components/ReviewDrawer";
import { WarningBanner } from "@/components/WarningBanner";
import {
  Upload,
  Layers,
  Plus,
  Cpu,
  Eye,
  EyeOff,
  AlertCircle,
  TableProperties,
  Tags,
} from "lucide-react";

export default function WorkspacePage() {
  const [projects, setProjects] = useState<ProjectMetadata[]>([]);
  const [currentProject, setCurrentProject] = useState<ProjectMetadata | null>(null);
  const [currentDrawing, setCurrentDrawing] = useState<NormalizedDrawing | null>(null);
  const [mappings, setMappings] = useState<ItemMappingRule[]>([]);
  const [takeoff, setTakeoff] = useState<TakeoffResult | null>(null);

  // UI state
  const [activeRightTab, setActiveRightTab] = useState<"takeoff" | "mapping" | "layers">("takeoff");
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [highlightedItemCode, setHighlightedItemCode] = useState<string | null>(null);
  const [hiddenLayers, setHiddenLayers] = useState<Set<string>>(new Set());
  const [isAddManualMode, setIsAddManualMode] = useState(false);

  // Async state
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Initialize: load or create default project
  useEffect(() => {
    async function init() {
      try {
        const list = await api.listProjects();
        setProjects(list);
        if (list.length > 0) {
          setCurrentProject(list[0]);
        } else {
          const created = await api.createProject("기본 전기공사 프로젝트");
          setProjects([created]);
          setCurrentProject(created);
        }
      } catch (err: unknown) {
        console.error("Failed to load projects", err);
      }
    }
    init();
  }, []);

  // When a drawing is loaded or mappings change, refresh takeoff
  const refreshTakeoff = async (projectId: string, drawingId: string) => {
    try {
      const res = await api.getTakeoff(projectId, drawingId);
      setTakeoff(res);
    } catch (err) {
      console.error("Failed to refresh takeoff", err);
    }
  };

  // Upload DXF handler
  const handleFileUpload = async (file: File) => {
    if (!currentProject) return;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const uploadRes = await api.uploadDrawing(currentProject.id, file);
      const drawingData = await api.getDrawing(currentProject.id, uploadRes.drawing_id);
      setCurrentDrawing(drawingData);

      // Load mappings
      const mappingRules = await api.getMappings(currentProject.id, uploadRes.drawing_id);
      setMappings(mappingRules);

      // Calculate initial takeoff
      await refreshTakeoff(currentProject.id, uploadRes.drawing_id);
      setSelectedObjectId(null);
      setHighlightedItemCode(null);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("파일 업로드 중 오류가 발생했습니다.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Save Mappings
  const handleSaveMappings = async (newMappings: ItemMappingRule[]) => {
    if (!currentProject || !currentDrawing) return;
    setIsSaving(true);
    try {
      await api.saveMappings(currentProject.id, currentDrawing.drawing_id, newMappings);
      setMappings(newMappings);
      await refreshTakeoff(currentProject.id, currentDrawing.drawing_id);
      setActiveRightTab("takeoff");
    } catch (err: unknown) {
      setErrorMessage("매핑 저장 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSaving(false);
    }
  };

  // Update Review (Exclude/Restore)
  const handleUpdateReview = async (
    objectId: string,
    inclusionStatus: "INCLUDED" | "EXCLUDED",
    mappedItemCode?: string,
    reason?: string
  ) => {
    if (!currentProject || !currentDrawing) return;
    setIsSaving(true);
    try {
      await api.saveReviews(currentProject.id, currentDrawing.drawing_id, [
        {
          source_object_id: objectId,
          inclusion_status: inclusionStatus,
          mapped_item_code: mappedItemCode,
          review_status: "REVIEWED",
          reason: reason || "",
        },
      ]);
      await refreshTakeoff(currentProject.id, currentDrawing.drawing_id);
    } catch (err: unknown) {
      setErrorMessage("검수 저장 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSaving(false);
    }
  };

  // Add Manual Object (on canvas click)
  const handleAddManualPoint = async (x: number, y: number) => {
    if (!currentProject || !currentDrawing) return;
    const itemCode = highlightedItemCode || "LIGHT";
    try {
      const manualId = `manual_${Date.now()}`;
      await api.addManualObject(currentProject.id, currentDrawing.drawing_id, {
        id: manualId,
        drawing_id: currentDrawing.drawing_id,
        x: Math.round(x * 100) / 100,
        y: Math.round(y * 100) / 100,
        item_code: itemCode,
        item_name: "수동 추가 기구",
        unit: "EA",
        note: "도면상 누락 기구 현장 확인 추가",
      });
      setIsAddManualMode(false);
      await refreshTakeoff(currentProject.id, currentDrawing.drawing_id);
    } catch (err: unknown) {
      setErrorMessage("수동 기구 추가 실패: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  // Toggle Layer visibility
  const toggleLayer = (layerName: string) => {
    setHiddenLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layerName)) next.delete(layerName);
      else next.add(layerName);
      return next;
    });
  };

  // Find selected object and its evidence row
  const selectedObject: SourceObject | null = useMemo(() => {
    if (!selectedObjectId || !currentDrawing) return null;
    return currentDrawing.objects.find((o) => o.id === selectedObjectId) || null;
  }, [selectedObjectId, currentDrawing]);

  const selectedEvidence: TakeoffEvidenceRow | null = useMemo(() => {
    if (!selectedObjectId || !takeoff) return null;
    return takeoff.evidence.find((e) => e.source_object_id === selectedObjectId) || null;
  }, [selectedObjectId, takeoff]);

  // Object IDs highlighted by item code selection
  const highlightedObjectIds: string[] = useMemo(() => {
    if (!highlightedItemCode || !takeoff) return [];
    return takeoff.evidence
      .filter((e) => e.mapped_item_code === highlightedItemCode && e.inclusion_status === "INCLUDED")
      .map((e) => e.source_object_id);
  }, [highlightedItemCode, takeoff]);

  return (
    <div className="flex flex-col h-screen w-screen bg-slate-950 text-slate-100 overflow-hidden font-sans">
      {/* Top Application Header */}
      <header className="h-14 border-b border-slate-800 bg-slate-900/90 backdrop-blur px-4 flex items-center justify-between shrink-0 z-30">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-sky-600 to-emerald-500 flex items-center justify-center text-white shadow-md shadow-sky-500/20">
            <Cpu size={18} />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight text-white flex items-center gap-2">
              Electrical AI Platform
              <span className="text-[10px] font-mono px-1.5 py-0.2 bg-sky-500/20 text-sky-400 border border-sky-500/30 rounded">
                MVP 1
              </span>
            </h1>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[11px] text-slate-400">
                {currentProject?.name || "기본 프로젝트"}
              </span>
              {projects.length > 1 && (
                <span className="text-[10px] text-slate-500 font-mono">
                  ({projects.length}개 프로젝트)
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Center / Drawing Info */}
        {currentDrawing && (
          <div className="hidden md:flex items-center gap-4 text-xs font-mono text-slate-300 bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800">
            <span className="text-sky-400 font-semibold">{currentDrawing.source.filename}</span>
            <span className="text-slate-600">|</span>
            <span>단위: {currentDrawing.dxf.units_name}</span>
            <span className="text-slate-600">|</span>
            <span>객체: {currentDrawing.objects.length}</span>
            <span className="text-slate-600">|</span>
            <span>프리미티브: {currentDrawing.primitives.length}</span>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2">
          {currentDrawing && (
            <button
              onClick={() => setIsAddManualMode(!isAddManualMode)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition border ${
                isAddManualMode
                  ? "bg-amber-500 text-slate-950 border-amber-400 shadow-lg shadow-amber-500/20"
                  : "bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700"
              }`}
            >
              <Plus size={14} />
              누락 기구 수동 추가
            </button>
          )}

          <input
            type="file"
            ref={fileInputRef}
            accept=".dxf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFileUpload(file);
            }}
          />

          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-md shadow-sky-600/20 transition"
          >
            <Upload size={14} />
            {isLoading ? "도면 분석 중..." : "DXF 업로드"}
          </button>
        </div>
      </header>

      {/* Drawing Warnings Bar */}
      {currentDrawing && <WarningBanner warnings={currentDrawing.warnings} />}

      {/* Global Error Banner */}
      {errorMessage && (
        <div className="bg-red-950/80 border-b border-red-800 px-4 py-2 text-xs text-red-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle size={15} className="text-red-400 shrink-0" />
            <span>{errorMessage}</span>
          </div>
          <button
            onClick={() => setErrorMessage(null)}
            className="text-red-300 hover:text-white text-xs underline"
          >
            닫기
          </button>
        </div>
      )}

      {/* Main Workspace Body */}
      <div className="flex-1 flex overflow-hidden relative">
        {currentDrawing ? (
          <>
            {/* Left / Center: Interactive CAD 2D Viewer */}
            <div className="flex-1 relative h-full">
              <CadViewer
                drawing={currentDrawing}
                selectedObjectId={selectedObjectId}
                highlightedObjectIds={highlightedObjectIds}
                hiddenLayers={hiddenLayers}
                onSelectObject={(id) => setSelectedObjectId(id)}
                isAddManualMode={isAddManualMode}
                onAddManualPoint={handleAddManualPoint}
              />

              {/* Floating Review Drawer when object is selected */}
              <ReviewDrawer
                object={selectedObject}
                evidence={selectedEvidence}
                mappings={mappings}
                onUpdateReview={handleUpdateReview}
                onClose={() => setSelectedObjectId(null)}
                isSaving={isSaving}
              />
            </div>

            {/* Right Panel: Split with Tabs (Takeoff, Mapping, Layers) */}
            <div className="w-[480px] h-full flex flex-col border-l border-slate-800 bg-slate-900 shrink-0">
              {/* Top Tab Bar */}
              <div className="flex items-center border-b border-slate-800 bg-slate-950/80 px-2 text-xs">
                <button
                  onClick={() => setActiveRightTab("takeoff")}
                  className={`flex items-center gap-1.5 py-3 px-3.5 border-b-2 font-medium transition ${
                    activeRightTab === "takeoff"
                      ? "border-emerald-500 text-emerald-400"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <TableProperties size={14} />
                  물량산출표
                </button>
                <button
                  onClick={() => setActiveRightTab("mapping")}
                  className={`flex items-center gap-1.5 py-3 px-3.5 border-b-2 font-medium transition ${
                    activeRightTab === "mapping"
                      ? "border-sky-500 text-sky-400"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Tags size={14} />
                  블록 매핑
                </button>
                <button
                  onClick={() => setActiveRightTab("layers")}
                  className={`flex items-center gap-1.5 py-3 px-3.5 border-b-2 font-medium transition ${
                    activeRightTab === "layers"
                      ? "border-amber-500 text-amber-400"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Layers size={14} />
                  레이어 ({currentDrawing.layers.length})
                </button>
              </div>

              {/* Panel Content */}
              <div className="flex-1 overflow-hidden">
                {activeRightTab === "takeoff" && takeoff && (
                  <TakeoffTable
                    takeoff={takeoff}
                    selectedItemCode={highlightedItemCode}
                    onSelectItemCode={(code) => setHighlightedItemCode(code)}
                    onSelectEvidence={(id) => setSelectedObjectId(id)}
                    csvSummaryUrl={api.getCsvExportUrl(
                      currentProject!.id,
                      currentDrawing.drawing_id,
                      "summary"
                    )}
                    csvEvidenceUrl={api.getCsvExportUrl(
                      currentProject!.id,
                      currentDrawing.drawing_id,
                      "evidence"
                    )}
                    xlsxUrl={api.getXlsxExportUrl(
                      currentProject!.id,
                      currentDrawing.drawing_id
                    )}
                  />
                )}

                {activeRightTab === "mapping" && (
                  <MappingPanel
                    blocks={currentDrawing.blocks}
                    mappings={mappings}
                    onSaveMappings={handleSaveMappings}
                    isSaving={isSaving}
                  />
                )}

                {activeRightTab === "layers" && (
                  <div className="p-4 space-y-2 overflow-y-auto h-full text-xs">
                    <p className="text-slate-400 text-[11px] mb-3">
                      도면 레이어의 가시성을 토글하여 원하는 설비만 집중해서 볼 수 있습니다.
                    </p>
                    {currentDrawing.layers.map((layer) => {
                      const isHidden = hiddenLayers.has(layer.name);
                      return (
                        <div
                          key={layer.name}
                          onClick={() => toggleLayer(layer.name)}
                          className={`flex items-center justify-between p-2.5 rounded border cursor-pointer transition ${
                            isHidden
                              ? "bg-slate-950/40 border-slate-800 text-slate-500"
                              : "bg-slate-800/60 border-slate-700 text-slate-200"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            {isHidden ? (
                              <EyeOff size={14} className="text-slate-500" />
                            ) : (
                              <Eye size={14} className="text-sky-400" />
                            )}
                            <span className="font-mono">{layer.name}</span>
                          </div>
                          <span className="text-[10px] bg-slate-900 px-1.5 py-0.5 rounded text-slate-400">
                            {layer.object_count} 개
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </>
        ) : (
          /* Empty Initial State */
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-slate-950">
            <div className="max-w-md w-full p-8 rounded-2xl border border-slate-800 bg-slate-900/50 backdrop-blur shadow-2xl space-y-5">
              <div className="w-16 h-16 mx-auto rounded-2xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
                <Upload size={32} />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">
                  DXF 전기 도면을 업로드하세요
                </h3>
                <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
                  AutoCAD DXF 형식의 전기설계도면을 업로드하면, CAD 블록·레이어·회로를 자동
                  분석하여 2D 평면도 렌더링 및 스마트 물량산출을 시작합니다.
                </p>
              </div>

              <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 text-[11px] text-slate-400 text-left space-y-1">
                <div>✓ <b>P0 지원 포맷:</b> ASCII / Binary DXF (.dxf)</div>
                <div>✓ <b>반자동 적산:</b> 블록 매핑 → 수량 집계 → 도면 검수 → CSV/Excel</div>
                <div className="text-amber-400/90">
                  ⚠️ <b>DWG 파일 안내:</b> CAD에서 DXF로 변환 후 업로드해 주세요.
                </div>
              </div>

              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isLoading}
                className="w-full py-2.5 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-sm font-semibold shadow-lg shadow-sky-600/30 transition flex items-center justify-center gap-2"
              >
                <Upload size={16} />
                도면 파일 선택 (.dxf)
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
