"""API models and Takeoff Review schemas for the Electrical AI Platform."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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


class TakeoffResult(BaseModel):
    drawing_id: str
    drawing_name: str
    drawing_revision: str
    summary: list[TakeoffSummaryRow]
    evidence: list[TakeoffEvidenceRow]
    warnings_count: int


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
