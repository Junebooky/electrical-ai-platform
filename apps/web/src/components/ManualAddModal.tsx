"use client";

import React, { useEffect, useState } from "react";
import { PlusCircle, X, AlertCircle } from "lucide-react";

interface ManualAddModalProps {
  isOpen: boolean;
  coords: { x: number; y: number } | null;
  drawingName: string;
  availableItems: { code: string; name: string }[];
  isSaving: boolean;
  onClose: () => void;
  onConfirm: (itemCode: string, reason: string, note: string) => Promise<void>;
}

function ManualAddModalInner({
  coords,
  drawingName,
  availableItems,
  isSaving,
  onClose,
  onConfirm,
}: {
  coords: { x: number; y: number };
  drawingName: string;
  availableItems: { code: string; name: string }[];
  isSaving: boolean;
  onClose: () => void;
  onConfirm: (itemCode: string, reason: string, note: string) => Promise<void>;
}) {
  const [itemCode, setItemCode] = useState<string>("");
  const [reason, setReason] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const [customItemCode, setCustomItemCode] = useState<string>("");
  const [isCustomItem, setIsCustomItem] = useState(false);
  const [submitAttempted, setSubmitAttempted] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isSaving) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isSaving, onClose]);

  const effectiveItemCode = isCustomItem ? customItemCode.trim() : itemCode;
  const isItemValid = effectiveItemCode.length > 0;
  const isReasonValid = reason.length > 0;
  const isNoteValid = reason !== "기타" || note.trim().length > 0;
  const isValid = isItemValid && isReasonValid && isNoteValid;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitAttempted(true);
    if (!isValid || isSaving) return;
    await onConfirm(effectiveItemCode, reason, note.trim());
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="manual-add-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isSaving) onClose();
      }}
    >
      <div
        className="w-full max-w-md bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl overflow-hidden text-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800 bg-slate-950/50">
          <div className="flex items-center gap-2">
            <PlusCircle size={18} className="text-amber-400" />
            <h3 id="manual-add-title" className="text-sm font-semibold text-slate-100">
              누락 기구 수동 추가
            </h3>
          </div>
          <button
            onClick={onClose}
            disabled={isSaving}
            className="p-1 text-slate-400 hover:text-slate-200 rounded transition"
            title="닫기 (Esc)"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Coordinates display */}
          <div className="p-3 bg-slate-950/80 rounded border border-slate-800/80 text-xs font-mono space-y-1">
            <div className="flex items-center justify-between text-slate-400">
              <span>기준 도면</span>
              <span className="text-slate-200 truncate max-w-[200px]">{drawingName}</span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <span>지정 좌표</span>
              <span className="text-amber-300 font-bold">
                X: {coords.x}, Y: {coords.y}
              </span>
            </div>
          </div>

          {/* Item Selection (Mandatory, No default) */}
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              품목 선택 <span className="text-amber-400">*</span>
            </label>
            {!isCustomItem ? (
              <select
                id="manual-item-select"
                value={itemCode}
                onChange={(e) => {
                  if (e.target.value === "__CUSTOM__") {
                    setIsCustomItem(true);
                    setItemCode("");
                  } else {
                    setItemCode(e.target.value);
                  }
                }}
                className={`w-full px-3 py-2 bg-slate-950 border rounded text-xs focus:outline-none focus:ring-1 focus:ring-amber-500 transition ${
                  submitAttempted && !isItemValid
                    ? "border-rose-500 text-rose-300"
                    : "border-slate-800 text-slate-200"
                }`}
              >
                <option value="">품목을 선택해 주세요 (필수)</option>
                {availableItems.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.code} — {item.name}
                  </option>
                ))}
                <option value="__CUSTOM__">+ 직접 품목코드 입력</option>
              </select>
            ) : (
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="품목코드 직접 입력 (예: LIGHT-SPEC)"
                  value={customItemCode}
                  onChange={(e) => setCustomItemCode(e.target.value)}
                  className="flex-1 px-3 py-2 bg-slate-950 border border-slate-800 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-amber-500"
                />
                <button
                  type="button"
                  onClick={() => {
                    setIsCustomItem(false);
                    setCustomItemCode("");
                  }}
                  className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                >
                  목록 선택
                </button>
              </div>
            )}
            {submitAttempted && !isItemValid && (
              <p className="text-[11px] text-rose-400 flex items-center gap-1">
                <AlertCircle size={12} /> 품목을 반드시 선택해 주세요.
              </p>
            )}
          </div>

          {/* Reason Selection (Mandatory, No default) */}
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              추가 사유 <span className="text-amber-400">*</span>
            </label>
            <select
              id="manual-reason-select"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className={`w-full px-3 py-2 bg-slate-950 border rounded text-xs focus:outline-none focus:ring-1 focus:ring-amber-500 transition ${
                submitAttempted && !isReasonValid
                  ? "border-rose-500 text-rose-300"
                  : "border-slate-800 text-slate-200"
              }`}
            >
              <option value="">추가 사유를 선택해 주세요 (필수)</option>
              <option value="도면 누락">도면 누락</option>
              <option value="현장 검수">현장 검수</option>
              <option value="기타">기타</option>
            </select>
            {submitAttempted && !isReasonValid && (
              <p className="text-[11px] text-rose-400 flex items-center gap-1">
                <AlertCircle size={12} /> 추가 사유를 선택해 주세요.
              </p>
            )}
          </div>

          {/* Note Input (Optional, Mandatory if '기타') */}
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              상세 메모 {reason === "기타" && <span className="text-amber-400">* (필수)</span>}
            </label>
            <input
              type="text"
              id="manual-note-input"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={
                reason === "기타"
                  ? "기타 사유를 구체적으로 입력하세요 (필수)"
                  : "설치 위치 및 추가 설명 (선택)"
              }
              className={`w-full px-3 py-2 bg-slate-950 border rounded text-xs focus:outline-none focus:ring-1 focus:ring-amber-500 transition ${
                submitAttempted && !isNoteValid
                  ? "border-rose-500 text-rose-300"
                  : "border-slate-800 text-slate-200"
              }`}
            />
            {submitAttempted && !isNoteValid && (
              <p className="text-[11px] text-rose-400 flex items-center gap-1">
                <AlertCircle size={12} /> 사유가 &apos;기타&apos;인 경우 상세 메모가 필수입니다.
              </p>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs font-medium transition"
            >
              취소
            </button>
            <button
              type="submit"
              id="btn-confirm-manual-add"
              disabled={!isValid || isSaving}
              className={`px-3 py-1.5 rounded text-xs font-medium shadow transition ${
                isValid && !isSaving
                  ? "bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold cursor-pointer"
                  : "bg-slate-800 text-slate-500 cursor-not-allowed"
              }`}
            >
              {isSaving ? "저장 중..." : "추가 확정"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function ManualAddModal(props: ManualAddModalProps) {
  if (!props.isOpen || !props.coords) return null;
  return <ManualAddModalInner {...props} coords={props.coords} />;
}
