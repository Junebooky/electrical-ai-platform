"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import {
  NormalizedDrawing,
  ProjectMetadata,
  ItemMappingRule,
  TakeoffResult,
  SourceObject,
  TakeoffEvidenceRow,
  DrawingSummary,
  PdfPageFeatures,
  PdfTextFeature,
  PdfPathFeature,
} from "@/types/cad";
import { CadViewer } from "@/components/CadViewer";
import { MappingPanel } from "@/components/MappingPanel";
import { TakeoffTable } from "@/components/TakeoffTable";
import { ReviewDrawer } from "@/components/ReviewDrawer";
import { WarningBanner } from "@/components/WarningBanner";
import { ManualAddModal } from "@/components/ManualAddModal";
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
  FileText,
} from "lucide-react";

export default function WorkspacePage() {
  const [projects, setProjects] = useState<ProjectMetadata[]>([]);
  const [currentProject, setCurrentProject] = useState<ProjectMetadata | null>(null);
  const [drawings, setDrawings] = useState<DrawingSummary[]>([]);
  const [currentDrawing, setCurrentDrawing] = useState<NormalizedDrawing | null>(null);
  const [mappings, setMappings] = useState<ItemMappingRule[]>([]);
  const [takeoff, setTakeoff] = useState<TakeoffResult | null>(null);

  // UI state
  const [activeRightTab, setActiveRightTab] = useState<"takeoff" | "mapping" | "layers">("takeoff");
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [highlightedItemCode, setHighlightedItemCode] = useState<string | null>(null);
  const [hiddenLayers, setHiddenLayers] = useState<Set<string>>(new Set());
  const [isAddManualMode, setIsAddManualMode] = useState(false);
  const [currentPageIndex, setCurrentPageIndex] = useState<number>(0);

  interface PendingManualMarker {
    drawingId: string;
    pageIndex: number;
    x: number;
    y: number;
  }

  // Async state & race defense (QA-DEF-04)
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pendingManualCoord, setPendingManualCoord] = useState<PendingManualMarker | null>(null);

  // PR C: Vector PDF Text & Path Features
  const [showFeatures, setShowFeatures] = useState<boolean>(false);
  const [pageFeatures, setPageFeatures] = useState<PdfPageFeatures | null>(null);
  const [selectedFeature, setSelectedFeature] = useState<PdfTextFeature | PdfPathFeature | null>(null);
  const [isFeaturesLoading, setIsFeaturesLoading] = useState<boolean>(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const requestSeqRef = useRef<number>(0);
  const refreshSeqRef = useRef<number>(0);
  const activeDrawingIdRef = useRef<string | null>(null);

  // When a drawing is loaded or mappings change, refresh takeoff
  const refreshTakeoff = useCallback(async (projectId: string, drawingId: string) => {
    const seq = ++refreshSeqRef.current;
    try {
      const res = await api.getTakeoff(projectId, drawingId);
      if (activeDrawingIdRef.current !== drawingId || refreshSeqRef.current !== seq) {
        return; // Stale request, discard
      }
      setTakeoff(res);
    } catch (err: unknown) {
      if (activeDrawingIdRef.current !== drawingId || refreshSeqRef.current !== seq) {
        return; // Stale request error, discard
      }
      console.error("Failed to refresh takeoff", err);
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
          ? err.message
          : "물량산출 재계산에 실패했습니다.";
      setErrorMessage(`물량산출 재계산 실패: ${msg}`);
    }
  }, []);

  // Load a specific drawing by ID with async race defense
  const loadDrawing = useCallback(
    async (projectId: string, drawingId: string) => {
      setIsLoading(true);
      setErrorMessage(null);
      const seq = ++requestSeqRef.current;
      activeDrawingIdRef.current = drawingId;
      try {
        const [drawingData, mappingRules] = await Promise.all([
          api.getDrawing(projectId, drawingId),
          api.getMappings(projectId, drawingId),
        ]);
        if (requestSeqRef.current !== seq || activeDrawingIdRef.current !== drawingId) {
          return; // Newer request already initiated, discard stale response
        }
        setCurrentDrawing(drawingData);
        setMappings(mappingRules);
        setCurrentPageIndex(0);
        setSelectedFeature(null);
        setPageFeatures(null);
        await refreshTakeoff(projectId, drawingId);
        setSelectedObjectId(null);
        setHighlightedItemCode(null);
        setHiddenLayers(new Set());
      } catch (err: unknown) {
        if (requestSeqRef.current !== seq || activeDrawingIdRef.current !== drawingId) {
          return;
        }
        if (err instanceof ApiError) {
          setErrorMessage(err.message);
        } else if (err instanceof Error) {
          setErrorMessage(err.message);
        } else {
          setErrorMessage("도면을 불러오는 중 오류가 발생했습니다.");
        }
      } finally {
        if (requestSeqRef.current === seq) {
          setIsLoading(false);
        }
      }
    },
    [refreshTakeoff]
  );

  // Refresh drawings list for project and optionally auto-select a drawing
  const refreshDrawings = useCallback(
    async (projectId: string, selectDrawingId?: string) => {
      try {
        const dList = await api.listDrawings(projectId);
        setDrawings(dList);
        if (selectDrawingId) {
          await loadDrawing(projectId, selectDrawingId);
        } else if (dList.length > 0) {
          await loadDrawing(projectId, dList[0].id);
        }
      } catch (err) {
        console.error("Failed to load drawings list", err);
      }
    },
    [loadDrawing]
  );

  // Initialize: load or create default project and load existing drawings
  useEffect(() => {
    async function init() {
      try {
        const list = await api.listProjects();
        setProjects(list);
        let activeProj: ProjectMetadata;
        if (list.length > 0) {
          activeProj = list[0];
        } else {
          activeProj = await api.createProject("기본 전기공사 프로젝트");
          setProjects([activeProj]);
        }
        setCurrentProject(activeProj);
        await refreshDrawings(activeProj.id);
      } catch (err: unknown) {
        console.error("Failed to load projects", err);
      }
    }
    init();
  }, [refreshDrawings]);

  // Upload DXF handler
  const handleFileUpload = async (file: File) => {
    if (!currentProject) return;
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const uploadRes = await api.uploadDrawing(currentProject.id, file);
      await refreshDrawings(currentProject.id, uploadRes.drawing_id);
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

  // Update Review (Exclude/Restore/Manual Update)
  const handleUpdateReview = async (
    objectId: string,
    inclusionStatus: "INCLUDED" | "EXCLUDED" | "MANUAL_ADDED",
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

  // Available items for manual addition derived from mappings or defaults
  const availableItems = useMemo(() => {
    const list: { code: string; name: string; unit: string }[] = [];
    const seen = new Set<string>();
    for (const m of mappings) {
      if (m.item_code && m.item_code !== "EXCLUDE" && !seen.has(m.item_code)) {
        seen.add(m.item_code);
        list.push({ code: m.item_code, name: m.item_name || m.item_code, unit: m.unit || "EA" });
      }
    }
    if (!seen.has("LIGHT")) list.push({ code: "LIGHT", name: "전등 (다운라이트/평판등)", unit: "EA" });
    if (!seen.has("OUTLET")) list.push({ code: "OUTLET", name: "전열 (매입 콘센트)", unit: "EA" });
    if (!seen.has("SWITCH")) list.push({ code: "SWITCH", name: "스위치 (텀블러 스위치)", unit: "EA" });
    return list;
  }, [mappings]);

  // Open Manual Object Dialog (DEC-011 / DEC-012 / P0-01)
  const handleAddManualPoint = (x: number, y: number) => {
    if (!currentDrawing) return;
    const isPdf = currentDrawing.source_type === "PDF" || currentDrawing.coordinate_space === "PDF_PAGE_POINT";
    setPendingManualCoord({
      drawingId: currentDrawing.drawing_id,
      pageIndex: isPdf ? currentPageIndex : 0,
      x,
      y,
    });
  };

  // Safe page navigation canceling pending marker on page switch (P0-01)
  const handlePageChange = (newIndex: number) => {
    if (pendingManualCoord) {
      setPendingManualCoord(null);
    }
    setCurrentPageIndex(newIndex);
    setSelectedObjectId(null);
    setSelectedFeature(null);
  };

  // Confirm manual object addition after mandatory item & reason selection
  const handleConfirmManualAdd = async (
    itemCode: string,
    reason: string,
    note: string,
    selectedUnit?: string
  ) => {
    if (!currentProject || !currentDrawing || !pendingManualCoord) return;
    if (pendingManualCoord.drawingId !== currentDrawing.drawing_id) {
      setPendingManualCoord(null);
      return;
    }
    setIsSaving(true);
    try {
      const manualId = `manual_${Date.now()}`;
      const matched = availableItems.find((i) => i.code === itemCode);
      const unit = matched ? (matched.unit || "EA").trim() : (selectedUnit?.trim() || "EA");
      const isPdf = currentDrawing.source_type === "PDF" || currentDrawing.coordinate_space === "PDF_PAGE_POINT";
      await api.addManualObject(currentProject.id, currentDrawing.drawing_id, {
        id: manualId,
        drawing_id: currentDrawing.drawing_id,
        x: pendingManualCoord.x,
        y: pendingManualCoord.y,
        item_code: itemCode,
        item_name: matched?.name || itemCode,
        unit: unit,
        note: note ? `[${reason}] ${note}` : `[${reason}] 수동 추가`,
        page_index: isPdf ? pendingManualCoord.pageIndex : 0,
      });
      setPendingManualCoord(null);
      setIsAddManualMode(false);
      await refreshTakeoff(currentProject.id, currentDrawing.drawing_id);
    } catch (err: unknown) {
      setErrorMessage("수동 기구 추가 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSaving(false);
    }
  };

  // Fetch vector features when toggled on or page changes (PR C)
  useEffect(() => {
    let isCancelled = false;
    async function loadFeatures() {
      if (!showFeatures || !currentProject || !currentDrawing || currentDrawing.source_type !== "PDF") {
        return;
      }
      setIsFeaturesLoading(true);
      try {
        const res = await api.getPageFeatures(currentProject.id, currentDrawing.drawing_id, currentPageIndex);
        if (!isCancelled) {
          setPageFeatures(res);
        }
      } catch (err) {
        console.error("Failed to load page features:", err);
      } finally {
        if (!isCancelled) {
          setIsFeaturesLoading(false);
        }
      }
    }
    loadFeatures();
    return () => {
      isCancelled = true;
    };
  }, [showFeatures, currentProject, currentDrawing, currentPageIndex]);

  // Delete Manual Object
  const handleDeleteManualObject = async (manualId: string) => {
    if (!currentProject || !currentDrawing) return;
    setIsSaving(true);
    try {
      await api.deleteManualObject(currentProject.id, currentDrawing.drawing_id, manualId);
      setSelectedObjectId(null);
      await refreshTakeoff(currentProject.id, currentDrawing.drawing_id);
    } catch (err: unknown) {
      setErrorMessage("수동 기구 삭제 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSaving(false);
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

  // Manually added markers for interactive canvas rendering
  const manualMarkers = useMemo(() => {
    if (!takeoff) return [];
    return takeoff.evidence
      .filter((e) => e.inclusion_status === "MANUAL_ADDED")
      .map((e) => ({
        id: e.source_object_id,
        x: e.x,
        y: e.y,
        item_code: e.mapped_item_code,
        note: e.review_reason,
        page_index: e.page_index ?? 0,
      }));
  }, [takeoff]);

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

        {/* Center / Drawing Info & Reopen Selector */}
        <div className="flex items-center gap-3">
          {drawings.length > 0 && (
            <div className="flex items-center gap-1.5 bg-slate-950 px-2.5 py-1.5 rounded-lg border border-slate-800 text-xs">
              <FileText size={14} className="text-sky-400 shrink-0" />
              <select
                aria-label="저장된 도면 목록"
                value={currentDrawing?.drawing_id || ""}
                onChange={(e) => {
                  if (e.target.value && currentProject) {
                    loadDrawing(currentProject.id, e.target.value);
                  }
                }}
                className="bg-transparent text-slate-200 text-xs focus:outline-none cursor-pointer max-w-[200px] truncate"
              >
                {drawings.map((d) => (
                  <option key={d.id} value={d.id} className="bg-slate-900 text-slate-200">
                    {d.filename} ({d.revision})
                  </option>
                ))}
              </select>
            </div>
          )}

          {currentDrawing && (
            <div className="hidden lg:flex items-center gap-3 text-xs font-mono text-slate-300 bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800">
              <span className={currentDrawing.source_type === "PDF" || currentDrawing.source_type === "IMAGE" ? "text-amber-400 font-semibold" : "text-sky-400 font-semibold"}>
                {currentDrawing.source.filename}
              </span>
              <span className="text-slate-600">|</span>
              {currentDrawing.source_type === "PDF" ? (
                <>
                  <span className="px-1.5 py-0.5 bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded text-[11px]">
                    PDF 도면 (수동 적산)
                  </span>
                  <span className="text-slate-600">|</span>
                  <span>
                    페이지: {currentPageIndex + 1} / {currentDrawing.page_count || 1}
                  </span>
                  <span className="text-slate-600">|</span>
                  <span>수동 마커: {manualMarkers.length}개</span>
                </>
              ) : currentDrawing.source_type === "IMAGE" ? (
                <>
                  <span className="px-1.5 py-0.5 bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded text-[11px]">
                    2D 이미지 (수동 마커)
                  </span>
                  <span className="text-slate-600">|</span>
                  <span>
                    해상도: {currentDrawing.dimensions?.width || currentDrawing.extents?.max[0]}x{currentDrawing.dimensions?.height || currentDrawing.extents?.max[1]}px
                  </span>
                  <span className="text-slate-600">|</span>
                  <span>수동 마커: {manualMarkers.length}개</span>
                </>
              ) : (
                <>
                  <span>단위: {currentDrawing.dxf.units_name}</span>
                  <span className="text-slate-600">|</span>
                  <span>객체: {currentDrawing.objects.length}</span>
                  <span className="text-slate-600">|</span>
                  <span>프리미티브: {currentDrawing.primitives.length}</span>
                </>
              )}
            </div>
          )}
        </div>

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
            accept=".dxf,.png,.jpg,.jpeg,.pdf"
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
            {isLoading ? "도면 분석 중..." : "도면 업로드"}
          </button>
        </div>
      </header>

      {/* PDF Mode Notice Banner & Page Navigation (PR B) */}
      {currentDrawing?.source_type === "PDF" && (
        <div className="bg-amber-950/70 border-b border-amber-800/60 px-4 py-2 text-xs text-amber-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="px-1.5 py-0.5 bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded text-[10px] font-mono font-semibold">
              PDF 모드 (PR B/C)
            </span>
            <span>
              ※ PDF 도면을 표시했습니다. 기구 위치를 직접 표시해 주세요. (잠정 수량). 상단 <b>[누락 기구 수동 추가]</b> 활성화 후 도면을 클릭하여 각 페이지 좌표계(pt)에 마커(EA)를 등록합니다.
            </span>
          </div>
          <div className="flex items-center gap-2">
            {/* Vector Features Toggle Button (PR C) */}
            <button
              onClick={() => {
                setShowFeatures((prev) => {
                  if (prev) {
                    setPageFeatures(null);
                    setSelectedFeature(null);
                  }
                  return !prev;
                });
              }}
              className={`px-2.5 py-1 rounded text-xs transition flex items-center gap-1.5 font-medium border ${
                showFeatures
                  ? "bg-sky-600 hover:bg-sky-500 text-white border-sky-400 shadow-sm"
                  : "bg-slate-900/90 hover:bg-slate-800 text-slate-300 border-slate-700"
              }`}
              title="PDF 원본 텍스트 및 선/도형 벡터 근거 하이라이트"
            >
              <span>{showFeatures ? "✓ 원문 근거 표시 중" : "원문 근거 보기"}</span>
              {isFeaturesLoading ? (
                <span className="text-[10px] text-sky-300 animate-pulse">로딩 중...</span>
              ) : (
                pageFeatures && (
                  <span className="text-[10px] bg-sky-950/90 px-1 py-0.5 rounded text-sky-200 border border-sky-600/50">
                    T:{pageFeatures.texts.length} P:{pageFeatures.paths.length}
                  </span>
                )
              )}
            </button>

            {currentDrawing.page_count && currentDrawing.page_count > 1 && (
              <div className="flex items-center gap-2 bg-slate-900/80 px-2 py-1 rounded border border-slate-700">
                <button
                  onClick={() => handlePageChange(Math.max(0, currentPageIndex - 1))}
                  disabled={Boolean(pendingManualCoord) || currentPageIndex <= 0}
                  className="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-white rounded text-xs transition"
                  title={pendingManualCoord ? "마커 추가 중에는 페이지를 변경할 수 없습니다." : "이전 페이지"}
                >
                  ◀
                </button>
                <span className="font-mono font-medium text-xs text-slate-200">
                  {currentPageIndex + 1} / {currentDrawing.page_count} 페이지
                </span>
                <button
                  onClick={() => handlePageChange(Math.min((currentDrawing.page_count || 1) - 1, currentPageIndex + 1))}
                  disabled={Boolean(pendingManualCoord) || currentPageIndex >= (currentDrawing.page_count || 1) - 1}
                  className="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-white rounded text-xs transition"
                  title={pendingManualCoord ? "마커 추가 중에는 페이지를 변경할 수 없습니다." : "다음 페이지"}
                >
                  ▶
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 2D Image Mode Notice Banner (FR-015/016) */}
      {currentDrawing?.source_type === "IMAGE" && (
        <div className="bg-sky-950/70 border-b border-sky-800/60 px-4 py-2 text-xs text-sky-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="px-1.5 py-0.5 bg-sky-500/20 text-sky-300 border border-sky-500/40 rounded text-[10px] font-mono font-semibold">
              v1.1 이미지 모드
            </span>
            <span>
              ※ 2D 이미지 도면은 자동 기호 인식이 제공되지 않으며(FR-016), 상단 <b>[누락 기구 수동 추가]</b> 활성화 후 도면을 클릭하여 픽셀 좌표에 마커(EA)를 등록하고 실시간 적산표를 산출합니다.
            </span>
          </div>
        </div>
      )}

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
                onOutOfBoundsClick={(x, y, maxX, maxY) => {
                  if (currentDrawing.source_type === "PDF") {
                    setErrorMessage(
                      `도면 밖 좌표(X: ${x.toFixed(1)}, Y: ${y.toFixed(1)})에는 기구를 추가할 수 없습니다. 페이지 유효 범위: [0, ${maxX.toFixed(1)}) × [0, ${maxY.toFixed(1)}) pt`
                    );
                  } else {
                    setErrorMessage(
                      `도면 밖 좌표(X: ${Math.round(x)}, Y: ${Math.round(y)})에는 기구를 추가할 수 없습니다. 유효 도면 범위: [0, ${maxX}) × [0, ${maxY}) px (0~${maxX - 1}, 0~${maxY - 1})`
                    );
                  }
                }}
                manualMarkers={manualMarkers}
                currentPageIndex={currentPageIndex}
                imageUrl={
                  currentDrawing.source_type === "PDF" && currentProject
                    ? api.getPageImageUrl(currentProject.id, currentDrawing.drawing_id, currentPageIndex)
                    : currentDrawing.source_type === "IMAGE" && currentProject
                    ? api.getImageUrl(currentProject.id, currentDrawing.drawing_id)
                    : null
                }
                features={pageFeatures}
                showFeatures={showFeatures}
                selectedFeatureId={selectedFeature?.source_object_id || null}
                onSelectFeature={(feat) => {
                  setSelectedFeature(feat);
                  if (feat) setSelectedObjectId(null);
                }}
              />

              {/* Selected Vector Feature Inspection Card (PR C) */}
              {selectedFeature && (
                <div
                  data-testid="selected-feature-card"
                  className="absolute bottom-6 right-6 z-30 w-96 bg-slate-900/95 backdrop-blur-md border border-sky-500/50 rounded-xl shadow-2xl p-4 text-slate-200"
                >
                  <div className="flex items-start justify-between border-b border-slate-800 pb-2 mb-3">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 bg-sky-500/20 text-sky-300 border border-sky-500/40 rounded text-xs font-semibold">
                        {selectedFeature.extraction_method === "PDF_TEXT"
                          ? "도면 원문 텍스트"
                          : `도면 벡터 ${(selectedFeature as PdfPathFeature).type}`}
                      </span>
                      <span className="text-xs text-slate-400 font-mono">
                        P.{selectedFeature.page_index + 1}
                      </span>
                    </div>
                    <button
                      onClick={() => setSelectedFeature(null)}
                      className="text-slate-400 hover:text-white text-sm"
                    >
                      ✕
                    </button>
                  </div>

                  <div className="space-y-2 text-xs">
                    {"text" in selectedFeature && (
                      <div className="p-2.5 bg-slate-950/80 rounded border border-slate-800 font-mono text-sm text-sky-200 font-semibold break-all">
                        {selectedFeature.text}
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-2 text-slate-400">
                      <div>
                        <span className="block text-[10px] uppercase tracking-wider text-slate-500">객체 ID</span>
                        <span className="font-mono text-slate-300">{selectedFeature.source_object_id}</span>
                      </div>
                      <div>
                        <span className="block text-[10px] uppercase tracking-wider text-slate-500">추출 방식</span>
                        <span className="font-mono text-slate-300">{selectedFeature.extraction_method}</span>
                      </div>
                      <div className="col-span-2">
                        <span className="block text-[10px] uppercase tracking-wider text-slate-500">바운딩 박스 (pt)</span>
                        <span className="font-mono text-slate-300">[{selectedFeature.bbox.join(", ")}]</span>
                      </div>
                    </div>

                    <div className="p-2 bg-amber-950/40 border border-amber-800/40 rounded text-[11px] text-amber-300/90 leading-relaxed">
                      ℹ️ <b>도메인 불변식</b>: 원문 도면에서 추출된 벡터 근거입니다. 전기설비 설치 수량(EA)으로 자동 산출되지 않으며, 사용자 수동 마커 지정을 통해서만 물량에 반영됩니다.
                    </div>

                    <button
                      onClick={() => {
                        handleAddManualPoint(selectedFeature.x, selectedFeature.y);
                        setSelectedFeature(null);
                      }}
                      className="w-full mt-2 py-2 px-3 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-medium text-xs flex items-center justify-center gap-1.5 transition shadow"
                    >
                      <Plus size={14} />
                      <span>이 위치에 수동 기구 마커 추가 (1 EA)</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Floating Review Drawer when object is selected */}
              <ReviewDrawer
                object={selectedObject}
                evidence={selectedEvidence}
                mappings={mappings}
                sourceType={currentDrawing.source_type}
                coordinateSpace={currentDrawing.coordinate_space}
                onUpdateReview={handleUpdateReview}
                onDeleteManualObject={handleDeleteManualObject}
                onClose={() => setSelectedObjectId(null)}
                isSaving={isSaving}
              />

              {/* Explicit Manual Add Modal (DEC-011 / DEC-012) */}
              <ManualAddModal
                isOpen={Boolean(pendingManualCoord)}
                coords={pendingManualCoord}
                drawingName={currentDrawing.source.filename}
                availableItems={availableItems}
                isSaving={isSaving}
                onClose={() => setPendingManualCoord(null)}
                onConfirm={handleConfirmManualAdd}
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
                  currentDrawing.source_type === "IMAGE" ? (
                    <div className="p-8 text-center text-slate-400 text-xs flex flex-col items-center justify-center h-full">
                      <div className="w-12 h-12 mb-3 rounded-full bg-slate-800/80 border border-slate-700 flex items-center justify-center text-amber-400 shadow-inner">
                        <Tags size={22} />
                      </div>
                      <h3 className="font-semibold text-slate-200 text-sm mb-1.5">2D 이미지 도면 (CAD 블록 없음)</h3>
                      <p className="text-slate-400 mb-5 max-w-[320px] leading-relaxed">
                        래스터 이미지 도면은 CAD 블록 구조가 없으므로 블록-품목 매핑 대신 도면상 <b>[누락 기구 수동 추가]</b>를 활성화하여 기구 마커를 직접 배치합니다.
                      </p>
                      <button
                        onClick={() => setActiveRightTab("takeoff")}
                        className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold shadow-md shadow-emerald-600/20 transition"
                      >
                        물량산출표 보기
                      </button>
                    </div>
                  ) : (
                    <MappingPanel
                      key={currentDrawing.drawing_id}
                      blocks={currentDrawing.blocks}
                      mappings={mappings}
                      onSaveMappings={handleSaveMappings}
                      isSaving={isSaving}
                    />
                  )
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
