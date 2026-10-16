import {
  ItemMappingRule,
  EvidenceReviewItem,
  ManualObjectItem,
  NormalizedDrawing,
  ProjectMetadata,
  DrawingSummary,
  TakeoffResult,
  PdfPageFeatures,
  CandidateBulkReviewRequest,
  CandidatesResponse,
  MappingTemplate,
  MappingTemplateCreate,
  MappingTemplateListResponse,
  DemoSeedResponse,
  SymbolSearchRequest,
  SymbolSearchResponse,
  DrawingScope,
  DrawingScopeUpdate,
  ProjectTakeoffResult,
  RevisionComparisonResult,
} from "@/types/cad";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  code?: string;
  detail?: string;
  constructor(message: string, code?: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.detail = detail;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errBody: { message?: string; detail?: string; code?: string } | null = null;
    try {
      errBody = (await res.json()) as { message?: string; detail?: string; code?: string };
    } catch {
      // ignore json parse error
    }
    const message = errBody?.message || errBody?.detail || `HTTP Error ${res.status}`;
    throw new ApiError(message, errBody?.code, errBody?.detail);
  }
  return res.json();
}

export const api = {
  getHealth: async (): Promise<{ status: string }> => {
    const res = await fetch(`${API_BASE}/api/health`);
    return handleResponse(res);
  },

  listProjects: async (): Promise<ProjectMetadata[]> => {
    const res = await fetch(`${API_BASE}/api/projects`);
    return handleResponse(res);
  },

  createProject: async (name: string, description = ""): Promise<ProjectMetadata> => {
    const res = await fetch(`${API_BASE}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description }),
    });
    return handleResponse(res);
  },

  uploadDrawing: async (
    projectId: string,
    file: File,
    revision = "REV0"
  ): Promise<{
    project_id: string;
    drawing_id: string;
    filename: string;
    revision: string;
    objects_count: number;
    warnings_count: number;
  }> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/drawings?revision=${encodeURIComponent(revision)}`,
      {
        method: "POST",
        body: formData,
      }
    );
    return handleResponse(res);
  },

  listDrawings: async (projectId: string): Promise<DrawingSummary[]> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings`);
    return handleResponse(res);
  },

  getDrawing: async (projectId: string, drawingId: string): Promise<NormalizedDrawing> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}`);
    return handleResponse(res);
  },

  getMappings: async (projectId: string, drawingId: string): Promise<ItemMappingRule[]> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/mappings`);
    return handleResponse(res);
  },

  saveMappings: async (
    projectId: string,
    drawingId: string,
    mappings: ItemMappingRule[]
  ): Promise<{ status: string }> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/mappings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(mappings),
    });
    return handleResponse(res);
  },

  saveReviews: async (
    projectId: string,
    drawingId: string,
    reviews: EvidenceReviewItem[]
  ): Promise<{ status: string }> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/reviews`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reviews),
    });
    return handleResponse(res);
  },

  getManualObjects: async (
    projectId: string,
    drawingId: string
  ): Promise<ManualObjectItem[]> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/manual-objects`);
    return handleResponse(res);
  },

  addManualObject: async (
    projectId: string,
    drawingId: string,
    item: ManualObjectItem
  ): Promise<ManualObjectItem> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/manual-objects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(item),
    });
    return handleResponse(res);
  },

  deleteManualObject: async (
    projectId: string,
    drawingId: string,
    manualId: string
  ): Promise<{ status: string }> => {
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/manual-objects/${manualId}`,
      {
        method: "DELETE",
      }
    );
    return handleResponse(res);
  },

  getTakeoff: async (projectId: string, drawingId: string): Promise<TakeoffResult> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/takeoff`);
    return handleResponse(res);
  },

  getCsvExportUrl: (projectId: string, drawingId: string, type: "summary" | "evidence"): string => {
    return `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/export/csv?type=${type}`;
  },

  getXlsxExportUrl: (projectId: string, drawingId: string): string => {
    return `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/export/xlsx`;
  },

  getImageUrl: (projectId: string, drawingId: string): string => {
    return `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/image`;
  },

  getPageImageUrl: (projectId: string, drawingId: string, pageIndex: number): string => {
    return `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/pages/${pageIndex}/image`;
  },

  getPageFeatures: async (
    projectId: string,
    drawingId: string,
    pageIndex: number
  ): Promise<PdfPageFeatures> => {
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/pages/${pageIndex}/features`
    );
    return handleResponse(res);
  },

  getCandidates: async (
    projectId: string,
    drawingId: string
  ): Promise<CandidatesResponse> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/candidates`);
    return handleResponse(res);
  },

  detectCandidates: async (
    projectId: string,
    drawingId: string
  ): Promise<CandidatesResponse> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/candidates/detect`, {
      method: "POST",
    });
    return handleResponse(res);
  },

  reviewCandidates: async (
    projectId: string,
    drawingId: string,
    body: CandidateBulkReviewRequest
  ): Promise<CandidatesResponse> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/candidates/review`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return handleResponse(res);
  },

  clearCandidates: async (
    projectId: string,
    drawingId: string
  ): Promise<{ status: string }> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/candidates`, {
      method: "DELETE",
    });
    return handleResponse(res);
  },

  getRawUrl: (projectId: string, drawingId: string): string => {
    return `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/raw`;
  },

  listMappingTemplates: async (): Promise<MappingTemplateListResponse> => {
    const res = await fetch(`${API_BASE}/api/mapping-templates`);
    return handleResponse(res);
  },

  getMappingTemplate: async (templateId: string): Promise<MappingTemplate> => {
    const res = await fetch(`${API_BASE}/api/mapping-templates/${templateId}`);
    return handleResponse(res);
  },

  createMappingTemplate: async (data: MappingTemplateCreate): Promise<MappingTemplate> => {
    const res = await fetch(`${API_BASE}/api/mapping-templates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    return handleResponse(res);
  },

  deleteMappingTemplate: async (templateId: string): Promise<{ status: string }> => {
    const res = await fetch(`${API_BASE}/api/mapping-templates/${templateId}`, {
      method: "DELETE",
    });
    return handleResponse(res);
  },

  applyMappingTemplate: async (
    projectId: string,
    drawingId: string,
    templateId: string,
    mergeStrategy: "MERGE" | "REPLACE" = "MERGE"
  ): Promise<ItemMappingRule[]> => {
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/apply-template`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_id: templateId,
          merge_strategy: mergeStrategy,
        }),
      }
    );
    return handleResponse(res);
  },

  seedDemoProject: async (reset: boolean = false): Promise<DemoSeedResponse> => {
    const res = await fetch(`${API_BASE}/api/demo/seed?reset=${reset ? "true" : "false"}`, {
      method: "POST",
    });
    return handleResponse(res);
  },

  searchSymbol: async (
    projectId: string,
    drawingId: string,
    req: SymbolSearchRequest
  ): Promise<SymbolSearchResponse> => {
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/search-symbol`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      }
    );
    return handleResponse(res);
  },

  // ---------------------------------------------------------------------------
  // Issue #35: Multi-Drawing Scope & Revision, Project Takeoff & Diff
  // ---------------------------------------------------------------------------
  getProjectScopes: async (projectId: string): Promise<DrawingScope[]> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/scopes`);
    return handleResponse(res);
  },

  getDrawingScope: async (projectId: string, drawingId: string): Promise<DrawingScope> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/scope`);
    return handleResponse(res);
  },

  updateDrawingScope: async (
    projectId: string,
    drawingId: string,
    payload: DrawingScopeUpdate
  ): Promise<DrawingScope> => {
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/scope`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );
    return handleResponse(res);
  },

  activateRevision: async (
    projectId: string,
    drawingId: string,
    active = true
  ): Promise<DrawingScope> => {
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/drawings/${drawingId}/activate-revision`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active }),
      }
    );
    return handleResponse(res);
  },

  getProjectTakeoff: async (projectId: string): Promise<ProjectTakeoffResult> => {
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/takeoff`);
    return handleResponse(res);
  },

  compareRevisions: async (
    projectId: string,
    baseDrawingId: string,
    compareDrawingId: string
  ): Promise<RevisionComparisonResult> => {
    const res = await fetch(
      `${API_BASE}/api/projects/${projectId}/revisions/compare?base_drawing_id=${encodeURIComponent(
        baseDrawingId
      )}&compare_drawing_id=${encodeURIComponent(compareDrawingId)}`
    );
    return handleResponse(res);
  },

  seedMultiDrawingDemo: async (reset = true): Promise<DemoSeedResponse> => {
    const res = await fetch(`${API_BASE}/api/demo/seed-multi-drawing?reset=${reset ? "true" : "false"}`, {
      method: "POST",
    });
    return handleResponse(res);
  },

  getProjectExportXlsxUrl: (projectId: string): string => {
    return `${API_BASE}/api/projects/${projectId}/export/xlsx`;
  },

  getProjectExportCsvUrl: (
    projectId: string,
    type: "summary" | "breakdown" | "delta" = "summary"
  ): string => {
    return `${API_BASE}/api/projects/${projectId}/export/csv?type=${type}`;
  },
};


