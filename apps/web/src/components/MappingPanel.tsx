"use client";

import React, { useEffect, useState } from "react";
import { BlockInfo, ItemMappingRule, MappingTemplate } from "@/types/cad";
import { api } from "@/lib/api";
import { Save, Tag, BookOpen, BookmarkPlus, Check, Trash2, RefreshCw } from "lucide-react";

interface MappingPanelProps {
  blocks: BlockInfo[];
  mappings: ItemMappingRule[];
  projectId?: string;
  drawingId?: string;
  onSaveMappings: (mappings: ItemMappingRule[]) => Promise<void>;
  onReloadMappings?: () => Promise<void>;
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
  projectId,
  drawingId,
  onSaveMappings,
  onReloadMappings,
  isSaving,
}: MappingPanelProps) {
  // Local state for mappings editing
  const [localMap, setLocalMap] = useState<Record<string, ItemMappingRule>>(() => {
    const map: Record<string, ItemMappingRule> = {};
    mappings.forEach((m) => {
      map[m.block_name] = { ...m };
    });
    return map;
  });

  // Template management state
  const [templates, setTemplates] = useState<MappingTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("tpl_standard_elec");
  const [mergeStrategy, setMergeStrategy] = useState<"MERGE" | "REPLACE">("MERGE");
  const [isApplyingTemplate, setIsApplyingTemplate] = useState(false);
  const [isSavingTemplate, setIsSavingTemplate] = useState(false);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [newTemplateName, setNewTemplateName] = useState("");
  const [newTemplateDesc, setNewTemplateDesc] = useState("");
  const [templateFeedback, setTemplateFeedback] = useState<string | null>(null);

  // Load templates on mount
  useEffect(() => {
    async function loadTpls() {
      try {
        const res = await api.listMappingTemplates();
        setTemplates(res.templates);
        if (res.templates.length > 0) {
          setSelectedTemplateId((curr) => curr || res.templates[0].id);
        }
      } catch (err) {
        console.error("Failed to load mapping templates", err);
      }
    }
    loadTpls();
  }, []);

  const handleApplyTemplate = async () => {
    if (!selectedTemplateId) return;
    setIsApplyingTemplate(true);
    setTemplateFeedback(null);
    try {
      if (projectId && drawingId) {
        const res = await api.applyMappingTemplate(
          projectId,
          drawingId,
          selectedTemplateId,
          mergeStrategy
        );
        const tpl = templates.find((t) => t.id === selectedTemplateId);
        if (tpl) {
          setLocalMap((prev) => {
            const nextMap = mergeStrategy === "REPLACE" ? {} : { ...prev };
            tpl.mappings.forEach((item) => {
              nextMap[item.block_name] = {
                block_name: item.block_name,
                item_code: item.item_code,
                item_name: item.item_name,
                specification: item.specification || "",
                unit: item.unit || "EA",
              };
            });
            return nextMap;
          });
        }
        setTemplateFeedback(`템플릿 적용 완료: ${res.applied_count}개 규칙 반영됨 (${res.total_mappings}개 총 매핑)`);
        if (onReloadMappings) {
          await onReloadMappings();
        }
      } else {
        // Fallback local application
        const tpl = templates.find((t) => t.id === selectedTemplateId);
        if (tpl) {
          const nextMap = mergeStrategy === "REPLACE" ? {} : { ...localMap };
          tpl.mappings.forEach((item) => {
            nextMap[item.block_name] = {
              block_name: item.block_name,
              item_code: item.item_code,
              item_name: item.item_name,
              specification: item.specification || "",
              unit: item.unit || "EA",
            };
          });
          setLocalMap(nextMap);
          setTemplateFeedback(`템플릿 "${tpl.name}"이 로컬에 적용되었습니다.`);
        }
      }
    } catch (err: unknown) {
      console.error("Failed to apply template", err);
      setTemplateFeedback("템플릿 적용 실패");
    } finally {
      setIsApplyingTemplate(false);
      setTimeout(() => setTemplateFeedback(null), 4000);
    }
  };

  const handleSaveAsNewTemplate = async () => {
    if (!newTemplateName.trim()) return;
    setIsSavingTemplate(true);
    try {
      const activeRules = Object.values(localMap).filter((r) => r.item_code && r.item_code !== "EXCLUDE");
      if (activeRules.length === 0) {
        alert("저장할 활성 매핑 규칙이 없습니다.");
        return;
      }
      const created = await api.createMappingTemplate({
        name: newTemplateName.trim(),
        description: newTemplateDesc.trim() || undefined,
        mappings: activeRules.map((r) => ({
          block_name: r.block_name,
          item_code: r.item_code,
          item_name: r.item_name || r.item_code,
          specification: r.specification || undefined,
          unit: r.unit || "EA",
        })),
      });
      setTemplates((prev) => [...prev, created]);
      setSelectedTemplateId(created.id);
      setShowSaveModal(false);
      setNewTemplateName("");
      setNewTemplateDesc("");
      setTemplateFeedback(`새 템플릿 "${created.name}" 저장 완료!`);
      setTimeout(() => setTemplateFeedback(null), 3500);
    } catch (err) {
      console.error("Failed to save template", err);
      alert("템플릿 저장 중 오류가 발생했습니다.");
    } finally {
      setIsSavingTemplate(false);
    }
  };

  const handleDeleteTemplate = async (templateId: string) => {
    if (!confirm("이 템플릿을 삭제하시겠습니까?")) return;
    try {
      await api.deleteMappingTemplate(templateId);
      setTemplates((prev) => prev.filter((t) => t.id !== templateId));
      if (selectedTemplateId === templateId) {
        setSelectedTemplateId(templates[0]?.id || "");
      }
    } catch (err) {
      console.error("Failed to delete template", err);
    }
  };

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

  const activeTemplate = templates.find((t) => t.id === selectedTemplateId);

  return (
    <div className="flex flex-col h-full bg-slate-900 border-l border-slate-800 text-slate-200">
      {/* Header & Global Actions */}
      <div className="p-4 border-b border-slate-800 space-y-3 bg-slate-950/40">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <Tag size={16} className="text-sky-400" />
              도면 블록 → 품목 매핑 & 템플릿
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              도면의 CAD 기호를 전기공사 적산 품목으로 분류하거나 표준 템플릿을 적용합니다.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowSaveModal(true)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs font-medium border border-slate-700 transition"
              title="현재 매핑을 새 템플릿으로 저장"
            >
              <BookmarkPlus size={13} className="text-amber-400" />
              템플릿으로 저장
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded text-xs font-medium shadow transition"
            >
              <Save size={14} />
              {isSaving ? "저장 중..." : "매핑 직접 저장"}
            </button>
          </div>
        </div>

        {/* Reusable Template Toolbar */}
        <div className="p-3 bg-slate-900/90 border border-slate-800 rounded-lg space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-slate-300 flex items-center gap-1.5">
              <BookOpen size={14} className="text-indigo-400" />
              범례·품목 매핑 템플릿
            </span>
            {activeTemplate?.is_built_in ? (
              <span className="text-[10px] bg-indigo-950 text-indigo-300 px-1.5 py-0.5 rounded border border-indigo-800">
                표준 제공 템플릿
              </span>
            ) : (
              <span className="text-[10px] bg-emerald-950 text-emerald-300 px-1.5 py-0.5 rounded border border-emerald-800">
                사용자 정의 템플릿
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center">
            <div className="md:col-span-6">
              <select
                value={selectedTemplateId}
                onChange={(e) => setSelectedTemplateId(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                {templates.map((tpl) => (
                  <option key={tpl.id} value={tpl.id}>
                    {tpl.is_built_in ? "⭐ " : "📁 "}
                    {tpl.name} ({tpl.mappings.length}개 규칙)
                  </option>
                ))}
              </select>
            </div>

            <div className="md:col-span-3 flex items-center gap-1 bg-slate-950 p-0.5 rounded border border-slate-800 text-[11px]">
              <button
                type="button"
                onClick={() => setMergeStrategy("MERGE")}
                className={`flex-1 py-1 rounded transition text-center font-medium ${
                  mergeStrategy === "MERGE"
                    ? "bg-indigo-600 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
                title="기존 매핑은 유지하고 새로운 블록만 추가"
              >
                병합 (MERGE)
              </button>
              <button
                type="button"
                onClick={() => setMergeStrategy("REPLACE")}
                className={`flex-1 py-1 rounded transition text-center font-medium ${
                  mergeStrategy === "REPLACE"
                    ? "bg-rose-600 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
                title="기존 매핑을 초기화하고 템플릿으로 전체 대체"
              >
                덮어쓰기
              </button>
            </div>

            <div className="md:col-span-3 flex items-center gap-1.5">
              <button
                onClick={handleApplyTemplate}
                disabled={isApplyingTemplate || !selectedTemplateId}
                className="flex-1 flex items-center justify-center gap-1 py-1.5 px-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded text-xs font-semibold shadow transition"
              >
                <RefreshCw size={12} className={isApplyingTemplate ? "animate-spin" : ""} />
                {isApplyingTemplate ? "적용 중..." : "템플릿 적용"}
              </button>
              {activeTemplate && !activeTemplate.is_built_in && (
                <button
                  onClick={() => handleDeleteTemplate(activeTemplate.id)}
                  className="p-1.5 bg-rose-950/60 hover:bg-rose-900 border border-rose-800 text-rose-300 rounded transition"
                  title="템플릿 삭제"
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          </div>

          {activeTemplate?.description && (
            <p className="text-[11px] text-slate-400 pt-0.5">
              💡 {activeTemplate.description}
            </p>
          )}

          {templateFeedback && (
            <div className="p-2 rounded bg-emerald-950/60 border border-emerald-800/80 text-emerald-300 text-xs flex items-center gap-1.5 animate-fadeIn">
              <Check size={14} />
              <span>{templateFeedback}</span>
            </div>
          )}
        </div>
      </div>

      {/* Save Template Modal */}
      {showSaveModal && (
        <div className="p-4 border-b border-indigo-500/30 bg-indigo-950/40 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-bold text-indigo-300 flex items-center gap-1.5">
              <BookmarkPlus size={14} />새 매핑 템플릿 생성
            </h4>
            <button
              onClick={() => setShowSaveModal(false)}
              className="text-slate-400 hover:text-slate-200 text-xs"
            >
              닫기
            </button>
          </div>
          <div className="space-y-2 text-xs">
            <div>
              <label className="block text-[10px] text-slate-400 mb-0.5">템플릿 이름 *</label>
              <input
                type="text"
                value={newTemplateName}
                onChange={(e) => setNewTemplateName(e.target.value)}
                placeholder="예: 2026 표준 상가 전기 도면 매핑"
                className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-400"
              />
            </div>
            <div>
              <label className="block text-[10px] text-slate-400 mb-0.5">설명 (선택)</label>
              <input
                type="text"
                value={newTemplateDesc}
                onChange={(e) => setNewTemplateDesc(e.target.value)}
                placeholder="예: DL, 콘센트, 스위치 기본 규격 포함"
                className="w-full bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-400"
              />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => setShowSaveModal(false)}
                className="px-2.5 py-1 bg-slate-800 text-slate-300 rounded text-xs"
              >
                취소
              </button>
              <button
                onClick={handleSaveAsNewTemplate}
                disabled={isSavingTemplate || !newTemplateName.trim()}
                className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded text-xs font-semibold"
              >
                {isSavingTemplate ? "저장 중..." : "템플릿 등록"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {blocks.length === 0 ? (
          <div className="text-center py-12 text-slate-500 text-sm">
            도면에 정의된 블록이 없습니다.
          </div>
        ) : (
          blocks.map((b) => {
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
