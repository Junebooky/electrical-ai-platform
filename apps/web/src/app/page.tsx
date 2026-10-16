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
  SymbolCandidate,
  CandidateBulkReviewRequest,
} from "@/types/cad";
import { CadViewer } from "@/components/CadViewer";
import { MappingPanel } from "@/components/MappingPanel";
import { TakeoffTable } from "@/components/TakeoffTable";
import { ReviewDrawer } from "@/components/ReviewDrawer";
import { WarningBanner } from "@/components/WarningBanner";
import { ManualAddModal } from "@/components/ManualAddModal";
import { CandidateReviewTable } from "@/components/CandidateReviewTable";
import { ProjectOverview } from "@/components/ProjectOverview";
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
  Sparkles,
  Check,
  X,
  Play,
  Crop,
  CheckCircle2,
  Building,
} from "lucide-react";

export default function WorkspacePage() {
  const [projects, setProjects] = useState<ProjectMetadata[]>([]);
  const [currentProject, setCurrentProject] = useState<ProjectMetadata | null>(null);
  const [drawings, setDrawings] = useState<DrawingSummary[]>([]);
  const [currentDrawing, setCurrentDrawing] = useState<NormalizedDrawing | null>(null);
  const [mappings, setMappings] = useState<ItemMappingRule[]>([]);
  const [takeoff, setTakeoff] = useState<TakeoffResult | null>(null);

  // UI state
  const [viewMode, setViewMode] = useState<"project" | "drawing">("drawing");
  const [activeRightTab, setActiveRightTab] = useState<"takeoff" | "candidates" | "mapping" | "layers">("takeoff");
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [highlightedItemCode, setHighlightedItemCode] = useState<string | null>(null);
  const [hiddenLayers, setHiddenLayers] = useState<Set<string>>(new Set());
  const [isAddManualMode, setIsAddManualMode] = useState(false);
  const [currentPageIndex, setCurrentPageIndex] = useState<number>(0);

  // Issue #23: Symbol Candidates & Review
  const [candidates, setCandidates] = useState<SymbolCandidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<SymbolCandidate | null>(null);
  const [isDetecting, setIsDetecting] = useState<boolean>(false);
  const [showCandidates, setShowCandidates] = useState<boolean>(true);

  // Issue #29: Interactive User-Defined Visual Symbol Search
  const [isCropSearchMode, setIsCropSearchMode] = useState<boolean>(false);
  const [cropModalOpen, setCropModalOpen] = useState<boolean>(false);
  const [pendingCropBbox, setPendingCropBbox] = useState<[number, number, number, number] | null>(null);
  const [cropSearchItemCode, setCropSearchItemCode] = useState<string>("LIGHT");
  const [cropSearchThreshold, setCropSearchThreshold] = useState<number>(0.75);
  const [cropSearchIncludeRotations, setCropSearchIncludeRotations] = useState<boolean>(true);
  const [cropSearchAllPages, setCropSearchAllPages] = useState<boolean>(false);
  const [isSearchingSymbols, setIsSearchingSymbols] = useState<boolean>(false);
  const [searchSuccessMessage, setSearchSuccessMessage] = useState<string | null>(null);

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
        const [drawingData, mappingRules, candData] = await Promise.all([
          api.getDrawing(projectId, drawingId),
          api.getMappings(projectId, drawingId),
          api.getCandidates(projectId, drawingId).catch(() => ({
            drawing_id: drawingId,
            summary: { total: 0, proposed: 0, accepted: 0, rejected: 0 },
            candidates: [],
          })),
        ]);
        if (requestSeqRef.current !== seq || activeDrawingIdRef.current !== drawingId) {
          return; // Newer request already initiated, discard stale response
        }
        setCurrentDrawing(drawingData);
        setMappings(mappingRules);
        setCandidates(candData.candidates || []);
        setSelectedCandidate(null);
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

  // Safe page navigation canceling pending marker on page switch (P0-01, Risk-2)
  const handlePageChange = (newIndex: number) => {
    if (pendingManualCoord) {
      setPendingManualCoord(null);
    }
    setCurrentPageIndex(newIndex);
    setSelectedObjectId(null);
    setSelectedFeature(null);
    setSelectedCandidate(null);
    setPageFeatures(null);
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
        setPageFeatures(null);
        setSelectedFeature(null);
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

  // Issue #23: Run candidate detection
  const handleRunDetection = async () => {
    if (!currentProject || !currentDrawing) return;
    const targetDrawingId = currentDrawing.drawing_id;
    setIsDetecting(true);
    try {
      const res = await api.detectCandidates(currentProject.id, targetDrawingId);
      if (activeDrawingIdRef.current === targetDrawingId) {
        setCandidates(res.candidates);
        await refreshTakeoff(currentProject.id, targetDrawingId);
      }
    } catch (err: unknown) {
      setErrorMessage("기호 탐지 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsDetecting(false);
    }
  };

  // Issue #23: Review candidates (single or bulk)
  const handleCandidateReview = async (req: CandidateBulkReviewRequest) => {
    if (!currentProject || !currentDrawing) return;
    const targetDrawingId = currentDrawing.drawing_id;
    setIsSaving(true);
    try {
      const res = await api.reviewCandidates(currentProject.id, targetDrawingId, req);
      if (activeDrawingIdRef.current === targetDrawingId) {
        setCandidates(res.candidates);
        if (selectedCandidate) {
          const updated = res.candidates.find((c) => c.candidate_id === selectedCandidate.candidate_id);
          setSelectedCandidate(updated || null);
        }
        await refreshTakeoff(currentProject.id, targetDrawingId);
      }
    } catch (err: unknown) {
      setErrorMessage("기호 검수 반영 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSaving(false);
    }
  };

  // Issue #29: Interactive User-Defined Visual Symbol Search
  const handleCropComplete = useCallback((bbox: [number, number, number, number]) => {
    setPendingCropBbox(bbox);
    setCropModalOpen(true);
    setIsCropSearchMode(false);
  }, []);

  const handleRunSymbolSearch = useCallback(async () => {
    if (!currentProject || !currentDrawing || !pendingCropBbox) return;
    const targetDrawingId = currentDrawing.drawing_id;
    setIsSearchingSymbols(true);
    setErrorMessage(null);
    setSearchSuccessMessage(null);
    try {
      const itemName =
        availableItems.find((i) => i.code === cropSearchItemCode)?.name || cropSearchItemCode;
      const res = await api.searchSymbol(currentProject.id, targetDrawingId, {
        sample_bbox: pendingCropBbox,
        page_index: currentPageIndex,
        suggested_item_code: cropSearchItemCode,
        suggested_item_name: itemName,
        threshold: cropSearchThreshold,
        search_all_pages: cropSearchAllPages,
      });

      if (activeDrawingIdRef.current === targetDrawingId) {
        const updatedCandRes = await api.getCandidates(currentProject.id, targetDrawingId);
        setCandidates(updatedCandRes.candidates || []);
        setCropModalOpen(false);
        setPendingCropBbox(null);
        setActiveRightTab("candidates");
        if (res.total_found > 0) {
          const avgConf =
            res.candidates.length > 0
              ? Math.round(
                  (res.candidates.reduce((acc, c) => acc + c.confidence, 0) /
                    res.candidates.length) *
                    100
                )
              : Math.round(cropSearchThreshold * 100);
          setSearchSuccessMessage(
            `성공: ${res.total_found}건의 유사 기호(${cropSearchItemCode})를 탐지했습니다. (평균 유사도: ${avgConf}%)`
          );
        } else {
          setErrorMessage(
            `선택한 영역과 유사도 ${Math.round(cropSearchThreshold * 100)}% 이상 일치하는 기호를 찾지 못했습니다. 임계값을 낮추거나 영역을 다시 지정해보세요.`
          );
        }
        await refreshTakeoff(currentProject.id, targetDrawingId);
      }
    } catch (err: unknown) {
      console.error("Failed visual symbol search", err);
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
          ? err.message
          : "기호 검색에 실패했습니다.";
      setErrorMessage(`기호 검색 실패: ${msg}`);
    } finally {
      setIsSearchingSymbols(false);
    }
  }, [
    currentProject,
    currentDrawing,
    pendingCropBbox,
    currentPageIndex,
    cropSearchItemCode,
    availableItems,
    cropSearchThreshold,
    cropSearchAllPages,
    refreshTakeoff,
  ]);

  // Toggle Layer visibility
  const toggleLayer = (layerName: string) => {
    setHiddenLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layerName)) next.delete(layerName);
      else next.add(layerName);
      return next;
    });
  };

  // Live Demo Seed Project
  const handleSeedDemo = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const res = await api.seedDemoProject();
      const pList = await api.listProjects();
      setProjects(pList);
      const demoProj = pList.find((p) => p.id === res.project_id) || {
        id: res.project_id,
        name: res.project_name,
        description: "실전 전기공사 샘플 프로젝트",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        drawing_count: res.drawings.length,
      };
      setCurrentProject(demoProj);
      await refreshDrawings(demoProj.id, res.drawings[0]?.drawing_id);
      setActiveRightTab("candidates");
    } catch (err: unknown) {
      console.error("Failed to seed demo project", err);
      setErrorMessage("실전 데모 프로젝트 초기화 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsLoading(false);
    }
  };

  // Multi-Drawing Demo Seed (Issue #35)
  const handleSeedMultiDrawingDemo = async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const res = await api.seedMultiDrawingDemo(true);
      const pList = await api.listProjects();
      setProjects(pList);
      const demoProj = pList.find((p) => p.id === res.project_id) || {
        id: res.project_id,
        name: res.project_name,
        description: "다중 도면 리비전 통합 프로젝트",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        drawing_count: res.drawings.length,
      };
      setCurrentProject(demoProj);
      await refreshDrawings(demoProj.id, res.drawings[0]?.drawing_id);
      setViewMode("project");
    } catch (err: unknown) {
      console.error("Failed to seed multi-drawing demo", err);
      setErrorMessage("다중 도면 데모 시딩 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsLoading(false);
    }
  };

  // Reload mappings after template application
  const handleReloadMappings = async () => {
    if (!currentProject || !currentDrawing) return;
    const newMappings = await api.getMappings(currentProject.id, currentDrawing.drawing_id);
    setMappings(newMappings);
    await refreshTakeoff(currentProject.id, currentDrawing.drawing_id);
  };

  // Bidirectional Inspection: Select evidence row & auto-switch PDF page if necessary
  const handleSelectEvidence = (objectId: string) => {
    setSelectedObjectId(objectId);
    const ev = takeoff?.evidence.find((e) => e.source_object_id === objectId);
    if (ev && ev.page_index !== undefined && ev.page_index !== null) {
      setCurrentPageIndex(ev.page_index);
    }
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

        {/* Center / View Mode Switcher & Drawing Info */}
        <div className="flex items-center gap-3">
          {currentProject && (
            <div className="flex items-center bg-slate-950 p-0.5 rounded-lg border border-slate-800 shrink-0">
              <button
                type="button"
                data-testid="btn-view-project"
                onClick={() => setViewMode("project")}
                className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition whitespace-nowrap ${
                  viewMode === "project"
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Building size={13} />
                <span>프로젝트 전체</span>
              </button>
              <button
                type="button"
                data-testid="btn-view-drawing"
                onClick={() => setViewMode("drawing")}
                className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition whitespace-nowrap ${
                  viewMode === "drawing"
                    ? "bg-sky-600 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Layers size={13} />
                <span>도면 상세</span>
              </button>
            </div>
          )}

          {drawings.length > 0 && (
            <div className="flex items-center gap-1.5 bg-slate-950 px-2.5 py-1.5 rounded-lg border border-slate-800 text-xs">
              <FileText size={14} className="text-sky-400 shrink-0" />
              <select
                aria-label="저장된 도면 목록"
                value={currentDrawing?.drawing_id || ""}
                onChange={(e) => {
                  if (e.target.value && currentProject) {
                    loadDrawing(currentProject.id, e.target.value);
                    setViewMode("drawing");
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

          {currentDrawing && viewMode === "drawing" && (
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
          {currentDrawing && viewMode === "drawing" && (
            <>
              <button
                onClick={handleRunDetection}
                disabled={isDetecting || isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-md shadow-sky-600/20 transition"
                title="도면에서 AI 전기기구 후보 자동 탐지"
              >
                <Sparkles size={14} className={isDetecting ? "animate-spin" : ""} />
                {isDetecting ? "기호 탐지 중..." : "AI 기호 탐지"}
              </button>
              {candidates.length > 0 && (
                <button
                  onClick={() => setShowCandidates((prev) => !prev)}
                  className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition border ${
                    showCandidates
                      ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
                      : "bg-slate-800 text-slate-400 border-slate-700"
                  }`}
                  title="기호 후보 오버레이 표시 토글"
                >
                  <Eye size={13} />
                  <span>기호 {showCandidates ? "표시 중" : "숨김"}</span>
                </button>
              )}
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
            </>
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
            onClick={handleSeedMultiDrawingDemo}
            disabled={isLoading}
            data-testid="btn-multi-drawing-demo"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-md shadow-indigo-600/20 transition"
            title="Issue #35 다중 도면(1F REV0/REV1, 2F, 1F단선도) 리비전 데모 로드"
          >
            <Sparkles size={13} />
            <span>다중 도면 데모 (Issue #35)</span>
          </button>

          <button
            onClick={handleSeedDemo}
            disabled={isLoading}
            data-testid="btn-live-demo"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-md shadow-emerald-600/20 transition"
            title="CAD·PDF·이미지 종합 실전 데모 프로젝트 로드 (템플릿 및 기호 탐지 포함)"
          >
            <Play size={13} className="fill-current" />
            <span>실전 데모 (Live Demo)</span>
          </button>

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
      {viewMode === "drawing" && currentDrawing?.source_type === "PDF" && (
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
                pageFeatures &&
                pageFeatures.page_index === currentPageIndex &&
                currentDrawing &&
                pageFeatures.drawing_id === currentDrawing.drawing_id && (
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

      {/* 2D Image Mode Notice Banner (FR-015/016 / Issue #29) */}
      {viewMode === "drawing" && currentDrawing?.source_type === "IMAGE" && (
        <div className="bg-sky-950/70 border-b border-sky-800/60 px-4 py-2 text-xs text-sky-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="px-1.5 py-0.5 bg-sky-500/20 text-sky-300 border border-sky-500/40 rounded text-[10px] font-mono font-semibold">
              v1.2 비주얼 인식 모드
            </span>
            <span>
              ※ 2D 이미지 도면은 <b>[기호 영역 검색]</b>을 통해 드래그한 샘플 기호를 자동 탐지하거나, <b>[누락 기구 수동 추가]</b>로 직접 마커(EA)를 등록하여 적산할 수 있습니다.
            </span>
          </div>
        </div>
      )}

      {/* Drawing Warnings Bar */}
      {viewMode === "drawing" && currentDrawing && <WarningBanner warnings={currentDrawing.warnings} />}

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

      {/* Search Success Notification Banner */}
      {searchSuccessMessage && (
        <div
          data-testid="search-success-banner"
          className="bg-emerald-950/80 border-b border-emerald-800 px-4 py-2 text-xs text-emerald-200 flex items-center justify-between"
        >
          <div className="flex items-center gap-2">
            <CheckCircle2 size={15} className="text-emerald-400 shrink-0" />
            <span>{searchSuccessMessage}</span>
          </div>
          <button
            onClick={() => setSearchSuccessMessage(null)}
            className="text-emerald-300 hover:text-white text-xs underline"
          >
            닫기
          </button>
        </div>
      )}

      {/* Main Workspace Body */}
      <div className="flex-1 flex overflow-hidden relative">
        {viewMode === "project" && currentProject ? (
          <div className="flex-1 overflow-hidden">
            <ProjectOverview
              currentProject={currentProject}
              onOpenDrawing={(drawingId) => {
                loadDrawing(currentProject.id, drawingId);
                setViewMode("drawing");
              }}
              onRefreshProject={() => {
                refreshDrawings(currentProject.id);
              }}
            />
          </div>
        ) : currentDrawing ? (
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
                features={
                  pageFeatures &&
                  pageFeatures.page_index === currentPageIndex &&
                  currentDrawing &&
                  pageFeatures.drawing_id === currentDrawing.drawing_id
                    ? pageFeatures
                    : null
                }
                showFeatures={showFeatures}
                selectedFeatureId={selectedFeature?.source_object_id || null}
                onSelectFeature={(feat) => {
                  setSelectedFeature(feat);
                  if (feat) {
                    setSelectedObjectId(null);
                    setSelectedCandidate(null);
                  }
                }}
                candidates={candidates}
                showCandidates={showCandidates}
                selectedCandidateId={selectedCandidate?.candidate_id || null}
                onSelectCandidate={(cand) => {
                  setSelectedCandidate(cand);
                  if (cand) {
                    setSelectedObjectId(null);
                    setSelectedFeature(null);
                    setActiveRightTab("candidates");
                  }
                }}
                isCropSearchMode={isCropSearchMode}
                onCropComplete={handleCropComplete}
              />

              {/* Selected AI Candidate Card (Issue #23) */}
              {selectedCandidate && (
                <div
                  data-testid="selected-candidate-card"
                  className="absolute bottom-6 right-6 z-30 w-96 bg-slate-900/95 backdrop-blur-md border border-amber-500/50 rounded-xl shadow-2xl p-4 text-slate-200"
                >
                  <div className="flex items-start justify-between border-b border-slate-800 pb-2 mb-3">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 bg-amber-500/20 text-amber-300 border border-amber-500/40 rounded text-xs font-semibold">
                        AI 탐지 기호 후보
                      </span>
                      <span className="text-xs text-slate-400 font-mono">
                        P.{selectedCandidate.page_index + 1}
                      </span>
                    </div>
                    <button
                      onClick={() => setSelectedCandidate(null)}
                      className="text-slate-400 hover:text-white text-sm"
                    >
                      ✕
                    </button>
                  </div>

                  <div className="space-y-2 text-xs">
                    <div className="flex items-center justify-between p-2.5 bg-slate-950/80 rounded border border-slate-800">
                      <div>
                        <span className="block text-slate-400 text-[10px] uppercase">추천 품목</span>
                        <span className="font-semibold text-amber-300 text-sm">
                          {selectedCandidate.suggested_item_name} ({selectedCandidate.reviewed_item_code || selectedCandidate.suggested_item_code})
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="block text-slate-400 text-[10px] uppercase">신뢰도</span>
                        <span className="font-mono text-sky-300 font-bold">
                          {Math.round(selectedCandidate.confidence * 100)}%
                        </span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-slate-400 font-mono">
                      <div>
                        <span className="block text-[10px] uppercase tracking-wider text-slate-500">후보 ID</span>
                        <span className="text-slate-300 truncate block text-[11px]">{selectedCandidate.candidate_id}</span>
                      </div>
                      <div>
                        <span className="block text-[10px] uppercase tracking-wider text-slate-500">현재 상태</span>
                        <span className={`font-semibold ${
                          selectedCandidate.status === "ACCEPTED" ? "text-emerald-400" : selectedCandidate.status === "REJECTED" ? "text-rose-400" : "text-amber-400"
                        }`}>
                          {selectedCandidate.status === "ACCEPTED" ? "✓ 승인 (1 EA 반영)" : selectedCandidate.status === "REJECTED" ? "✕ 제외됨 (0 EA)" : "대기 중 (0 EA)"}
                        </span>
                      </div>
                      <div className="col-span-2">
                        <span className="block text-[10px] uppercase tracking-wider text-slate-500">좌표계 / 위치</span>
                        <span className="text-slate-300">
                          {selectedCandidate.coordinate_space} ({selectedCandidate.x}, {selectedCandidate.y})
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 pt-2">
                      <button
                        onClick={() =>
                          handleCandidateReview({
                            updates: [
                              {
                                candidate_id: selectedCandidate.candidate_id,
                                status: "ACCEPTED",
                                reviewed_item_code: selectedCandidate.reviewed_item_code || selectedCandidate.suggested_item_code,
                                review_note: "검수 승인",
                              },
                            ],
                          })
                        }
                        disabled={isSaving}
                        className="flex-1 py-2 px-3 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-medium text-xs flex items-center justify-center gap-1.5 transition shadow"
                      >
                        <Check size={14} />
                        <span>승인 (1 EA 반영)</span>
                      </button>
                      <button
                        onClick={() =>
                          handleCandidateReview({
                            updates: [
                              {
                                candidate_id: selectedCandidate.candidate_id,
                                status: "REJECTED",
                                review_note: "검수 제외",
                              },
                            ],
                          })
                        }
                        disabled={isSaving}
                        className="flex-1 py-2 px-3 bg-rose-600/80 hover:bg-rose-500 text-white rounded font-medium text-xs flex items-center justify-center gap-1.5 transition shadow"
                      >
                        <X size={14} />
                        <span>거부 (제외)</span>
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Selected Vector Feature Inspection Card (PR C) */}
              {selectedFeature &&
                selectedFeature.page_index === currentPageIndex &&
                currentDrawing && (
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

              {/* User-Defined Visual Symbol Search Modal (Issue #29 Workstream B) */}
              {cropModalOpen && pendingCropBbox && (
                <div
                  data-testid="symbol-search-modal"
                  className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
                >
                  <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl max-w-md w-full p-5 text-slate-100 space-y-4 animate-in fade-in zoom-in-95 duration-150">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <div className="p-1.5 rounded-lg bg-sky-500/20 text-sky-400 border border-sky-500/30">
                          <Crop size={18} />
                        </div>
                        <div>
                          <h3 className="text-sm font-semibold text-slate-100">사용자 지정 기호 검색</h3>
                          <p className="text-[11px] text-slate-400">지정한 영역의 기호와 유사한 패턴을 도면 전체에서 검색합니다.</p>
                        </div>
                      </div>
                      <button
                        onClick={() => {
                          setCropModalOpen(false);
                          setPendingCropBbox(null);
                        }}
                        className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition"
                      >
                        <X size={16} />
                      </button>
                    </div>

                    {/* Selected Bbox Info */}
                    <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono text-slate-300 flex items-center justify-between">
                      <span>선택 영역 (BBox)</span>
                      <span className="text-sky-300">
                        [{pendingCropBbox[0]}, {pendingCropBbox[1]}] ~ [{pendingCropBbox[2]}, {pendingCropBbox[3]}]
                        <span className="text-slate-400 ml-1.5 font-sans">
                          ({Math.round(pendingCropBbox[2] - pendingCropBbox[0])} × {Math.round(pendingCropBbox[3] - pendingCropBbox[1])}
                          {currentDrawing?.source_type === "PDF" ? " pt" : " px"})
                        </span>
                      </span>
                    </div>

                    {/* Item Code Selection */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-slate-300 block">탐지 기호 품목 매핑</label>
                      <select
                        value={cropSearchItemCode}
                        onChange={(e) => setCropSearchItemCode(e.target.value)}
                        data-testid="select-crop-search-item"
                        className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
                      >
                        <option value="LIGHT">LIGHT (조명 설비)</option>
                        <option value="OUTLET">OUTLET (콘센트 설비)</option>
                        <option value="SWITCH">SWITCH (스위치 설비)</option>
                        <option value="PANEL">PANEL (분전반)</option>
                        {availableItems
                          .filter((i) => !["LIGHT", "OUTLET", "SWITCH", "PANEL", "EXCLUDE", "UNMAPPED"].includes(i.code))
                          .map((i) => (
                            <option key={i.code} value={i.code}>
                              {i.code} ({i.name || i.code})
                            </option>
                          ))}
                      </select>
                    </div>

                    {/* Similarity Threshold Slider */}
                    <div className="space-y-1.5">
                      <div className="flex justify-between text-xs">
                        <span className="font-medium text-slate-300">유사도 임계값 (Threshold)</span>
                        <span className="font-mono text-sky-400 font-semibold">{Math.round(cropSearchThreshold * 100)}%</span>
                      </div>
                      <input
                        type="range"
                        min="50"
                        max="95"
                        step="5"
                        value={Math.round(cropSearchThreshold * 100)}
                        onChange={(e) => setCropSearchThreshold(Number(e.target.value) / 100)}
                        data-testid="input-crop-threshold"
                        className="w-full accent-sky-500 cursor-pointer"
                      />
                      <div className="flex justify-between text-[10px] text-slate-400 font-mono">
                        <span>50% (넓은 검출)</span>
                        <span>75% (권장 표준)</span>
                        <span>95% (엄격한 일치)</span>
                      </div>
                    </div>

                    {/* Options */}
                    <div className="space-y-2 pt-1 border-t border-slate-800 text-xs text-slate-300">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={cropSearchIncludeRotations}
                          onChange={(e) => setCropSearchIncludeRotations(e.target.checked)}
                          className="rounded border-slate-700 text-sky-600 focus:ring-sky-500 bg-slate-950"
                        />
                        <span>90° / 180° / 270° 회전된 기호도 함께 검색 (권장)</span>
                      </label>

                      {currentDrawing?.source_type === "PDF" && (
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={cropSearchAllPages}
                            onChange={(e) => setCropSearchAllPages(e.target.checked)}
                            className="rounded border-slate-700 text-sky-600 focus:ring-sky-500 bg-slate-950"
                          />
                          <span>전체 페이지 일괄 검색</span>
                        </label>
                      )}
                    </div>

                    {/* Footer buttons */}
                    <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
                      <button
                        onClick={() => {
                          setCropModalOpen(false);
                          setPendingCropBbox(null);
                        }}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition"
                      >
                        취소
                      </button>
                      <button
                        onClick={handleRunSymbolSearch}
                        disabled={isSearchingSymbols}
                        data-testid="btn-submit-symbol-search"
                        className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-sky-600 hover:bg-sky-500 text-white shadow-md shadow-sky-600/30 disabled:opacity-50 transition"
                      >
                        <Sparkles size={14} className={isSearchingSymbols ? "animate-spin" : ""} />
                        {isSearchingSymbols ? "기호 검색 중..." : "유사 기호 탐지"}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Right Panel: Split with Tabs (Takeoff, Mapping, Layers) */}
            <div className="w-[480px] h-full flex flex-col border-l border-slate-800 bg-slate-900 shrink-0">
              {/* Top Tab Bar */}
              <div className="flex items-center border-b border-slate-800 bg-slate-950/80 px-1 text-xs">
                <button
                  onClick={() => setActiveRightTab("takeoff")}
                  className={`flex items-center gap-1.5 py-3 px-3 border-b-2 font-medium transition ${
                    activeRightTab === "takeoff"
                      ? "border-emerald-500 text-emerald-400"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <TableProperties size={14} />
                  물량산출표
                </button>
                <button
                  onClick={() => setActiveRightTab("candidates")}
                  className={`flex items-center gap-1.5 py-3 px-3 border-b-2 font-medium transition ${
                    activeRightTab === "candidates"
                      ? "border-sky-500 text-sky-400"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Sparkles size={14} />
                  기호 검수 ({candidates.length})
                </button>
                <button
                  onClick={() => setActiveRightTab("mapping")}
                  className={`flex items-center gap-1.5 py-3 px-3 border-b-2 font-medium transition ${
                    activeRightTab === "mapping"
                      ? "border-indigo-500 text-indigo-400"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Tags size={14} />
                  블록 매핑
                </button>
                <button
                  onClick={() => setActiveRightTab("layers")}
                  className={`flex items-center gap-1.5 py-3 px-3 border-b-2 font-medium transition ${
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
                {activeRightTab === "candidates" && (
                  <CandidateReviewTable
                    candidates={candidates}
                    availableItems={availableItems}
                    isDetecting={isDetecting}
                    selectedCandidateId={selectedCandidate?.candidate_id || null}
                    onDetect={handleRunDetection}
                    onReview={handleCandidateReview}
                    onSelectCandidate={(cand) => setSelectedCandidate(cand)}
                    isSaving={isSaving}
                    isCropSearchMode={isCropSearchMode}
                    onToggleCropSearch={() => setIsCropSearchMode((prev) => !prev)}
                  />
                )}
                {activeRightTab === "takeoff" && takeoff && (
                  <TakeoffTable
                    takeoff={takeoff}
                    selectedItemCode={highlightedItemCode}
                    selectedObjectId={selectedObjectId}
                    onSelectItemCode={(code) => setHighlightedItemCode(code)}
                    onSelectEvidence={handleSelectEvidence}
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
                      projectId={currentProject?.id}
                      drawingId={currentDrawing.drawing_id}
                      onSaveMappings={handleSaveMappings}
                      onReloadMappings={handleReloadMappings}
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

              <div className="flex items-center gap-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={handleSeedMultiDrawingDemo}
                  disabled={isLoading}
                  className="flex-1 py-2 bg-indigo-600/90 hover:bg-indigo-600 text-white rounded-lg text-xs font-semibold shadow transition flex items-center justify-center gap-1.5"
                  title="다중 도면 리비전 통합 데모 (Issue #35)"
                >
                  <Sparkles size={13} />
                  다중 도면 데모
                </button>
                <button
                  type="button"
                  onClick={handleSeedDemo}
                  disabled={isLoading}
                  className="flex-1 py-2 bg-emerald-600/90 hover:bg-emerald-600 text-white rounded-lg text-xs font-semibold shadow transition flex items-center justify-center gap-1.5"
                  title="실전 종합 데모 (CAD·PDF·이미지)"
                >
                  <Play size={13} />
                  종합 실전 데모
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
