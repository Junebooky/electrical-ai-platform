"""Normalized drawing contract (draft) produced by :mod:`cad_engine.normalize`.

This module is the single source of truth for the JSON contract described in
``docs/CAD_SCHEMA.md``. Bump :data:`SCHEMA_VERSION` on any breaking change.

Design notes
------------
* All coordinates are **world coordinates (WCS) of Model Space**, expressed in the
  drawing's own units (see :attr:`DxfInfo.units_name`). No unit conversion is done.
* ``SourceObject`` is the *traceable unit*: every takeoff evidence row must point
  to exactly one ``SourceObject.id`` (or to a manual object in a later task).
* ``Primitive`` is render-only geometry. Every primitive carries the id of the
  ``SourceObject`` it belongs to, so the viewer can highlight / select it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.1.0"

Point2 = tuple[float, float]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=False, extra="forbid")


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class WarningCode(StrEnum):
    """Machine-readable warning codes. Messages are user-facing (Korean)."""

    UNITS_UNDEFINED = "UNITS_UNDEFINED"
    XREF_UNRESOLVED = "XREF_UNRESOLVED"
    ANONYMOUS_BLOCK = "ANONYMOUS_BLOCK"
    DYNAMIC_BLOCK = "DYNAMIC_BLOCK"
    NESTED_BLOCK = "NESTED_BLOCK"
    NESTING_TOO_DEEP = "NESTING_TOO_DEEP"
    CIRCULAR_BLOCK_REFERENCE = "CIRCULAR_BLOCK_REFERENCE"
    MINSERT_EXPANDED = "MINSERT_EXPANDED"
    HIDDEN_LAYER = "HIDDEN_LAYER"
    MISSING_BLOCK_DEFINITION = "MISSING_BLOCK_DEFINITION"
    PAPER_SPACE_IGNORED = "PAPER_SPACE_IGNORED"
    UNSUPPORTED_ENTITY = "UNSUPPORTED_ENTITY"
    EMPTY_MODELSPACE = "EMPTY_MODELSPACE"
    AUDIT_FIXES_APPLIED = "AUDIT_FIXES_APPLIED"
    AUDIT_ERRORS = "AUDIT_ERRORS"
    GEOMETRY_ERROR = "GEOMETRY_ERROR"
    PRIMITIVE_LIMIT_REACHED = "PRIMITIVE_LIMIT_REACHED"


class DrawingWarning(_Model):
    code: WarningCode
    severity: Severity
    message: str
    object_ids: list[str] = Field(default_factory=list)
    details: dict[str, int | str] = Field(default_factory=dict)


class SourceInfo(_Model):
    filename: str
    sha256: str
    size_bytes: int


class DxfInfo(_Model):
    version: str  # e.g. "AC1032"
    release: str  # e.g. "R2018"
    encoding: str
    insunits: int
    units_name: str
    units_defined: bool
    measurement: int | None  # $MEASUREMENT 0=imperial 1=metric


class BBox(_Model):
    min: Point2
    max: Point2


class LayerInfo(_Model):
    name: str
    color: int
    is_off: bool
    is_frozen: bool
    is_locked: bool
    object_count: int = 0


class BlockInfo(_Model):
    name: str
    effective_name: str
    is_xref: bool
    is_anonymous: bool
    is_dynamic_reference: bool
    base_point: tuple[float, float, float]
    entity_count: int
    top_level_insert_count: int = 0
    nested_insert_count: int = 0


class SourceObject(_Model):
    """A traceable CAD object.

    ``id`` format: ``"{drawing_id}:{h0}/{h1}/..."`` where ``h0`` is the handle of the
    Model Space entity and ``h1..`` are handles of nested INSERTs *inside block
    definitions*. MINSERT cells get the suffix ``#r{row}c{col}``.
    """

    id: str
    drawing_id: str
    raw_handle: str
    insert_path: list[str]
    parent_id: str | None
    depth: int
    entity_type: str
    layer: str
    visible: bool
    block_name: str | None = None
    effective_block_name: str | None = None
    insert_point: Point2 | None = None
    rotation_deg: float | None = None
    scale: tuple[float, float, float] | None = None
    bbox: BBox | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    text: str | None = None
    geometric_length: float | None = Field(
        default=None,
        description=(
            "Informational drawn length in drawing units. NOT a cable/conduit length "
            "(PRD §5: P0 must not treat drawn lines as installed wiring)."
        ),
    )
    is_count_candidate: bool = False
    warnings: list[WarningCode] = Field(default_factory=list)


class PrimitiveKind(StrEnum):
    POLYLINE = "polyline"
    TEXT = "text"


class Primitive(_Model):
    object_id: str
    kind: PrimitiveKind
    layer: str
    color: str  # "#rrggbb"
    points: list[Point2] = Field(default_factory=list)
    closed: bool = False
    text: str | None = None
    height: float | None = None
    rotation_deg: float | None = None


class ParseStats(_Model):
    modelspace_entities: int
    paperspace_entities: int
    source_objects: int
    primitives: int
    primitive_points: int
    entity_types: dict[str, int]
    unsupported_types: dict[str, int]
    parse_ms: float


class NormalizedDrawing(_Model):
    schema_version: str = SCHEMA_VERSION
    drawing_id: str
    source: SourceInfo
    dxf: DxfInfo
    extents: BBox | None
    layers: list[LayerInfo]
    blocks: list[BlockInfo]
    objects: list[SourceObject]
    primitives: list[Primitive]
    warnings: list[DrawingWarning]
    stats: ParseStats
