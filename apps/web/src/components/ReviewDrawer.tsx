"use client";

import React, { useState } from "react";
import { SourceObject, TakeoffEvidenceRow, ItemMappingRule } from "@/types/cad";
import { X, CheckCircle, Ban, MapPin, Trash2 } from "lucide-react";

interface ReviewDrawerProps {
  object: SourceObject | null;
  evidence: TakeoffEvidenceRow | null;
  mappings: ItemMappingRule[];
  sourceType?: string;
  coordinateSpace?: string;
  onUpdateReview: (
    objectId: string,
    inclusionStatus: "INCLUDED" | "EXCLUDED" | "MANUAL_ADDED",
    mappedItemCode?: string,
    reason?: string
  ) => Promise<void>;
  onDeleteManualObject?: (objectId: string) => Promise<void>;
  onClose: () => void;
  isSaving: boolean;
}

export function ReviewDrawer(props: ReviewDrawerProps) {
  const { object, evidence } = props;
  if (!object && !evidence) return null;

  const objectId = object?.id || evidence?.source_object_id || "";
  return <ReviewDrawerContent key={objectId} {...props} objectId={objectId} />;
}

interface ContentProps extends ReviewDrawerProps {
  objectId: string;
}

function ReviewDrawerContent({
  object,
  evidence,
  mappings,
  onUpdateReview,
  onDeleteManualObject,
  onClose,
  isSaving,
  objectId,
  sourceType,
  coordinateSpace,
}: ContentProps) {
  const isImageCoordinate = sourceType === "IMAGE" || coordinateSpace === "IMAGE_PIXEL";
  const coordLabel = isImageCoordinate ? "이미지 좌표 (px)" : "CAD 좌표 (WCS)";

  const isManual =
    evidence?.inclusion_status === "MANUAL_ADDED" ||
    evidence?.entity_type === "MANUAL_POINT" ||
    objectId.startsWith("manual_");

  const blockName = isManual
    ? evidence?.mapped_item_code
      ? `[${evidence.mapped_item_code}] 수동 추가 기구`
      : "수동 추가 기구"
    : object?.block_name || evidence?.block_name || "";
  const layerName = isManual ? "MANUAL" : object?.layer || evidence?.layer_name || "";
  const coordX = object?.insert_point?.[0] ?? evidence?.x ?? 0;
  const coordY = object?.insert_point?.[1] ?? evidence?.y ?? 0;
  const currentStatus = evidence?.inclusion_status || "INCLUDED";
  const reviewStatus = evidence?.review_status || "UNREVIEWED";
  const defaultItemCode = evidence?.mapped_item_code || "UNMAPPED";

  const [selectedItemCode, setSelectedItemCode] = useState(defaultItemCode);
  const [reasonInput, setReasonInput] = useState(evidence?.review_reason || "");

  const handleConfirmReview = async () => {
    await onUpdateReview(
      objectId,
      isManual ? "MANUAL_ADDED" : "INCLUDED",
      selectedItemCode !== "UNMAPPED" ? selectedItemCode : undefined,
      reasonInput || (isManual ? "수동 기구 품목 확인" : "사용자 검수 확인 완료")
    );
  };

  const handleExclude = async () => {
    await onUpdateReview(
      objectId,
      "EXCLUDED",
      selectedItemCode !== "UNMAPPED" ? selectedItemCode : undefined,
      reasonInput || "사용자 오탐 제외"
    );
  };

  const handleRestore = async () => {
    await onUpdateReview(
      objectId,
      isManual ? "MANUAL_ADDED" : "INCLUDED",
      selectedItemCode !== "UNMAPPED" ? selectedItemCode : undefined,
      reasonInput || "사용자 수동 복원"
    );
  };

  return (
    <div className="absolute bottom-6 right-6 z-30 w-96 bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-4 text-slate-200 backdrop-blur-md">
      <div className="flex items-start justify-between border-b border-slate-800 pb-2.5">
        <div>
          <span className="text-[10px] font-mono uppercase tracking-wider text-sky-400 font-bold">
            {isManual ? "현장 보정 수동 기구" : "선택된 CAD 기구 객체"}
          </span>
          <h3 className="text-sm font-bold text-white mt-0.5">{blockName}</h3>
        </div>
        <button
          onClick={onClose}
          className="p-1 hover:bg-slate-800 rounded text-slate-400 hover:text-white transition"
        >
          <X size={16} />
        </button>
      </div>

      <div className="py-3 space-y-2 text-xs">
        <div className="flex items-center justify-between text-slate-400">
          <span>레이어</span>
          <span className="font-mono text-slate-200">{layerName}</span>
        </div>
        <div className="flex items-center justify-between text-slate-400">
          <span>{coordLabel}</span>
          <span className="font-mono text-slate-200 flex items-center gap-1">
            <MapPin size={12} className="text-amber-400" />({coordX}, {coordY}){isImageCoordinate ? " px" : ""}
          </span>
        </div>
        <div className="flex items-center justify-between text-slate-400">
          <span>현재 상태</span>
          <div className="flex items-center gap-1.5">
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                currentStatus === "INCLUDED" || currentStatus === "MANUAL_ADDED"
                  ? "bg-emerald-500/20 text-emerald-400"
                  : currentStatus === "EXCLUDED"
                  ? "bg-red-500/20 text-red-400"
                  : "bg-amber-500/20 text-amber-400"
              }`}
            >
              {currentStatus}
            </span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                reviewStatus === "REVIEWED"
                  ? "bg-sky-500/20 text-sky-400"
                  : reviewStatus === "UNRESOLVED"
                  ? "bg-amber-500/20 text-amber-400"
                  : "bg-slate-700/60 text-slate-400"
              }`}
            >
              {reviewStatus}
            </span>
          </div>
        </div>

        {/* Change Item Code */}
        <div className="pt-2 border-t border-slate-800">
          <label className="text-[11px] text-slate-400 block mb-1">
            연결 적산 품목 {isManual ? "변경" : "변경"}
          </label>
          <select
            value={selectedItemCode}
            onChange={(e) => setSelectedItemCode(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
          >
            <option value="UNMAPPED">미지정 (UNMAPPED)</option>
            {mappings
              .filter((m) => m.item_code !== "EXCLUDE")
              .map((m) => (
                <option key={m.item_code} value={m.item_code}>
                  [{m.item_code}] {m.item_name || m.block_name}
                </option>
              ))}
          </select>
        </div>

        {/* Reason input */}
        <div>
          <label className="text-[11px] text-slate-400 block mb-1">
            검수 메모 / 사유
          </label>
          <input
            type="text"
            value={reasonInput}
            onChange={(e) => setReasonInput(e.target.value)}
            placeholder="예: 설계변경 미시공, 도면 표기 오탐, 현장 검증 완료"
            className="w-full bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
          />
        </div>
      </div>

      {/* Action Buttons */}
      <div className="pt-3 border-t border-slate-800 flex items-center gap-2">
        {isManual ? (
          <>
            <button
              onClick={handleConfirmReview}
              disabled={isSaving}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow transition"
            >
              <CheckCircle size={14} />
              품목/메모 저장
            </button>
            {onDeleteManualObject && (
              <button
                onClick={() => onDeleteManualObject(objectId)}
                disabled={isSaving}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-red-600/90 hover:bg-red-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow transition"
              >
                <Trash2 size={14} />
                수동 기구 삭제
              </button>
            )}
          </>
        ) : currentStatus === "INCLUDED" ? (
          <>
            <button
              onClick={handleConfirmReview}
              disabled={isSaving}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow transition"
            >
              <CheckCircle size={14} />
              {reviewStatus === "REVIEWED" ? "검수 확인 유지" : "검수 확인"}
            </button>
            <button
              onClick={handleExclude}
              disabled={isSaving}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-red-600/90 hover:bg-red-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow transition"
            >
              <Ban size={14} />
              오탐 제외
            </button>
          </>
        ) : (
          <button
            onClick={handleRestore}
            disabled={isSaving}
            className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-emerald-600/90 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow transition"
          >
            <CheckCircle size={14} />
            집계에 복원
          </button>
        )}
      </div>
    </div>
  );
}
