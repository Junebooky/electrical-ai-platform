"use client";

import React, { useState } from "react";
import { TakeoffResult } from "@/types/cad";
import {
  FileSpreadsheet,
  Download,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  ListFilter,
} from "lucide-react";

interface TakeoffTableProps {
  takeoff: TakeoffResult;
  selectedItemCode: string | null;
  selectedObjectId?: string | null;
  onSelectItemCode: (code: string | null) => void;
  onSelectEvidence: (objectId: string) => void;
  csvSummaryUrl: string;
  csvEvidenceUrl: string;
  xlsxUrl: string;
}

export function TakeoffTable({
  takeoff,
  selectedItemCode,
  selectedObjectId,
  onSelectItemCode,
  onSelectEvidence,
  csvSummaryUrl,
  csvEvidenceUrl,
  xlsxUrl,
}: TakeoffTableProps) {
  const [activeTab, setActiveTab] = useState<"summary" | "evidence">("summary");
  const [evidenceFilter, setEvidenceFilter] = useState<string>("ALL");

  const totalQuantity = takeoff.summary.reduce((acc, row) => acc + row.quantity, 0);

  const filteredEvidence = takeoff.evidence.filter((ev) => {
    if (evidenceFilter === "ALL") return true;
    if (evidenceFilter === "INCLUDED") return ev.inclusion_status === "INCLUDED";
    if (evidenceFilter === "EXCLUDED") return ev.inclusion_status === "EXCLUDED";
    if (evidenceFilter === "MANUAL") return ev.inclusion_status === "MANUAL_ADDED";
    if (evidenceFilter === "UNRESOLVED") return ev.review_status === "UNRESOLVED";
    return true;
  });

  return (
    <div className="flex flex-col h-full bg-slate-900 border-l border-slate-800 text-slate-200">
      {/* Header & Export Actions */}
      <div className="p-4 border-b border-slate-800 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <FileSpreadsheet size={16} className="text-emerald-400" />
              물량산출 결과표
            </h2>
            {takeoff.is_provisional || (takeoff.unresolved_count ?? 0) > 0 ? (
              <div className="flex items-center gap-1.5">
                <span
                  id="badge-takeoff-provisional"
                  className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30"
                >
                  잠정 {totalQuantity} 개
                </span>
                {(takeoff.unresolved_count ?? 0) > 0 && (
                  <span
                    id="badge-takeoff-unresolved"
                    className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-rose-500/20 text-rose-300 border border-rose-500/30"
                  >
                    미해결 {takeoff.unresolved_count}건
                  </span>
                )}
              </div>
            ) : (
              <span
                id="badge-takeoff-complete"
                className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
              >
                총 {totalQuantity} 개 (검수완료)
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            도면: {takeoff.drawing_name} ({takeoff.drawing_revision})
          </p>
        </div>

        {/* Export Buttons */}
        <div className="flex items-center gap-1.5">
          <a
            href={xlsxUrl}
            download
            data-testid="btn-export-xlsx"
            className="flex items-center gap-1 px-2.5 py-1.5 bg-emerald-700 hover:bg-emerald-600 text-white rounded text-xs font-medium shadow transition"
            title="Excel 통합 파일 다운로드 (Summary + Evidence 2개 시트)"
          >
            <Download size={13} />
            Excel
          </a>
          <a
            href={csvSummaryUrl}
            download
            data-testid="btn-export-csv-summary"
            className="flex items-center gap-1 px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded text-xs font-medium transition"
            title="CSV 요약본 다운로드"
          >
            <Download size={13} />
            CSV 요약
          </a>
          <a
            href={csvEvidenceUrl}
            download
            data-testid="btn-export-csv-evidence"
            className="flex items-center gap-1 px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded text-xs font-medium transition"
            title="CSV 근거 상세 다운로드"
          >
            <Download size={13} />
            CSV 근거
          </a>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center px-4 border-b border-slate-800 text-xs">
        <button
          onClick={() => setActiveTab("summary")}
          className={`py-2.5 px-3 border-b-2 font-medium transition ${
            activeTab === "summary"
              ? "border-emerald-500 text-emerald-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          산출 요약 ({takeoff.summary.length})
        </button>
        <button
          onClick={() => setActiveTab("evidence")}
          className={`py-2.5 px-3 border-b-2 font-medium transition ${
            activeTab === "evidence"
              ? "border-emerald-500 text-emerald-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          객체 근거 ({takeoff.evidence.length})
        </button>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === "summary" ? (
          <div className="p-4 space-y-2">
            {takeoff.summary.length === 0 ? (
              <div className="text-center py-12 text-slate-500 text-sm">
                집계된 품목이 없습니다. 블록 매핑을 확인하세요.
              </div>
            ) : (
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 font-mono">
                    <th className="py-2 px-2">품목코드</th>
                    <th className="py-2 px-2">품목명</th>
                    <th className="py-2 px-2">규격</th>
                    <th className="py-2 px-2 text-right">수량</th>
                    <th className="py-2 px-2 text-center">산출방식</th>
                    <th className="py-2 px-2 text-center">상태</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {takeoff.summary.map((row) => {
                    const isSelected = selectedItemCode === row.item_code;
                    return (
                      <tr
                        key={row.item_code}
                        onClick={() =>
                          onSelectItemCode(isSelected ? null : row.item_code)
                        }
                        className={`cursor-pointer transition ${
                          isSelected
                            ? "bg-emerald-500/15 text-emerald-300 font-medium"
                            : "hover:bg-slate-800/50"
                        }`}
                      >
                        <td className="py-2.5 px-2 font-mono font-semibold text-sky-400">
                          {row.item_code}
                        </td>
                        <td className="py-2.5 px-2">{row.item_name}</td>
                        <td className="py-2.5 px-2 text-slate-400">
                          {row.specification || "-"}
                        </td>
                        <td className="py-2.5 px-2 text-right font-bold font-mono text-emerald-400 text-sm">
                          {row.quantity} {row.unit}
                        </td>
                        <td className="py-2.5 px-2 text-center">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] ${
                              row.quantity_method === "MANUAL"
                                ? "bg-amber-500/20 text-amber-300"
                                : row.quantity_method === "MIXED"
                                ? "bg-purple-500/20 text-purple-300"
                                : "bg-slate-800 text-slate-300"
                            }`}
                          >
                            {row.quantity_method}
                          </span>
                        </td>
                        <td className="py-2.5 px-2 text-center">
                          {row.review_status === "REVIEWED" ? (
                            <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400">
                              <CheckCircle2 size={12} /> 검수완료
                            </span>
                          ) : row.review_status === "UNRESOLVED" ? (
                            <span className="inline-flex items-center gap-1 text-[11px] text-red-400">
                              <AlertTriangle size={12} /> 미확인
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[11px] text-slate-400">
                              <HelpCircle size={12} /> 미검수
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        ) : (
          <div className="p-4 space-y-3">
            {/* Filter pills */}
            <div className="flex items-center gap-1 text-xs">
              <ListFilter size={14} className="text-slate-400 mr-1" />
              {["ALL", "INCLUDED", "EXCLUDED", "MANUAL", "UNRESOLVED"].map((f) => (
                <button
                  key={f}
                  onClick={() => setEvidenceFilter(f)}
                  className={`px-2 py-0.5 rounded text-[11px] transition ${
                    evidenceFilter === f
                      ? "bg-slate-700 text-white font-medium"
                      : "bg-slate-800/40 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>

            {/* Evidence Rows */}
            <div className="space-y-2">
              {filteredEvidence.map((ev) => {
                const isSelected = ev.source_object_id === selectedObjectId;
                return (
                  <div
                    key={ev.source_object_id}
                    data-testid={`evidence-row-${ev.source_object_id}`}
                    onClick={() => onSelectEvidence(ev.source_object_id)}
                    className={`p-2.5 rounded border cursor-pointer text-xs transition ${
                      isSelected
                        ? "bg-sky-950/80 border-sky-400 ring-1 ring-sky-400/80 shadow-lg shadow-sky-500/10"
                        : "border-slate-800 bg-slate-950/70 hover:border-slate-700"
                    }`}
                  >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sky-400 font-semibold">
                      {ev.block_name}
                    </span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        ev.inclusion_status === "INCLUDED"
                          ? "bg-emerald-500/20 text-emerald-400"
                          : ev.inclusion_status === "EXCLUDED"
                          ? "bg-red-500/20 text-red-400"
                          : "bg-amber-500/20 text-amber-400"
                      }`}
                    >
                      {ev.inclusion_status}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-slate-400 mt-1">
                    <span>
                      품목: <b className="text-slate-200">{ev.mapped_item_code}</b>
                      {ev.page_index !== undefined && ev.page_index !== null && (
                        <span className="ml-1.5 px-1 py-0.2 bg-sky-950 text-sky-400 border border-sky-800 rounded text-[9px] font-mono">
                          P.{ev.page_index + 1}
                        </span>
                      )}
                    </span>
                    <span className="font-mono text-[10px]">
                      ({ev.x}, {ev.y})
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1 truncate">
                    사유: {ev.review_reason}
                  </div>
                </div>
              );
            })}
          </div>
          </div>
        )}
      </div>
    </div>
  );
}
