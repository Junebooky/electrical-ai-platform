import {
  ItemMappingRule,
  EvidenceReviewItem,
  ManualObjectItem,
  NormalizedDrawing,
  ProjectMetadata,
  DrawingSummary,
  TakeoffResult,
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
};
