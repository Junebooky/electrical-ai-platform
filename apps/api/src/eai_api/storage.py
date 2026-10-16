"""Local file-based persistence for projects, drawings, mappings, and takeoff reviews."""

from __future__ import annotations

import json
import math
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from cad_engine.schema import NormalizedDrawing, WarningCode
from cad_engine.takeoff import BlockMapping, Disposition, aggregate

from .models import (
    CandidateStatus,
    DrawingSummary,
    EvidenceReviewItem,
    InclusionStatus,
    ItemMappingRule,
    ManualObjectItem,
    ProjectCreate,
    ProjectMetadata,
    QuantityMethod,
    ReviewStatus,
    SymbolCandidate,
    TakeoffEvidenceRow,
    TakeoffResult,
    TakeoffSummaryRow,
)

DEFAULT_DATA_DIR = Path(os.environ.get("EAI_DATA_DIR", "./.eai_data")).resolve()


class Storage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DEFAULT_DATA_DIR
        self.projects_dir = self.root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- Projects
    def create_project(self, payload: ProjectCreate) -> ProjectMetadata:
        project_id = f"proj_{uuid.uuid4().hex[:8]}"
        proj_dir = self.projects_dir / project_id
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "drawings").mkdir(exist_ok=True)

        now = datetime.now(UTC)
        meta = ProjectMetadata(
            id=project_id,
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

        return build_takeoff_result(
            drawing=drawing,
            meta=meta,
            mapping_rules=mappings,
            reviews=reviews,
            manual_objects=manual_objects,
            candidates=candidates,
        )

    def _save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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

        # Structural & Domain blocking check (AC-06 / DEC-014 / QA-09-C, QA-09-D):
        # The following CAD entities MUST NEVER be forcefully included into verified CAD counts:
        # 1. Structural defects (XREF, missing block definitions, circular references)
        # 2. Dynamic blocks & anonymous blocks (DEC-014 / QA-09-C)
        # 3. Nested block hierarchies (both nested children and parent assemblies) (DEC-014 / QA-09-D)
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

        is_structurally_blocked = (
            is_xref_or_def_blocked
            or is_dynamic_or_anon_blocked
            or is_nested_hierarchy_blocked
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

    # 3. Process Accepted Symbol Candidates (Issue #23)
    if candidates:
        for cand in candidates:
            # Domain Invariant: PROPOSED and REJECTED candidates MUST NEVER contribute to takeoff
            if cand.status != CandidateStatus.ACCEPTED:
                continue

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

    summary_rows.sort(key=lambda s: s.item_code)

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
