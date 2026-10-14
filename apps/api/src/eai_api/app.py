"""FastAPI Application for the Electrical AI Platform (MVP 1: DXF Smart Takeoff)."""

from __future__ import annotations

import math
import os
import urllib.parse
import uuid
from typing import Any, Literal

from cad_engine import DxfLoadError, parse_dxf
from cad_engine.schema import NormalizedDrawing
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .exporter import export_csv_evidence, export_csv_summary, export_xlsx
from .image_parser import build_image_drawing, inspect_image
from .models import (
    DrawingSummary,
    EvidenceReviewItem,
    InclusionStatus,
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
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3005,http://127.0.0.1:3005,http://localhost:8000,http://127.0.0.1:8000",
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


MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MiB (FR-002, QA-DEF-02)
CHUNK_SIZE = 64 * 1024  # 64 KiB chunks


async def read_upload_file_bounded(file: UploadFile, max_bytes: int = MAX_UPLOAD_SIZE) -> bytes:
    """Read upload file stream in chunks, aborting immediately if exceeding max_bytes."""
    buffer = bytearray()
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기가 허용 한도({max_bytes // (1024 * 1024)} MiB)를 초과했습니다.",
            )
    return bytes(buffer)


# ----------------------------------------------------------------- Direct parse
@app.post("/api/dxf/parse-direct")
async def parse_direct(file: UploadFile = File(...)) -> NormalizedDrawing:
    """Parse untrusted DXF directly and return normalized JSON without creating a project."""
    filename = file.filename or "drawing.dxf"
    content = await read_upload_file_bounded(file)
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
    lower_name = filename.lower()
    content = await read_upload_file_bounded(file)

    if lower_name.endswith(".dxf"):
        # Deterministic normalization for DXF
        drawing = parse_dxf(content, filename=filename)
        storage.save_drawing(
            project_id,
            drawing,
            revision=revision,
            raw_bytes=content,
            source_type="DXF",
            file_type="DXF",
            coordinate_space="WORLD",
        )
        return {
            "project_id": project_id,
            "drawing_id": drawing.drawing_id,
            "filename": filename,
            "revision": revision,
            "objects_count": len(drawing.objects),
            "warnings_count": len(drawing.warnings),
            "raw_saved": True,
            "file_size_bytes": len(content),
            "source_type": "DXF",
            "file_type": "DXF",
            "coordinate_space": "WORLD",
        }
    elif lower_name.endswith((".png", ".jpg", ".jpeg")):
        try:
            img_meta = inspect_image(content, filename=filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        drawing_id = f"dwg_{uuid.uuid4().hex[:8]}"
        drawing = build_image_drawing(img_meta, drawing_id)
        storage.save_drawing(
            project_id,
            drawing,
            revision=revision,
            raw_bytes=content,
            source_type="IMAGE",
            file_type=img_meta.file_type,
            coordinate_space="IMAGE_PIXEL",
            dimensions={"width": img_meta.width, "height": img_meta.height},
        )
        return {
            "project_id": project_id,
            "drawing_id": drawing.drawing_id,
            "filename": filename,
            "revision": revision,
            "objects_count": 0,
            "warnings_count": len(drawing.warnings),
            "raw_saved": True,
            "file_size_bytes": len(content),
            "source_type": "IMAGE",
            "file_type": img_meta.file_type,
            "coordinate_space": "IMAGE_PIXEL",
            "dimensions": {"width": img_meta.width, "height": img_meta.height},
        }
    elif lower_name.endswith(".dwg"):
        raise HTTPException(
            status_code=400,
            detail="DWG 직접 업로드는 지원하지 않습니다. DXF 또는 PNG/JPG/PDF 형식으로 변환 후 업로드하세요 (DEC-001/PRD FR-002).",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 파일 형식입니다. .dxf, .png, .jpg 파일만 지원됩니다.",
        )


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


@app.get("/api/projects/{project_id}/drawings/{drawing_id}/image")
def get_drawing_image(project_id: str, drawing_id: str) -> Response:
    image_path = storage.get_drawing_image_path(project_id, drawing_id)
    if not image_path or not image_path.exists():
        raise HTTPException(status_code=404, detail="이미지 도면 파일을 찾을 수 없습니다.")
    meta = storage.get_drawing_meta(project_id, drawing_id)
    file_type = (meta.get("file_type") if meta else "PNG") or "PNG"
    media_type = "image/png" if file_type.upper() == "PNG" else "image/jpeg"
    return Response(
        content=image_path.read_bytes(),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/projects/{project_id}/drawings/{drawing_id}/raw")
def get_raw_drawing(project_id: str, drawing_id: str) -> Response:
    raw_path = storage.get_raw_drawing_path(project_id, drawing_id)
    if not raw_path or not raw_path.exists():
        raise HTTPException(status_code=404, detail="원본 도면 파일을 찾을 수 없습니다.")
    meta = storage.get_drawing_meta(project_id, drawing_id)
    filename = (meta.get("filename") if meta else None) or raw_path.name
    encoded_filename = urllib.parse.quote(filename)
    media_type = "application/dxf"
    if raw_path.suffix.lower() == ".png":
        media_type = "image/png"
    elif raw_path.suffix.lower() in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    return Response(
        content=raw_path.read_bytes(),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
    )


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
    try:
        storage.save_mappings(project_id, drawing_id, mappings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
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

    mappings = storage.get_mappings(project_id, drawing_id)
    canon_defs = {m.item_code: m for m in mappings if m.item_code not in ("EXCLUDE", "UNMAPPED")}
    manual_objs = {mo.id: mo for mo in storage.get_manual_objects(project_id, drawing_id)}
    cad_objs = {obj.id: obj for obj in drawing.objects if obj.entity_type == "INSERT"}

    # MUNIT-D: Validate unit consistency on review reclassification
    for r in reviews:
        if not r.mapped_item_code or r.mapped_item_code in ("EXCLUDE", "UNMAPPED"):
            continue

        target_unit = (canon_defs[r.mapped_item_code].unit or "EA").strip() if r.mapped_item_code in canon_defs else "EA"

        if r.source_object_id in manual_objs:
            mo = manual_objs[r.source_object_id]
            mo_unit = (mo.unit or "EA").strip()
            if r.inclusion_status in (InclusionStatus.INCLUDED, InclusionStatus.MANUAL_ADDED) and mo_unit != target_unit:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"수동 객체('{mo.id}')의 단위('{mo_unit}')와 재분류 대상 품목('{r.mapped_item_code}')의 "
                        f"정규 단위('{target_unit}')가 상충합니다 (MUNIT-D)."
                    ),
                )
        elif r.source_object_id in cad_objs:
            cad_obj = cad_objs[r.source_object_id]
            base_rule = next(
                (m for m in mappings if m.block_name == cad_obj.block_name and (not m.layer or m.layer == cad_obj.layer)),
                None,
            )
            if base_rule and base_rule.item_code in canon_defs:
                base_unit = (canon_defs[base_rule.item_code].unit or "EA").strip()
                if r.inclusion_status in (InclusionStatus.INCLUDED, InclusionStatus.MANUAL_ADDED) and base_unit != target_unit:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"CAD 객체('{r.source_object_id}')의 기존 매핑 단위('{base_unit}')와 "
                            f"재분류 대상 품목('{r.mapped_item_code}')의 정규 단위('{target_unit}')가 상충합니다 (MUNIT-D)."
                        ),
                    )

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

    # High-2 Defense: Strict coordinate bounds for IMAGE drawings
    is_image = getattr(drawing, "source_type", None) == "IMAGE" or getattr(drawing, "coordinate_space", None) == "IMAGE_PIXEL"
    if is_image:
        dims = getattr(drawing, "dimensions", None) or {}
        img_w = float(dims.get("width") or (drawing.extents.max[0] if drawing.extents else 0))
        img_h = float(dims.get("height") or (drawing.extents.max[1] if drawing.extents else 0))
        if not (math.isfinite(item.x) and math.isfinite(item.y)):
            raise HTTPException(
                status_code=400,
                detail=f"수동 추가 좌표가 유효한 유한수(finite number)가 아닙니다 (x={item.x}, y={item.y}).",
            )
        if item.x < 0.0 or item.x > img_w or item.y < 0.0 or item.y > img_h:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"수동 추가 기구 좌표(x={item.x}, y={item.y})가 "
                    f"이미지 도면의 픽셀 경계(가로 0~{int(img_w)}, 세로 0~{int(img_h)})를 벗어났습니다."
                ),
            )

    # ADR-005 / MUNIT-E: Validate non-empty unit
    actual_unit = (item.unit or "").strip()
    if not actual_unit:
        raise HTTPException(
            status_code=400,
            detail="수동 추가 기구의 단위(unit)가 누락되었거나 공백입니다. 유효한 단위(예: 'EA', 'SET' 등)를 지정해야 합니다 (ADR-005).",
        )

    mappings = storage.get_mappings(project_id, drawing_id)
    canon_defs = {m.item_code: m for m in mappings if m.item_code not in ("EXCLUDE", "UNMAPPED")}
    objs = storage.get_manual_objects(project_id, drawing_id)

    if item.item_code in canon_defs:
        expected_unit = (canon_defs[item.item_code].unit or "EA").strip()
        if expected_unit != actual_unit:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"수동 추가 기구의 단위('{item.unit}')가 도면 매핑 정규 단위('{expected_unit}')와 "
                    f"일치하지 않습니다 (ADR-005)."
                ),
            )
    else:
        # P0 policy (M-UNIT-01 / BLOCKER-1): Manual-only items MUST be 'EA'. Non-EA (SET, M, etc.) is rejected with 400.
        if actual_unit != "EA":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"매핑되지 않은 수동 전용 품목('{item.item_code}')은 P0 정책(M-UNIT-01)상 'EA' 단위만 허용됩니다 "
                    f"(요청 단위: '{item.unit}')."
                ),
            )

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
    comp_header = "provisional" if result.is_provisional else "confirmed"
    return Response(
        content=data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "X-Takeoff-Completeness": comp_header,
            "X-Takeoff-Unresolved-Count": str(result.unresolved_count),
        },
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
    comp_header = "provisional" if result.is_provisional else "confirmed"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "X-Takeoff-Completeness": comp_header,
            "X-Takeoff-Unresolved-Count": str(result.unresolved_count),
        },
    )
