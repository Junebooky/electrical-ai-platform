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

