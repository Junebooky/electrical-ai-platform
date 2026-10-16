"""Local file-based persistence for projects, drawings, mappings, and takeoff reviews."""

from __future__ import annotations

import contextlib
import json
import math
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from cad_engine.schema import NormalizedDrawing, WarningCode
from cad_engine.takeoff import BlockMapping, Disposition, aggregate

from .models import (
    CalibrationData,
    CalibrationMethod,
    CalibrationRequest,
    CandidateStatus,
    DrawingScope,
    DrawingSummary,
    DrawingTakeoffBreakdownItem,
    EvidenceReviewItem,
    InclusionStatus,
    ItemMappingRule,
    ManualMeasuredRoute,
    ManualObjectItem,
    MappingTemplate,
    MappingTemplateCreate,
    ProjectCreate,
    ProjectMetadata,
    ProjectTakeoffResult,
    ProjectTakeoffSummaryRow,
    QuantityMethod,
    ReviewStatus,
    RevisionComparisonResult,
    RevisionItemDelta,
    RevisionObjectDelta,
    RouteCategory,
    RouteCreateRequest,
    RouteStatus,
    RouteUpdateRequest,
    SheetRole,
    SymbolCandidate,
    TakeoffEvidenceRow,
    TakeoffResult,
    TakeoffSummaryRow,
)
from .visual_search import are_candidates_spatially_coincident

DEFAULT_DATA_DIR = Path(os.environ.get("EAI_DATA_DIR", "./.eai_data")).resolve()


class Storage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DEFAULT_DATA_DIR
        self.projects_dir = self.root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir = self.root / "templates"
        self.templates_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- Projects
    def create_project(self, payload: ProjectCreate, project_id: str | None = None) -> ProjectMetadata:
        pid = project_id or f"proj_{uuid.uuid4().hex[:8]}"
        proj_dir = self.projects_dir / pid
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "drawings").mkdir(exist_ok=True)

        now = datetime.now(UTC)
        meta = ProjectMetadata(
            id=pid,
            name=payload.name or "새 프로젝트",
            description=payload.description or "",
            created_at=now,
            updated_at=now,
            drawing_count=0,
        )
        self._save_json(proj_dir / "project.json", meta.model_dump(mode="json"))
        return meta

    def list_projects(self) -> list[ProjectMetadata]:
        projects: list[ProjectMetadata] = []
        for p_dir in self.projects_dir.iterdir():
            if not p_dir.is_dir():
                continue
            meta_file = p_dir / "project.json"
            if meta_file.exists():
                try:
                    data = json.loads(meta_file.read_text(encoding="utf-8"))
                    # calculate actual drawing count
                    drawings_dir = p_dir / "drawings"
                    if drawings_dir.exists():
                        data["drawing_count"] = sum(1 for d in drawings_dir.iterdir() if d.is_dir())
                    projects.append(ProjectMetadata(**data))
                except Exception:
                    pass
        projects.sort(key=lambda p: p.created_at, reverse=True)
        return projects

    def get_project(self, project_id: str) -> ProjectMetadata | None:
        p_dir = self.projects_dir / project_id
        meta_file = p_dir / "project.json"
        if not meta_file.exists():
            return None
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        drawings_dir = p_dir / "drawings"
        if drawings_dir.exists():
            data["drawing_count"] = sum(1 for d in drawings_dir.iterdir() if d.is_dir())
        return ProjectMetadata(**data)

    def delete_project(self, project_id: str) -> bool:
        p_dir = self.projects_dir / project_id
        if not p_dir.exists():
            return False
        shutil.rmtree(p_dir, ignore_errors=True)
        return True

    # ------------------------------------------------------------- Drawings
    def save_drawing(
        self,
        project_id: str,
        drawing: NormalizedDrawing,
        revision: str = "REV0",
        raw_bytes: bytes | None = None,
        source_type: str = "DXF",
        file_type: str = "DXF",
        coordinate_space: str = "WORLD",
        dimensions: dict[str, int] | None = None,
        page_count: int = 1,
        pages: list[dict[str, object]] | None = None,
    ) -> Path:
        d_dir = self.projects_dir / project_id / "drawings" / drawing.drawing_id
        d_dir.mkdir(parents=True, exist_ok=True)

        # 1. save normalized drawing
        drawing_file = d_dir / "drawing.json"
        self._save_json(drawing_file, drawing.model_dump(mode="json"))

        # 2. save raw bytes if provided (FR-002, QA-DEF-01)
        raw_saved = False
        raw_filename = (
            f"raw.{file_type.lower()}"
            if file_type.lower() in ("png", "jpg", "jpeg", "pdf")
            else "raw.dxf"
        )
        if raw_bytes is not None:
            raw_file = d_dir / raw_filename
            raw_file.write_bytes(raw_bytes)
            raw_saved = True

        # 3. save metadata
        meta = {
            "id": drawing.drawing_id,
            "project_id": project_id,
            "filename": drawing.source.filename,
            "file_hash": drawing.source.sha256,
            "file_size_bytes": len(raw_bytes) if raw_bytes is not None else drawing.source.size_bytes,
            "raw_file_saved": raw_saved,
            "raw_filename": raw_filename if raw_saved else None,
            "revision": revision,
            "units_name": drawing.dxf.units_name,
            "insunits": drawing.dxf.insunits,
            "created_at": datetime.now(UTC).isoformat(),
            "objects_count": len(drawing.objects),
            "warnings_count": len(drawing.warnings),
            "source_type": source_type,
            "file_type": file_type,
            "coordinate_space": coordinate_space,
            "dimensions": dimensions,
            "page_count": page_count,
            "pages": pages,
        }
        self._save_json(d_dir / "meta.json", meta)

        # 4. default mappings / reviews / manual objects if not present
        if not (d_dir / "mappings.json").exists():
            self._save_json(d_dir / "mappings.json", [])
        if not (d_dir / "reviews.json").exists():
            self._save_json(d_dir / "reviews.json", {})
        if not (d_dir / "manual_objects.json").exists():
            self._save_json(d_dir / "manual_objects.json", [])

        return d_dir

    def get_raw_drawing_path(self, project_id: str, drawing_id: str) -> Path | None:
        d_dir = self.projects_dir / project_id / "drawings" / drawing_id
        meta_file = d_dir / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if meta.get("raw_filename"):
                    raw_fn = str(meta["raw_filename"])
                    p = d_dir / raw_fn
                    if p.exists():
                        return p
            except Exception:
                pass
        for name in ("raw.dxf", "raw.png", "raw.jpg", "raw.jpeg", "raw.pdf"):
            raw_file = d_dir / name
            if raw_file.exists():
                return raw_file
        return None

    def get_drawing_page_image_path(
        self, project_id: str, drawing_id: str, page_index: int = 0
    ) -> Path | None:
        meta = self.get_drawing_meta(project_id, drawing_id)
        if meta and meta.get("source_type") == "PDF":
            page_count = int(meta.get("page_count", 1))
            if page_index < 0 or page_index >= page_count:
                return None

        d_dir = self.projects_dir / project_id / "drawings" / drawing_id
        page_img = d_dir / "pages" / f"page_{page_index}.png"
        if page_img.exists():
            return page_img

        # P0-03: Bounded lazy-on-demand render (renders single requested page on demand)
        raw_pdf = d_dir / "raw.pdf"
        if raw_pdf.exists():
            from .pdf_parser import render_pdf_page_image
            png_bytes, _, _ = render_pdf_page_image(raw_pdf.read_bytes(), page_index)
            pages_dir = d_dir / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)
            page_img.write_bytes(png_bytes)
            return page_img
        return None

    def get_drawing_page_features(
        self, project_id: str, drawing_id: str, page_index: int
    ) -> dict[str, Any] | None:
        feat_path = (
            self.projects_dir
            / project_id
            / "drawings"
            / drawing_id
            / "features"
            / f"page_{page_index}.json"
        )
        if feat_path.exists():
            return cast(dict[str, Any], json.loads(feat_path.read_text(encoding="utf-8")))
        return None

    def save_drawing_page_features(
        self, project_id: str, drawing_id: str, page_index: int, features: dict[str, Any]
    ) -> None:
        feat_dir = self.projects_dir / project_id / "drawings" / drawing_id / "features"
        feat_dir.mkdir(parents=True, exist_ok=True)
        self._save_json(feat_dir / f"page_{page_index}.json", features)

    def get_drawing_image_path(self, project_id: str, drawing_id: str) -> Path | None:
        d_dir = self.projects_dir / project_id / "drawings" / drawing_id
        for name in ("raw.png", "raw.jpg", "raw.jpeg"):
            p = d_dir / name
            if p.exists():
                return p
        # For PDF drawing, return page 0 image
        return self.get_drawing_page_image_path(project_id, drawing_id, 0)

    def list_drawings(self, project_id: str) -> list[DrawingSummary]:
        d_root = self.projects_dir / project_id / "drawings"
        if not d_root.exists():
            return []
        drawings: list[DrawingSummary] = []
        for d_dir in d_root.iterdir():
            if not d_dir.is_dir():
                continue
            meta_file = d_dir / "meta.json"
            if meta_file.exists():
                try:
                    data = json.loads(meta_file.read_text(encoding="utf-8"))
                    drawings.append(DrawingSummary(**data))
                except Exception:
                    pass
        drawings.sort(key=lambda d: d.created_at, reverse=True)
        return drawings

    def get_drawing(self, project_id: str, drawing_id: str) -> NormalizedDrawing | None:
        d_file = self.projects_dir / project_id / "drawings" / drawing_id / "drawing.json"
        if not d_file.exists():
            return None
        data = json.loads(d_file.read_text(encoding="utf-8"))
        nd = NormalizedDrawing(**data)
        meta = self.get_drawing_meta(project_id, drawing_id)
        if meta:
            if meta.get("page_count"):
                nd.page_count = int(meta["page_count"])
            if meta.get("pages"):
                nd.pages = meta["pages"]
            if meta.get("source_type"):
                nd.source_type = str(meta["source_type"])
            if meta.get("file_type"):
                nd.file_type = str(meta["file_type"])
            if meta.get("coordinate_space"):
                nd.coordinate_space = str(meta["coordinate_space"])
            if meta.get("dimensions"):
                nd.dimensions = meta["dimensions"]
        return nd

    def delete_drawing(self, project_id: str, drawing_id: str) -> bool:
        d_dir = self.projects_dir / project_id / "drawings" / drawing_id
        if d_dir.exists():
            shutil.rmtree(d_dir, ignore_errors=True)
            return True
        return False

    def get_drawing_meta(self, project_id: str, drawing_id: str) -> dict[str, Any] | None:
        meta_file = self.projects_dir / project_id / "drawings" / drawing_id / "meta.json"
        if not meta_file.exists():
            return None
        return cast(dict[str, Any], json.loads(meta_file.read_text(encoding="utf-8")))

    # ------------------------------------------------------------- Mappings
    def get_mappings(self, project_id: str, drawing_id: str) -> list[ItemMappingRule]:
        f = self.projects_dir / project_id / "drawings" / drawing_id / "mappings.json"
        if not f.exists():
            return []
        data = json.loads(f.read_text(encoding="utf-8"))
        return [ItemMappingRule(**m) for m in data]

    def save_mappings(
        self, project_id: str, drawing_id: str, mappings: list[ItemMappingRule]
    ) -> None:
        validate_canonical_mappings(mappings)
        f = self.projects_dir / project_id / "drawings" / drawing_id / "mappings.json"
        self._save_json(f, [m.model_dump(mode="json") for m in mappings])

    # ------------------------------------------------------------- Mapping Templates (Issue #23)
    def _get_builtin_templates(self) -> list[MappingTemplate]:
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        return [
            MappingTemplate(
                id="tpl_standard_elec",
                name="표준 전기설비 기본 템플릿 (조명·전열·스위치·분전반)",
                description="아파트·상업용 기본 블록명(LT-DL, OT-2P, SW-1 등) 표준 매핑",
                created_at=now,
                updated_at=now,
                is_builtin=True,
                rules=[
                    ItemMappingRule(block_name="LT-DL", item_code="LIGHT", item_name="다운라이트", unit="EA"),
                    ItemMappingRule(block_name="LT-FL", item_code="LIGHT", item_name="형광등/직부등", unit="EA"),
                    ItemMappingRule(block_name="LIGHT", item_code="LIGHT", item_name="조명기구", unit="EA"),
                    ItemMappingRule(block_name="OT-2P", item_code="OUTLET", item_name="2구 매입 콘센트", unit="EA"),
                    ItemMappingRule(block_name="OUTLET", item_code="OUTLET", item_name="전열 콘센트", unit="EA"),
                    ItemMappingRule(block_name="SW-1", item_code="SWITCH", item_name="1로 조명 스위치", unit="EA"),
                    ItemMappingRule(block_name="SW-2", item_code="SWITCH", item_name="2로 조명 스위치", unit="EA"),
                    ItemMappingRule(block_name="SWITCH", item_code="SWITCH", item_name="조명 스위치", unit="EA"),
                    ItemMappingRule(block_name="PANEL", item_code="PANEL", item_name="분전반", unit="EA"),
                    ItemMappingRule(block_name="DB", item_code="PANEL", item_name="배전분전반", unit="EA"),
                ],
            ),
            MappingTemplate(
                id="tpl_kec_standard",
                name="KEC 참고 배선기구 템플릿 (참고 예시)",
                description="한국전기설비규정(KEC) 설계 참고용 예시 심벌 (공인 인증 기호 아님)",
                created_at=now,
                updated_at=now,
                is_builtin=True,
                rules=[
                    ItemMappingRule(block_name="KEC-LT", item_code="LIGHT", item_name="KEC 고효율 조명기구", unit="EA"),
                    ItemMappingRule(block_name="KEC-CON", item_code="OUTLET", item_name="KEC 접지극부 2구 콘센트", unit="EA"),
                    ItemMappingRule(block_name="KEC-SW", item_code="SWITCH", item_name="KEC 로커 스위치", unit="EA"),
                    ItemMappingRule(block_name="KEC-DB", item_code="PANEL", item_name="KEC 주택용 분전반", unit="EA"),
                ],
            ),
        ]

    def list_mapping_templates(self) -> list[MappingTemplate]:
        templates = self._get_builtin_templates()
        if self.templates_dir.exists():
            for t_file in sorted(self.templates_dir.glob("*.json")):
                try:
                    data = json.loads(t_file.read_text(encoding="utf-8"))
                    templates.append(MappingTemplate(**data))
                except Exception:
                    pass
        return templates

    def get_mapping_template(self, template_id: str) -> MappingTemplate | None:
        for t in self._get_builtin_templates():
            if t.id == template_id:
                return t
        t_file = self.templates_dir / f"{template_id}.json"
        if t_file.exists():
            try:
                data = json.loads(t_file.read_text(encoding="utf-8"))
                return MappingTemplate(**data)
            except Exception:
                pass
        return None

    def create_mapping_template(self, payload: MappingTemplateCreate) -> MappingTemplate:
        tpl_id = f"tpl_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        validate_canonical_mappings(payload.rules)
        template = MappingTemplate(
            id=tpl_id,
            name=payload.name,
            description=payload.description,
            created_at=now,
            updated_at=now,
            rules=payload.rules,
            is_builtin=False,
        )
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self._save_json(self.templates_dir / f"{tpl_id}.json", template.model_dump(mode="json"))
        return template

    def delete_mapping_template(self, template_id: str) -> bool:
        if any(t.id == template_id for t in self._get_builtin_templates()):
            return False
        t_file = self.templates_dir / f"{template_id}.json"
        if t_file.exists():
            t_file.unlink()
            return True
        return False

    def compute_template_mappings(
        self,
        project_id: str,
        drawing_id: str,
        template_id: str,
        merge_strategy: str = "MERGE",
    ) -> list[ItemMappingRule]:
        """Compute candidate mappings when applying a template without saving to disk yet.

        MERGE: Preserves existing mappings completely (user overrides like LT-DL -> EM_LIGHT are
               NOT overwritten). Only missing block mappings from the template are appended.
        REPLACE: Completely replaces the drawing's mapping rules with the template's rules.
        """
        template = self.get_mapping_template(template_id)
        if not template:
            raise ValueError(f"템플릿을 찾을 수 없습니다: {template_id}")

        existing = self.get_mappings(project_id, drawing_id)
        if merge_strategy == "REPLACE":
            return list(template.rules)

        # MERGE: Keep existing rule intact, only append rules for unseen block names
        merged = list(existing)
        seen_blocks = {r.block_name for r in existing}
        for tpl_r in template.rules:
            if tpl_r.block_name not in seen_blocks:
                merged.append(tpl_r)
                seen_blocks.add(tpl_r.block_name)

        return merged

    def apply_mapping_template(
        self,
        project_id: str,
        drawing_id: str,
        template_id: str,
        merge_strategy: str = "MERGE",
    ) -> list[ItemMappingRule]:
        new_rules = self.compute_template_mappings(
            project_id=project_id,
            drawing_id=drawing_id,
            template_id=template_id,
            merge_strategy=merge_strategy,
        )
        self.save_mappings(project_id, drawing_id, new_rules)
        return new_rules

    # ------------------------------------------------------------- Reviews
    def get_reviews(self, project_id: str, drawing_id: str) -> dict[str, EvidenceReviewItem]:
        f = self.projects_dir / project_id / "drawings" / drawing_id / "reviews.json"
        if not f.exists():
            return {}
        data = json.loads(f.read_text(encoding="utf-8"))
        return {k: EvidenceReviewItem(**v) for k, v in data.items()}

    def save_reviews(
        self, project_id: str, drawing_id: str, reviews: dict[str, EvidenceReviewItem]
    ) -> None:
        f = self.projects_dir / project_id / "drawings" / drawing_id / "reviews.json"
        self._save_json(f, {k: v.model_dump(mode="json") for k, v in reviews.items()})

    # ------------------------------------------------------------- Manual Objects
    def get_manual_objects(self, project_id: str, drawing_id: str) -> list[ManualObjectItem]:
        f = self.projects_dir / project_id / "drawings" / drawing_id / "manual_objects.json"
        if not f.exists():
            return []
        data = json.loads(f.read_text(encoding="utf-8"))
        objects: list[ManualObjectItem] = []
        for item in data:
            try:
                objects.append(ManualObjectItem(**item))
            except Exception:
                # Allow legacy/tampered non-finite or out-of-spec items to load
                # so calculate_takeoff can rigorously fail-close them
                objects.append(ManualObjectItem.model_construct(**item))
        return objects

    def save_manual_objects(
        self, project_id: str, drawing_id: str, objects: list[ManualObjectItem]
    ) -> None:
        f = self.projects_dir / project_id / "drawings" / drawing_id / "manual_objects.json"
        self._save_json(f, [item.model_dump(mode="json") for item in objects])

    # ------------------------------------------------------------- Candidates (Issue #23)
    def get_candidates(self, project_id: str, drawing_id: str) -> list[SymbolCandidate]:
        f = self.projects_dir / project_id / "drawings" / drawing_id / "candidates.json"
        if not f.exists():
            return []
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return [SymbolCandidate.model_validate(item) for item in data]
        except Exception:
            return []

    def save_candidates(
        self, project_id: str, drawing_id: str, candidates: list[SymbolCandidate]
    ) -> None:
        f = self.projects_dir / project_id / "drawings" / drawing_id / "candidates.json"
        self._save_json(f, [item.model_dump(mode="json") for item in candidates])

    # ------------------------------------------------------------- Calculations
    def calculate_takeoff(self, project_id: str, drawing_id: str) -> TakeoffResult | None:
        drawing = self.get_drawing(project_id, drawing_id)
        if drawing is None:
            return None
        meta = self.get_drawing_meta(project_id, drawing_id) or {}
        mappings = self.get_mappings(project_id, drawing_id)
        reviews = self.get_reviews(project_id, drawing_id)
        manual_objects = self.get_manual_objects(project_id, drawing_id)
        candidates = self.get_candidates(project_id, drawing_id)
        routes = self.list_drawing_routes(project_id, drawing_id)

        return build_takeoff_result(
            drawing=drawing,
            meta=meta,
            mapping_rules=mappings,
            reviews=reviews,
            manual_objects=manual_objects,
            candidates=candidates,
            routes=routes,
        )

    # ------------------------------------------------------------- Calibration (Issue #37 Workstream A)
    def get_drawing_calibration(
        self, project_id: str, drawing_id: str, page_index: int = 0
    ) -> CalibrationData:
        d_dir = self.projects_dir / project_id / "drawings" / drawing_id
        calib_file = d_dir / "calibrations.json"
        if calib_file.exists():
            try:
                data = json.loads(calib_file.read_text(encoding="utf-8"))
                if str(page_index) in data:
                    return CalibrationData.model_validate(data[str(page_index)])
            except Exception:
                pass

        meta = self.get_drawing_meta(project_id, drawing_id) or {}
        source_type = meta.get("source_type", "DXF")
        coord_space = meta.get("coordinate_space", "WORLD")

        if source_type == "DXF":
            insunits = meta.get("insunits", 0)
            insunits_to_scale = {
                1: (0.0254, "인치(Inches) 0.0254m"),
                2: (0.3048, "피트(Feet) 0.3048m"),
                4: (0.001, "밀리미터(mm) 0.001m"),
                5: (0.01, "센티미터(cm) 0.01m"),
                6: (1.0, "미터(m) 1.0m"),
            }
            if insunits in insunits_to_scale:
                ratio, desc = insunits_to_scale[insunits]
                return CalibrationData(
                    drawing_id=drawing_id,
                    page_index=page_index,
                    coordinate_space=coord_space,
                    scale_ratio_m_per_unit=ratio,
                    is_calibrated=True,
                    method=CalibrationMethod.DXF_INSUNITS,
                    notes=f"DXF $INSUNITS={insunits} ({desc}) 기반 자동 축척 환산",
                )
            else:
                return CalibrationData(
                    drawing_id=drawing_id,
                    page_index=page_index,
                    coordinate_space=coord_space,
                    scale_ratio_m_per_unit=None,
                    is_calibrated=False,
                    method=CalibrationMethod.DXF_INSUNITS,
                    warning="DXF INSUNITS 미설정(0/단위미지정) 도면입니다. 실측 2점 축척 보정이 필요합니다.",
                )
        elif source_type == "PDF":
            return CalibrationData(
                drawing_id=drawing_id,
                page_index=page_index,
                coordinate_space="PDF_PAGE_POINT",
                scale_ratio_m_per_unit=None,
                is_calibrated=False,
                method=CalibrationMethod.TWO_POINT_MANUAL,
                warning=f"PDF {page_index + 1}페이지 미보정 상태입니다. 도면 위 두 점의 실제 거리를 입력해 축척을 보정하세요.",
            )
        else:  # IMAGE
            return CalibrationData(
                drawing_id=drawing_id,
                page_index=page_index,
                coordinate_space="IMAGE_PIXEL",
                scale_ratio_m_per_unit=None,
                is_calibrated=False,
                method=CalibrationMethod.TWO_POINT_MANUAL,
                warning="이미지 미보정 상태입니다. 도면 위 두 점의 실제 거리를 입력해 축척을 보정하세요.",
            )

    def save_drawing_calibration(
        self, project_id: str, drawing_id: str, req: CalibrationRequest
    ) -> CalibrationData:
        d_dir = self.projects_dir / project_id / "drawings" / drawing_id
        meta = self.get_drawing_meta(project_id, drawing_id) or {}
        coord_space = meta.get("coordinate_space", "WORLD")
        if meta.get("source_type") == "PDF":
            coord_space = "PDF_PAGE_POINT"
        elif meta.get("source_type") == "IMAGE":
            coord_space = "IMAGE_PIXEL"

        dx = req.point_b.x - req.point_a.x
        dy = req.point_b.y - req.point_a.y
        pixel_dist = math.hypot(dx, dy)
        if pixel_dist <= 1e-6:
            raise ValueError("두 점 사이의 거리가 너무 가깝거나 동일합니다. 서로 다른 두 점을 선택해 주세요.")

        real_m = req.real_distance if req.unit == "m" else req.real_distance / 1000.0
        if real_m <= 0 or not math.isfinite(real_m):
            raise ValueError("실제 거리는 0보다 큰 유한한 숫자여야 합니다.")

        scale_ratio = real_m / pixel_dist

        calib = CalibrationData(
            drawing_id=drawing_id,
            page_index=req.page_index,
            coordinate_space=coord_space,
            point_a=req.point_a,
            point_b=req.point_b,
            pixel_distance=round(pixel_dist, 4),
            real_world_distance_m=round(real_m, 4),
            input_unit=req.unit,
            scale_ratio_m_per_unit=scale_ratio,
            is_calibrated=True,
            method=CalibrationMethod.TWO_POINT_MANUAL,
            notes=req.notes or f"2점 실측 보정: {pixel_dist:.1f}단위 = {real_m:.2f}m",
            warning=None,
            calibrated_at=datetime.now(UTC),
        )

        calib_file = d_dir / "calibrations.json"
        calibs_dict: dict[str, Any] = {}
        if calib_file.exists():
            with contextlib.suppress(Exception):
                calibs_dict = json.loads(calib_file.read_text(encoding="utf-8"))
        calibs_dict[str(req.page_index)] = calib.model_dump(mode="json")
        self._save_json(calib_file, calibs_dict)

        self._recalculate_routes_for_page(project_id, drawing_id, req.page_index, calib)
        return calib

    def delete_drawing_calibration(
        self, project_id: str, drawing_id: str, page_index: int = 0
    ) -> None:
        d_dir = self.projects_dir / project_id / "drawings" / drawing_id
        calib_file = d_dir / "calibrations.json"
        if calib_file.exists():
            try:
                calibs_dict = json.loads(calib_file.read_text(encoding="utf-8"))
                if str(page_index) in calibs_dict:
                    del calibs_dict[str(page_index)]
                    self._save_json(calib_file, calibs_dict)
            except Exception:
                pass

        fallback_calib = self.get_drawing_calibration(project_id, drawing_id, page_index)
        self._recalculate_routes_for_page(project_id, drawing_id, page_index, fallback_calib)

    def _recalculate_routes_for_page(
        self, project_id: str, drawing_id: str, page_index: int, calib: CalibrationData
    ) -> None:
        routes = self.list_drawing_routes(project_id, drawing_id)
        updated = False
        for r in routes:
            if r.page_index == page_index:
                if calib.is_calibrated and calib.scale_ratio_m_per_unit:
                    r.length_2d_m = round(r.raw_length * calib.scale_ratio_m_per_unit, 2)
                    r.is_calibrated = True
                    r.calibration_id = f"calib_{page_index}"
                else:
                    r.length_2d_m = None
                    r.is_calibrated = False
                    r.calibration_id = None
                r.updated_at = datetime.now(UTC)
                updated = True
        if updated:
            self._save_routes(project_id, drawing_id, routes)

    # ------------------------------------------------------------- Route Measurement (Issue #37 Workstream B & C)
    def list_drawing_routes(
        self, project_id: str, drawing_id: str, page_index: int | None = None
    ) -> list[ManualMeasuredRoute]:
        d_dir = self.projects_dir / project_id / "drawings" / drawing_id
        route_file = d_dir / "routes.json"
        if not route_file.exists():
            return []
        try:
            data = json.loads(route_file.read_text(encoding="utf-8"))
            routes = [ManualMeasuredRoute.model_validate(item) for item in data]
            if page_index is not None:
                routes = [r for r in routes if r.page_index == page_index]
            return routes
        except Exception:
            return []

    def _save_routes(
        self, project_id: str, drawing_id: str, routes: list[ManualMeasuredRoute]
    ) -> None:
        d_dir = self.projects_dir / project_id / "drawings" / drawing_id
        d_dir.mkdir(parents=True, exist_ok=True)
        self._save_json(d_dir / "routes.json", [r.model_dump(mode="json") for r in routes])

    def get_drawing_route(
        self, project_id: str, drawing_id: str, route_id: str
    ) -> ManualMeasuredRoute | None:
        routes = self.list_drawing_routes(project_id, drawing_id)
        for r in routes:
            if r.id == route_id:
                return r
        return None

    def create_drawing_route(
        self, project_id: str, drawing_id: str, req: RouteCreateRequest
    ) -> ManualMeasuredRoute:
        if len(req.points) < 2:
            raise ValueError("경로는 최소 2개 이상의 좌표점이 필요합니다.")

        meta = self.get_drawing_meta(project_id, drawing_id) or {}
        scope = self.get_drawing_scope(project_id, drawing_id)

        coord_space = req.coordinate_space or meta.get("coordinate_space", "WORLD")
        if meta.get("source_type") == "PDF":
            coord_space = "PDF_PAGE_POINT"
        elif meta.get("source_type") == "IMAGE":
            coord_space = "IMAGE_PIXEL"

        raw_len = 0.0
        for i in range(len(req.points) - 1):
            p1 = req.points[i]
            p2 = req.points[i + 1]
            raw_len += math.hypot(p2.x - p1.x, p2.y - p1.y)

        calib = self.get_drawing_calibration(project_id, drawing_id, req.page_index)
        length_2d_m: float | None = None
        is_calibrated = False
        calib_id: str | None = None
        if calib.is_calibrated and calib.scale_ratio_m_per_unit:
            length_2d_m = round(raw_len * calib.scale_ratio_m_per_unit, 2)
            is_calibrated = True
            calib_id = f"calib_{req.page_index}"

        item_code = req.item_code
        item_name = req.item_name
        if not item_code:
            if req.category == RouteCategory.WIRING:
                item_code = "ROUTE_WIRING"
                item_name = item_name or "배선 (2D 계획 경로)"
            elif req.category == RouteCategory.CONDUIT:
                item_code = "ROUTE_CONDUIT"
                item_name = item_name or "전선관 (2D 계획 경로)"
            else:
                item_code = "ROUTE_OTHER"
                item_name = item_name or "기타 경로 (2D 계획 경로)"
        else:
            item_name = item_name or item_code

        route = ManualMeasuredRoute(
            id=f"route_{uuid.uuid4().hex[:8]}",
            drawing_id=drawing_id,
            sheet_key=scope.sheet_key if scope else None,
            revision=scope.revision if scope else None,
            page_index=req.page_index,
            coordinate_space=coord_space,
            points=req.points,
            category=req.category,
            item_code=item_code,
            item_name=item_name,
            spec=req.spec,
            raw_length=round(raw_len, 4),
            length_2d_m=length_2d_m,
            is_calibrated=is_calibrated,
            calibration_id=calib_id,
            status=req.status,
            review_note=req.review_note,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        routes = self.list_drawing_routes(project_id, drawing_id)
        routes.append(route)
        self._save_routes(project_id, drawing_id, routes)
        return route

    def update_drawing_route(
        self, project_id: str, drawing_id: str, route_id: str, req: RouteUpdateRequest
    ) -> ManualMeasuredRoute | None:
        routes = self.list_drawing_routes(project_id, drawing_id)
        target: ManualMeasuredRoute | None = None
        for r in routes:
            if r.id == route_id:
                target = r
                break
        if not target:
            return None

        if req.points is not None:
            if len(req.points) < 2:
                raise ValueError("경로는 최소 2개 이상의 좌표점이 필요합니다.")
            target.points = req.points
            raw_len = sum(
                math.hypot(req.points[i + 1].x - req.points[i].x, req.points[i + 1].y - req.points[i].y)
                for i in range(len(req.points) - 1)
            )
            target.raw_length = round(raw_len, 4)
            calib = self.get_drawing_calibration(project_id, drawing_id, target.page_index)
            if calib.is_calibrated and calib.scale_ratio_m_per_unit:
                target.length_2d_m = round(raw_len * calib.scale_ratio_m_per_unit, 2)
                target.is_calibrated = True
            else:
                target.length_2d_m = None
                target.is_calibrated = False

        if req.category is not None:
            target.category = req.category
        if req.item_code is not None:
            target.item_code = req.item_code
        if req.item_name is not None:
            target.item_name = req.item_name
        if req.spec is not None:
            target.spec = req.spec
        if req.status is not None:
            target.status = req.status
        if req.review_note is not None:
            target.review_note = req.review_note

        target.updated_at = datetime.now(UTC)
        self._save_routes(project_id, drawing_id, routes)
        return target

    def delete_drawing_route(
        self, project_id: str, drawing_id: str, route_id: str
    ) -> bool:
        routes = self.list_drawing_routes(project_id, drawing_id)
        init_len = len(routes)
        routes = [r for r in routes if r.id != route_id]
        if len(routes) < init_len:
            self._save_routes(project_id, drawing_id, routes)
            return True
        return False

    # -------------------------------------------------- Scope & Revision Registry
    def get_drawing_scope(self, project_id: str, drawing_id: str) -> DrawingScope:
        scope_file = self.projects_dir / project_id / "drawings" / drawing_id / "scope.json"
        if scope_file.exists():
            try:
                data = json.loads(scope_file.read_text(encoding="utf-8"))
                return DrawingScope.model_validate(data)
            except Exception:
                pass

        # Graceful fallback: infer from meta.json without modifying it
        meta = self.get_drawing_meta(project_id, drawing_id) or {}
        raw_rev = meta.get("revision", "REV0")
        filename = meta.get("filename", "")

        fn_lower = filename.lower()
        floor = "1F"
        if "floor2" in fn_lower or "2f" in fn_lower or "2층" in fn_lower:
            floor = "2F"
        elif "floor3" in fn_lower or "3f" in fn_lower:
            floor = "3F"
        elif "b1" in fn_lower or "지하1층" in fn_lower:
            floor = "B1"

        discipline = "ELEC_LIGHT"
        if "power" in fn_lower or "전열" in fn_lower:
            discipline = "ELEC_POWER"
        elif "comm" in fn_lower or "통신" in fn_lower:
            discipline = "ELEC_COMM"
        elif "fire" in fn_lower or "소방" in fn_lower:
            discipline = "ELEC_FIRE"

        role = SheetRole.INSTALLATION
        active_for_takeoff = True
        if "ref" in fn_lower or "singleline" in fn_lower or "계통도" in fn_lower:
            role = SheetRole.REFERENCE
            active_for_takeoff = False
        elif "detail" in fn_lower or "상세" in fn_lower:
            role = SheetRole.DETAIL
            active_for_takeoff = False
        elif "legend" in fn_lower or "범례" in fn_lower:
            role = SheetRole.LEGEND
            active_for_takeoff = False

        sheet_key = f"{floor}_{discipline}"

        return DrawingScope(
            drawing_id=drawing_id,
            project_id=project_id,
            sheet_key=sheet_key,
            floor=floor,
            zone=None,
            discipline=discipline,
            revision=raw_rev,
            sheet_role=role,
            active_for_takeoff=active_for_takeoff,
            is_latest=True,
            description=filename,
        )

    def save_drawing_scope(
        self, project_id: str, drawing_id: str, scope: DrawingScope
    ) -> None:
        scope_file = self.projects_dir / project_id / "drawings" / drawing_id / "scope.json"
        self._save_json(scope_file, scope.model_dump(mode="json"))

    def list_drawing_scopes(self, project_id: str) -> list[DrawingScope]:
        drawings = self.list_drawings(project_id)
        return [self.get_drawing_scope(project_id, d.id) for d in drawings]

    def activate_drawing_revision(
        self, project_id: str, target_drawing_id: str
    ) -> tuple[DrawingScope, list[DrawingScope]]:
        """Set target drawing active for takeoff, deactivating other revisions with the same sheet_key."""
        target_scope = self.get_drawing_scope(project_id, target_drawing_id)
        if target_scope.sheet_role != SheetRole.INSTALLATION:
            raise ValueError(
                f"시공 설치 도면(INSTALLATION)만 수량 산출 활성화가 가능합니다. (현재 역할: {target_scope.sheet_role})"
            )
        target_scope.active_for_takeoff = True
        target_scope.updated_at = datetime.now(UTC)
        self.save_drawing_scope(project_id, target_drawing_id, target_scope)

        deactivated: list[DrawingScope] = []
        all_scopes = self.list_drawing_scopes(project_id)
        for s in all_scopes:
            if s.drawing_id != target_drawing_id and s.sheet_key == target_scope.sheet_key and s.active_for_takeoff:
                s.active_for_takeoff = False
                s.updated_at = datetime.now(UTC)
                self.save_drawing_scope(project_id, s.drawing_id, s)
                deactivated.append(s)

        return target_scope, deactivated

    # ------------------------------------------------------------- Project Takeoff
    def calculate_project_takeoff(self, project_id: str) -> ProjectTakeoffResult:
        proj = self.get_project(project_id)
        project_name = proj.name if proj else "프로젝트"

        scopes = self.list_drawing_scopes(project_id)
        # Workstream 0 Guardrail 2: Only INSTALLATION drawings can contribute to takeoff!
        active_scopes = [s for s in scopes if s.active_for_takeoff and s.sheet_role == SheetRole.INSTALLATION]
        inactive_scopes = [s for s in scopes if not (s.active_for_takeoff and s.sheet_role == SheetRole.INSTALLATION)]

        scope_warnings: list[str] = []
        # Workstream 0 Guardrail 1: Check for duplicate active scopes in installation role
        active_sheet_keys: dict[str, list[DrawingScope]] = {}
        for s in active_scopes:
            active_sheet_keys.setdefault(s.sheet_key, []).append(s)

        conflicted_sheet_keys: set[str] = set()
        for sk, dwg_scopes in active_sheet_keys.items():
            if len(dwg_scopes) > 1:
                conflicted_sheet_keys.add(sk)
                scope_warnings.append(
                    f"동일 도면 그룹 '{sk}'에 복수의 활성 도면({len(dwg_scopes)}개)이 활성화되어 있어 "
                    "중복 합산 방지를 위해 해당 그룹 산출이 보류(fail-closed)되었습니다. 단일 활성 REV를 지정해 주세요."
                )

        drawings_breakdown: list[DrawingTakeoffBreakdownItem] = []
        agg_map: dict[tuple[str, str, str], dict[str, Any]] = {}
        total_unresolved = 0
        any_provisional = False

        for s in active_scopes:
            t_res = self.calculate_takeoff(project_id, s.drawing_id)
            if not t_res:
                continue

            drawings_breakdown.append(
                DrawingTakeoffBreakdownItem(
                    drawing_id=s.drawing_id,
                    filename=t_res.drawing_name,
                    sheet_key=s.sheet_key,
                    floor=s.floor,
                    discipline=s.discipline,
                    revision=s.revision,
                    sheet_role=s.sheet_role,
                    active_for_takeoff=s.active_for_takeoff,
                    items=t_res.summary,
                    unresolved_count=t_res.unresolved_count,
                    is_provisional=t_res.is_provisional or (s.sheet_key in conflicted_sheet_keys),
                )
            )

            if t_res.is_provisional or (s.sheet_key in conflicted_sheet_keys):
                any_provisional = True
            total_unresolved += t_res.unresolved_count

            # Fail-closed: do NOT aggregate conflicted sheet_keys into project summary
            if s.sheet_key in conflicted_sheet_keys:
                continue

            for row in t_res.summary:
                # Key strictly separates item_code, unit, and specification
                key = (row.item_code, row.unit, row.specification)
                if key not in agg_map:
                    agg_map[key] = {
                        "item_code": row.item_code,
                        "item_name": row.item_name,
                        "specification": row.specification,
                        "unit": row.unit,
                        "total_quantity": 0 if row.unit == "EA" else 0.0,
                        "contributing_drawings": set(),
                        "is_provisional": False,
                        "review_status": ReviewStatus.REVIEWED,
                        "quantity_method": row.quantity_method,
                    }
                agg_map[key]["total_quantity"] += row.quantity
                if isinstance(agg_map[key]["total_quantity"], float):
                    agg_map[key]["total_quantity"] = round(agg_map[key]["total_quantity"], 2)
                agg_map[key]["contributing_drawings"].add(s.drawing_id)
                if row.is_provisional or row.review_status != ReviewStatus.REVIEWED:
                    agg_map[key]["is_provisional"] = True
                    agg_map[key]["review_status"] = ReviewStatus.UNREVIEWED

        summary_rows: list[ProjectTakeoffSummaryRow] = []
        total_equipment_ea = 0
        total_route_length_m = 0.0

        for _key, d in sorted(agg_map.items(), key=lambda x: (x[0][0], x[0][1])):
            summary_rows.append(
                ProjectTakeoffSummaryRow(
                    item_code=d["item_code"],
                    item_name=d["item_name"],
                    specification=d["specification"],
                    unit=d["unit"],
                    total_quantity=d["total_quantity"],
                    active_drawings_count=len(d["contributing_drawings"]),
                    is_provisional=d["is_provisional"],
                    review_status=d["review_status"],
                    quantity_method=d["quantity_method"],
                    notes=f"{len(d['contributing_drawings'])}개 활성 도면에서 합산",
                )
            )
            if d["unit"] == "EA" and isinstance(d["total_quantity"], (int, float)):
                total_equipment_ea += int(d["total_quantity"])
            elif d["unit"] == "m" and isinstance(d["total_quantity"], (int, float)):
                total_route_length_m += float(d["total_quantity"])

        total_route_length_m = round(total_route_length_m, 2)

        return ProjectTakeoffResult(
            project_id=project_id,
            project_name=project_name,
            total_active_drawings=len(active_scopes),
            total_inactive_drawings=len(inactive_scopes),
            summary=summary_rows,
            drawings_breakdown=drawings_breakdown,
            drawings_scope=scopes,
            scope_warnings=scope_warnings,
            unresolved_count=total_unresolved,
            is_provisional=any_provisional or bool(conflicted_sheet_keys),
            total_equipment_ea=total_equipment_ea,
            total_route_length_m=total_route_length_m,
            exported_at=datetime.now(UTC),
        )

    # -------------------------------------------------------- Revision Comparison
    def compare_revisions(
        self, project_id: str, base_drawing_id: str, compare_drawing_id: str
    ) -> RevisionComparisonResult:
        base_takeoff = self.calculate_takeoff(project_id, base_drawing_id)
        compare_takeoff = self.calculate_takeoff(project_id, compare_drawing_id)
        base_scope = self.get_drawing_scope(project_id, base_drawing_id)
        compare_scope = self.get_drawing_scope(project_id, compare_drawing_id)

        base_sum_map = {
            (r.item_code, r.unit): r for r in (base_takeoff.summary if base_takeoff else [])
        }
        compare_sum_map = {
            (r.item_code, r.unit): r for r in (compare_takeoff.summary if compare_takeoff else [])
        }

        all_keys = sorted(set(base_sum_map.keys()) | set(compare_sum_map.keys()))
        items_delta: list[RevisionItemDelta] = []
        total_base: int | float = 0
        total_compare: int | float = 0

        for item_code, unit in all_keys:
            b_row = base_sum_map.get((item_code, unit))
            c_row = compare_sum_map.get((item_code, unit))
            b_qty = b_row.quantity if b_row else (0 if unit == "EA" else 0.0)
            c_qty = c_row.quantity if c_row else (0 if unit == "EA" else 0.0)
            delta = round(c_qty - b_qty, 2) if isinstance(c_qty, float) or isinstance(b_qty, float) else c_qty - b_qty
            total_base += b_qty
            total_compare += c_qty

            item_name = c_row.item_name if c_row else (b_row.item_name if b_row else item_code)
            spec = c_row.specification if c_row else (b_row.specification if b_row else "기본")

            if b_qty == 0 and c_qty > 0:
                change_type = "ADDED"
            elif b_qty > 0 and c_qty == 0:
                change_type = "REMOVED"
            elif delta > 0:
                change_type = "INCREASED"
            elif delta < 0:
                change_type = "DECREASED"
            else:
                change_type = "UNCHANGED"

            items_delta.append(
                RevisionItemDelta(
                    item_code=item_code,
                    item_name=item_name,
                    specification=spec,
                    unit=unit,
                    base_quantity=b_qty,
                    compare_quantity=c_qty,
                    delta=delta,
                    change_type=change_type,
                    notes=f"기준: {b_qty} {unit} → 변경: {c_qty} {unit} ({delta:+d})",
                )
            )

        # Object-level correspondence diff
        base_ev = base_takeoff.evidence if base_takeoff else []
        compare_ev = compare_takeoff.evidence if compare_takeoff else []

        object_deltas: list[RevisionObjectDelta] = []
        matched_base_ids: set[str] = set()

        for c_obj in compare_ev:
            if c_obj.inclusion_status != InclusionStatus.INCLUDED:
                continue
            best_match: TakeoffEvidenceRow | None = None
            best_dist = float("inf")
            for b_obj in base_ev:
                if b_obj.inclusion_status != InclusionStatus.INCLUDED:
                    continue
                if b_obj.source_object_id in matched_base_ids:
                    continue
                if b_obj.mapped_item_code == c_obj.mapped_item_code:
                    dist = math.hypot(b_obj.x - c_obj.x, b_obj.y - c_obj.y)
                    if dist < best_dist:
                        best_dist = dist
                        best_match = b_obj

            if best_match and best_dist < 1.0:
                matched_base_ids.add(best_match.source_object_id)
                object_deltas.append(
                    RevisionObjectDelta(
                        object_id=c_obj.source_object_id,
                        item_code=c_obj.mapped_item_code,
                        x=c_obj.x,
                        y=c_obj.y,
                        layer=c_obj.layer_name,
                        match_status="MATCHED",
                        confidence=1.0,
                        notes="동일 위치 기물 일치",
                    )
                )
            elif best_match and best_dist < 60.0:
                matched_base_ids.add(best_match.source_object_id)
                object_deltas.append(
                    RevisionObjectDelta(
                        object_id=c_obj.source_object_id,
                        item_code=c_obj.mapped_item_code,
                        x=c_obj.x,
                        y=c_obj.y,
                        layer=c_obj.layer_name,
                        match_status="PROPOSED_MATCH",
                        confidence=0.75,
                        notes="위치 근접 기물 (추정/검토 필요)",
                    )
                )
            else:
                object_deltas.append(
                    RevisionObjectDelta(
                        object_id=c_obj.source_object_id,
                        item_code=c_obj.mapped_item_code,
                        x=c_obj.x,
                        y=c_obj.y,
                        layer=c_obj.layer_name,
                        match_status="ADDED",
                        confidence=1.0,
                        notes="신규 추가된 기물",
                    )
                )

        for b_obj in base_ev:
            if b_obj.inclusion_status == InclusionStatus.INCLUDED and b_obj.source_object_id not in matched_base_ids:
                object_deltas.append(
                    RevisionObjectDelta(
                        object_id=b_obj.source_object_id,
                        item_code=b_obj.mapped_item_code,
                        x=b_obj.x,
                        y=b_obj.y,
                        layer=b_obj.layer_name,
                        match_status="REMOVED",
                        confidence=1.0,
                        notes="설계변경으로 삭제된 기물",
                    )
                )

        return RevisionComparisonResult(
            project_id=project_id,
            base_drawing={
                "drawing_id": base_drawing_id,
                "drawing_name": base_takeoff.drawing_name if base_takeoff else "",
                "revision": base_scope.revision,
                "sheet_key": base_scope.sheet_key,
                "floor": base_scope.floor,
                "discipline": base_scope.discipline,
                "total_quantity": total_base,
            },
            compare_drawing={
                "drawing_id": compare_drawing_id,
                "drawing_name": compare_takeoff.drawing_name if compare_takeoff else "",
                "revision": compare_scope.revision,
                "sheet_key": compare_scope.sheet_key,
                "floor": compare_scope.floor,
                "discipline": compare_scope.discipline,
                "total_quantity": total_compare,
            },
            items_delta=items_delta,
            object_deltas=object_deltas,
            total_base_qty=total_base,
            total_compare_qty=total_compare,
            total_delta=round(total_compare - total_base, 2) if isinstance(total_compare, float) or isinstance(total_base, float) else total_compare - total_base,
            notes=f"품목 총합 증감: {total_compare - total_base:+}",
        )

    def _save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp.{uuid.uuid4().hex[:6]}")
        try:
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                with contextlib.suppress(OSError):
                    tmp_path.unlink()


def find_canonical_item_conflicts(
    mapping_rules: list[ItemMappingRule],
) -> tuple[dict[str, ItemMappingRule], set[str]]:
    """Verify ADR-005: 1 item_code = 1 canonical definition (unit, specification).
    Returns (canonical_meta, conflicted_item_codes).
    If multiple rules define conflicting units or specifications for the same item_code,
    the item_code is flagged in conflicted_item_codes and neither definition overrides the other.
    """
    canonical_meta: dict[str, ItemMappingRule] = {}
    conflicted_codes: set[str] = set()

    for m in mapping_rules:
        if m.item_code in ("EXCLUDE", "UNMAPPED"):
            continue
        code = m.item_code
        if code in canonical_meta:
            prev = canonical_meta[code]
            prev_u = (prev.unit or "").strip()
            curr_u = (m.unit or "").strip()
            prev_s = (prev.specification or "").strip()
            curr_s = (m.specification or "").strip()

            if prev_u != curr_u or prev_s != curr_s:
                conflicted_codes.add(code)
            elif not prev.item_name and m.item_name:
                # Merge non-empty item_name if definition matches
                canonical_meta[code] = m
        else:
            canonical_meta[code] = m

    return canonical_meta, conflicted_codes


def validate_canonical_mappings(mapping_rules: list[ItemMappingRule]) -> None:
    """Validate that mappings do not violate ADR-005 canonical item contract.
    Raises ValueError with descriptive detail if conflicting definitions exist or unit is empty."""
    for r in mapping_rules:
        if r.item_code in ("EXCLUDE", "UNMAPPED"):
            continue
        if not (r.unit or "").strip():
            raise ValueError(
                f"품목 '{r.item_code}'의 단위(unit)가 누락되었거나 공백입니다. "
                "P0 실물 품목은 유효한 단위(예: 'EA', 'SET', 'M' 등)를 지정해야 합니다 (ADR-005 / A05 도메인 기준)."
            )

    _, conflicted = find_canonical_item_conflicts(mapping_rules)
    if conflicted:
        code = next(iter(sorted(conflicted)))
        conflicting_rules = [r for r in mapping_rules if r.item_code == code]
        r1, r2 = conflicting_rules[0], conflicting_rules[1]
        diff_parts: list[str] = []
        if (r1.unit or "").strip() != (r2.unit or "").strip():
            diff_parts.append(f"단위('{r1.unit}' vs '{r2.unit}')")
        if (r1.specification or "").strip() != (r2.specification or "").strip():
            diff_parts.append(f"규격('{r1.specification}' vs '{r2.specification}')")
        diff_str = " 및 ".join(diff_parts) or "규격/단위"
        raise ValueError(
            f"동일한 item_code('{code}')에 대해 서로 다른 {diff_str}이 지정되었습니다. "
            f"P0에서는 1 item_code = 1 canonical definition 원칙을 준수해야 합니다 (ADR-005)."
        )


def build_takeoff_result(
    drawing: NormalizedDrawing,
    meta: dict[str, Any],
    mapping_rules: list[ItemMappingRule],
    reviews: dict[str, EvidenceReviewItem],
    manual_objects: list[ManualObjectItem],
    candidates: list[SymbolCandidate] | None = None,
    routes: list[ManualMeasuredRoute] | None = None,
) -> TakeoffResult:
    """Build PRD 7.1 and 7.2 summary and evidence rows with user overrides."""
    # Convert mapping rules to takeoff BlockMapping with full unit and specification (ADR-005)
    engine_mappings = [
        BlockMapping(
            block_name=m.block_name,
            layer=m.layer,
            item_code=m.item_code,
            unit=m.unit,
            specification=m.specification,
        )
        for m in mapping_rules
    ]

    is_image_dwg = (
        getattr(drawing, "source_type", None) == "IMAGE"
        or getattr(drawing, "coordinate_space", None) == "IMAGE_PIXEL"
    )
    is_pdf_dwg = (
        getattr(drawing, "source_type", None) == "PDF"
        or getattr(drawing, "coordinate_space", None) == "PDF_PAGE_POINT"
    )

    # Map item code to canonical metadata and detect cross-mapping attribute conflicts (ADR-005)
    item_meta, conflicted_codes = find_canonical_item_conflicts(mapping_rules)

    # ADR-005 / M-UNIT-01: Integrate manual objects into canonical metadata and detect unit consistency
    for mo in manual_objects:
        code = mo.item_code
        if not code or code in ("EXCLUDE", "UNMAPPED"):
            continue
        mo_u = (mo.unit or "").strip()
        if not mo_u:
            conflicted_codes.add(code)
            continue

        if code in item_meta:
            expected_u = (item_meta[code].unit or "").strip()
            if expected_u and expected_u != mo_u:
                conflicted_codes.add(code)
        else:
            # P0 policy (M-UNIT-01 / BLOCKER-1): Manual-only items MUST be 'EA'. Non-EA in storage is fail-closed.
            if mo_u != "EA":
                conflicted_codes.add(code)
            else:
                if code not in item_meta:
                    item_meta[code] = ItemMappingRule(
                        block_name="[MANUAL]",
                        item_code=code,
                        item_name=mo.item_name or code,
                        unit="EA",
                        specification="",
                    )

    # Run deterministic base aggregation
    agg = aggregate(drawing, engine_mappings)
    agg_by_id = {res.object_id: res for res in agg.objects}

    evidence_rows: list[TakeoffEvidenceRow] = []

    # 1. Process CAD Objects
    cad_objects = [obj for obj in drawing.objects if obj.entity_type == "INSERT"]
    parent_ids = {o.parent_id for o in cad_objects if o.parent_id is not None}
    cad_object_ids = {str(o.id) for o in cad_objects}

    # P0-QTY-01: Index candidates targeting CAD objects to prevent double counting
    candidate_by_cad_id: dict[str, SymbolCandidate] = {}
    if candidates:
        for cand in candidates:
            sid = cand.raw_evidence.get("source_object_id") if cand.raw_evidence else None
            if sid:
                sid_str = str(sid)
                ex_c = candidate_by_cad_id.get(sid_str)
                if not ex_c or (ex_c.status == CandidateStatus.PROPOSED and cand.status != CandidateStatus.PROPOSED):
                    candidate_by_cad_id[sid_str] = cand

    # Step 1: Compute tentative statuses including structural & domain blocking & reviews
    tentative_status: dict[str, dict[str, Any]] = {}
    for obj in cad_objects:
        res = agg_by_id.get(obj.id)
        base_item_code = res.item_code if res else None
        base_disp = res.disposition if res else Disposition.UNMAPPED

        # ADR-005: If base_item_code has conflicting canonical definitions across mappings,
        # fail-closed to UNRESOLVED regardless of block matching!
        is_canonical_conflict = bool(base_item_code and base_item_code in conflicted_codes)
        if is_canonical_conflict:
            base_disp = Disposition.UNRESOLVED

        # Determine base inclusion
        if base_disp == Disposition.INCLUDED:
            inc_status = InclusionStatus.INCLUDED
            rev_status = ReviewStatus.UNREVIEWED
            reason = "CAD_BLOCK"
        elif base_disp == Disposition.EXCLUDED:
            inc_status = InclusionStatus.EXCLUDED
            rev_status = ReviewStatus.UNREVIEWED
            reason = res.reason if res else "매핑에서 제외"
        elif base_disp == Disposition.UNRESOLVED:
            inc_status = InclusionStatus.EXCLUDED
            rev_status = ReviewStatus.UNRESOLVED
            if is_canonical_conflict:
                reason = f"품목 정의 충돌: 동일 item_code('{base_item_code}')에 상충하는 단위/규격 매핑 (ADR-005)"
            elif res and res.reason:
                reason = res.reason
            else:
                reason = "미확인 블록"
        else:
            inc_status = InclusionStatus.EXCLUDED
            rev_status = ReviewStatus.UNREVIEWED
            reason = "미매핑 블록"

        # Structural & Domain blocking check (AC-06 / DEC-014 / QA-09-C, QA-09-D / P0-QTY-02):
        # The following CAD entities MUST NEVER be forcefully included into verified CAD counts:
        # 1. Structural defects (XREF, missing block definitions, circular references)
        # 2. Dynamic blocks & anonymous blocks (DEC-014 / QA-09-C)
        # 3. Nested block hierarchies (both nested children and parent assemblies) (DEC-014 / QA-09-D)
        # 4. is_count_candidate=False
        is_xref_or_def_blocked = any(
            code in obj.warnings
            for code in (
                WarningCode.XREF_UNRESOLVED,
                WarningCode.MISSING_BLOCK_DEFINITION,
                WarningCode.CIRCULAR_BLOCK_REFERENCE,
            )
        )
        is_dynamic_or_anon_blocked = any(
            code in obj.warnings
            for code in (
                WarningCode.DYNAMIC_BLOCK,
                WarningCode.ANONYMOUS_BLOCK,
            )
        )
        is_nested_hierarchy_blocked = (
            obj.depth > 0
            or WarningCode.NESTED_BLOCK in obj.warnings
            or obj.parent_id is not None
            or obj.id in parent_ids
        )
        is_count_candidate_blocked = not getattr(obj, "is_count_candidate", True) and obj.depth == 0

        # Also check candidate-level structural diagnosis (P0-QTY-02)
        cand_for_obj = candidate_by_cad_id.get(str(obj.id))
        is_cand_blocked = bool(
            cand_for_obj
            and cand_for_obj.raw_evidence
            and cand_for_obj.raw_evidence.get("is_structurally_blocked")
        )

        is_structurally_blocked = (
            is_xref_or_def_blocked
            or is_dynamic_or_anon_blocked
            or is_nested_hierarchy_blocked
            or is_count_candidate_blocked
            or is_cand_blocked
        )

        # Apply User Review Override
        override = reviews.get(obj.id)
        if override:
            override_code = override.mapped_item_code or base_item_code
            is_override_conflict = bool(override_code and override_code in conflicted_codes)

            # MUNIT-D: Check unit conflict between base mapping unit and override mapping unit
            base_u = (item_meta[base_item_code].unit or "").strip() if (base_item_code and base_item_code in item_meta) else None
            override_u = (item_meta[override_code].unit or "").strip() if (override_code and override_code in item_meta) else None
            is_unit_conflict = bool(base_u and override_u and base_u != override_u)

            if (is_structurally_blocked or is_canonical_conflict or is_override_conflict or is_unit_conflict) and override.inclusion_status in (InclusionStatus.INCLUDED, InclusionStatus.MANUAL_ADDED):
                # Defend against false positive confirmation of structurally unverified or definition-conflicted entities
                inc_status = InclusionStatus.EXCLUDED
                rev_status = ReviewStatus.UNRESOLVED
                if is_unit_conflict:
                    reason = f"CAD 객체 단위('{base_u}')와 재분류 품목('{override_code}') 정규 단위('{override_u}') 상충 (MUNIT-D)"
                elif is_canonical_conflict or is_override_conflict:
                    reason = "품목 정의 충돌 객체는 CAD 자동 집계에 포함할 수 없습니다 (ADR-005)"
                elif is_dynamic_or_anon_blocked:
                    reason = (
                        "동적/익명 블록은 검수 근거 없이 CAD 자동 집계에 포함할 수 없습니다 (필요 시 수동 추가 사용)"
                    )
                elif is_nested_hierarchy_blocked:
                    reason = (
                        "중첩 블록 계층(상위/하위)은 P0 집계 기준 미확정으로 CAD 자동 집계에 포함할 수 없습니다 (필요 시 수동 추가 사용)"
                    )
                else:
                    reason = (
                        "구조적 결함(외부참조/정의 누락) 객체는 CAD 자동 집계에 포함할 수 없습니다 (필요 시 수동 추가 사용)"
                    )
            else:
                inc_status = override.inclusion_status
                rev_status = override.review_status
                if override.reason:
                    reason = override.reason
            if override.mapped_item_code:
                base_item_code = override.mapped_item_code
        elif cand_for_obj:
            # P0-QTY-01: Symbol candidate exists for this CAD object. Apply candidate decision in-place.
            cand_effective_code = cand_for_obj.reviewed_item_code or cand_for_obj.suggested_item_code
            if cand_for_obj.status == CandidateStatus.ACCEPTED:
                if cand_effective_code and cand_effective_code not in ("EXCLUDE", "UNMAPPED") and cand_effective_code not in conflicted_codes:
                    if is_structurally_blocked or is_canonical_conflict:
                        # P0-QTY-02: Blocked/unverified objects MUST NOT be revived by candidate approval
                        inc_status = InclusionStatus.EXCLUDED
                        rev_status = ReviewStatus.UNRESOLVED
                        block_diag = (
                            cand_for_obj.raw_evidence.get("structural_block_reason")
                            if cand_for_obj.raw_evidence
                            else None
                        ) or "구조적 결함/비집계 블록"
                        reason = f"구조상 집계 불가 객체는 후보 승인으로 포함 불가: {block_diag}"
                        base_item_code = cand_effective_code
                    else:
                        inc_status = InclusionStatus.INCLUDED
                        rev_status = ReviewStatus.REVIEWED
                        reason = cand_for_obj.review_note or f"기호 검수 승인 ({cand_for_obj.detection_source})"
                        base_item_code = cand_effective_code
                        if base_item_code not in item_meta:
                            item_meta[base_item_code] = ItemMappingRule(
                                block_name=f"[CANDIDATE:{cand_for_obj.detection_source}]",
                                item_code=base_item_code,
                                item_name=cand_for_obj.suggested_item_name or base_item_code,
                                unit="EA",
                                specification="",
                            )
            elif cand_for_obj.status == CandidateStatus.REJECTED:
                if base_disp == Disposition.UNMAPPED:
                    inc_status = InclusionStatus.EXCLUDED
                    rev_status = ReviewStatus.REVIEWED
                    reason = cand_for_obj.review_note or "기호 검수 거부"
            elif is_structurally_blocked:
                inc_status = InclusionStatus.EXCLUDED
                rev_status = ReviewStatus.UNRESOLVED
                if is_dynamic_or_anon_blocked:
                    reason = "동적/익명 블록: 가시성·구조 검수 필요"
                elif is_nested_hierarchy_blocked:
                    reason = (
                        "중첩 블록 계층(상위 어셈블리): 집계 기준 미확정(A05)"
                        if obj.id in parent_ids
                        else "중첩 블록: 집계 기준 미확정(A05)"
                    )
                else:
                    reason = "외부참조(XREF) 또는 블록 정의 누락으로 집계 불가"
        elif is_structurally_blocked:
            inc_status = InclusionStatus.EXCLUDED
            rev_status = ReviewStatus.UNRESOLVED
            if is_dynamic_or_anon_blocked:
                reason = "동적/익명 블록: 가시성·구조 검수 필요"
            elif is_nested_hierarchy_blocked:
                reason = (
                    "중첩 블록 계층(상위 어셈블리): 집계 기준 미확정(A05)"
                    if obj.id in parent_ids
                    else "중첩 블록: 집계 기준 미확정(A05)"
                )
            else:
                reason = "외부참조(XREF) 또는 블록 정의 누락으로 집계 불가"

        tentative_status[obj.id] = {
            "inc_status": inc_status,
            "rev_status": rev_status,
            "reason": reason,
            "item_code": base_item_code or "UNMAPPED",
        }

    for obj in cad_objects:
        st = tentative_status[obj.id]
        x = obj.insert_point[0] if obj.insert_point else 0.0
        y = obj.insert_point[1] if obj.insert_point else 0.0

        evidence_rows.append(
            TakeoffEvidenceRow(
                source_object_id=obj.id,
                drawing_id=drawing.drawing_id,
                parent_source_id=obj.parent_id,
                block_name=obj.block_name or "",
                layer_name=obj.layer,
                entity_type=obj.entity_type,
                x=x,
                y=y,
                mapped_item_code=st["item_code"],
                inclusion_status=st["inc_status"],
                review_status=st["rev_status"],
                review_reason=st["reason"],
                page_index=None,
                source_type="IMAGE" if is_image_dwg else "DXF",
                file_type=getattr(drawing, "file_type", "IMAGE" if is_image_dwg else "DXF"),
                coordinate_space="IMAGE_PIXEL" if is_image_dwg else "WORLD",
            )
        )

    # 2. Process Manual Objects
    for mo in manual_objects:
        base_item_code = mo.item_code
        mo_u = (mo.unit or "").strip()
        inc_status = InclusionStatus.MANUAL_ADDED
        rev_status = ReviewStatus.REVIEWED
        reason = mo.note or "수동 추가 기구"

        override = reviews.get(mo.id)
        effective_code = (override.mapped_item_code if override and override.mapped_item_code else base_item_code)

        # MUNIT-D / M-UNIT-01: Check unit consistency and P0 manual-only constraint
        is_conflicted = False
        conflict_reason = ""

        # IMG-02 & IMG-03: Strict coordinate boundary [0, W) x [0, H) and EA-only unit safety for IMAGE drawings
        if is_image_dwg:
            dims = getattr(drawing, "dimensions", None) or {}
            img_w = float(dims.get("width") or (drawing.extents.max[0] if drawing.extents else 0.0))
            img_h = float(dims.get("height") or (drawing.extents.max[1] if drawing.extents else 0.0))
            is_coord_finite = math.isfinite(mo.x) and math.isfinite(mo.y)
            if not is_coord_finite or mo.x < 0.0 or mo.x >= img_w or mo.y < 0.0 or mo.y >= img_h:
                is_conflicted = True
                conflict_reason = (
                    f"이미지 도면 픽셀 유효 범위([0, {int(img_w)}) × [0, {int(img_h)})) 이탈/비유한 좌표"
                    f"(x={mo.x}, y={mo.y}) - 수량 산출 보류 (IMG-02)"
                )
            elif mo_u != "EA":
                is_conflicted = True
                conflict_reason = f"이미지 도면 수동 기구 단위('{mo.unit}') 비EA 불허 (IMG-03/M-UNIT-01: EA 전용)"
            elif effective_code in item_meta and (item_meta[effective_code].unit or "").strip() != "EA":
                is_conflicted = True
                conflict_reason = f"이미지 도면 품목('{effective_code}') 매핑 단위('{item_meta[effective_code].unit}') 비EA 불허 (IMG-03)"
        elif is_pdf_dwg:
            page_idx = getattr(mo, "page_index", 0) or 0
            pages_list = getattr(drawing, "pages", None)
            if not pages_list:
                pages_list = meta.get("pages") or []
            page_cnt = int(getattr(drawing, "page_count", len(pages_list)) or len(pages_list) or 1)

            if page_idx < 0 or page_idx >= page_cnt:
                is_conflicted = True
                conflict_reason = (
                    f"PDF 도면 페이지 인덱스(page_index={page_idx}) 유효 범위([0, {page_cnt})) 이탈 (PR B)"
                )
            else:
                p_meta = pages_list[page_idx] if page_idx < len(pages_list) else None
                if p_meta:
                    page_w = float(p_meta.get("display_width_pt") or 0.0)
                    page_h = float(p_meta.get("display_height_pt") or 0.0)
                else:
                    dims = getattr(drawing, "dimensions", None) or {}
                    page_w = float(dims.get("width") or (drawing.extents.max[0] if drawing.extents else 595.0))
                    page_h = float(dims.get("height") or (drawing.extents.max[1] if drawing.extents else 842.0))

                is_coord_finite = math.isfinite(mo.x) and math.isfinite(mo.y)
                if not is_coord_finite or mo.x < 0.0 or mo.x >= page_w or mo.y < 0.0 or mo.y >= page_h:
                    is_conflicted = True
                    conflict_reason = (
                        f"PDF 도면 페이지({page_idx}) pt 유효 범위([0, {page_w:.1f}) × [0, {page_h:.1f})) 이탈/비유한 좌표"
                        f"(x={mo.x}, y={mo.y}) - 수량 산출 보류 (PR B)"
                    )
                elif mo_u != "EA":
                    is_conflicted = True
                    conflict_reason = f"PDF 도면 수동 기구 단위('{mo.unit}') 비EA 불허 (M-UNIT-01: EA 전용)"
                elif effective_code in item_meta and (item_meta[effective_code].unit or "").strip() != "EA":
                    is_conflicted = True
                    conflict_reason = f"PDF 도면 품목('{effective_code}') 매핑 단위('{item_meta[effective_code].unit}') 비EA 불허"
        elif base_item_code in conflicted_codes:
            is_conflicted = True
            conflict_reason = f"수동 추가 기구 단위('{mo.unit}') 상충/결함 (P0 비EA 또는 단위 불일치)"
        elif effective_code in conflicted_codes:
            is_conflicted = True
            conflict_reason = f"재분류 대상 품목('{effective_code}') 정의 충돌 (ADR-005)"
        elif effective_code in item_meta:
            target_unit = (item_meta[effective_code].unit or "EA").strip()
            if mo_u != target_unit:
                is_conflicted = True
                conflict_reason = (
                    f"수동 객체 단위('{mo.unit}')와 재분류 품목('{effective_code}') 정규 단위('{target_unit}') 상충 (MUNIT-D)"
                )
        else:
            # Reclassified to an unmapped manual-only item: in P0, must be EA
            if mo_u != "EA":
                is_conflicted = True
                conflict_reason = f"수동 전용 품목 재분류 단위('{mo.unit}') 비EA 불허 (P0 M-UNIT-01)"

        if is_conflicted:
            inc_status = InclusionStatus.EXCLUDED
            rev_status = ReviewStatus.UNRESOLVED
            reason = conflict_reason
        elif override:
            inc_status = override.inclusion_status
            rev_status = override.review_status
            if override.reason:
                reason = override.reason

        evidence_rows.append(
            TakeoffEvidenceRow(
                source_object_id=mo.id,
                drawing_id=drawing.drawing_id,
                parent_source_id=None,
                block_name="[MANUAL]",
                layer_name="MANUAL",
                entity_type="MANUAL_POINT",
                x=mo.x,
                y=mo.y,
                mapped_item_code=effective_code,
                inclusion_status=inc_status,
                review_status=rev_status,
                review_reason=reason,
                page_index=getattr(mo, "page_index", 0) if is_pdf_dwg else None,
                source_type="PDF" if is_pdf_dwg else ("IMAGE" if is_image_dwg else "DXF"),
                file_type=getattr(drawing, "file_type", "PDF" if is_pdf_dwg else ("IMAGE" if is_image_dwg else "DXF")),
                coordinate_space="PDF_PAGE_POINT" if is_pdf_dwg else ("IMAGE_PIXEL" if is_image_dwg else "WORLD"),
            )
        )

    # 3. Process Accepted Symbol Candidates (Issue #23 & Issue #29)
    if candidates:
        accepted_evidence_candidates: list[SymbolCandidate] = []
        for cand in candidates:
            # Domain Invariant: PROPOSED and REJECTED candidates MUST NEVER contribute to takeoff
            if cand.status != CandidateStatus.ACCEPTED:
                continue

            # P0-QTY-01: If this candidate is linked to a CAD object, its status and 1 EA was already
            # processed into the CAD object row in #1. NEVER create a duplicate row!
            cand_obj_id = cand.raw_evidence.get("source_object_id") if cand.raw_evidence else None
            if cand_obj_id and (str(cand_obj_id) in cad_object_ids or cand.candidate_id in cad_object_ids):
                continue

            # P0-01: Structurally blocked candidate must fail-closed to 0 EA even if accepted
            if cand.raw_evidence and cand.raw_evidence.get("is_structurally_blocked"):
                continue

            # On DXF drawings, if this candidate spatially matches any CAD object without source_object_id,
            # it belongs to CAD object processing (P0-REVIEW-02)
            if not is_pdf_dwg and not is_image_dwg and cand_obj_id is None:
                is_cad_match = False
                for o in cad_objects:
                    pt = getattr(o, "insert_point", None)
                    if pt:
                        ox, oy = float(pt[0]), float(pt[1])
                        b = cand.bbox
                        if b and len(b) == 4 and abs(b[2] - b[0]) > 0 and abs(b[3] - b[1]) > 0:
                            min_x, max_x = min(b[0], b[2]), max(b[0], b[2])
                            min_y, max_y = min(b[1], b[3]), max(b[1], b[3])
                            if min_x <= ox <= max_x and min_y <= oy <= max_y:
                                bw = max_x - min_x
                                bh = max_y - min_y
                                if math.hypot(cand.x - ox, cand.y - oy) <= max(2.0, min(bw, bh) * 0.35):
                                    is_cad_match = True
                                    break
                        elif math.hypot(cand.x - ox, cand.y - oy) <= 2.0:
                            is_cad_match = True
                            break
                if is_cad_match:
                    continue

            # P0-02 Level 2 Defense: 하나의 물리 설치 위치는 최대 1 EA
            # Check if another accepted candidate on the same page already claimed this physical spot
            if any(are_candidates_spatially_coincident(claimed, cand) for claimed in accepted_evidence_candidates):
                continue
            accepted_evidence_candidates.append(cand)

            effective_code = cand.reviewed_item_code or cand.suggested_item_code
            if not effective_code or effective_code in ("EXCLUDE", "UNMAPPED") or effective_code in conflicted_codes:
                continue

            # Ensure canonical item metadata has this code
            if effective_code not in item_meta:
                item_meta[effective_code] = ItemMappingRule(
                    block_name=f"[CANDIDATE:{cand.detection_source}]",
                    item_code=effective_code,
                    item_name=cand.suggested_item_name or effective_code,
                    unit="EA",
                    specification="",
                )

            evidence_rows.append(
                TakeoffEvidenceRow(
                    source_object_id=cand.candidate_id,
                    drawing_id=drawing.drawing_id,
                    parent_source_id=None,
                    block_name=f"[CANDIDATE:{cand.detection_source}]",
                    layer_name="CANDIDATE",
                    entity_type="SYMBOL_CANDIDATE",
                    x=cand.x,
                    y=cand.y,
                    mapped_item_code=effective_code,
                    inclusion_status=InclusionStatus.INCLUDED,
                    review_status=ReviewStatus.REVIEWED,
                    review_reason=cand.review_note or f"검수 승인 ({cand.detection_source}, 신뢰도 {int(cand.confidence * 100)}%)",
                    page_index=cand.page_index if is_pdf_dwg else None,
                    source_type=getattr(drawing, "source_type", None) or ("PDF" if is_pdf_dwg else ("IMAGE" if is_image_dwg else "DXF")),
                    file_type=getattr(drawing, "file_type", None) or ("PDF" if is_pdf_dwg else ("IMAGE" if is_image_dwg else "DXF")),
                    coordinate_space=cand.coordinate_space,
                )
            )

    # 4. Calculate Summary Rows
    # Group included items by mapped_item_code
    counts: dict[str, int] = {}
    methods: dict[str, set[str]] = {}
    review_states: dict[str, set[ReviewStatus]] = {}

    for ev in evidence_rows:
        code = ev.mapped_item_code
        if not code or code in ("UNMAPPED", "EXCLUDE") or code in conflicted_codes:
            continue

        if ev.inclusion_status in (InclusionStatus.INCLUDED, InclusionStatus.MANUAL_ADDED):
            counts[code] = counts.get(code, 0) + 1
            is_manual_source = (
                ev.inclusion_status == InclusionStatus.MANUAL_ADDED
                or ev.entity_type in ("MANUAL_POINT", "SYMBOL_CANDIDATE")
                or ev.block_name.startswith("[CANDIDATE:")
                or ev.block_name == "[MANUAL]"
            )
            methods.setdefault(code, set()).add("MANUAL" if is_manual_source else "CAD_BLOCK")
            review_states.setdefault(code, set()).add(ev.review_status)
        elif ev.review_status == ReviewStatus.UNRESOLVED:
            # AC-06 / FR-011: Excluded UNRESOLVED evidence (such as structural XREFs, missing blocks, unit conflict)
            # must also be reflected in the overall item review status so unverified quantities aren't concealed.
            review_states.setdefault(code, set()).add(ReviewStatus.UNRESOLVED)

    summary_rows: list[TakeoffSummaryRow] = []
    drawing_name = meta.get("filename", drawing.source.filename)
    revision = meta.get("revision", "REV0")

    # Include all mapped item codes, manual item codes, and review overrides even if quantity is 0
    all_codes = sorted(
        set(
            list(counts.keys())
            + [m.item_code for m in mapping_rules if m.item_code != "EXCLUDE"]
            + [mo.item_code for mo in manual_objects if mo.item_code not in ("EXCLUDE", "UNMAPPED")]
            + [ev.mapped_item_code for ev in evidence_rows if ev.mapped_item_code not in ("EXCLUDE", "UNMAPPED")]
            + list(conflicted_codes)
        )
    )

    for code in all_codes:
        if code in conflicted_codes:
            qty = 0
            is_man_only = any(mo.item_code == code for mo in manual_objects) and not any(m.item_code == code for m in mapping_rules)
            q_method = QuantityMethod.MANUAL if is_man_only else QuantityMethod.CAD_BLOCK
            r_status = ReviewStatus.UNRESOLVED
            notes = "품목 정의 충돌: 서로 다른 규격/단위 상충 또는 P0 비EA 수동 품목 (ADR-005) - 집계 불가"
            m_info = item_meta.get(code)
            name = m_info.item_name if m_info and m_info.item_name else code
            spec = "[상충 규격 충돌]"
            unit = "[상충 단위 충돌]"
        else:
            qty = counts.get(code, 0)
            m_set = methods.get(code, set())
            if "MANUAL" in m_set and "CAD_BLOCK" in m_set:
                q_method = QuantityMethod.MIXED
            elif "MANUAL" in m_set:
                q_method = QuantityMethod.MANUAL
            else:
                q_method = QuantityMethod.CAD_BLOCK

            r_set = review_states.get(code, set())
            notes = ""
            if ReviewStatus.UNRESOLVED in r_set:
                r_status = ReviewStatus.UNRESOLVED
                notes = "미해결 객체(단위 상충 재분류/XREF 등) 포함 - 현장 확인 필요"
            elif ReviewStatus.UNREVIEWED in r_set or not r_set:
                r_status = ReviewStatus.UNREVIEWED
            else:
                r_status = ReviewStatus.REVIEWED

            m_info = item_meta.get(code)
            name = m_info.item_name if m_info and m_info.item_name else code
            spec = m_info.specification if m_info and m_info.specification else ""
            unit = m_info.unit if m_info and m_info.unit else "EA"

            if is_image_dwg and unit.strip() != "EA":
                qty = 0
                r_status = ReviewStatus.UNRESOLVED
                notes = f"이미지 도면 단위('{unit}') 비EA 불허 (IMG-03/M-UNIT-01: EA 전용) - 수량 산출 보류"
            elif is_pdf_dwg and unit.strip() != "EA":
                qty = 0
                r_status = ReviewStatus.UNRESOLVED
                notes = f"PDF 도면 단위('{unit}') 비EA 불허 (PR B/M-UNIT-01: EA 전용) - 수량 산출 보류"
            elif is_pdf_dwg and not notes:
                notes = "PDF 수동 적산 잠정 수량 (PR B)"

        summary_rows.append(
            TakeoffSummaryRow(
                item_code=code,
                item_name=name,
                specification=spec,
                unit=unit,
                quantity=qty,
                quantity_method=q_method,
                review_status=r_status,
                drawing_name=drawing_name,
                drawing_revision=revision,
                notes=notes,
                is_provisional=is_pdf_dwg,
            )
        )

    # 5. Process Manual Measured Routes (Issue #37 Workstream C)
    if routes:
        for r in routes:
            evidence_rows.append(
                TakeoffEvidenceRow(
                    source_object_id=r.id,
                    drawing_id=drawing.drawing_id,
                    parent_source_id=None,
                    block_name=f"[ROUTE:{r.category}]",
                    layer_name="ROUTE",
                    entity_type="POLYLINE_ROUTE",
                    x=r.points[0].x,
                    y=r.points[0].y,
                    mapped_item_code=r.item_code,
                    inclusion_status=InclusionStatus.INCLUDED if (r.status == RouteStatus.PROVISIONAL_CONFIRMED and r.is_calibrated and r.length_2d_m is not None) else InclusionStatus.EXCLUDED,
                    review_status=ReviewStatus.REVIEWED if (r.status == RouteStatus.PROVISIONAL_CONFIRMED and r.is_calibrated) else ReviewStatus.UNRESOLVED,
                    review_reason=r.review_note or (f"2D 계획 경로 (길이 {r.length_2d_m or 0.0}m, 원시 {r.raw_length:.1f})" if r.is_calibrated else "미보정 경로 (0m)"),
                    page_index=r.page_index if is_pdf_dwg else None,
                    source_type=getattr(drawing, "source_type", None) or ("PDF" if is_pdf_dwg else ("IMAGE" if is_image_dwg else "DXF")),
                    file_type=getattr(drawing, "file_type", None) or ("PDF" if is_pdf_dwg else ("IMAGE" if is_image_dwg else "DXF")),
                    coordinate_space=r.coordinate_space,
                )
            )

        route_groups: dict[tuple[str, str], list[ManualMeasuredRoute]] = {}
        for r in routes:
            if r.status == RouteStatus.PROVISIONAL_CONFIRMED:
                route_groups.setdefault((r.item_code, r.spec), []).append(r)

        for (r_code, r_spec), r_list in sorted(route_groups.items()):
            calibrated = [r for r in r_list if r.is_calibrated and r.length_2d_m is not None]
            uncalibrated = [r for r in r_list if not (r.is_calibrated and r.length_2d_m is not None)]
            r_first = r_list[0]
            if calibrated:
                tot_len = round(sum(r.length_2d_m for r in calibrated if r.length_2d_m is not None), 2)
                notes_str = f"수동 2D 계획 경로 {len(calibrated)}구간 측정치 잠정 합산 (m)"
                if uncalibrated:
                    notes_str += f" [미보정 {len(uncalibrated)}구간 0m 제외]"
                summary_rows.append(
                    TakeoffSummaryRow(
                        item_code=r_code,
                        item_name=r_first.item_name,
                        specification=r_spec,
                        unit="m",
                        quantity=tot_len,
                        quantity_method=QuantityMethod.MANUAL,
                        review_status=ReviewStatus.REVIEWED,
                        drawing_name=drawing_name,
                        drawing_revision=revision,
                        notes=notes_str,
                        is_provisional=True,
                    )
                )
            elif uncalibrated:
                summary_rows.append(
                    TakeoffSummaryRow(
                        item_code=r_code,
                        item_name=r_first.item_name,
                        specification=r_spec,
                        unit="m",
                        quantity=0.0,
                        quantity_method=QuantityMethod.MANUAL,
                        review_status=ReviewStatus.UNRESOLVED,
                        drawing_name=drawing_name,
                        drawing_revision=revision,
                        notes=f"미보정 경로 {len(uncalibrated)}구간 (실측 거리 미보정으로 수량 0m 처리)",
                        is_provisional=True,
                    )
                )

    summary_rows.sort(key=lambda s: (s.unit, s.item_code))

    unresolved_count = sum(
        1
        for e in evidence_rows
        if e.review_status == ReviewStatus.UNRESOLVED or e.mapped_item_code == "UNMAPPED"
    )
    # In P0 (DEC-011 / Issue #9), drawings lack formal legend/count_scope verification.
    # Therefore, takeoffs remain provisional (is_provisional = True) by default
    # unless explicit certified count scope metadata is present.
    # For PDF drawings in PR B, all quantities are strictly provisional ("잠정 수량").
    is_count_scope_verified = bool(meta.get("count_scope_verified", False))
    is_provisional = (
        is_pdf_dwg
        or not is_count_scope_verified
        or (unresolved_count > 0)
        or any(s.review_status != ReviewStatus.REVIEWED for s in summary_rows)
    )

    return TakeoffResult(
        drawing_id=drawing.drawing_id,
        drawing_name=drawing_name,
        drawing_revision=revision,
        summary=summary_rows,
        evidence=evidence_rows,
        warnings_count=len(drawing.warnings),
        exported_at=datetime.now(UTC),
        is_provisional=is_provisional,
        unresolved_count=unresolved_count,
    )
