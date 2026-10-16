"""FastAPI Application for the Electrical AI Platform (MVP 1: DXF Smart Takeoff)."""

from __future__ import annotations

import math
import os
import urllib.parse
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cad_engine import DxfLoadError, parse_dxf
from cad_engine.schema import NormalizedDrawing
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .detector import detect_candidates
from .exporter import (
    export_csv_evidence,
    export_csv_summary,
    export_project_csv_breakdown,
    export_project_csv_delta,
    export_project_csv_summary,
    export_project_xlsx,
    export_xlsx,
)
from .image_parser import build_image_drawing, inspect_image
from .models import (
    ActivateRevisionRequest,
    ApplyTemplateRequest,
    CandidateBulkReviewRequest,
    CandidatesResponse,
    CandidatesSummary,
    CandidateStatus,
    DemoDrawingItem,
    DemoSeedResponse,
    DrawingScope,
    DrawingScopeUpdate,
    DrawingSummary,
    EvidenceReviewItem,
    InclusionStatus,
    ItemMappingRule,
    ManualObjectItem,
    MappingTemplate,
    MappingTemplateCreate,
    MappingTemplateListResponse,
    ProjectCreate,
    ProjectMetadata,
    ProjectTakeoffResult,
    RevisionComparisonResult,
    SheetRole,
    SymbolCandidate,
    SymbolSearchRequest,
    SymbolSearchResponse,
    TakeoffResult,
)
from .pdf_parser import (
    PdfCorruptError,
    PdfEncryptedError,
    PdfPageLimitExceededError,
    build_pdf_drawing,
    parse_pdf_document,
)
from .storage import Storage
from .visual_search import merge_candidates_spatial, search_visual_symbols

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
    user_message = f"{exc.message} {exc.detail}" if exc.detail else exc.message
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "DXF_LOAD_ERROR",
            "code": exc.code,
            "message": user_message,
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
    elif lower_name.endswith(".pdf") or content.startswith(b"%PDF-"):
        try:
            pdf_info = parse_pdf_document(content)
        except PdfEncryptedError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PdfPageLimitExceededError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PdfCorruptError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"PDF 도면 분석 실패: {e}") from e

        drawing_id = f"dwg_{uuid.uuid4().hex[:8]}"
        drawing = build_pdf_drawing(pdf_info, drawing_id, filename)
        first_p = pdf_info.pages[0] if pdf_info.pages else None
        pw = int(first_p.display_width_pt) if first_p else 595
        ph = int(first_p.display_height_pt) if first_p else 842

        storage.save_drawing(
            project_id,
            drawing,
            revision=revision,
            raw_bytes=content,
            source_type="PDF",
            file_type="PDF",
            coordinate_space="PDF_PAGE_POINT",
            dimensions={"width": pw, "height": ph},
            page_count=pdf_info.page_count,
            pages=[p.to_dict() for p in pdf_info.pages],
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
            "source_type": "PDF",
            "file_type": "PDF",
            "coordinate_space": "PDF_PAGE_POINT",
            "dimensions": {"width": pw, "height": ph},
            "page_count": pdf_info.page_count,
            "pages": [p.to_dict() for p in pdf_info.pages],
        }
    elif lower_name.endswith(".dwg"):
        raise HTTPException(
            status_code=400,
            detail="DWG 직접 업로드는 지원하지 않습니다. DXF 또는 PNG/JPG/PDF 형식으로 변환 후 업로드하세요 (DEC-001/PRD FR-002).",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 파일 형식입니다. .dxf, .png, .jpg, .pdf 파일만 지원됩니다.",
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


@app.get("/api/projects/{project_id}/drawings/{drawing_id}/pages/{page_index}/image")
def get_drawing_page_image(project_id: str, drawing_id: str, page_index: int) -> Response:
    try:
        image_path = storage.get_drawing_page_image_path(project_id, drawing_id, page_index)
    except (PdfCorruptError, PdfPageLimitExceededError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IndexError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not image_path or not image_path.exists():
        raise HTTPException(status_code=404, detail=f"페이지({page_index}) 이미지 파일을 찾을 수 없습니다.")
    return Response(
        content=image_path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/projects/{project_id}/drawings/{drawing_id}/pages/{page_index}/features")
def get_drawing_page_features(
    project_id: str,
    drawing_id: str,
    page_index: int,
) -> dict[str, Any]:
    """Extract vector PDF text and path features for a specific page (PR C: Issue #22)."""
    meta = storage.get_drawing_meta(project_id, drawing_id)
    if not meta:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")
    if meta.get("source_type") != "PDF":
        raise HTTPException(status_code=400, detail="PDF 도면만 벡터 피처(문자/선/도형) 추출을 지원합니다.")

    page_count = int(meta.get("page_count", 1))
    if page_index < 0 or page_index >= page_count:
        raise HTTPException(
            status_code=404,
            detail=f"페이지 인덱스({page_index})가 범위를 벗어났습니다. (총 {page_count}페이지)",
        )

    # 1. Check cached features
    cached = storage.get_drawing_page_features(project_id, drawing_id, page_index)
    if cached is not None:
        return cached

    # 2. Extract on demand
    raw_pdf_path = storage.get_raw_drawing_path(project_id, drawing_id)
    if not raw_pdf_path or not raw_pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF 원본 파일을 찾을 수 없습니다.")

    try:
        from .pdf_features import extract_pdf_page_features

        pdf_bytes = raw_pdf_path.read_bytes()
        pages_info = meta.get("pages", [])
        cb = None
        rot = None
        if isinstance(pages_info, list) and 0 <= page_index < len(pages_info):
            p_data = pages_info[page_index]
            if isinstance(p_data, dict):
                cb = p_data.get("cropbox")
                rot = p_data.get("rotation")

        feats = extract_pdf_page_features(
            pdf_bytes=pdf_bytes,
            page_index=page_index,
            drawing_id=drawing_id,
            cropbox=cb,
            rotation=rot,
        )
        data = feats.to_dict()
        storage.save_drawing_page_features(project_id, drawing_id, page_index, data)
        return data
    except (PdfCorruptError, PdfPageLimitExceededError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IndexError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"벡터 피처 추출 중 오류가 발생했습니다: {e}") from e


@app.get("/api/projects/{project_id}/drawings/{drawing_id}/image")
def get_drawing_image(project_id: str, drawing_id: str, page: int = Query(default=0, ge=0)) -> Response:
    meta = storage.get_drawing_meta(project_id, drawing_id)
    if meta and meta.get("source_type") == "PDF":
        try:
            image_path = storage.get_drawing_page_image_path(project_id, drawing_id, page)
        except (PdfCorruptError, PdfPageLimitExceededError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except IndexError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        if not image_path or not image_path.exists():
            raise HTTPException(status_code=404, detail="PDF 도면 페이지 이미지 파일을 찾을 수 없습니다.")
        return Response(
            content=image_path.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    image_path = storage.get_drawing_image_path(project_id, drawing_id)
    if not image_path or not image_path.exists():
        raise HTTPException(status_code=404, detail="이미지 도면 파일을 찾을 수 없습니다.")
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
    elif raw_path.suffix.lower() == ".pdf":
        media_type = "application/pdf"
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


def validate_drawing_mapping_units(drawing: Any, rules: list[ItemMappingRule]) -> None:
    """IMG-03, PR B & P0-MUNIT-03: On IMAGE/PDF drawings, all mapping units must be strictly 'EA'."""
    is_image = getattr(drawing, "source_type", None) == "IMAGE" or getattr(drawing, "coordinate_space", None) == "IMAGE_PIXEL"
    is_pdf = getattr(drawing, "source_type", None) == "PDF" or getattr(drawing, "coordinate_space", None) == "PDF_PAGE_POINT"
    if is_image:
        for r in rules:
            actual_u = (r.unit or "EA").strip()
            if actual_u != "EA":
                raise HTTPException(
                    status_code=400,
                    detail=f"이미지 도면(IMAGE_PIXEL)의 매핑 단위는 P0 원칙(IMG-03/M-UNIT-01)상 'EA'만 허용됩니다 (요청 단위: '{r.unit}').",
                )
    elif is_pdf:
        for r in rules:
            actual_u = (r.unit or "EA").strip()
            if actual_u != "EA":
                raise HTTPException(
                    status_code=400,
                    detail=f"PDF 도면(PDF_PAGE_POINT)의 매핑 단위는 P0 원칙(PR B/M-UNIT-01)상 'EA'만 허용됩니다 (요청 단위: '{r.unit}').",
                )


@app.put("/api/projects/{project_id}/drawings/{drawing_id}/mappings")
def save_mappings(
    project_id: str,
    drawing_id: str,
    mappings: list[ItemMappingRule],
) -> dict[str, Any]:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    validate_drawing_mapping_units(drawing, mappings)

    try:
        storage.save_mappings(project_id, drawing_id, mappings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "saved", "count": len(mappings)}


# ------------------------------------------------------------- Mapping Templates (Issue #23)
@app.get("/api/mapping-templates", response_model=MappingTemplateListResponse)
def list_mapping_templates() -> MappingTemplateListResponse:
    """List built-in and custom reusable legend/item mapping templates."""
    templates = storage.list_mapping_templates()
    return MappingTemplateListResponse(templates=templates, total=len(templates))


@app.post("/api/mapping-templates", response_model=MappingTemplate)
def create_mapping_template(payload: MappingTemplateCreate) -> MappingTemplate:
    """Save a new custom legend/item mapping template."""
    try:
        return storage.create_mapping_template(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/mapping-templates/{template_id}", response_model=MappingTemplate)
def get_mapping_template(template_id: str) -> MappingTemplate:
    """Get mapping template by ID."""
    tpl = storage.get_mapping_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")
    return tpl


@app.delete("/api/mapping-templates/{template_id}")
def delete_mapping_template(template_id: str) -> dict[str, str]:
    """Delete a custom mapping template (built-ins cannot be deleted)."""
    success = storage.delete_mapping_template(template_id)
    if not success:
        raise HTTPException(status_code=400, detail="기본 제공 템플릿은 삭제할 수 없거나 템플릿이 존재하지 않습니다.")
    return {"status": "deleted", "template_id": template_id}


@app.post("/api/projects/{project_id}/drawings/{drawing_id}/apply-template", response_model=list[ItemMappingRule])
def apply_mapping_template(
    project_id: str,
    drawing_id: str,
    req: ApplyTemplateRequest,
) -> list[ItemMappingRule]:
    """Apply a mapping template to the specified drawing."""
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    try:
        new_rules = storage.compute_template_mappings(
            project_id=project_id,
            drawing_id=drawing_id,
            template_id=req.template_id,
            merge_strategy=req.merge_strategy,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # P0-MUNIT-03: Shared unit validation ensures PDF/IMAGE drawings reject any non-EA template rules before saving
    validate_drawing_mapping_units(drawing, new_rules)

    storage.save_mappings(project_id, drawing_id, new_rules)
    return new_rules


# ------------------------------------------------------------- Guided Live Demo Seed (Issue #23)
def get_fixture_path(subpath: str) -> Path:
    p = Path(subpath)
    if p.exists():
        return p
    curr = Path(__file__).resolve().parent
    for _ in range(6):
        cand = curr / subpath
        if cand.exists():
            return cand
        curr = curr.parent
    raise FileNotFoundError(f"필수 데모 도면 fixture를 찾을 수 없습니다: {subpath}")


@app.post("/api/demo/seed", response_model=DemoSeedResponse)
def seed_demo_project(
    reset: bool = Query(False, description="기존 데모 데이터 초기화 여부"),
    type: Literal["format", "multi_drawing"] = Query(
        "format", description="데모 시나리오 (format: 3개 포맷, multi_drawing: 다중 도면 및 REV)"
    ),
) -> DemoSeedResponse:
    """Seed live demo project.

    Supports:
    - type="format": DXF, PDF, Image 3 formats with visual search (Issue #23/#29)
    - type="multi_drawing": Multi-drawing scope, 1F REV0 (6) + 2F (8) = 14 -> REV1 (10) = 18 (+4) (Issue #35)
    """
    if type == "multi_drawing":
        return seed_multi_drawing_demo_project(reset=reset)

    demo_name = "EAI 실전 전기 적산 데모 (Issue #23)"
    existing_projects = storage.list_projects()
    proj = next((p for p in existing_projects if p.name == demo_name), None)
    if not proj:
        proj_payload = ProjectCreate(
            name=demo_name,
            description="DXF, PDF, Image 3개 포맷 기호 탐지·매핑·일괄검수·물량산출 통합 시연 프로젝트",
        )
        proj = storage.create_project(proj_payload)
    else:
        existing_drawings = storage.list_drawings(proj.id)
        if not reset and len(existing_drawings) == 3:
            # Idempotent return: preserve user reviews and existing drawing states
            seeded_drawings: list[DemoDrawingItem] = []
            for d in existing_drawings:
                dwg = storage.get_drawing(proj.id, d.id)
                cands = storage.get_candidates(proj.id, d.id)
                meta = storage.get_drawing_meta(proj.id, d.id) or {}
                seeded_drawings.append(
                    DemoDrawingItem(
                        drawing_id=d.id,
                        filename=d.filename,
                        source_type=meta.get("source_type", "DXF"),
                        objects_count=len(dwg.objects) if dwg else 0,
                        candidates_count=len(cands),
                        status="ready",
                    )
                )
            return DemoSeedResponse(
                status="seeded",
                project_id=proj.id,
                project_name=proj.name,
                drawings=seeded_drawings,
                applied_template="tpl_standard_elec",
                note="기존 실전 데모 프로젝트 도면 및 검수 데이터 유지 (Idempotent No-op)",
            )

    seeded_drawings = []

    # 1. DXF Fixture with deterministic stable ID
    dxf_fixture = get_fixture_path("fixtures/dxf/basic_devices.dxf")
    raw_bytes = dxf_fixture.read_bytes()
    norm_dwg = parse_dxf(raw_bytes, filename=dxf_fixture.name)
    dxf_dwg_id = f"dwg_demo_dxf_{proj.id[-6:]}"
    norm_dwg.drawing_id = dxf_dwg_id
    storage.save_drawing(
        proj.id,
        norm_dwg,
        raw_bytes=raw_bytes,
        source_type="DXF",
        file_type="DXF",
        coordinate_space="WORLD",
    )
    storage.apply_mapping_template(proj.id, dxf_dwg_id, "tpl_standard_elec")
    cands = detect_candidates(
        norm_dwg,
        raw_bytes,
        dxf_dwg_id,
        source_type="DXF",
        mapping_rules=storage.get_mappings(proj.id, dxf_dwg_id),
    )
    storage.save_candidates(proj.id, dxf_dwg_id, cands)
    seeded_drawings.append(
        DemoDrawingItem(
            drawing_id=dxf_dwg_id,
            filename=dxf_fixture.name,
            source_type="DXF",
            objects_count=len(norm_dwg.objects),
            candidates_count=len(cands),
            status="ready",
        )
    )

    # 2. Vector PDF Fixture with deterministic stable ID
    pdf_fixture = get_fixture_path("fixtures/pdf/pdf_c_vector_features.pdf")
    raw_bytes = pdf_fixture.read_bytes()
    doc_info = parse_pdf_document(raw_bytes)
    pdf_dwg_id = f"dwg_demo_pdf_{proj.id[-6:]}"
    norm_dwg = build_pdf_drawing(doc_info, pdf_dwg_id, filename=pdf_fixture.name)
    first_p = doc_info.pages[0] if doc_info.pages else None
    pw = int(first_p.display_width_pt) if first_p else 595
    ph = int(first_p.display_height_pt) if first_p else 842
    storage.save_drawing(
        proj.id,
        norm_dwg,
        raw_bytes=raw_bytes,
        source_type="PDF",
        file_type="PDF",
        coordinate_space="PDF_PAGE_POINT",
        dimensions={"width": pw, "height": ph},
        page_count=doc_info.page_count,
        pages=[p.to_dict() for p in doc_info.pages],
    )
    cands = detect_candidates(
        norm_dwg,
        raw_bytes,
        pdf_dwg_id,
        source_type="PDF",
        page_count=doc_info.page_count,
    )
    storage.save_candidates(proj.id, pdf_dwg_id, cands)
    seeded_drawings.append(
        DemoDrawingItem(
            drawing_id=pdf_dwg_id,
            filename=pdf_fixture.name,
            source_type="PDF",
            objects_count=len(norm_dwg.objects),
            candidates_count=len(cands),
            status="ready",
        )
    )

    # 3. Raster Image Fixture with deterministic stable ID
    img_fixture = get_fixture_path("fixtures/images/floorplan_sample.png")
    raw_bytes = img_fixture.read_bytes()
    img_info = inspect_image(raw_bytes, filename=img_fixture.name)
    img_dwg_id = f"dwg_demo_img_{proj.id[-6:]}"
    norm_dwg = build_image_drawing(img_info, img_dwg_id)
    storage.save_drawing(
        proj.id,
        norm_dwg,
        raw_bytes=raw_bytes,
        source_type="IMAGE",
        file_type="PNG",
        coordinate_space="IMAGE_PIXEL",
        dimensions={"width": img_info.width, "height": img_info.height},
    )
    cands = detect_candidates(
        norm_dwg,
        raw_bytes,
        img_dwg_id,
        source_type="IMAGE",
    )
    storage.save_candidates(proj.id, img_dwg_id, cands)
    seeded_drawings.append(
        DemoDrawingItem(
            drawing_id=img_dwg_id,
            filename=img_fixture.name,
            source_type="IMAGE",
            objects_count=len(norm_dwg.objects),
            candidates_count=len(cands),
            status="ready",
        )
    )

    return DemoSeedResponse(
        status="seeded",
        project_id=proj.id,
        project_name=proj.name,
        drawings=seeded_drawings,
        applied_template="tpl_standard_elec",
        note="DXF·PDF·이미지 3개 포맷 데모 도면 및 표준 템플릿·기호 탐지 사전 적용 완료",
    )


@app.post(
    "/api/projects/{project_id}/drawings/{drawing_id}/search-symbol",
    response_model=SymbolSearchResponse,
)
def search_symbol(
    project_id: str,
    drawing_id: str,
    req: SymbolSearchRequest,
) -> SymbolSearchResponse:
    """Perform visual symbol template matching across an Image, PDF, or DXF drawing (Workstream B)."""
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    raw_path = storage.get_raw_drawing_path(project_id, drawing_id)
    raw_bytes = raw_path.read_bytes() if raw_path and raw_path.exists() else b""

    meta = storage.get_drawing_meta(project_id, drawing_id) or {}
    source_type = meta.get("source_type", "DXF")
    page_count = meta.get("page_count", 1)

    try:
        new_candidates = search_visual_symbols(
            drawing=drawing,
            raw_bytes=raw_bytes,
            drawing_id=drawing_id,
            source_type=source_type,
            sample_bbox=req.sample_bbox,
            page_index=req.page_index,
            search_all_pages=req.search_all_pages,
            page_count=page_count,
            suggested_item_code=req.suggested_item_code,
            suggested_item_name=req.suggested_item_name,
            threshold=req.threshold,
            max_results=req.max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"기호 시각적 검색 중 오류 발생: {e}") from e

    # Persist newly found visual candidates, merging with existing candidates spatially (P0-02)
    existing = storage.get_candidates(project_id, drawing_id)
    merged = merge_candidates_spatial(existing, new_candidates)
    storage.save_candidates(project_id, drawing_id, merged)

    return SymbolSearchResponse(
        drawing_id=drawing_id,
        page_index=req.page_index,
        total_found=len(new_candidates),
        candidates=new_candidates,
        message=f"{len(new_candidates)}개의 유사 기호 후보를 탐지하여 등록했습니다.",
    )



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

    is_image = getattr(drawing, "source_type", None) == "IMAGE" or getattr(drawing, "coordinate_space", None) == "IMAGE_PIXEL"
    is_pdf = getattr(drawing, "source_type", None) == "PDF" or getattr(drawing, "coordinate_space", None) == "PDF_PAGE_POINT"
    mappings = storage.get_mappings(project_id, drawing_id)
    canon_defs = {m.item_code: m for m in mappings if m.item_code not in ("EXCLUDE", "UNMAPPED")}
    manual_objs = {mo.id: mo for mo in storage.get_manual_objects(project_id, drawing_id)}
    cad_objs = {obj.id: obj for obj in drawing.objects if obj.entity_type == "INSERT"}

    # MUNIT-D / IMG-03 / PR B: Validate unit consistency on review reclassification
    for r in reviews:
        if not r.mapped_item_code or r.mapped_item_code in ("EXCLUDE", "UNMAPPED"):
            continue

        target_unit = (canon_defs[r.mapped_item_code].unit or "EA").strip() if r.mapped_item_code in canon_defs else "EA"

        # On IMAGE and PDF drawings, review reclassification to non-EA is strictly forbidden
        if is_image and target_unit != "EA":
            raise HTTPException(
                status_code=400,
                detail=f"이미지 도면(IMAGE_PIXEL)의 검수 재분류 단위는 P0 원칙(IMG-03)상 'EA'만 허용됩니다 (대상 단위: '{target_unit}').",
            )
        elif is_pdf and target_unit != "EA":
            raise HTTPException(
                status_code=400,
                detail=f"PDF 도면(PDF_PAGE_POINT)의 검수 재분류 단위는 P0 원칙(PR B)상 'EA'만 허용됩니다 (대상 단위: '{target_unit}').",
            )

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
@app.get("/api/projects/{project_id}/drawings/{drawing_id}/manual-objects")
def get_manual_objects(
    project_id: str,
    drawing_id: str,
) -> list[ManualObjectItem]:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")
    return storage.get_manual_objects(project_id, drawing_id)


@app.post("/api/projects/{project_id}/drawings/{drawing_id}/manual-objects")
def add_manual_object(
    project_id: str,
    drawing_id: str,
    item: ManualObjectItem,
) -> ManualObjectItem:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    # Traceability boundary: Ensure drawing_id in payload matches URL path parameter
    if item.drawing_id and item.drawing_id != drawing_id:
        raise HTTPException(
            status_code=400,
            detail=f"요청 본문의 drawing_id('{item.drawing_id}')가 URL 경로의 drawing_id('{drawing_id}')와 일치하지 않습니다.",
        )

    # High-2 Defense: Strict coordinate bounds for IMAGE drawings [0, width) and [0, height)
    is_image = getattr(drawing, "source_type", None) == "IMAGE" or getattr(drawing, "coordinate_space", None) == "IMAGE_PIXEL"
    is_pdf = getattr(drawing, "source_type", None) == "PDF" or getattr(drawing, "coordinate_space", None) == "PDF_PAGE_POINT"

    if is_image:
        dims = getattr(drawing, "dimensions", None) or {}
        img_w = float(dims.get("width") or (drawing.extents.max[0] if drawing.extents else 0))
        img_h = float(dims.get("height") or (drawing.extents.max[1] if drawing.extents else 0))
        if not (math.isfinite(item.x) and math.isfinite(item.y)):
            raise HTTPException(
                status_code=400,
                detail=f"수동 추가 좌표가 유효한 유한수(finite number)가 아닙니다 (x={item.x}, y={item.y}).",
            )
        # Pixel indices must be strictly within half-open interval [0, width) and [0, height)
        if item.x < 0.0 or item.x >= img_w or item.y < 0.0 or item.y >= img_h:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"수동 추가 기구 좌표(x={item.x}, y={item.y})가 "
                    f"이미지 도면의 픽셀 유효 범위(가로 0~{int(img_w) - 1}, 세로 0~{int(img_h) - 1})를 벗어났습니다. "
                    f"반열림 구간 [0, {int(img_w)}) × [0, {int(img_h)}) 내의 좌표만 허용됩니다."
                ),
            )
    elif is_pdf:
        pages_list = getattr(drawing, "pages", None) or []
        page_cnt = int(getattr(drawing, "page_count", len(pages_list)) or len(pages_list) or 1)
        if item.page_index < 0 or item.page_index >= page_cnt:
            raise HTTPException(
                status_code=400,
                detail=f"수동 추가 기구의 page_index({item.page_index})가 PDF 도면 페이지 범위([0, {page_cnt}))를 벗어났습니다.",
            )
        p_meta = pages_list[item.page_index] if item.page_index < len(pages_list) else None
        if p_meta:
            page_w = float(p_meta.get("display_width_pt") or 0.0)
            page_h = float(p_meta.get("display_height_pt") or 0.0)
        else:
            dims = getattr(drawing, "dimensions", None) or {}
            page_w = float(dims.get("width") or 595.0)
            page_h = float(dims.get("height") or 842.0)

        if not (math.isfinite(item.x) and math.isfinite(item.y)):
            raise HTTPException(
                status_code=400,
                detail=f"수동 추가 좌표가 유효한 유한수(finite number)가 아닙니다 (x={item.x}, y={item.y}).",
            )
        if item.x < 0.0 or item.x >= page_w or item.y < 0.0 or item.y >= page_h:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"수동 추가 기구 좌표(x={item.x}, y={item.y})가 "
                    f"PDF 도면 페이지({item.page_index})의 pt 유효 범위([0, {page_w:.1f}) × [0, {page_h:.1f}))를 벗어났습니다."
                ),
            )

    # ADR-005 / MUNIT-E: Validate non-empty unit
    actual_unit = (item.unit or "").strip()
    if not actual_unit:
        raise HTTPException(
            status_code=400,
            detail="수동 추가 기구의 단위(unit)가 누락되었거나 공백입니다. 유효한 단위(예: 'EA', 'SET' 등)를 지정해야 합니다 (ADR-005).",
        )

    # IMG-03 & PR B: On IMAGE and PDF drawings, manual objects MUST strictly have unit == "EA" (mapping-bypass prohibited)
    if is_image and actual_unit != "EA":
        raise HTTPException(
            status_code=400,
            detail=(
                f"이미지 도면(IMAGE_PIXEL)의 수동 추가 기구는 P0 원칙(IMG-03/M-UNIT-01)상 'EA' 단위만 허용됩니다 "
                f"(품목: '{item.item_code}', 요청 단위: '{item.unit}')."
            ),
        )
    elif is_pdf and actual_unit != "EA":
        raise HTTPException(
            status_code=400,
            detail=(
                f"PDF 도면(PDF_PAGE_POINT)의 수동 추가 기구는 P0 원칙(PR B/M-UNIT-01)상 'EA' 단위만 허용됩니다 "
                f"(품목: '{item.item_code}', 요청 단위: '{item.unit}')."
            ),
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

    # P0-02 (DOMAIN): Duplicate ID defense (idempotent replay on identical payload, 409 Conflict on mismatch)
    existing = next((o for o in objs if o.id == item.id), None)
    if existing is not None:
        is_identical = (
            math.isclose(existing.x, item.x, abs_tol=1e-5)
            and math.isclose(existing.y, item.y, abs_tol=1e-5)
            and existing.item_code == item.item_code
            and (existing.item_name or "") == (item.item_name or "")
            and existing.unit == item.unit
            and existing.drawing_id == item.drawing_id
            and getattr(existing, "page_index", None) == getattr(item, "page_index", None)
        )
        if is_identical:
            return existing
        else:
            raise HTTPException(
                status_code=409,
                detail=f"수동 기구 ID '{item.id}'가 이미 다른 속성으로 등록되어 있습니다 (중복 충돌).",
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


# ----------------------------------------------------------------------- Candidates (Issue #23)
@app.get("/api/projects/{project_id}/drawings/{drawing_id}/candidates")
def get_drawing_candidates(
    project_id: str,
    drawing_id: str,
) -> CandidatesResponse:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    candidates = storage.get_candidates(project_id, drawing_id)
    summary = CandidatesSummary(
        total=len(candidates),
        proposed=sum(1 for c in candidates if c.status == CandidateStatus.PROPOSED),
        accepted=sum(1 for c in candidates if c.status == CandidateStatus.ACCEPTED),
        rejected=sum(1 for c in candidates if c.status == CandidateStatus.REJECTED),
    )
    return CandidatesResponse(
        drawing_id=drawing_id,
        summary=summary,
        candidates=candidates,
    )


@app.post("/api/projects/{project_id}/drawings/{drawing_id}/candidates/detect")
def run_candidate_detection(
    project_id: str,
    drawing_id: str,
) -> CandidatesResponse:
    drawing = storage.get_drawing(project_id, drawing_id)
    meta = storage.get_drawing_meta(project_id, drawing_id)
    if not drawing or not meta:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    raw_path = storage.get_raw_drawing_path(project_id, drawing_id)
    raw_bytes = raw_path.read_bytes() if raw_path and raw_path.exists() else b""

    source_type = str(meta.get("source_type") or getattr(drawing, "source_type", "DXF"))
    page_count = int(meta.get("page_count", 1) or getattr(drawing, "page_count", 1) or 1)
    mapping_rules = storage.get_mappings(project_id, drawing_id)

    new_candidates = detect_candidates(
        drawing=drawing,
        raw_bytes=raw_bytes,
        drawing_id=drawing_id,
        source_type=source_type,
        page_count=page_count,
        mapping_rules=mapping_rules,
    )

    # Preserve any existing user reviews
    existing = {c.candidate_id: c for c in storage.get_candidates(project_id, drawing_id)}
    merged: list[SymbolCandidate] = []
    for cand in new_candidates:
        if cand.candidate_id in existing:
            prev = existing[cand.candidate_id]
            if prev.status in (CandidateStatus.ACCEPTED, CandidateStatus.REJECTED):
                cand.status = prev.status
                cand.suggested_item_code = prev.suggested_item_code
                cand.suggested_item_name = prev.suggested_item_name
                cand.reviewed_item_code = prev.reviewed_item_code
                cand.reviewed_at = prev.reviewed_at
                cand.review_note = prev.review_note
                cand.raw_evidence = prev.raw_evidence
            else:
                cand.status = prev.status
                cand.reviewed_item_code = prev.reviewed_item_code
                cand.reviewed_at = prev.reviewed_at
                cand.review_note = prev.review_note
        merged.append(cand)

    storage.save_candidates(project_id, drawing_id, merged)

    summary = CandidatesSummary(
        total=len(merged),
        proposed=sum(1 for c in merged if c.status == CandidateStatus.PROPOSED),
        accepted=sum(1 for c in merged if c.status == CandidateStatus.ACCEPTED),
        rejected=sum(1 for c in merged if c.status == CandidateStatus.REJECTED),
    )
    return CandidatesResponse(
        drawing_id=drawing_id,
        summary=summary,
        candidates=merged,
    )


@app.put("/api/projects/{project_id}/drawings/{drawing_id}/candidates/review")
def review_drawing_candidates(
    project_id: str,
    drawing_id: str,
    req: CandidateBulkReviewRequest,
) -> CandidatesResponse:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    candidates = storage.get_candidates(project_id, drawing_id)
    now = datetime.now(UTC)

    if req.action:
        for c in candidates:
            if req.filter_item_code and c.suggested_item_code != req.filter_item_code:
                continue

            if req.action == "ACCEPT_ALL":
                # P0-QTY-03: Only approve currently PROPOSED candidates, preserving existing ACCEPTED/REJECTED decisions
                if c.status == CandidateStatus.PROPOSED:
                    c.status = CandidateStatus.ACCEPTED
                    c.reviewed_at = now
                    if not c.review_note:
                        c.review_note = "일괄 승인"
            elif req.action == "REJECT_ALL":
                # P0-QTY-03: Only reject currently PROPOSED candidates, preserving existing ACCEPTED/REJECTED decisions
                if c.status == CandidateStatus.PROPOSED:
                    c.status = CandidateStatus.REJECTED
                    c.reviewed_at = now
                    if not c.review_note:
                        c.review_note = "일괄 거부"
            elif req.action == "RESET_ALL":
                c.status = CandidateStatus.PROPOSED
                c.reviewed_item_code = None
                c.reviewed_at = None
                c.review_note = ""
    elif req.updates:
        update_map = {u.candidate_id: u for u in req.updates}
        for c in candidates:
            if c.candidate_id in update_map:
                u = update_map[c.candidate_id]
                c.status = u.status
                c.reviewed_item_code = u.reviewed_item_code
                c.review_note = u.review_note
                c.reviewed_at = now

    storage.save_candidates(project_id, drawing_id, candidates)

    summary = CandidatesSummary(
        total=len(candidates),
        proposed=sum(1 for c in candidates if c.status == CandidateStatus.PROPOSED),
        accepted=sum(1 for c in candidates if c.status == CandidateStatus.ACCEPTED),
        rejected=sum(1 for c in candidates if c.status == CandidateStatus.REJECTED),
    )
    return CandidatesResponse(
        drawing_id=drawing_id,
        summary=summary,
        candidates=candidates,
    )


@app.delete("/api/projects/{project_id}/drawings/{drawing_id}/candidates")
def clear_drawing_candidates(
    project_id: str,
    drawing_id: str,
) -> dict[str, str]:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")
    storage.save_candidates(project_id, drawing_id, [])
    return {"status": "cleared"}


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


# -------------------------------------------------- Scope & Revision Registry (Issue #35)
@app.get("/api/projects/{project_id}/scopes", response_model=list[DrawingScope])
def get_project_drawing_scopes(project_id: str) -> list[DrawingScope]:
    proj = storage.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    return storage.list_drawing_scopes(project_id)


@app.get("/api/projects/{project_id}/drawings/{drawing_id}/scope", response_model=DrawingScope)
def get_drawing_scope(project_id: str, drawing_id: str) -> DrawingScope:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")
    return storage.get_drawing_scope(project_id, drawing_id)


@app.put("/api/projects/{project_id}/drawings/{drawing_id}/scope", response_model=DrawingScope)
def update_drawing_scope(
    project_id: str,
    drawing_id: str,
    req: DrawingScopeUpdate,
) -> DrawingScope:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    scope = storage.get_drawing_scope(project_id, drawing_id)
    if req.sheet_key is not None:
        scope.sheet_key = req.sheet_key
    if req.floor is not None:
        scope.floor = req.floor
    if req.zone is not None:
        scope.zone = req.zone
    if req.discipline is not None:
        scope.discipline = req.discipline
    if req.revision is not None:
        scope.revision = req.revision
    if req.sheet_role is not None:
        scope.sheet_role = req.sheet_role
        if req.sheet_role != SheetRole.INSTALLATION and req.active_for_takeoff is None:
            scope.active_for_takeoff = False
    if req.active_for_takeoff is not None:
        scope.active_for_takeoff = req.active_for_takeoff
    if req.description is not None:
        scope.description = req.description

    scope.updated_at = datetime.now(UTC)
    storage.save_drawing_scope(project_id, drawing_id, scope)
    return scope


@app.post(
    "/api/projects/{project_id}/drawings/{drawing_id}/activate-revision",
    response_model=DrawingScope,
)
def activate_revision(
    project_id: str,
    drawing_id: str,
    req: ActivateRevisionRequest | None = None,
) -> DrawingScope:
    drawing = storage.get_drawing(project_id, drawing_id)
    if not drawing:
        raise HTTPException(status_code=404, detail="도면을 찾을 수 없습니다.")

    active = req.active if req else True
    if active:
        target_scope, _ = storage.activate_drawing_revision(project_id, drawing_id)
        return target_scope
    else:
        scope = storage.get_drawing_scope(project_id, drawing_id)
        scope.active_for_takeoff = False
        scope.updated_at = datetime.now(UTC)
        storage.save_drawing_scope(project_id, drawing_id, scope)
        return scope


# -------------------------------------------------- Project Takeoff (Issue #35)
@app.get("/api/projects/{project_id}/takeoff", response_model=ProjectTakeoffResult)
def get_project_consolidated_takeoff(project_id: str) -> ProjectTakeoffResult:
    proj = storage.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    return storage.calculate_project_takeoff(project_id)


# -------------------------------------------------- Revision Comparison (Issue #35)
@app.get("/api/projects/{project_id}/revisions/compare", response_model=RevisionComparisonResult)
def compare_drawing_revisions(
    project_id: str,
    base_drawing_id: str = Query(..., description="기준 도면 ID (이전 REV)"),
    compare_drawing_id: str = Query(..., description="비교 도면 ID (신규/변경 REV)"),
) -> RevisionComparisonResult:
    base_dwg = storage.get_drawing(project_id, base_drawing_id)
    if not base_dwg:
        raise HTTPException(status_code=404, detail="기준 도면을 찾을 수 없습니다.")
    comp_dwg = storage.get_drawing(project_id, compare_drawing_id)
    if not comp_dwg:
        raise HTTPException(status_code=404, detail="비교 도면을 찾을 수 없습니다.")

    return storage.compare_revisions(project_id, base_drawing_id, compare_drawing_id)


# -------------------------------------------------- Project Export (Issue #35)
@app.get("/api/projects/{project_id}/export/xlsx")
def export_project_excel(project_id: str) -> Response:
    proj = storage.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    p_result = storage.calculate_project_takeoff(project_id)

    scopes = storage.list_drawing_scopes(project_id)
    groups: dict[str, list[DrawingScope]] = {}
    for s in scopes:
        groups.setdefault(s.sheet_key, []).append(s)

    deltas: list[RevisionComparisonResult] = []
    for _sk, dwg_list in groups.items():
        if len(dwg_list) >= 2:
            dwg_list_sorted = sorted(dwg_list, key=lambda x: x.revision)
            for i in range(len(dwg_list_sorted) - 1):
                try:
                    delta = storage.compare_revisions(
                        project_id, dwg_list_sorted[i].drawing_id, dwg_list_sorted[i + 1].drawing_id
                    )
                    deltas.append(delta)
                except Exception:
                    pass

    active_takeoffs: list[TakeoffResult] = []
    for s in p_result.drawings_scope:
        if s.active_for_takeoff:
            t_res = storage.calculate_takeoff(project_id, s.drawing_id)
            if t_res:
                active_takeoffs.append(t_res)

    data = export_project_xlsx(p_result, revision_deltas=deltas, active_takeoffs=active_takeoffs)
    filename = f"{proj.name}_project_takeoff_4sheets.xlsx"
    quoted = urllib.parse.quote(filename)
    comp_header = "provisional" if p_result.is_provisional else "confirmed"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "X-Takeoff-Completeness": comp_header,
            "X-Takeoff-Unresolved-Count": str(p_result.unresolved_count),
        },
    )


@app.get("/api/projects/{project_id}/export/csv")
def export_project_csv_endpoint(
    project_id: str,
    type: Literal["summary", "breakdown", "delta"] = "summary",
) -> Response:
    proj = storage.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")

    p_result = storage.calculate_project_takeoff(project_id)
    if type == "summary":
        data = export_project_csv_summary(p_result)
        filename = f"{proj.name}_project_summary.csv"
    elif type == "breakdown":
        data = export_project_csv_breakdown(p_result)
        filename = f"{proj.name}_drawing_breakdown.csv"
    else:
        scopes = storage.list_drawing_scopes(project_id)
        groups: dict[str, list[DrawingScope]] = {}
        for s in scopes:
            groups.setdefault(s.sheet_key, []).append(s)

        deltas: list[RevisionComparisonResult] = []
        for _sk, dwg_list in groups.items():
            if len(dwg_list) >= 2:
                dwg_list_sorted = sorted(dwg_list, key=lambda x: x.revision)
                for i in range(len(dwg_list_sorted) - 1):
                    try:
                        delta = storage.compare_revisions(
                            project_id, dwg_list_sorted[i].drawing_id, dwg_list_sorted[i + 1].drawing_id
                        )
                        deltas.append(delta)
                    except Exception:
                        pass
        data = export_project_csv_delta(deltas)
        filename = f"{proj.name}_revision_delta.csv"

    quoted = urllib.parse.quote(filename)
    comp_header = "provisional" if p_result.is_provisional else "confirmed"
    return Response(
        content=data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "X-Takeoff-Completeness": comp_header,
            "X-Takeoff-Unresolved-Count": str(p_result.unresolved_count),
        },
    )


# -------------------------------------------------- Multi-Drawing Demo Seeding (Issue #35)
@app.post("/api/demo/seed-multi-drawing", response_model=DemoSeedResponse)
def seed_multi_drawing_demo_project(
    reset: bool = Query(True, description="기존 프로젝트 데이터 재설정 여부"),
) -> DemoSeedResponse:
    """Seed multi-drawing project with 1F REV0 (6), 2F REV0 (8), 1F REV1 (10), 1F REF (6).

    Target ground truth:
    - Initial active: 1F REV0 (6) + 2F REV0 (8) = 14 LIGHT
    - Switch 1F to REV1 (10): Total = 18 LIGHT (+4)
    - 1F REF is reference role and inactive (6 excluded).
    """
    demo_name = "EAI 실전 다중 도면 및 설계변경 적산 데모 (Issue #35)"
    existing_projects = storage.list_projects()
    proj = next((p for p in existing_projects if p.name == demo_name), None)
    if not proj:
        proj_payload = ProjectCreate(
            name=demo_name,
            description="다중 도면 스코프·REV 교체(14→18/+4)·4시트 엑셀 내보내기 실전 시연 프로젝트",
        )
        proj = storage.create_project(proj_payload)
    elif reset:
        for d in storage.list_drawings(proj.id):
            storage.delete_drawing(proj.id, d.id)

    seeded_drawings: list[DemoDrawingItem] = []

    # 1. 1F REV0
    p1 = get_fixture_path("fixtures/dxf/project_demo/floor1_rev0.dxf")
    raw1 = p1.read_bytes()
    dwg1 = parse_dxf(raw1, filename=p1.name)
    id1 = f"dwg_f1_r0_{proj.id[-6:]}"
    dwg1.drawing_id = id1
    storage.save_drawing(proj.id, dwg1, revision="REV0", raw_bytes=raw1, source_type="DXF")
    storage.apply_mapping_template(proj.id, id1, "tpl_standard_elec")
    scope1 = DrawingScope(
        drawing_id=id1,
        project_id=proj.id,
        sheet_key="1F_LIGHT",
        floor="1F",
        discipline="ELEC_LIGHT",
        revision="REV0",
        sheet_role=SheetRole.INSTALLATION,
        active_for_takeoff=True,
        is_latest=False,
        description="1층 전등설비 평면도 REV0",
    )
    storage.save_drawing_scope(proj.id, id1, scope1)
    seeded_drawings.append(DemoDrawingItem(drawing_id=id1, filename=p1.name, source_type="DXF", objects_count=len(dwg1.objects), status="ready"))

    # 2. 2F REV0
    p2 = get_fixture_path("fixtures/dxf/project_demo/floor2_rev0.dxf")
    raw2 = p2.read_bytes()
    dwg2 = parse_dxf(raw2, filename=p2.name)
    id2 = f"dwg_f2_r0_{proj.id[-6:]}"
    dwg2.drawing_id = id2
    storage.save_drawing(proj.id, dwg2, revision="REV0", raw_bytes=raw2, source_type="DXF")
    storage.apply_mapping_template(proj.id, id2, "tpl_standard_elec")
    scope2 = DrawingScope(
        drawing_id=id2,
        project_id=proj.id,
        sheet_key="2F_LIGHT",
        floor="2F",
        discipline="ELEC_LIGHT",
        revision="REV0",
        sheet_role=SheetRole.INSTALLATION,
        active_for_takeoff=True,
        is_latest=True,
        description="2층 전등설비 평면도 REV0",
    )
    storage.save_drawing_scope(proj.id, id2, scope2)
    seeded_drawings.append(DemoDrawingItem(drawing_id=id2, filename=p2.name, source_type="DXF", objects_count=len(dwg2.objects), status="ready"))

    # 3. 1F REV1 (Design Change: +4 LIGHTs)
    p3 = get_fixture_path("fixtures/dxf/project_demo/floor1_rev1.dxf")
    raw3 = p3.read_bytes()
    dwg3 = parse_dxf(raw3, filename=p3.name)
    id3 = f"dwg_f1_r1_{proj.id[-6:]}"
    dwg3.drawing_id = id3
    storage.save_drawing(proj.id, dwg3, revision="REV1", raw_bytes=raw3, source_type="DXF")
    storage.apply_mapping_template(proj.id, id3, "tpl_standard_elec")
    scope3 = DrawingScope(
        drawing_id=id3,
        project_id=proj.id,
        sheet_key="1F_LIGHT",
        floor="1F",
        discipline="ELEC_LIGHT",
        revision="REV1",
        sheet_role=SheetRole.INSTALLATION,
        active_for_takeoff=False,
        is_latest=True,
        description="1층 전등설비 설계변경 REV1 (+4구)",
    )
    storage.save_drawing_scope(proj.id, id3, scope3)
    seeded_drawings.append(DemoDrawingItem(drawing_id=id3, filename=p3.name, source_type="DXF", objects_count=len(dwg3.objects), status="ready"))

    # 4. 1F Reference Schematic (Reference role, inactive)
    p4 = get_fixture_path("fixtures/dxf/project_demo/floor1_ref_singleline.dxf")
    raw4 = p4.read_bytes()
    dwg4 = parse_dxf(raw4, filename=p4.name)
    id4 = f"dwg_f1_ref_{proj.id[-6:]}"
    dwg4.drawing_id = id4
    storage.save_drawing(proj.id, dwg4, revision="REV0", raw_bytes=raw4, source_type="DXF")
    storage.apply_mapping_template(proj.id, id4, "tpl_standard_elec")
    scope4 = DrawingScope(
        drawing_id=id4,
        project_id=proj.id,
        sheet_key="1F_REF",
        floor="1F",
        discipline="ELEC_LIGHT",
        revision="REV0",
        sheet_role=SheetRole.REFERENCE,
        active_for_takeoff=False,
        is_latest=False,
        description="1층 전등 간선계통도 (참조용, 산출 제외)",
    )
    storage.save_drawing_scope(proj.id, id4, scope4)
    seeded_drawings.append(DemoDrawingItem(drawing_id=id4, filename=p4.name, source_type="DXF", objects_count=len(dwg4.objects), status="ready"))

    return DemoSeedResponse(
        status="seeded",
        project_id=proj.id,
        project_name=proj.name,
        drawings=seeded_drawings,
        applied_template="tpl_standard_elec",
        note="다중 층(1F/2F), 설계변경 REV1, 참조도면 포함 실전 프로젝트 시드 완료 (14→18/+4 정답 검증 준비)",
    )

