"""Local file-based persistence for projects, drawings, mappings, and takeoff reviews."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from cad_engine.schema import NormalizedDrawing, WarningCode
from cad_engine.takeoff import BlockMapping, Disposition, aggregate

from .models import (
    DrawingSummary,
    EvidenceReviewItem,
    InclusionStatus,
    ItemMappingRule,
    ManualObjectItem,
    ProjectCreate,
    ProjectMetadata,
    QuantityMethod,
    ReviewStatus,
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
    ) -> Path:
        d_dir = self.projects_dir / project_id / "drawings" / drawing.drawing_id
        d_dir.mkdir(parents=True, exist_ok=True)

        # 1. save normalized drawing
        drawing_file = d_dir / "drawing.json"
        self._save_json(drawing_file, drawing.model_dump(mode="json"))

        # 2. save raw DXF bytes if provided (FR-002, QA-DEF-01)
        raw_saved = False
        if raw_bytes is not None:
            raw_file = d_dir / "raw.dxf"
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
            "raw_filename": "raw.dxf" if raw_saved else None,
            "revision": revision,
            "units_name": drawing.dxf.units_name,
            "insunits": drawing.dxf.insunits,
            "created_at": datetime.now(UTC).isoformat(),
            "objects_count": len(drawing.objects),
            "warnings_count": len(drawing.warnings),
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
        raw_file = self.projects_dir / project_id / "drawings" / drawing_id / "raw.dxf"
        if raw_file.exists():
            return raw_file
        return None

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
        return NormalizedDrawing(**data)

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
        return [ManualObjectItem(**item) for item in data]

    def save_manual_objects(
        self, project_id: str, drawing_id: str, objects: list[ManualObjectItem]
    ) -> None:
        f = self.projects_dir / project_id / "drawings" / drawing_id / "manual_objects.json"
        self._save_json(f, [item.model_dump(mode="json") for item in objects])

    # ------------------------------------------------------------- Calculations
    def calculate_takeoff(self, project_id: str, drawing_id: str) -> TakeoffResult | None:
        drawing = self.get_drawing(project_id, drawing_id)
        if drawing is None:
            return None
        meta = self.get_drawing_meta(project_id, drawing_id) or {}
        mappings = self.get_mappings(project_id, drawing_id)
        reviews = self.get_reviews(project_id, drawing_id)
        manual_objects = self.get_manual_objects(project_id, drawing_id)

        return build_takeoff_result(
            drawing=drawing,
            meta=meta,
            mapping_rules=mappings,
            reviews=reviews,
            manual_objects=manual_objects,
        )

    def _save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_takeoff_result(
    drawing: NormalizedDrawing,
    meta: dict[str, Any],
    mapping_rules: list[ItemMappingRule],
    reviews: dict[str, EvidenceReviewItem],
    manual_objects: list[ManualObjectItem],
) -> TakeoffResult:
    """Build PRD 7.1 and 7.2 summary and evidence rows with user overrides."""
    # Convert mapping rules to takeoff BlockMapping
    engine_mappings = [
        BlockMapping(
            block_name=m.block_name,
            layer=m.layer,
            item_code=m.item_code,
        )
        for m in mapping_rules
    ]

    # Map item code to metadata
    item_meta: dict[str, ItemMappingRule] = {m.item_code: m for m in mapping_rules}

    # Run deterministic base aggregation
    agg = aggregate(drawing, engine_mappings)
    agg_by_id = {res.object_id: res for res in agg.objects}

    evidence_rows: list[TakeoffEvidenceRow] = []

    # 1. Process CAD Objects
    for obj in drawing.objects:
        if obj.entity_type != "INSERT":
            continue

        res = agg_by_id.get(obj.id)
        base_item_code = res.item_code if res else None
        base_disp = res.disposition if res else Disposition.UNMAPPED

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
            reason = res.reason if res else "미확인 블록"
        else:
            inc_status = InclusionStatus.EXCLUDED
            rev_status = ReviewStatus.UNREVIEWED
            reason = "미매핑 블록"

        # Structural blocking check (AC-06): XREF, missing block definitions, or circular references
        # MUST NEVER be forcefully included into verified CAD counts.
        is_structurally_blocked = any(
            code in obj.warnings
            for code in (
                WarningCode.XREF_UNRESOLVED,
                WarningCode.MISSING_BLOCK_DEFINITION,
                WarningCode.CIRCULAR_BLOCK_REFERENCE,
            )
        )

        # Apply User Review Override
        override = reviews.get(obj.id)
        if override:
            if is_structurally_blocked and override.inclusion_status == InclusionStatus.INCLUDED:
                # Defend against false positive confirmation of structurally unverified CAD entities
                inc_status = InclusionStatus.EXCLUDED
                rev_status = ReviewStatus.UNRESOLVED
                reason = "구조적 결함(외부참조/정의 누락) 객체는 CAD 자동 집계에 포함할 수 없습니다 (필요 시 수동 추가 사용)"
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
            reason = "외부참조(XREF) 또는 블록 정의 누락으로 집계 불가"

        # Coordinates
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
                mapped_item_code=base_item_code or "UNMAPPED",
                inclusion_status=inc_status,
                review_status=rev_status,
                review_reason=reason,
            )
        )

    # 2. Process Manual Objects
    for mo in manual_objects:
        mapped_item_code = mo.item_code
        inc_status = InclusionStatus.MANUAL_ADDED
        rev_status = ReviewStatus.REVIEWED
        reason = mo.note or "수동 추가 기구"

        override = reviews.get(mo.id)
        if override:
            inc_status = override.inclusion_status
            rev_status = override.review_status
            if override.mapped_item_code:
                mapped_item_code = override.mapped_item_code
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
                mapped_item_code=mapped_item_code,
                inclusion_status=inc_status,
                review_status=rev_status,
                review_reason=reason,
            )
        )

    # 3. Calculate Summary Rows
    # Group included items by mapped_item_code
    counts: dict[str, int] = {}
    methods: dict[str, set[str]] = {}
    review_states: dict[str, set[ReviewStatus]] = {}

    for ev in evidence_rows:
        code = ev.mapped_item_code
        if not code or code in ("UNMAPPED", "EXCLUDE"):
            continue

        if ev.inclusion_status in (InclusionStatus.INCLUDED, InclusionStatus.MANUAL_ADDED):
            counts[code] = counts.get(code, 0) + 1
            methods.setdefault(code, set()).add(
                "MANUAL" if ev.inclusion_status == InclusionStatus.MANUAL_ADDED else "CAD_BLOCK"
            )
            review_states.setdefault(code, set()).add(ev.review_status)
        elif ev.review_status == ReviewStatus.UNRESOLVED:
            # AC-06 / FR-011: Excluded UNRESOLVED evidence (such as structural XREFs, missing blocks)
            # must also be reflected in the overall item review status so unverified quantities aren't concealed.
            review_states.setdefault(code, set()).add(ReviewStatus.UNRESOLVED)

    summary_rows: list[TakeoffSummaryRow] = []
    drawing_name = meta.get("filename", drawing.source.filename)
    revision = meta.get("revision", "REV0")

    # Include all mapped item codes even if quantity is 0
    all_codes = sorted(set(list(counts.keys()) + [m.item_code for m in mapping_rules if m.item_code != "EXCLUDE"]))

    for code in all_codes:
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
            notes = "미해결 객체(XREF/정의누락 등) 포함 - 현장 확인 필요"
        elif ReviewStatus.UNREVIEWED in r_set or not r_set:
            r_status = ReviewStatus.UNREVIEWED
        else:
            r_status = ReviewStatus.REVIEWED

        m_info = item_meta.get(code)
        name = m_info.item_name if m_info and m_info.item_name else code
        spec = m_info.specification if m_info and m_info.specification else ""
        unit = m_info.unit if m_info and m_info.unit else "EA"

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
            )
        )

    summary_rows.sort(key=lambda s: s.item_code)

    unresolved_count = sum(
        1
        for e in evidence_rows
        if e.review_status == ReviewStatus.UNRESOLVED or e.mapped_item_code == "UNMAPPED"
    )
    is_provisional = (unresolved_count > 0) or any(
        s.review_status != ReviewStatus.REVIEWED for s in summary_rows
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
