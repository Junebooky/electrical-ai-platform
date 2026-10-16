"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Layers,
  FileText,
  GitCompare,
  Download,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Play,
  ArrowRight,
  FileSpreadsheet,
  Building,
  Check,
  X,
} from "lucide-react";
import {
  ProjectMetadata,
  ProjectTakeoffResult,
  DrawingScope,
  RevisionComparisonResult,
} from "@/types/cad";
import { api } from "@/lib/api";

interface ProjectOverviewProps {
  currentProject: ProjectMetadata;
  onOpenDrawing: (drawingId: string) => void;
  onRefreshProject?: () => void;
}

export function ProjectOverview({
  currentProject,
  onOpenDrawing,
  onRefreshProject,
}: ProjectOverviewProps) {
  const [activeTab, setActiveTab] = useState<"summary" | "register" | "diff">("summary");
  const [isLoading, setIsLoading] = useState(false);
  const [takeoffResult, setTakeoffResult] = useState<ProjectTakeoffResult | null>(null);
  const [scopes, setScopes] = useState<DrawingScope[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Revision comparison state
  const [baseDrawingId, setBaseDrawingId] = useState<string>("");
  const [compareDrawingId, setCompareDrawingId] = useState<string>("");
  const [diffResult, setDiffResult] = useState<RevisionComparisonResult | null>(null);
  const [isComparing, setIsComparing] = useState(false);

  // Load project takeoff & scopes
  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [tResult, sList] = await Promise.all([
        api.getProjectTakeoff(currentProject.id),
        api.getProjectScopes(currentProject.id),
      ]);
      setTakeoffResult(tResult);
      setScopes(sList);

      // Auto-select initial pair for diff if available
      if (sList.length >= 2) {
        const groups: Record<string, DrawingScope[]> = {};
        for (const s of sList) {
          if (!groups[s.sheet_key]) groups[s.sheet_key] = [];
          groups[s.sheet_key].push(s);
        }
        for (const list of Object.values(groups)) {
          if (list.length >= 2) {
            const sorted = [...list].sort((a, b) => a.revision.localeCompare(b.revision));
            setBaseDrawingId((prev) => prev || sorted[0].drawing_id);
            setCompareDrawingId((prev) => prev || sorted[1].drawing_id);
            break;
          }
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
    }
  }, [currentProject.id]);

  useEffect(() => {
    let ignore = false;
    async function init() {
      try {
        const [tResult, sList] = await Promise.all([
          api.getProjectTakeoff(currentProject.id),
          api.getProjectScopes(currentProject.id),
        ]);
        if (ignore) return;
        setTakeoffResult(tResult);
        setScopes(sList);
        if (sList.length >= 2) {
          const groups: Record<string, DrawingScope[]> = {};
          for (const s of sList) {
            if (!groups[s.sheet_key]) groups[s.sheet_key] = [];
            groups[s.sheet_key].push(s);
          }
          for (const list of Object.values(groups)) {
            if (list.length >= 2) {
              const sorted = [...list].sort((a, b) => a.revision.localeCompare(b.revision));
              setBaseDrawingId((prev) => prev || sorted[0].drawing_id);
              setCompareDrawingId((prev) => prev || sorted[1].drawing_id);
              break;
            }
          }
        }
      } catch (err: unknown) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }
    init();
    return () => {
      ignore = true;
    };
  }, [currentProject.id]);

  // Handle revision comparison
  const handleRunDiff = async () => {
    if (!baseDrawingId || !compareDrawingId || baseDrawingId === compareDrawingId) {
      return;
    }
    setIsComparing(true);
    setError(null);
    try {
      const res = await api.compareRevisions(currentProject.id, baseDrawingId, compareDrawingId);
      setDiffResult(res);
    } catch (err: unknown) {
      setError("설계변경 비교 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsComparing(false);
    }
  };

  useEffect(() => {
    let ignore = false;
    if (activeTab === "diff" && baseDrawingId && compareDrawingId && baseDrawingId !== compareDrawingId) {
      api.compareRevisions(currentProject.id, baseDrawingId, compareDrawingId)
        .then((res) => {
          if (!ignore) setDiffResult(res);
        })
        .catch((err: unknown) => {
          if (!ignore) {
            setError("설계변경 비교 실패: " + (err instanceof Error ? err.message : String(err)));
          }
        });
    }
    return () => {
      ignore = true;
    };
  }, [activeTab, baseDrawingId, compareDrawingId, currentProject.id]);

  // Activate Revision handler
  const handleActivateRevision = async (drawingId: string) => {
    setIsLoading(true);
    setError(null);
    try {
      await api.activateRevision(currentProject.id, drawingId, true);
      await loadData();
      if (onRefreshProject) onRefreshProject();
    } catch (err: unknown) {
      setError("REV 활성화 변경 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsLoading(false);
    }
  };

  // 1-Click Multi-Drawing Demo Seed
  const handleSeedDemo = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await api.seedMultiDrawingDemo(true);
      await loadData();
      if (onRefreshProject) onRefreshProject();
    } catch (err: unknown) {
      setError("데모 시드 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsLoading(false);
    }
  };

  // 1-Click Route Oracle Demo Seed (Issue #37)
  const handleSeedRouteOracle = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.seedRouteOracleDemo(true);
      if (onRefreshProject) onRefreshProject();
      onOpenDrawing(res.drawing_id);
    } catch (err: unknown) {
      setError("경로 오라클 데모 시드 실패: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsLoading(false);
    }
  };

  const totalLightQty =
    takeoffResult?.summary.find((r) => r.item_code === "LIGHT")?.total_quantity || 0;

  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100 overflow-y-auto">
      {/* Top Header & Project Overview Stats */}
      <div className="p-6 border-b border-slate-800 bg-slate-900/60 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-5">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-br from-indigo-500/20 to-sky-500/20 border border-indigo-500/30 text-indigo-400">
              <Building size={22} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-slate-100">{currentProject.name}</h1>
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">
                  프로젝트 전체 통합 적산
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                다중 도면 스코프 지정, 독립 층/구역 합산, REV 교체(14→18/+4), 축척 보정·2D 경로 측정 및 엑셀 내보내기
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={handleSeedRouteOracle}
              disabled={isLoading}
              data-testid="btn-seed-route-oracle"
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow transition"
              title="축척 보정(100px=10m) 및 7.00m 배선 경로 오라클 데모 로드"
            >
              <Play size={13} className="fill-current" />
              <span>2D 경로 오라클 데모 (7m)</span>
            </button>

            <button
              onClick={handleSeedDemo}
              disabled={isLoading}
              data-testid="btn-seed-multi-demo"
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow transition"
              title="1F REV0(6) + 2F(8) = 14 / REV1(10) = 18(+4) 실전 데모 데이터 로드"
            >
              <Play size={13} className="fill-current" />
              <span>실전 다중 도면 데모 시드</span>
            </button>

            <button
              onClick={loadData}
              disabled={isLoading}
              className="p-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 rounded-lg text-xs transition border border-slate-700"
              title="데이터 새로고침"
            >
              <RefreshCw size={14} className={isLoading ? "animate-spin" : ""} />
            </button>

            <a
              href={api.getProjectExportXlsxUrl(currentProject.id)}
              download
              data-testid="btn-export-project-xlsx"
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow transition shadow-indigo-600/20"
            >
              <FileSpreadsheet size={14} />
              <span>엑셀 다운로드 (XLSX)</span>
            </a>
          </div>
        </div>

        {/* Scope Warnings Banner */}
        {takeoffResult && takeoffResult.scope_warnings.length > 0 && (
          <div className="mb-4 p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl text-amber-300 text-xs flex items-start gap-2.5">
            <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <span className="font-semibold block">도면 스코프 충돌 경고:</span>
              {takeoffResult.scope_warnings.map((w, idx) => (
                <div key={idx} className="text-amber-200/90">
                  • {w}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Metric KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3">
            <span className="block text-[11px] font-medium text-slate-400">활성 도면 / 전체 도면</span>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span
                data-testid="metric-active-drawings"
                className="text-xl font-bold text-sky-400"
              >
                {takeoffResult?.total_active_drawings || 0}
              </span>
              <span className="text-xs text-slate-500">
                / {scopes.length}개 도면
              </span>
            </div>
          </div>

          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3">
            <span className="block text-[11px] font-medium text-slate-400">기구 총 수량 (EA)</span>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span
                data-testid="metric-equipment-total-ea"
                className="text-xl font-bold text-emerald-400"
              >
                {takeoffResult?.total_equipment_ea ?? totalLightQty}
              </span>
              <span
                data-testid="metric-light-total-qty"
                className="text-xs text-slate-400 font-medium"
              >
                EA
              </span>
            </div>
          </div>

          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3">
            <span className="block text-[11px] font-medium text-slate-400">2D 계획 경로 총 연장 (m)</span>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span
                data-testid="metric-route-total-length-m"
                className="text-xl font-bold text-amber-400"
              >
                {typeof takeoffResult?.total_route_length_m === "number"
                  ? takeoffResult.total_route_length_m.toFixed(1)
                  : "0.0"}
              </span>
              <span className="text-xs text-amber-400/80 font-medium">m (잠정)</span>
            </div>
          </div>

          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3">
            <span className="block text-[11px] font-medium text-slate-400">집계 품목 가짓수</span>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span className="text-xl font-bold text-purple-400">
                {takeoffResult?.summary.length || 0}
              </span>
              <span className="text-xs text-slate-500">개 항목</span>
            </div>
          </div>

          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3">
            <span className="block text-[11px] font-medium text-slate-400">산출 상태</span>
            <div className="flex items-center gap-1.5 mt-1.5">
              {takeoffResult?.is_provisional ? (
                <span className="px-2 py-0.5 rounded text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1">
                  <AlertTriangle size={12} />
                  잠정 (검수 필요)
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1">
                  <CheckCircle2 size={12} />
                  검수 확정
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 mt-5 border-b border-slate-800">
          <button
            onClick={() => setActiveTab("summary")}
            data-testid="tab-project-summary"
            className={`flex items-center gap-2 px-4 py-2 text-xs font-semibold border-b-2 transition -mb-[1px] ${
              activeTab === "summary"
                ? "border-indigo-500 text-indigo-400 bg-indigo-500/10"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Layers size={14} />
            <span>프로젝트 총괄 집계표</span>
          </button>

          <button
            onClick={() => setActiveTab("register")}
            data-testid="tab-drawing-register"
            className={`flex items-center gap-2 px-4 py-2 text-xs font-semibold border-b-2 transition -mb-[1px] ${
              activeTab === "register"
                ? "border-indigo-500 text-indigo-400 bg-indigo-500/10"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <FileText size={14} />
            <span>도면 등록부 및 REV 관리</span>
          </button>

          <button
            onClick={() => setActiveTab("diff")}
            data-testid="tab-revision-diff"
            className={`flex items-center gap-2 px-4 py-2 text-xs font-semibold border-b-2 transition -mb-[1px] ${
              activeTab === "diff"
                ? "border-indigo-500 text-indigo-400 bg-indigo-500/10"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <GitCompare size={14} />
            <span>설계변경 비교 (Revision Diff)</span>
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="p-6 flex-1">
        {error && (
          <div className="mb-4 p-3 bg-rose-950/40 border border-rose-800 text-rose-300 rounded-lg text-xs">
            {error}
          </div>
        )}

        {/* Tab 1: Project Takeoff Summary */}
        {activeTab === "summary" && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-bold text-slate-200">
                  프로젝트 통합 산출 집계표 (활성 도면 기준)
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  단위가 다른 값(EA, m, m²)은 절대 혼합하지 않고 분리 집계합니다.
                </p>
              </div>

              <div className="flex items-center gap-2 text-xs">
                <a
                  href={api.getProjectExportCsvUrl(currentProject.id, "summary")}
                  download
                  className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded transition flex items-center gap-1"
                >
                  <Download size={12} />
                  <span>요약 CSV</span>
                </a>
                <a
                  href={api.getProjectExportCsvUrl(currentProject.id, "breakdown")}
                  download
                  className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded transition flex items-center gap-1"
                >
                  <Download size={12} />
                  <span>도면별 내역 CSV</span>
                </a>
              </div>
            </div>

            <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/50">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-900 text-slate-400 border-b border-slate-800 text-[11px] font-semibold uppercase">
                  <tr>
                    <th className="py-2.5 px-4 w-12 text-center">순번</th>
                    <th className="py-2.5 px-4">품목코드</th>
                    <th className="py-2.5 px-4">품목명</th>
                    <th className="py-2.5 px-4">규격</th>
                    <th className="py-2.5 px-4 text-center">단위</th>
                    <th className="py-2.5 px-4 text-right">총 산출수량</th>
                    <th className="py-2.5 px-4 text-center">활성 도면 수</th>
                    <th className="py-2.5 px-4 text-center">산출 방식</th>
                    <th className="py-2.5 px-4 text-center">검수 상태</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {takeoffResult?.summary.map((row, idx) => (
                    <tr
                      key={idx}
                      className="hover:bg-slate-800/40 transition"
                      data-testid={`project-takeoff-row-${row.item_code}`}
                    >
                      <td className="py-2.5 px-4 text-center text-slate-500 font-mono">
                        {idx + 1}
                      </td>
                      <td className="py-2.5 px-4 font-mono font-bold text-sky-400">
                        {row.item_code}
                      </td>
                      <td className="py-2.5 px-4 text-slate-200">{row.item_name}</td>
                      <td className="py-2.5 px-4 text-slate-400 font-mono text-[11px]">
                        {row.specification}
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                          {row.unit}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-right font-mono font-bold text-sm text-emerald-400">
                        {row.total_quantity}
                      </td>
                      <td className="py-2.5 px-4 text-center font-mono text-slate-300">
                        {row.active_drawings_count}개
                      </td>
                      <td className="py-2.5 px-4 text-center text-slate-400 text-[11px]">
                        {row.quantity_method}
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        {row.review_status === "REVIEWED" ? (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                            승인 완료
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/40">
                            검수 필요
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}

                  {(!takeoffResult || takeoffResult.summary.length === 0) && (
                    <tr>
                      <td colSpan={9} className="py-8 text-center text-slate-500">
                        활성화된 도면의 산출 결과가 없습니다.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Drawing Breakdown Section */}
            <div>
              <h3 className="text-xs font-bold text-slate-300 mb-3 flex items-center gap-1.5">
                <Building size={14} className="text-indigo-400" />
                <span>도면별 기여 물량 내역 (Drawings Breakdown)</span>
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {takeoffResult?.drawings_breakdown.map((dwg) => (
                  <div
                    key={dwg.drawing_id}
                    className="p-3.5 bg-slate-900 border border-slate-800 rounded-xl space-y-2"
                  >
                    <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                      <div className="flex items-center gap-2">
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-sky-950 text-sky-400 border border-sky-800">
                          {dwg.sheet_key}
                        </span>
                        <span className="text-xs font-semibold text-slate-200 truncate max-w-[180px]">
                          {dwg.filename}
                        </span>
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-950 text-purple-300 border border-purple-800">
                          {dwg.revision}
                        </span>
                      </div>
                      <button
                        onClick={() => onOpenDrawing(dwg.drawing_id)}
                        className="text-[11px] text-sky-400 hover:text-sky-300 flex items-center gap-1"
                      >
                        <span>도면 열기</span>
                        <ArrowRight size={12} />
                      </button>
                    </div>

                    <div className="flex flex-wrap gap-2 pt-1">
                      {dwg.items.map((itm, i) => (
                        <div
                          key={i}
                          className="px-2 py-1 rounded bg-slate-800/70 border border-slate-700/60 text-xs flex items-center gap-2"
                        >
                          <span className="text-slate-400 font-mono">{itm.item_code}:</span>
                          <span className="font-bold text-emerald-400 font-mono">
                            {itm.quantity} {itm.unit}
                          </span>
                        </div>
                      ))}
                      {dwg.items.length === 0 && (
                        <span className="text-xs text-slate-500">산출 항목 없음</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Drawing Register & Scope Management */}
        {activeTab === "register" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-bold text-slate-200">
                  도면 등록부 및 Revision 관리 (Drawing Register)
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  동일 도면 그룹(sheet_key) 당 산출 활성 REV는 최대 1개만 지정됩니다.
                  신규 REV 활성화 시 이전 REV는 보존된 채 프로젝트 총합에서 안전하게 자동 제외됩니다.
                </p>
              </div>
            </div>

            <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/50">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-900 text-slate-400 border-b border-slate-800 text-[11px] font-semibold uppercase">
                  <tr>
                    <th className="py-2.5 px-4">도면 그룹 (Key)</th>
                    <th className="py-2.5 px-4 text-center">층 (Floor)</th>
                    <th className="py-2.5 px-4">공종 (Discipline)</th>
                    <th className="py-2.5 px-4 text-center">REV</th>
                    <th className="py-2.5 px-4">시트 역할 (Role)</th>
                    <th className="py-2.5 px-4 text-center">산출 활성 상태</th>
                    <th className="py-2.5 px-4">도면 설명</th>
                    <th className="py-2.5 px-4 text-right">조치</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {scopes.map((s) => (
                    <tr
                      key={s.drawing_id}
                      className={`hover:bg-slate-800/40 transition ${
                        s.active_for_takeoff ? "bg-indigo-950/10" : ""
                      }`}
                      data-testid={`drawing-scope-row-${s.drawing_id}`}
                    >
                      <td className="py-3 px-4 font-mono font-bold text-sky-400">
                        {s.sheet_key}
                      </td>
                      <td className="py-3 px-4 text-center font-mono">{s.floor}</td>
                      <td className="py-3 px-4 text-slate-300 font-mono text-[11px]">
                        {s.discipline}
                      </td>
                      <td className="py-3 px-4 text-center font-mono font-bold text-purple-400">
                        {s.revision}
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${
                            s.sheet_role === "INSTALLATION"
                              ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                              : s.sheet_role === "REFERENCE"
                              ? "bg-slate-800 text-slate-400 border-slate-700"
                              : "bg-amber-500/10 text-amber-300 border-amber-500/30"
                          }`}
                        >
                          {s.sheet_role === "INSTALLATION"
                            ? "시공/배치도"
                            : s.sheet_role === "REFERENCE"
                            ? "참고/계통도"
                            : s.sheet_role}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-center">
                        {s.active_for_takeoff ? (
                          <span
                            data-testid={`status-active-${s.drawing_id}`}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                          >
                            <Check size={11} />
                            산출 활성
                          </span>
                        ) : (
                          <span
                            data-testid={`status-inactive-${s.drawing_id}`}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700"
                          >
                            <X size={11} />
                            산출 제외
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-slate-400 truncate max-w-[200px]">
                        {s.description}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {!s.active_for_takeoff && (
                            <button
                              onClick={() => handleActivateRevision(s.drawing_id)}
                              disabled={isLoading}
                              data-testid={`btn-activate-rev-${s.drawing_id}`}
                              className="px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded text-[11px] font-semibold transition"
                            >
                              활성 REV로 교체
                            </button>
                          )}
                          <button
                            onClick={() => onOpenDrawing(s.drawing_id)}
                            className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-[11px] transition"
                          >
                            열기
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Tab 3: Revision Comparison (Diff) */}
        {activeTab === "diff" && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4 p-4 bg-slate-900 border border-slate-800 rounded-xl">
              <div>
                <h2 className="text-sm font-bold text-slate-200">
                  설계변경 수량 비교 (Revision Pragmatic Diff)
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  기준 REV와 비교 REV 간의 품목별 증감(+/-) 및 CAD 객체 위치 일치를 실시간 비교합니다.
                </p>
              </div>

              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-slate-400 font-medium">기준(이전) REV:</span>
                  <select
                    value={baseDrawingId}
                    onChange={(e) => setBaseDrawingId(e.target.value)}
                    data-testid="select-base-drawing"
                    className="bg-slate-950 border border-slate-700 rounded px-2.5 py-1 text-slate-200 text-xs"
                  >
                    {scopes.map((s) => (
                      <option key={s.drawing_id} value={s.drawing_id}>
                        {s.sheet_key} ({s.revision}) - {s.description}
                      </option>
                    ))}
                  </select>
                </div>

                <ArrowRight size={16} className="text-slate-600" />

                <div className="flex items-center gap-2 text-xs">
                  <span className="text-slate-400 font-medium">비교(신규) REV:</span>
                  <select
                    value={compareDrawingId}
                    onChange={(e) => setCompareDrawingId(e.target.value)}
                    data-testid="select-compare-drawing"
                    className="bg-slate-950 border border-slate-700 rounded px-2.5 py-1 text-slate-200 text-xs"
                  >
                    {scopes.map((s) => (
                      <option key={s.drawing_id} value={s.drawing_id}>
                        {s.sheet_key} ({s.revision}) - {s.description}
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  onClick={handleRunDiff}
                  disabled={isComparing || baseDrawingId === compareDrawingId}
                  data-testid="btn-run-diff"
                  className="px-3.5 py-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded text-xs font-semibold shadow transition"
                >
                  {isComparing ? "비교 계산 중..." : "비교 실행"}
                </button>
              </div>
            </div>

            {diffResult && (
              <div className="space-y-4">
                {/* Diff KPI Summary Cards */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3">
                    <span className="block text-[11px] text-slate-400">
                      기준 수량 ({diffResult.base_drawing.revision})
                    </span>
                    <span className="text-xl font-bold text-slate-300 font-mono mt-1 block">
                      {diffResult.total_base_qty} EA
                    </span>
                  </div>

                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3">
                    <span className="block text-[11px] text-slate-400">
                      변경 수량 ({diffResult.compare_drawing.revision})
                    </span>
                    <span className="text-xl font-bold text-indigo-400 font-mono mt-1 block">
                      {diffResult.total_compare_qty} EA
                    </span>
                  </div>

                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3">
                    <span className="block text-[11px] text-slate-400">총 증감량 (Delta)</span>
                    <span
                      data-testid="metric-diff-delta"
                      className={`text-xl font-bold font-mono mt-1 block ${
                        diffResult.total_delta > 0
                          ? "text-emerald-400"
                          : diffResult.total_delta < 0
                          ? "text-rose-400"
                          : "text-slate-400"
                      }`}
                    >
                      {diffResult.total_delta > 0 ? `+${diffResult.total_delta}` : diffResult.total_delta} EA
                    </span>
                  </div>
                </div>

                {/* Items Delta Table */}
                <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/50">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-900 text-slate-400 border-b border-slate-800 text-[11px] font-semibold uppercase">
                      <tr>
                        <th className="py-2.5 px-4">품목코드</th>
                        <th className="py-2.5 px-4">품목명</th>
                        <th className="py-2.5 px-4">규격</th>
                        <th className="py-2.5 px-4 text-center">단위</th>
                        <th className="py-2.5 px-4 text-right">기준 수량</th>
                        <th className="py-2.5 px-4 text-right">변경 수량</th>
                        <th className="py-2.5 px-4 text-right">증감 (Delta)</th>
                        <th className="py-2.5 px-4 text-center">변경 유형</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {diffResult.items_delta.map((row, idx) => (
                        <tr
                          key={idx}
                          className="hover:bg-slate-800/40 transition"
                          data-testid={`diff-row-${row.item_code}`}
                        >
                          <td className="py-2.5 px-4 font-mono font-bold text-sky-400">
                            {row.item_code}
                          </td>
                          <td className="py-2.5 px-4 text-slate-200">{row.item_name}</td>
                          <td className="py-2.5 px-4 text-slate-400 font-mono text-[11px]">
                            {row.specification}
                          </td>
                          <td className="py-2.5 px-4 text-center font-mono">{row.unit}</td>
                          <td className="py-2.5 px-4 text-right font-mono text-slate-400">
                            {row.base_quantity}
                          </td>
                          <td className="py-2.5 px-4 text-right font-mono text-slate-200">
                            {row.compare_quantity}
                          </td>
                          <td
                            className={`py-2.5 px-4 text-right font-mono font-bold ${
                              row.delta > 0
                                ? "text-emerald-400"
                                : row.delta < 0
                                ? "text-rose-400"
                                : "text-slate-500"
                            }`}
                          >
                            {row.delta > 0 ? `+${row.delta}` : row.delta}
                          </td>
                          <td className="py-2.5 px-4 text-center">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                                row.change_type === "INCREASED"
                                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                  : row.change_type === "DECREASED"
                                  ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                                  : row.change_type === "ADDED"
                                  ? "bg-sky-500/20 text-sky-300 border border-sky-500/30"
                                  : "bg-slate-800 text-slate-400"
                              }`}
                            >
                              {row.change_type === "INCREASED"
                                ? "수량 증가"
                                : row.change_type === "DECREASED"
                                ? "수량 감소"
                                : row.change_type === "ADDED"
                                ? "신규 추가"
                                : "변경 없음"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Object-Level Correspondence Details */}
                <div>
                  <h3 className="text-xs font-bold text-slate-300 mb-2 flex items-center gap-1.5">
                    <CheckCircle2 size={13} className="text-emerald-400" />
                    <span>객체 단위 정밀 Correspondence 추적</span>
                  </h3>
                  <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/40 max-h-56 overflow-y-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-900 text-slate-400 text-[10px] uppercase font-semibold sticky top-0">
                        <tr>
                          <th className="py-2 px-3">객체 ID</th>
                          <th className="py-2 px-3">품목코드</th>
                          <th className="py-2 px-3 text-right">X 좌표</th>
                          <th className="py-2 px-3 text-right">Y 좌표</th>
                          <th className="py-2 px-3">레이어</th>
                          <th className="py-2 px-3 text-center">매칭 판정</th>
                          <th className="py-2 px-3">비고</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/50 font-mono text-[11px]">
                        {diffResult.object_deltas.map((obj, i) => (
                          <tr key={i} className="hover:bg-slate-800/30">
                            <td className="py-1.5 px-3 text-slate-400 truncate max-w-[120px]">
                              {obj.object_id}
                            </td>
                            <td className="py-1.5 px-3 text-sky-400 font-bold">{obj.item_code}</td>
                            <td className="py-1.5 px-3 text-right text-slate-300">
                              {obj.x.toFixed(1)}
                            </td>
                            <td className="py-1.5 px-3 text-right text-slate-300">
                              {obj.y.toFixed(1)}
                            </td>
                            <td className="py-1.5 px-3 text-slate-400">{obj.layer}</td>
                            <td className="py-1.5 px-3 text-center font-sans">
                              {obj.match_status === "MATCHED" ? (
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-emerald-950/60 text-emerald-400 border border-emerald-800">
                                  일치 (MATCHED)
                                </span>
                              ) : obj.match_status === "ADDED" ? (
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-sky-950/60 text-sky-400 border border-sky-800">
                                  신규 추가 (ADDED)
                                </span>
                              ) : obj.match_status === "PROPOSED_MATCH" ? (
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-950/60 text-amber-400 border border-amber-800">
                                  추정/검토 필요
                                </span>
                              ) : (
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-rose-950/60 text-rose-400 border border-rose-800">
                                  삭제됨 (REMOVED)
                                </span>
                              )}
                            </td>
                            <td className="py-1.5 px-3 font-sans text-slate-400">{obj.notes}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
