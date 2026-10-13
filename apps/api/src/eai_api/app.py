"""FastAPI Application for the Electrical AI Platform (MVP 1: DXF Smart Takeoff)."""

from __future__ import annotations

import os
import urllib.parse
from typing import Any, Literal

from cad_engine import DxfLoadError, parse_dxf
from cad_engine.schema import NormalizedDrawing
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .exporter import export_csv_evidence, export_csv_summary, export_xlsx
from .models import (
    DrawingSummary,
    EvidenceReviewItem,
    ItemMappingRule,
    ManualObjectItem,
    ProjectCreate,
    ProjectMetadata,
    TakeoffResult,
)
from .storage import Storage

app = FastAPI(
    title="Electrical AI Platform API",
    description="Local backend providing deterministic DXF parsing, normalization, takeoff, and exports.",
    version="0.1.0",
)

allowed_origins_env = os.getenv(
    "EAI_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000",
)
allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = Storage()


@app.exception_handler(DxfLoadError)
async def dxf_load_error_handler(_: Any, exc: DxfLoadError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "DXF_LOAD_ERROR",
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


# ----------------------------------------------------------------- Direct parse
@app.post("/api/dxf/parse-direct")
async def parse_direct(file: UploadFile = File(...)) -> NormalizedDrawing:
    """Parse untrusted DXF directly and return normalized JSON without creating a project."""
    filename = file.filename or "drawing.dxf"
    content = await file.read()
    return parse_dxf(content, filename=filename)


# --------------------------------------------------------------------- Projects
@app.post("/api/projects", response_model=ProjectMetadata)
def create_project(payload: ProjectCreate) -> ProjectMetadata:
    return storage.create_project(payload)


@app.get("/api/projects", response_model=list[ProjectMetadata])
def list_projects() -> list[ProjectMetadata]:
    return storage.list_projects()


@app.get("/api/projects/{project_id}", response_model=ProjectMetadata)
def get_project(project_id: str) -> ProjectMetadata:
    proj = storage.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    return proj


# --------------------------------------------------------------------- Drawings
@app.post("/api/projects/{project_id}/drawings")
async def upload_drawing(
    project_id: str,
    file: UploadFile = File(...),
    revision: str = Query("REV0", description="도면 개정 번호"),
) -> dict[str, Any]:
    proj = storage.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    filename = file.filename or "drawing.dxf"
    content = await file.read()

    # Deterministic normalization
    drawing = parse_dxf(content, filename=filename)
    storage.save_drawing(project_id, drawing, revision=revision)

    return {
        "project_id": project_id,
        "drawing_id": drawing.drawing_id,
        "filename": filename,
        "revision": revision,
        "objects_count": len(drawing.objects),
        "warnings_count": len(drawing.warnings),
    }


@app.get("/api/projects/{project_id}/drawings", response_model=list[DrawingSummary])
def list_drawings(project_id: str) -> list[DrawingSummary]:
    proj = storage.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    return storage.list_drawings(project_id)


@app.get("/api/projects/{project_id}/drawings/{drawing_id}")
def get_drawing(project_id: str, drawing_id: str) -> NormalizedDrawing:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")
    return drawing


# --------------------------------------------------------------------- Mappings
@app.get("/api/projects/{project_id}/drawings/{drawing_id}/mappings", response_model=list[ItemMappingRule])
def get_mappings(project_id: str, drawing_id: str) -> list[ItemMappingRule]:
    return storage.get_mappings(project_id, drawing_id)


@app.put("/api/projects/{project_id}/drawings/{drawing_id}/mappings")
def save_mappings(
    project_id: str,
    drawing_id: str,
    mappings: list[ItemMappingRule],
) -> dict[str, Any]:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")
    storage.save_mappings(project_id, drawing_id, mappings)
    return {"status": "saved", "count": len(mappings)}


# ---------------------------------------------------------------------- Reviews
@app.put("/api/projects/{project_id}/drawings/{drawing_id}/reviews")
def save_reviews(
    project_id: str,
    drawing_id: str,
    reviews: list[EvidenceReviewItem],
) -> dict[str, Any]:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")
    current = storage.get_reviews(project_id, drawing_id)
    for r in reviews:
        current[r.source_object_id] = r
    storage.save_reviews(project_id, drawing_id, current)
    return {"status": "saved", "count": len(current)}


# --------------------------------------------------------------- Manual Objects
@app.post("/api/projects/{project_id}/drawings/{drawing_id}/manual-objects")
def add_manual_object(
    project_id: str,
    drawing_id: str,
    item: ManualObjectItem,
) -> ManualObjectItem:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")
    objs = storage.get_manual_objects(project_id, drawing_id)
    objs.append(item)
    storage.save_manual_objects(project_id, drawing_id, objs)
    return item


@app.delete("/api/projects/{project_id}/drawings/{drawing_id}/manual-objects/{manual_id}")
def delete_manual_object(
    project_id: str,
    drawing_id: str,
    manual_id: str,
) -> dict[str, Any]:
    objs = storage.get_manual_objects(project_id, drawing_id)
    filtered = [o for o in objs if o.id != manual_id]
    storage.save_manual_objects(project_id, drawing_id, filtered)
    return {"status": "deleted", "manual_id": manual_id}


# ---------------------------------------------------------------------- Takeoff
@app.get("/api/projects/{project_id}/drawings/{drawing_id}/takeoff", response_model=TakeoffResult)
def get_takeoff(project_id: str, drawing_id: str) -> TakeoffResult:
    result = storage.calculate_takeoff(project_id, drawing_id)
    if not result:
        raise HTTPException(status_code=404, detail="도면 또는 집계 결과를 찾을 수 없습니다.")
    return result


# ----------------------------------------------------------------------- Export
@app.get("/api/projects/{project_id}/drawings/{drawing_id}/export/csv")
def export_csv(
    project_id: str,
    drawing_id: str,
    type: Literal["summary", "evidence"] = "summary",
) -> Response:
    result = storage.calculate_takeoff(project_id, drawing_id)
    if not result:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    if type == "summary":
        data = export_csv_summary(result)
        filename = f"{result.drawing_name}_takeoff_summary.csv"
    else:
        data = export_csv_evidence(result)
        filename = f"{result.drawing_name}_takeoff_evidence.csv"

    quoted = urllib.parse.quote(filename)
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


@app.get("/api/projects/{project_id}/drawings/{drawing_id}/export/xlsx")
def export_excel(
    project_id: str,
    drawing_id: str,
) -> Response:
    result = storage.calculate_takeoff(project_id, drawing_id)
    if not result:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    data = export_xlsx(result)
    filename = f"{result.drawing_name}_takeoff.xlsx"
    quoted = urllib.parse.quote(filename)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )
