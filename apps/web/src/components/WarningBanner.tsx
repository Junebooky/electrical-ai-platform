"use client";

import React, { useState } from "react";
import { DrawingWarning } from "@/types/cad";
import { AlertTriangle, Info, XCircle, ChevronDown, ChevronUp } from "lucide-react";

interface WarningBannerProps {
  warnings: DrawingWarning[];
}

export function WarningBanner({ warnings }: WarningBannerProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (warnings.length === 0) return null;

  const errorCount = warnings.filter((w) => w.severity === "ERROR").length;
  const warnCount = warnings.filter((w) => w.severity === "WARNING").length;

  return (
    <div className="bg-amber-950/70 border-b border-amber-800/80 px-4 py-2 text-xs text-amber-200">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle size={15} className="text-amber-400 shrink-0" />
          <span>
            도면 검토 알림: <b>{warnings.length}건</b>의 주의 항목이 감지되었습니다.
            {errorCount > 0 && (
              <span className="text-red-400 font-semibold ml-1.5">
                (오류 {errorCount}건)
              </span>
            )}
            {warnCount > 0 && (
              <span className="text-amber-300 ml-1">
                (경고 {warnCount}건)
              </span>
            )}
          </span>
        </div>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-1 text-[11px] text-amber-300 hover:text-white px-2 py-0.5 rounded bg-amber-900/60 transition"
        >
          {isExpanded ? (
            <>
              접기 <ChevronUp size={12} />
            </>
          ) : (
            <>
              상세보기 <ChevronDown size={12} />
            </>
          )}
        </button>
      </div>

      {isExpanded && (
        <div className="mt-2.5 pt-2 border-t border-amber-800/60 space-y-1.5 max-h-48 overflow-y-auto">
          {warnings.map((w, idx) => (
            <div
              key={idx}
              className="flex items-start gap-2 p-1.5 rounded bg-amber-900/30 text-[11px]"
            >
              {w.severity === "ERROR" ? (
                <XCircle size={13} className="text-red-400 shrink-0 mt-0.5" />
              ) : w.severity === "WARNING" ? (
                <AlertTriangle size={13} className="text-amber-400 shrink-0 mt-0.5" />
              ) : (
                <Info size={13} className="text-sky-400 shrink-0 mt-0.5" />
              )}
              <div className="flex-1">
                <div className="font-semibold text-slate-200">
                  [{w.code}] {w.message}
                </div>
                {w.object_ids.length > 0 && (
                  <div className="text-[10px] text-amber-300/80 mt-0.5">
                    영향 객체: {w.object_ids.length}개
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
