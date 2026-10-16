"use client";

import React, { useState, useEffect } from "react";
import {
  SymbolCandidate,
  CandidateStatus,
  CandidateBulkReviewRequest,
  DetectionSource,
} from "@/types/cad";
import {
  Sparkles,
  Check,
  X,
  RotateCcw,
  CheckCircle2,
  XCircle,
  Clock,
  Filter,
  Crop,
  Layers,
} from "lucide-react";

interface CandidateReviewTableProps {
  candidates: SymbolCandidate[];
  availableItems: { code: string; name: string; unit: string }[];
  isDetecting: boolean;
  selectedCandidateId: string | null;
  onDetect: () => Promise<void>;
  onReview: (req: CandidateBulkReviewRequest) => Promise<void>;
  onSelectCandidate: (candidate: SymbolCandidate | null) => void;
  isSaving: boolean;
  isCropSearchMode?: boolean;
  onToggleCropSearch?: () => void;
}

export function CandidateReviewTable({
  candidates,
  availableItems,
  isDetecting,
  selectedCandidateId,
  onDetect,
  onReview,
  onSelectCandidate,
  isSaving,
  isCropSearchMode = false,
  onToggleCropSearch,
}: CandidateReviewTableProps) {
  const [statusFilter, setStatusFilter] = useState<CandidateStatus | "ALL">("ALL");
  const [sourceFilter, setSourceFilter] = useState<DetectionSource | "ALL">("ALL");
  const [itemFilter, setItemFilter] = useState<string>("ALL");

  const totalCount = candidates.length;
  const proposedCount = candidates.filter((c) => c.status === "PROPOSED").length;
  const acceptedCount = candidates.filter((c) => c.status === "ACCEPTED").length;
  const rejectedCount = candidates.filter((c) => c.status === "REJECTED").length;

  const filteredCandidates = candidates.filter((c) => {
    if (statusFilter !== "ALL" && c.status !== statusFilter) return false;
    if (sourceFilter !== "ALL" && c.detection_source !== sourceFilter) return false;
    if (itemFilter !== "ALL" && (c.reviewed_item_code || c.suggested_item_code) !== itemFilter) {
      return false;
    }
    return true;
  });

  const uniqueItemCodes = Array.from(
    new Set(candidates.map((c) => c.reviewed_item_code || c.suggested_item_code))
  );

  // Workstream C: Keyboard shortcuts for professional review productivity ([A] Accept, [R] Reject, [↑/↓] Navigate)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLSelectElement ||
        e.target instanceof HTMLTextAreaElement
      ) {
        return;
      }

      if (e.key === "a" || e.key === "A") {
        const target = selectedCandidateId
          ? candidates.find((c) => c.candidate_id === selectedCandidateId)
          : filteredCandidates.find((c) => c.status === "PROPOSED");
        if (target && !isSaving) {
          e.preventDefault();
          onReview({
            updates: [
              {
                candidate_id: target.candidate_id,
                status: "ACCEPTED",
                reviewed_item_code: target.reviewed_item_code || target.suggested_item_code,
                review_note: "단축키 [A] 승인",
              },
            ],
          });
        }
      } else if (e.key === "r" || e.key === "R") {
        const target = selectedCandidateId
          ? candidates.find((c) => c.candidate_id === selectedCandidateId)
          : filteredCandidates.find((c) => c.status === "PROPOSED");
        if (target && !isSaving) {
          e.preventDefault();
          onReview({
            updates: [
              {
                candidate_id: target.candidate_id,
                status: "REJECTED",
                review_note: "단축키 [R] 제외",
              },
            ],
          });
        }
      } else if (e.key === "ArrowDown" || e.key === "j" || e.key === "J") {
        e.preventDefault();
        const currentIndex = filteredCandidates.findIndex(
          (c) => c.candidate_id === selectedCandidateId
        );
        if (currentIndex < filteredCandidates.length - 1) {
          onSelectCandidate(filteredCandidates[currentIndex + 1]);
        } else if (filteredCandidates.length > 0 && currentIndex === -1) {
          onSelectCandidate(filteredCandidates[0]);
        }
      } else if (e.key === "ArrowUp" || e.key === "k" || e.key === "K") {
        e.preventDefault();
        const currentIndex = filteredCandidates.findIndex(
          (c) => c.candidate_id === selectedCandidateId
        );
        if (currentIndex > 0) {
          onSelectCandidate(filteredCandidates[currentIndex - 1]);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedCandidateId, candidates, filteredCandidates, isSaving, onReview, onSelectCandidate]);

  return (
    <div className="flex flex-col h-full bg-slate-900 text-slate-200 select-none">
      {/* Header & Controls */}
      <div className="p-4 border-b border-slate-800 space-y-3 bg-slate-950/60">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="p-1.5 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/20">
              <Sparkles size={16} />
            </span>
            <div>
              <h3 className="text-sm font-semibold text-slate-100">AI 기호 탐지 & 검수</h3>
              <p className="text-[11px] text-slate-400">
                DXF·PDF·이미지 도면의 전기기구를 탐지하고 승인/거부합니다.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {onToggleCropSearch && (
              <button
                onClick={onToggleCropSearch}
                data-testid="btn-crop-search-toggle"
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition border ${
                  isCropSearchMode
                    ? "bg-sky-500 text-white border-sky-400 shadow-lg shadow-sky-500/30 animate-pulse"
                    : "bg-slate-800 hover:bg-slate-700 text-sky-300 border-slate-700"
                }`}
                title="도면에서 기호 영역을 마우스로 드래그하여 유사 기호를 검색합니다"
              >
                <Crop size={13} />
                <span>{isCropSearchMode ? "영역 지정 중..." : "기호 영역 검색"}</span>
              </button>
            )}

            <button
              onClick={() => onDetect()}
              disabled={isDetecting || isSaving}
              data-testid="btn-ai-detect"
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-md shadow-sky-600/20 transition"
            >
              <Sparkles size={14} className={isDetecting ? "animate-spin" : ""} />
              {isDetecting ? "기호 탐지 중..." : "AI 탐지 실행"}
            </button>
          </div>
        </div>

        {/* Metrics Bar */}
        <div className="grid grid-cols-4 gap-2 pt-1 text-center font-mono">
          <div className="bg-slate-900/90 border border-slate-800 rounded-lg p-2">
            <span className="block text-[10px] text-slate-400 uppercase tracking-wider">전체 탐지</span>
            <span className="text-sm font-bold text-slate-200">{totalCount}건</span>
          </div>
          <div className="bg-amber-950/30 border border-amber-900/40 rounded-lg p-2">
            <span className="block text-[10px] text-amber-400 uppercase tracking-wider">검수 대기</span>
            <span className="text-sm font-bold text-amber-300">{proposedCount}건</span>
          </div>
          <div className="bg-emerald-950/30 border border-emerald-900/40 rounded-lg p-2">
            <span className="block text-[10px] text-emerald-400 uppercase tracking-wider">승인 완료</span>
            <span className="text-sm font-bold text-emerald-300">{acceptedCount}건</span>
          </div>
          <div className="bg-rose-950/30 border border-rose-900/40 rounded-lg p-2">
            <span className="block text-[10px] text-rose-400 uppercase tracking-wider">제외/거부</span>
            <span className="text-sm font-bold text-rose-300">{rejectedCount}건</span>
          </div>
        </div>

        {/* Bulk Action Buttons */}
        {totalCount > 0 && (
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={() => onReview({ action: "ACCEPT_ALL" })}
              disabled={isSaving || proposedCount === 0}
              data-testid="btn-bulk-accept"
              className="flex-1 py-1.5 px-2 bg-emerald-600/90 hover:bg-emerald-500 disabled:opacity-40 text-white rounded text-xs font-medium flex items-center justify-center gap-1.5 transition shadow"
            >
              <CheckCircle2 size={13} />
              <span>대기 항목 전체 승인</span>
            </button>
            <button
              onClick={() => onReview({ action: "REJECT_ALL" })}
              disabled={isSaving || proposedCount === 0}
              data-testid="btn-bulk-reject"
              className="flex-1 py-1.5 px-2 bg-rose-600/80 hover:bg-rose-500 disabled:opacity-40 text-white rounded text-xs font-medium flex items-center justify-center gap-1.5 transition shadow"
            >
              <XCircle size={13} />
              <span>대기 항목 전체 거부</span>
            </button>
            <button
              onClick={() => onReview({ action: "RESET_ALL" })}
              disabled={isSaving}
              className="py-1.5 px-2.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-300 rounded text-xs font-medium flex items-center justify-center gap-1 transition"
              title="전체 대기 상태로 초기화"
            >
              <RotateCcw size={13} />
            </button>
          </div>
        )}

        {/* Filter Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs pt-1">
          <div className="flex items-center gap-1 bg-slate-900 px-1 py-0.5 rounded border border-slate-800">
            {(["ALL", "PROPOSED", "ACCEPTED", "REJECTED"] as const).map((st) => (
              <button
                key={st}
                onClick={() => setStatusFilter(st)}
                className={`px-2 py-0.5 rounded text-[11px] font-medium transition ${
                  statusFilter === st
                    ? "bg-slate-800 text-sky-300 shadow"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {st === "ALL" ? "전체" : st === "PROPOSED" ? "대기" : st === "ACCEPTED" ? "승인" : "거부"}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            {/* Detection Source Filter */}
            <div className="flex items-center gap-1 text-slate-400">
              <Layers size={11} />
              <select
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value as DetectionSource | "ALL")}
                className="bg-slate-950 text-slate-200 text-[11px] px-1.5 py-0.5 rounded border border-slate-800 focus:outline-none"
              >
                <option value="ALL">모든 출처</option>
                <option value="VISUAL_TEMPLATE">비주얼 템플릿</option>
                <option value="IMAGE_TEMPLATE">이미지 심볼</option>
                <option value="PDF_VECTOR_RULE">PDF 텍스트</option>
                <option value="DXF_BLOCK">DXF 블록</option>
              </select>
            </div>

            {uniqueItemCodes.length > 1 && (
              <div className="flex items-center gap-1 text-slate-400">
                <Filter size={11} />
                <select
                  value={itemFilter}
                  onChange={(e) => setItemFilter(e.target.value)}
                  className="bg-slate-950 text-slate-200 text-[11px] px-1.5 py-0.5 rounded border border-slate-800 focus:outline-none"
                >
                  <option value="ALL">모든 품목</option>
                  {uniqueItemCodes.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Domain Invariant Banner */}
      <div className="bg-sky-950/40 border-b border-sky-900/30 px-3.5 py-2 text-[11px] text-sky-200 flex items-start gap-2">
        <span className="text-sky-400 text-xs">ℹ️</span>
        <span className="leading-tight">
          <b>도메인 불변식</b>: 기호 후보는 <b>승인</b> 완료된 항목만 실제 물량산출(EA)에 합산됩니다. 대기 중인 후보는 물량에 포함되지 않습니다 (0 EA).
        </span>
      </div>

      {/* Candidates List Table */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-800/80">
        {filteredCandidates.length === 0 ? (
          <div className="p-8 text-center text-slate-500 text-xs flex flex-col items-center justify-center h-full">
            <Sparkles size={28} className="text-slate-600 mb-2" />
            <p className="font-medium text-slate-400 mb-1">탐지된 기호가 없습니다</p>
            <p className="text-[11px] text-slate-500 max-w-[260px]">
              상단의 <b>[AI 탐지 실행]</b> 버튼을 누르면 현재 도면에서 전기설비 기호 후보를 자동으로 추출합니다.
            </p>
          </div>
        ) : (
          filteredCandidates.map((cand) => {
            const isSelected = cand.candidate_id === selectedCandidateId;
            const effectiveCode = cand.reviewed_item_code || cand.suggested_item_code;
            const isAccepted = cand.status === "ACCEPTED";
            const isRejected = cand.status === "REJECTED";

            return (
              <div
                key={cand.candidate_id}
                data-testid="candidate-row"
                onClick={() => onSelectCandidate(cand)}
                className={`p-3 transition cursor-pointer flex flex-col gap-2 ${
                  isSelected
                    ? "bg-sky-950/40 border-l-4 border-sky-400"
                    : "hover:bg-slate-850 bg-slate-900/50"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase border ${
                        cand.detection_source === "VISUAL_TEMPLATE"
                          ? "bg-cyan-500/10 text-cyan-300 border-cyan-500/30"
                          : cand.detection_source === "DXF_BLOCK"
                          ? "bg-blue-500/10 text-blue-300 border-blue-500/30"
                          : cand.detection_source === "PDF_VECTOR_RULE"
                          ? "bg-purple-500/10 text-purple-300 border-purple-500/30"
                          : "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                      }`}
                    >
                      {cand.detection_source === "VISUAL_TEMPLATE"
                        ? "비주얼 템플릿"
                        : cand.detection_source === "DXF_BLOCK"
                        ? "DXF 블록"
                        : cand.detection_source === "PDF_VECTOR_RULE"
                        ? "PDF 텍스트"
                        : "이미지 심볼"}
                    </span>
                    <span className="text-xs font-semibold text-slate-200">
                      {cand.suggested_item_name}
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">
                      ({effectiveCode})
                    </span>
                  </div>

                  {/* Status Badge */}
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-semibold flex items-center gap-1 ${
                      isAccepted
                        ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                        : isRejected
                        ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                        : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                    }`}
                  >
                    {isAccepted ? (
                      <>
                        <Check size={10} /> 승인 (1 EA)
                      </>
                    ) : isRejected ? (
                      <>
                        <X size={10} /> 제외됨
                      </>
                    ) : (
                      <>
                        <Clock size={10} /> 대기 중
                      </>
                    )}
                  </span>
                </div>

                {/* Sub info: Coordinate, Page, Confidence */}
                <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono">
                  <div className="flex items-center gap-2">
                    <span>
                      P.{cand.page_index + 1}
                    </span>
                    <span>•</span>
                    <span>
                      ({cand.x}, {cand.y})
                    </span>
                    <span>•</span>
                    <span className="text-sky-300">
                      유사도 {Math.round(cand.confidence * 100)}%
                    </span>
                  </div>

                  {/* Inline Reclassify Dropdown */}
                  <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    <select
                      value={effectiveCode}
                      onChange={(e) => {
                        onReview({
                          updates: [
                            {
                              candidate_id: cand.candidate_id,
                              status: "ACCEPTED",
                              reviewed_item_code: e.target.value,
                              review_note: "품목 재분류 승인",
                            },
                          ],
                        });
                      }}
                      className="bg-slate-950 text-slate-300 text-[11px] px-1.5 py-0.5 rounded border border-slate-700 focus:outline-none"
                    >
                      <option value="LIGHT">LIGHT (조명)</option>
                      <option value="OUTLET">OUTLET (콘센트)</option>
                      <option value="SWITCH">SWITCH (스위치)</option>
                      <option value="PANEL">PANEL (분전반)</option>
                      {availableItems
                        .filter(
                          (i) =>
                            !["LIGHT", "OUTLET", "SWITCH", "PANEL", "EXCLUDE", "UNMAPPED"].includes(i.code)
                        )
                        .map((i) => (
                          <option key={i.code} value={i.code}>
                            {i.code} ({i.name || i.code})
                          </option>
                        ))}
                    </select>
                  </div>
                </div>

                {/* Inline Action Buttons */}
                <div className="flex items-center gap-2 pt-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() =>
                      onReview({
                        updates: [
                          {
                            candidate_id: cand.candidate_id,
                            status: "ACCEPTED",
                            reviewed_item_code: effectiveCode,
                            review_note: "검수 승인",
                          },
                        ],
                      })
                    }
                    disabled={isSaving}
                    className={`flex-1 py-1 px-2 rounded text-[11px] font-medium flex items-center justify-center gap-1 transition ${
                      isAccepted
                        ? "bg-emerald-600 text-white font-semibold"
                        : "bg-slate-800 hover:bg-emerald-600/80 text-slate-300 hover:text-white"
                    }`}
                  >
                    <Check size={12} />
                    <span>승인</span>
                  </button>

                  <button
                    onClick={() =>
                      onReview({
                        updates: [
                          {
                            candidate_id: cand.candidate_id,
                            status: "REJECTED",
                            review_note: "검수 제외",
                          },
                        ],
                      })
                    }
                    disabled={isSaving}
                    className={`flex-1 py-1 px-2 rounded text-[11px] font-medium flex items-center justify-center gap-1 transition ${
                      isRejected
                        ? "bg-rose-600 text-white font-semibold"
                        : "bg-slate-800 hover:bg-rose-600/80 text-slate-300 hover:text-white"
                    }`}
                  >
                    <X size={12} />
                    <span>거부</span>
                  </button>

                  {(isAccepted || isRejected) && (
                    <button
                      onClick={() =>
                        onReview({
                          updates: [
                            {
                              candidate_id: cand.candidate_id,
                              status: "PROPOSED",
                              review_note: "검수 대기 복원",
                            },
                          ],
                        })
                      }
                      disabled={isSaving}
                      title="대기 상태로 복원 (Undo)"
                      className="py-1 px-2 rounded text-[11px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-amber-300 transition flex items-center justify-center"
                    >
                      <RotateCcw size={12} />
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer domain notice & shortcuts */}
      <div className="p-2.5 border-t border-slate-800 bg-slate-950/80 text-[11px] text-slate-400 flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-amber-400">
            <Clock size={12} />
            <span>규칙 기반 후보 · 검수 전 0 EA 보장</span>
          </span>
          <span className="text-[10px] text-slate-400">승인 항목만 물량 반영</span>
        </div>
        <div className="flex items-center justify-between text-[10px] text-slate-400 border-t border-slate-800/60 pt-1 font-mono">
          <span>단축키: [A] 선택 승인 · [R] 선택 거부 · [↑/↓] 이동</span>
          <span>복원 아이콘으로 Undo 지원</span>
        </div>
      </div>
    </div>
  );
}
