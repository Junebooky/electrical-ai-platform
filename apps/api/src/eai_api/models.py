"""API models and Takeoff Review schemas for the Electrical AI Platform."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CandidateStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DetectionSource(StrEnum):
    DXF_BLOCK = "DXF_BLOCK"
    PDF_VECTOR_RULE = "PDF_VECTOR_RULE"
    IMAGE_TEMPLATE = "IMAGE_TEMPLATE"
    VISUAL_TEMPLATE = "VISUAL_TEMPLATE"


class InclusionStatus(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    MANUAL_ADDED = "MANUAL_ADDED"


class ReviewStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    UNRESOLVED = "UNRESOLVED"


class QuantityMethod(StrEnum):
    CAD_BLOCK = "CAD_BLOCK"
    MANUAL = "MANUAL"
    MIXED = "MIXED"


class ItemMappingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_name: str
    layer: str | None = None
    item_code: str  # e.g. "LIGHT", "OUTLET", "SWITCH", or "EXCLUDE"
    item_name: str | None = None
    specification: str | None = None
    unit: str = "EA"


class EvidenceReviewItem(BaseModel):
    """User review decision overriding the automatic aggregation."""
    model_config = ConfigDict(extra="forbid")
    source_object_id: str
    inclusion_status: InclusionStatus
    mapped_item_code: str | None = None
    review_status: ReviewStatus = ReviewStatus.REVIEWED
    reason: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ManualObjectItem(BaseModel):
    """Manually added takeoff object (PRD AC-05)."""
    model_config = ConfigDict(extra="forbid")
    id: str
    drawing_id: str
    x: float
    y: float
    item_code: str
    item_name: str | None = None
    unit: str = "EA"
    note: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    page_index: int = 0

    @field_validator("x", "y")
    @classmethod
    def validate_finite_coords(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("좌표값은 유한한 실수(finite float)여야 하며 NaN이나 무한대(Inf)일 수 없습니다.")
        return v

    @field_validator("page_index")
    @classmethod
    def validate_page_index(cls, v: int) -> int:
        if v < 0:
            raise ValueError("page_index는 0 이상의 정수(0-based)여야 합니다.")
        return v



class TakeoffSummaryRow(BaseModel):
    item_code: str
    item_name: str
    specification: str
    unit: str
    quantity: int
    quantity_method: QuantityMethod
    review_status: ReviewStatus
    drawing_name: str
    drawing_revision: str
    notes: str
    is_provisional: bool = False


class TakeoffEvidenceRow(BaseModel):
    source_object_id: str
    drawing_id: str
    parent_source_id: str | None
    block_name: str
    layer_name: str
    entity_type: str
    x: float
    y: float
    mapped_item_code: str
    inclusion_status: InclusionStatus
    review_status: ReviewStatus
    review_reason: str
    page_index: int | None = None
    source_type: str | None = None
    file_type: str | None = None
    coordinate_space: str | None = None


class TakeoffResult(BaseModel):
    drawing_id: str
    drawing_name: str
    drawing_revision: str
    summary: list[TakeoffSummaryRow]
    evidence: list[TakeoffEvidenceRow]
    warnings_count: int
    exported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_provisional: bool = False
    unresolved_count: int = 0


class ProjectCreate(BaseModel):
    name: str = "새 프로젝트"
    description: str = ""


class ProjectMetadata(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    drawing_count: int = 0


class DrawingSummary(BaseModel):
    id: str
    project_id: str
    filename: str
    file_hash: str
    revision: str
    units_name: str
    insunits: int
    created_at: datetime
    objects_count: int
    warnings_count: int
    source_type: str = "DXF"
    file_type: str = "DXF"
    coordinate_space: str = "WORLD"
    dimensions: dict[str, int] | None = None
    page_count: int = 1
    pages: list[dict[str, object]] | None = None


class SymbolCandidate(BaseModel):
    """Detected symbol candidate for electrical equipment (Issue #23)."""
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    drawing_id: str
    page_index: int = 0
    coordinate_space: str  # "WORLD", "IMAGE_PIXEL", "PDF_PAGE_POINT"
    x: float
    y: float
    bbox: list[float]  # [x0, y0, x1, y1]
    suggested_item_code: str
    suggested_item_name: str
    confidence: float  # 0.0 ~ 1.0
    detection_source: str
    status: CandidateStatus = CandidateStatus.PROPOSED
    reviewed_item_code: str | None = None
    reviewed_at: datetime | None = None
    review_note: str = ""
    raw_evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("x", "y")
    @classmethod
    def validate_finite_coords(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("좌표값은 유한한 실수(finite float)여야 합니다.")
        return v


class CandidateReviewUpdate(BaseModel):
    """Individual candidate review update (Issue #23)."""
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    status: CandidateStatus
    reviewed_item_code: str | None = None
    review_note: str = ""


class CandidateBulkReviewRequest(BaseModel):
    """Bulk or batch review update request (Issue #23)."""
    model_config = ConfigDict(extra="forbid")
    action: str | None = None  # "ACCEPT_ALL", "REJECT_ALL", "RESET_ALL"
    filter_item_code: str | None = None
    updates: list[CandidateReviewUpdate] | None = None


class CandidatesSummary(BaseModel):
    total: int
    proposed: int
    accepted: int
    rejected: int


class CandidatesResponse(BaseModel):
    drawing_id: str
    summary: CandidatesSummary
    candidates: list[SymbolCandidate]


# ---------------------------------------------------------------------------
# Mapping Templates (Issue #23)
# ---------------------------------------------------------------------------
class MappingTemplate(BaseModel):
    """Reusable legend / item mapping template (Issue #23)."""
    id: str
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime
    rules: list[ItemMappingRule]
    is_builtin: bool = False


class MappingTemplateCreate(BaseModel):
    """Payload to save a new mapping template."""
    name: str
    description: str = ""
    rules: list[ItemMappingRule]


class ApplyTemplateRequest(BaseModel):
    """Payload to apply a mapping template to a drawing."""
    template_id: str
    merge_strategy: str = "MERGE"  # "MERGE" (default, keeps existing if not overlapping) or "REPLACE"


class MappingTemplateListResponse(BaseModel):
    templates: list[MappingTemplate]
    total: int = 0


class DemoDrawingItem(BaseModel):
    drawing_id: str
    filename: str
    source_type: str
    objects_count: int = 0
    candidates_count: int = 0
    status: str = "ready"
    id: str | None = None
    format: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = self.drawing_id
        if not self.format:
            self.format = self.source_type


class DemoSeedResponse(BaseModel):
    status: str
    project_id: str
    project_name: str
    drawings: list[DemoDrawingItem]
    applied_template: str = ""
    note: str = ""


class SymbolSearchRequest(BaseModel):
    """Request payload for visual symbol template matching (Issue #29 Workstream B)."""
    sample_bbox: list[float]  # [x1, y1, x2, y2]
    page_index: int = 0
    suggested_item_code: str = "LIGHT"
    suggested_item_name: str = "조명기구"
    threshold: float = 0.70
    search_all_pages: bool = False
    max_results: int = 150


class SymbolSearchResponse(BaseModel):
    """Response returned when searching for visual symbols across drawing."""
    drawing_id: str
    page_index: int
    total_found: int
    candidates: list[SymbolCandidate]
    message: str = ""


# ---------------------------------------------------------------------------
# Scope & Revision Management (Issue #35 Workstream A)
# ---------------------------------------------------------------------------
class SheetRole(StrEnum):
    INSTALLATION = "INSTALLATION"  # 시공/배치도 (기본 산출 대상)
    REFERENCE = "REFERENCE"        # 참고도/간선계통도 (산출 제외)
    DETAIL = "DETAIL"              # 상세도 (산출 제외)
    LEGEND = "LEGEND"              # 범례표 (산출 제외)
    UNKNOWN = "UNKNOWN"            # 미지정


class DrawingScope(BaseModel):
    """Scope, Floor, Discipline, and Revision metadata for a drawing."""
    model_config = ConfigDict(extra="forbid")
    drawing_id: str
    project_id: str
    sheet_key: str  # Logical drawing group key, e.g. "1F_LIGHT"
    floor: str = "1F"  # "1F", "2F", "B1", "ROOF", "ALL"
    zone: str | None = None
    discipline: str = "ELEC_LIGHT"  # "ELEC_LIGHT", "ELEC_POWER", "ELEC_COMM", "ELEC_FIRE"
    revision: str = "REV0"
    sheet_role: SheetRole = SheetRole.INSTALLATION
    active_for_takeoff: bool = True
    is_latest: bool = True
    description: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DrawingScopeUpdate(BaseModel):
    """Request payload to update a drawing's scope metadata."""
    model_config = ConfigDict(extra="forbid")
    sheet_key: str | None = None
    floor: str | None = None
    zone: str | None = None
    discipline: str | None = None
    revision: str | None = None
    sheet_role: SheetRole | None = None
    active_for_takeoff: bool | None = None
    description: str | None = None


class ActivateRevisionRequest(BaseModel):
    """Request payload to set the active revision for a logical drawing group."""
    model_config = ConfigDict(extra="forbid")
    active: bool = True


# ---------------------------------------------------------------------------
# Project Consolidated Takeoff (Issue #35 Workstream B)
# ---------------------------------------------------------------------------
class ProjectTakeoffSummaryRow(BaseModel):
    """Consolidated takeoff row across active drawings in a project."""
    item_code: str
    item_name: str
    specification: str
    unit: str  # Strictly separated (EA, m, m² never combined)
    total_quantity: int
    active_drawings_count: int
    is_provisional: bool = False
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    quantity_method: QuantityMethod = QuantityMethod.CAD_BLOCK
    notes: str = ""


class DrawingTakeoffBreakdownItem(BaseModel):
    """Breakdown of an individual active drawing's contribution to project takeoff."""
    drawing_id: str
    filename: str
    sheet_key: str
    floor: str
    discipline: str
    revision: str
    sheet_role: SheetRole
    active_for_takeoff: bool
    items: list[TakeoffSummaryRow]
    unresolved_count: int = 0
    is_provisional: bool = False


class ProjectTakeoffResult(BaseModel):
    """Full project-level consolidated takeoff result."""
    project_id: str
    project_name: str
    total_active_drawings: int
    total_inactive_drawings: int
    summary: list[ProjectTakeoffSummaryRow]
    drawings_breakdown: list[DrawingTakeoffBreakdownItem]
    drawings_scope: list[DrawingScope]
    scope_warnings: list[str]
    unresolved_count: int = 0
    is_provisional: bool = False
    exported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Revision Comparison / Diff (Issue #35 Workstream C)
# ---------------------------------------------------------------------------
class RevisionItemDelta(BaseModel):
    """Quantity delta between two revisions for a single equipment item."""
    item_code: str
    item_name: str
    specification: str
    unit: str
    base_quantity: int
    compare_quantity: int
    delta: int  # compare_quantity - base_quantity
    change_type: str  # "INCREASED", "DECREASED", "UNCHANGED", "ADDED", "REMOVED"
    notes: str = ""


class RevisionObjectDelta(BaseModel):
    """CAD entity or detected symbol correspondence between two revisions."""
    object_id: str
    item_code: str
    x: float
    y: float
    layer: str
    match_status: str  # "MATCHED", "PROPOSED_MATCH", "ADDED", "REMOVED"
    confidence: float = 1.0
    notes: str = ""


class RevisionComparisonResult(BaseModel):
    """Pragmatic diff comparison between a base drawing and a compare drawing."""
    project_id: str
    base_drawing: dict[str, Any]
    compare_drawing: dict[str, Any]
    items_delta: list[RevisionItemDelta]
    object_deltas: list[RevisionObjectDelta]
    total_base_qty: int
    total_compare_qty: int
    total_delta: int
    notes: str = ""



