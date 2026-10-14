"use client";

import React, { useMemo, useState } from "react";
import { BlockInfo, ItemMappingRule } from "@/types/cad";
import { Save, Tag } from "lucide-react";

interface MappingPanelProps {
  blocks: BlockInfo[];
  mappings: ItemMappingRule[];
  onSaveMappings: (mappings: ItemMappingRule[]) => Promise<void>;
  isSaving: boolean;
}

const PRESET_CATEGORIES = [
  { code: "LIGHT", name: "조명설비", defaultItemName: "다운라이트 LED" },
  { code: "OUTLET", name: "전열콘센트", defaultItemName: "매입 2구 콘센트" },
  { code: "SWITCH", name: "배선스위치", defaultItemName: "1로 텀블러 스위치" },
  { code: "EXCLUDE", name: "집계 제외", defaultItemName: "-" },
];

export function MappingPanel({
  blocks,
  mappings,
  onSaveMappings,
  isSaving,
}: MappingPanelProps) {
  // Filter out system dimension blocks with 0 inserts if user blocks exist or if 0 inserts
  const availableBlocks = useMemo(() => {
    const withInserts = blocks.filter((b) => b.top_level_insert_count > 0 || b.nested_insert_count > 0);
    if (withInserts.length > 0) return withInserts;
    return blocks.filter((b) => !b.name.startsWith("_") && !b.name.startsWith("*"));
  }, [blocks]);

  // Local state for mappings editing
  const [localMap, setLocalMap] = useState<Record<string, ItemMappingRule>>(() => {
    const map: Record<string, ItemMappingRule> = {};
    mappings.forEach((m) => {
      map[m.block_name] = { ...m };
    });
    return map;
  });

  const handleSelectCode = (blockName: string, itemCode: string) => {
    const preset = PRESET_CATEGORIES.find((p) => p.code === itemCode);
    setLocalMap((prev) => {
      const existing = prev[blockName] || {
        block_name: blockName,
        item_code: itemCode,
        item_name: preset?.defaultItemName || itemCode,
        specification: "",
        unit: "EA",
      };

      // Reset item_name if it was empty or a default name from any preset category
      const isDefaultOrEmpty =
        !existing.item_name ||
        PRESET_CATEGORIES.some(
          (p) => p.defaultItemName === existing.item_name || p.code === existing.item_name
        );
      const nextItemName = isDefaultOrEmpty
        ? preset?.defaultItemName || itemCode
        : existing.item_name;

      return {
        ...prev,
        [blockName]: {
          ...existing,
          item_code: itemCode,
          item_name: nextItemName,
        },
      };
    });
  };

  const handleUpdateField = (
    blockName: string,
    field: keyof ItemMappingRule,
    value: string
  ) => {
    setLocalMap((prev) => {
      const existing = prev[blockName] || {
        block_name: blockName,
        item_code: "LIGHT",
        item_name: "",
        specification: "",
        unit: "EA",
      };
      return {
        ...prev,
        [blockName]: {
          ...existing,
          [field]: value,
        },
      };
    });
  };

  const handleSave = async () => {
    const rules = Object.values(localMap).filter((r) => r.item_code);
    await onSaveMappings(rules);
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border-l border-slate-800 text-slate-200">
      <div className="p-4 border-b border-slate-800 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Tag size={16} className="text-sky-400" />
            도면 블록 → 품목 매핑
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            도면의 CAD 기호를 전기공사 적산 품목으로 분류합니다.
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded text-xs font-medium shadow transition"
        >
          <Save size={14} />
          {isSaving ? "저장 중..." : "매핑 적용"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {availableBlocks.length === 0 ? (
          <div className="text-center py-10 px-4 bg-slate-900/60 rounded-xl border border-slate-800 my-4 flex flex-col items-center">
            <div className="w-12 h-12 mb-3 rounded-full bg-slate-800/80 border border-slate-700 flex items-center justify-center text-amber-400">
              <Tag size={20} />
            </div>
            <h4 className="text-slate-200 font-semibold text-sm mb-1.5">
              자동 집계 가능한 CAD 블록 없음
            </h4>
            <p className="text-slate-400 text-xs leading-relaxed max-w-[320px] mb-4">
              선·원·문자(LINE, CIRCLE, TEXT) 등 기본 엔티티로만 구성된 도면입니다. CAD INSERT 블록이 없으므로 기구 수량은 상단 <b>[누락 기구 수동 추가]</b> 버튼을 통해 직접 마커를 추가해 주세요.
            </p>
            <div className="text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/20 px-3 py-2 rounded text-left leading-relaxed">
              💡 <b>도메인 안전 수칙:</b> 도면 내에 &apos;LIGHT&apos;, &apos;OUTLET&apos; 등의 텍스트가 적혀 있더라도 실제 CAD 기구 블록이 아니므로 임의로 AI 자동 확정 수량으로 집계하지 않습니다 (FR-016).
            </div>
          </div>
        ) : (
          availableBlocks.map((b) => {
            const currentRule = localMap[b.name];
            const currentCode = currentRule?.item_code || "";
            const isExcluded = currentCode === "EXCLUDE";

            return (
              <div
                key={b.name}
                className={`p-3 rounded-lg border transition ${
                  currentCode
                    ? isExcluded
                      ? "bg-slate-950/60 border-slate-800 text-slate-400"
                      : "bg-slate-800/80 border-sky-500/30"
                    : "bg-slate-950 border-slate-800/80"
                }`}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-semibold text-sky-300">
                        {b.name}
                      </span>
                      {b.effective_name !== b.name && (
                        <span className="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-amber-300">
                          원형: {b.effective_name}
                        </span>
                      )}
                      {b.is_xref && (
                        <span className="text-[10px] bg-red-950 text-red-400 px-1.5 py-0.5 rounded border border-red-800">
                          XREF
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] text-slate-400 mt-1">
                      탑 레벨 삽입: <b>{b.top_level_insert_count}</b>개
                      {b.nested_insert_count > 0 && (
                        <span className="text-slate-500 ml-1.5">
                          (중첩: {b.nested_insert_count})
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Category Pills */}
                  <div className="flex items-center gap-1">
                    {PRESET_CATEGORIES.map((preset) => (
                      <button
                        key={preset.code}
                        onClick={() => handleSelectCode(b.name, preset.code)}
                        className={`px-2 py-1 text-[11px] rounded transition font-medium ${
                          currentCode === preset.code
                            ? preset.code === "EXCLUDE"
                              ? "bg-red-500/20 text-red-300 border border-red-500/40"
                              : "bg-sky-500/20 text-sky-300 border border-sky-500/40"
                            : "bg-slate-800/50 hover:bg-slate-800 text-slate-400"
                        }`}
                      >
                        {preset.name}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Additional Spec / Item Name inputs when mapped */}
                {currentCode && !isExcluded && (
                  <div className="mt-2.5 pt-2 border-t border-slate-700/50 grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <label className="text-[10px] text-slate-400 block mb-0.5">
                        품목명
                      </label>
                      <input
                        type="text"
                        value={currentRule?.item_name || ""}
                        onChange={(e) =>
                          handleUpdateField(b.name, "item_name", e.target.value)
                        }
                        placeholder="예: 6인치 다운라이트"
                        className="w-full bg-slate-900 border border-slate-700 px-2 py-1 rounded text-xs text-slate-200 focus:outline-none focus:border-sky-500"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-slate-400 block mb-0.5">
                        규격
                      </label>
                      <input
                        type="text"
                        value={currentRule?.specification || ""}
                        onChange={(e) =>
                          handleUpdateField(b.name, "specification", e.target.value)
                        }
                        placeholder="예: LED 15W 주백색"
                        className="w-full bg-slate-900 border border-slate-700 px-2 py-1 rounded text-xs text-slate-200 focus:outline-none focus:border-sky-500"
                      />
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
