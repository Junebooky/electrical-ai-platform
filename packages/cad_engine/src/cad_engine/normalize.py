"""DXF → :class:`~cad_engine.schema.NormalizedDrawing`.

Deterministic, side-effect free. The only input is the loaded ezdxf document plus
source metadata; the output is a JSON-serializable contract (see ``schema.py``).

Coordinate handling
-------------------
Every INSERT contributes a 4x4 matrix (``Insert.matrix44()``: block coords → parent
coords, including base point, OCS, rotation and (non-uniform) scale). Nested
matrices are chained as ``child.matrix44() @ parent_world`` (ezdxf uses row
vectors, so the left operand is applied first). Curve geometry is converted to
``ezdxf.path.Path`` *in the defining coordinate system* and then transformed, which
stays correct under non-uniform scaling where ARC/CIRCLE would otherwise break.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ezdxf import colors as ezcolors
from ezdxf import path as ezpath
from ezdxf.math import Matrix44, Vec3

from .loader import LoadedDxf
from .schema import (
    BBox,
    BlockInfo,
    DrawingWarning,
    DxfInfo,
    LayerInfo,
    NormalizedDrawing,
    ParseStats,
    Primitive,
    PrimitiveKind,
    Severity,
    SourceInfo,
    SourceObject,
    WarningCode,
)

UNIT_NAMES: dict[int, str] = {
    0: "Unitless",
    1: "Inches",
    2: "Feet",
    3: "Miles",
    4: "Millimeters",
    5: "Centimeters",
    6: "Meters",
    7: "Kilometers",
    8: "Microinches",
    9: "Mils",
    10: "Yards",
    11: "Angstroms",
    12: "Nanometers",
    13: "Microns",
    14: "Decimeters",
    15: "Decameters",
    16: "Hectometers",
    17: "Gigameters",
    18: "Astronomical units",
    19: "Light years",
    20: "Parsecs",
    21: "US Survey Feet",
}

# Entity types rendered through ezdxf.path.make_path().
PATH_TYPES = frozenset(
    {
        "LINE",
        "ARC",
        "CIRCLE",
        "ELLIPSE",
        "LWPOLYLINE",
        "POLYLINE",
        "SPLINE",
        "SOLID",
        "TRACE",
        "3DFACE",
        "HATCH",
        "MPOLYGON",
        "HELIX",
        "WIPEOUT",
    }
)
TEXT_TYPES = frozenset({"TEXT", "MTEXT", "ATTRIB"})
LENGTH_TYPES = frozenset({"LINE", "ARC", "CIRCLE", "ELLIPSE", "LWPOLYLINE", "POLYLINE", "SPLINE"})

_MESSAGES: dict[WarningCode, tuple[Severity, str]] = {
    WarningCode.UNITS_UNDEFINED: (
        Severity.WARNING,
        "도면 단위($INSUNITS)가 설정되지 않았습니다. 좌표·길이의 단위를 확인해야 합니다.",
    ),
    WarningCode.XREF_UNRESOLVED: (
        Severity.WARNING,
        "외부참조(XREF)가 포함되어 있습니다. 외부 도면의 내용은 표시·집계되지 않습니다.",
    ),
    WarningCode.ANONYMOUS_BLOCK: (
        Severity.WARNING,
        "익명 블록 참조가 있습니다. 블록명이 저장할 때마다 바뀔 수 있어 매핑에 주의해야 합니다.",
    ),
    WarningCode.DYNAMIC_BLOCK: (
        Severity.WARNING,
        "동적 블록 참조가 있습니다. 원본 블록명을 추정해 표시하며, 가시성 상태 등은 해석하지 않습니다.",
    ),
    WarningCode.NESTED_BLOCK: (
        Severity.INFO,
        "중첩 블록이 있습니다. 중첩된 블록의 집계 여부는 A05 규칙 확정 전까지 기본적으로 제외됩니다.",
    ),
    WarningCode.NESTING_TOO_DEEP: (
        Severity.WARNING,
        "블록 중첩 깊이가 허용 한도를 넘어 일부 내용을 해석하지 않았습니다.",
    ),
    WarningCode.CIRCULAR_BLOCK_REFERENCE: (
        Severity.ERROR,
        "순환 참조 블록이 발견되어 해당 부분을 해석하지 않았습니다.",
    ),
    WarningCode.MINSERT_EXPANDED: (
        Severity.INFO,
        "배열 삽입(MINSERT)을 개별 객체로 펼쳐서 처리했습니다.",
    ),
    WarningCode.HIDDEN_LAYER: (
        Severity.WARNING,
        "꺼짐/동결 레이어에 객체가 있습니다. 자동 집계에서 미확인으로 분리됩니다.",
    ),
    WarningCode.MISSING_BLOCK_DEFINITION: (
        Severity.ERROR,
        "블록 정의가 없는 블록 참조가 있습니다.",
    ),
    WarningCode.PAPER_SPACE_IGNORED: (
        Severity.INFO,
        "Paper Space(배치) 객체는 MVP에서 표시·집계하지 않습니다.",
    ),
    WarningCode.UNSUPPORTED_ENTITY: (
        Severity.INFO,
        "표시를 지원하지 않는 객체 유형이 있습니다.",
    ),
    WarningCode.EMPTY_MODELSPACE: (
        Severity.WARNING,
        "Model Space에 객체가 없습니다.",
    ),
    WarningCode.AUDIT_FIXES_APPLIED: (
        Severity.INFO,
        "DXF 구조 오류 일부를 자동으로 보정해 읽었습니다. 원본 파일은 변경되지 않습니다.",
    ),
    WarningCode.AUDIT_ERRORS: (
        Severity.WARNING,
        "보정할 수 없는 DXF 구조 오류가 있습니다. 결과를 반드시 검토하세요.",
    ),
    WarningCode.GEOMETRY_ERROR: (
        Severity.WARNING,
        "일부 객체의 형상을 계산하지 못했습니다.",
    ),
    WarningCode.PRIMITIVE_LIMIT_REACHED: (
        Severity.ERROR,
        "도면이 너무 커서 표시 형상 일부를 생략했습니다.",
    ),
}


@dataclass(frozen=True, slots=True)
class Limits:
    max_depth: int = 8
    max_objects: int = 300_000
    max_primitive_points: int = 3_000_000


@dataclass(slots=True)
class _Ctx:
    """Inherited state while walking into block definitions."""

    matrix: Matrix44
    layer: str | None  # effective layer of the owning INSERT (for layer "0" entities)
    color: str  # resolved color of the owning INSERT (for BYBLOCK)
    visible: bool
    owner: SourceObject | None
    ancestors: tuple[str, ...]  # ids of owner + its ancestors (for bbox propagation)
    path: tuple[str, ...]
    depth: int
    block_stack: tuple[str, ...]


@dataclass(slots=True)
class _Bounds:
    minx: float = math.inf
    miny: float = math.inf
    maxx: float = -math.inf
    maxy: float = -math.inf

    def add(self, x: float, y: float) -> None:
        if x < self.minx:
            self.minx = x
        if y < self.miny:
            self.miny = y
        if x > self.maxx:
            self.maxx = x
        if y > self.maxy:
            self.maxy = y

    def merge(self, other: _Bounds) -> None:
        if other.empty:
            return
        self.add(other.minx, other.miny)
        self.add(other.maxx, other.maxy)

    @property
    def empty(self) -> bool:
        return self.minx == math.inf

    def to_bbox(self) -> BBox | None:
        if self.empty:
            return None
        return BBox(min=(_r(self.minx), _r(self.miny)), max=(_r(self.maxx), _r(self.maxy)))


def _r(v: float) -> float:
    return round(float(v), 6)


@dataclass
class _Normalizer:
    doc: Any
    drawing_id: str
    limits: Limits
    objects: list[SourceObject] = field(default_factory=list)
    primitives: list[Primitive] = field(default_factory=list)
    point_count: int = 0
    bounds: dict[str, _Bounds] = field(default_factory=dict)
    extents: _Bounds = field(default_factory=_Bounds)
    warn_objects: dict[WarningCode, list[str]] = field(default_factory=dict)
    warn_details: dict[WarningCode, dict[str, int | str]] = field(default_factory=dict)
    entity_types: Counter[str] = field(default_factory=Counter)
    unsupported: Counter[str] = field(default_factory=Counter)
    layer_state: dict[str, tuple[bool, int]] = field(default_factory=dict)  # name -> (visible, aci)
    effective_names: dict[str, str] = field(default_factory=dict)
    primitive_limit_hit: bool = False
    object_limit_hit: bool = False

    # ------------------------------------------------------------------ helpers
    def warn(self, code: WarningCode, obj_id: str | None = None) -> None:
        ids = self.warn_objects.setdefault(code, [])
        if obj_id is not None:
            ids.append(obj_id)

    def layer_visible(self, name: str) -> bool:
        state = self.layer_state.get(name)
        return True if state is None else state[0]

    def layer_color(self, name: str) -> int:
        state = self.layer_state.get(name)
        return 7 if state is None else state[1]

    def resolve_color(self, entity: Any, layer: str, byblock_color: str) -> str:
        dxf = entity.dxf
        true_color = dxf.get("true_color")
        if true_color is not None:
            r, g, b = ezcolors.int2rgb(int(true_color))
            return f"#{r:02x}{g:02x}{b:02x}"
        aci = int(dxf.get("color", 256))
        if aci == 0:
            return byblock_color
        if aci == 256:
            aci = self.layer_color(layer)
        aci = abs(aci) if 1 <= abs(aci) <= 255 else 7
        r, g, b = ezcolors.aci2rgb(aci)
        return f"#{r:02x}{g:02x}{b:02x}"

    def effective_layer(self, entity: Any, ctx: _Ctx) -> str:
        layer = str(entity.dxf.get("layer", "0"))
        if layer == "0" and ctx.layer is not None:
            return ctx.layer
        return layer

    def make_id(self, path: tuple[str, ...]) -> str:
        return f"{self.drawing_id}:{'/'.join(path)}"

    def effective_block_name(self, name: str) -> str:
        """Resolve the original name of a dynamic-block anonymous reference (*U..)."""
        cached = self.effective_names.get(name)
        if cached is not None:
            return cached
        result = name
        if name.startswith("*"):
            try:
                record = self.doc.block_records.get(name)
                if record is not None and record.has_xdata("AcDbBlockRepBTag"):
                    for code, value in record.get_xdata("AcDbBlockRepBTag"):
                        if code == 1005:
                            original = self.doc.entitydb.get(value)
                            if original is not None:
                                result = str(original.dxf.name)
                            break
            except Exception:  # pragma: no cover - defensive against odd files
                result = name
        self.effective_names[name] = result
        return result

    def add_object(self, obj: SourceObject) -> bool:
        if len(self.objects) >= self.limits.max_objects:
            self.object_limit_hit = True
            return False
        self.objects.append(obj)
        self.bounds[obj.id] = _Bounds()
        return True

    def add_primitive(self, prim: Primitive, ancestors: tuple[str, ...]) -> None:
        n = max(len(prim.points), 1)
        if self.point_count + n > self.limits.max_primitive_points:
            self.primitive_limit_hit = True
            return
        self.point_count += n
        self.primitives.append(prim)
        pts = prim.points
        for oid in ancestors:
            b = self.bounds.get(oid)
            if b is None:
                continue
            for x, y in pts:
                b.add(x, y)
        for x, y in pts:
            self.extents.add(x, y)

    # ---------------------------------------------------------------- geometry
    def path_primitives(
        self, entity: Any, matrix: Matrix44, owner_id: str, layer: str, color: str
    ) -> list[Primitive]:
        p = ezpath.make_path(entity)
        if matrix is not _IDENTITY:
            p = p.transform(matrix)
        if len(p) == 0 and not p.has_sub_paths:
            start = p.start
            return [
                Primitive(
                    object_id=owner_id,
                    kind=PrimitiveKind.POLYLINE,
                    layer=layer,
                    color=color,
                    points=[(_r(start.x), _r(start.y))],
                )
            ]
        out: list[Primitive] = []
        for sub in p.sub_paths() if p.has_sub_paths else [p]:
            bb = ezpath.bbox([sub], fast=True)
            size = max(bb.size.x, bb.size.y) if bb.has_data else 0.0
            distance = max(size * 1e-3, 1e-6)
            pts = [(_r(v.x), _r(v.y)) for v in sub.flattening(distance)]
            if not pts:
                continue
            out.append(
                Primitive(
                    object_id=owner_id,
                    kind=PrimitiveKind.POLYLINE,
                    layer=layer,
                    color=color,
                    points=pts,
                    closed=bool(sub.is_closed),
                )
            )
        return out

    def text_primitive(
        self, entity: Any, matrix: Matrix44, owner_id: str, layer: str, color: str
    ) -> Primitive | None:
        etype = entity.dxftype()
        if etype == "MTEXT":
            content = str(entity.plain_text())
            insert = Vec3(entity.dxf.insert)  # MTEXT insert is WCS
            height = float(entity.dxf.get("char_height", 1.0))
            angle = math.radians(float(entity.get_rotation()))
            direction = Vec3(math.cos(angle), math.sin(angle), 0)
            up = Vec3(-math.sin(angle), math.cos(angle), 0)
        else:
            if etype == "ATTRIB" and entity.is_invisible:
                return None
            content = str(entity.dxf.get("text", ""))
            ocs = entity.ocs()
            insert = ocs.to_wcs(Vec3(entity.dxf.insert))
            height = float(entity.dxf.get("height", 1.0))
            angle = math.radians(float(entity.dxf.get("rotation", 0.0)))
            direction = ocs.to_wcs(Vec3(math.cos(angle), math.sin(angle), 0))
            up = ocs.to_wcs(Vec3(-math.sin(angle), math.cos(angle), 0))
        if not content:
            return None
        pos = matrix.transform(insert)
        d = matrix.transform_direction(direction)
        u = matrix.transform_direction(up)
        return Primitive(
            object_id=owner_id,
            kind=PrimitiveKind.TEXT,
            layer=layer,
            color=color,
            points=[(_r(pos.x), _r(pos.y))],
            text=content,
            height=_r(height * u.magnitude),
            rotation_deg=_r(math.degrees(math.atan2(d.y, d.x))),
        )

    def render_entity(self, entity: Any, ctx: _Ctx, owner_id: str, layer: str) -> None:
        etype = entity.dxftype()
        color = self.resolve_color(entity, layer, ctx.color)
        try:
            if etype in PATH_TYPES:
                for prim in self.path_primitives(entity, ctx.matrix, owner_id, layer, color):
                    self.add_primitive(prim, ctx.ancestors)
            elif etype in TEXT_TYPES:
                text = self.text_primitive(entity, ctx.matrix, owner_id, layer, color)
                if text is not None:
                    self.add_primitive(text, ctx.ancestors)
            elif etype == "DIMENSION":
                block = entity.get_geometry_block()
                if block is not None:
                    self.walk_block(block, ctx, create_objects=False)
            else:
                self.unsupported[etype] += 1
        except (TypeError, ValueError, ZeroDivisionError, AttributeError):
            self.warn(WarningCode.GEOMETRY_ERROR, owner_id)

    # ------------------------------------------------------------------- walk
    def walk_block(self, block: Any, ctx: _Ctx, *, create_objects: bool) -> None:
        for entity in block:
            etype = entity.dxftype()
            if etype == "ATTDEF":
                continue  # template only; values live on ATTRIBs of the INSERT
            if etype == "INSERT":
                self.process_insert(entity, ctx, create_objects=create_objects)
                continue
            layer = self.effective_layer(entity, ctx)
            if not self.layer_visible(layer):
                continue
            owner_id = ctx.owner.id if ctx.owner is not None else ""
            self.render_entity(entity, ctx, owner_id, layer)

    def process_insert(self, insert: Any, ctx: _Ctx, *, create_objects: bool) -> None:
        handle = str(insert.dxf.get("handle") or "anon")
        if int(insert.mcount) > 1:
            for idx, virtual in enumerate(insert.multi_insert()):
                self.process_single_insert(
                    virtual, ctx, handle=f"{handle}#m{idx}", create_objects=create_objects,
                    minsert=True,
                )
        else:
            self.process_single_insert(
                insert, ctx, handle=handle, create_objects=create_objects, minsert=False
            )

    def process_single_insert(
        self, insert: Any, ctx: _Ctx, *, handle: str, create_objects: bool, minsert: bool
    ) -> None:
        name = str(insert.dxf.name)
        layer = self.effective_layer(insert, ctx)
        visible = ctx.visible and self.layer_visible(layer)
        color = self.resolve_color(insert, layer, ctx.color)
        block = self.doc.blocks.get(name)
        path = (*ctx.path, handle)
        depth = ctx.depth

        local = insert.matrix44()
        world = local @ ctx.matrix if ctx.matrix is not _IDENTITY else local
        insert_pt = ctx.matrix.transform(insert.ocs().to_wcs(Vec3(insert.dxf.insert)))
        x_axis = world.transform_direction(Vec3(1, 0, 0))

        warnings: list[WarningCode] = []
        is_xref = bool(block is not None and block.block.is_xref)
        is_anon = name.startswith("*")
        eff_name = self.effective_block_name(name)
        if block is None:
            warnings.append(WarningCode.MISSING_BLOCK_DEFINITION)
        if is_xref:
            warnings.append(WarningCode.XREF_UNRESOLVED)
        if is_anon:
            warnings.append(WarningCode.DYNAMIC_BLOCK if eff_name != name else WarningCode.ANONYMOUS_BLOCK)
        if depth > 0:
            warnings.append(WarningCode.NESTED_BLOCK)
        if minsert:
            warnings.append(WarningCode.MINSERT_EXPANDED)
        if not visible:
            warnings.append(WarningCode.HIDDEN_LAYER)

        owner = ctx.owner
        ancestors = ctx.ancestors
        if create_objects:
            obj_id = self.make_id(path)
            obj = SourceObject(
                id=obj_id,
                drawing_id=self.drawing_id,
                raw_handle=handle,
                insert_path=list(path),
                parent_id=ctx.owner.id if ctx.owner is not None else None,
                depth=depth,
                entity_type="INSERT",
                layer=layer,
                visible=visible,
                block_name=name,
                effective_block_name=eff_name,
                insert_point=(_r(insert_pt.x), _r(insert_pt.y)),
                rotation_deg=_r(math.degrees(math.atan2(x_axis.y, x_axis.x))),
                scale=(
                    _r(insert.dxf.get("xscale", 1.0)),
                    _r(insert.dxf.get("yscale", 1.0)),
                    _r(insert.dxf.get("zscale", 1.0)),
                ),
                attributes={
                    str(a.dxf.tag): str(a.dxf.get("text", "")) for a in insert.attribs
                },
                is_count_candidate=depth == 0 and block is not None and not is_xref,
                warnings=warnings,
            )
            if not self.add_object(obj):
                return
            for code in warnings:
                self.warn(code, obj_id)
            owner = obj
            ancestors = (obj_id, *ctx.ancestors)

        owner_id = owner.id if owner is not None else ""
        # ATTRIBs live in the parent's coordinate system.
        if visible:
            parent_ctx = _Ctx(
                matrix=ctx.matrix, layer=layer, color=color, visible=visible, owner=owner,
                ancestors=ancestors, path=path, depth=depth, block_stack=ctx.block_stack,
            )
            for attrib in insert.attribs:
                a_layer = self.effective_layer(attrib, parent_ctx)
                if self.layer_visible(a_layer):
                    self.render_entity(attrib, parent_ctx, owner_id, a_layer)

        if block is None or is_xref:
            return
        if name in ctx.block_stack:
            self.warn(WarningCode.CIRCULAR_BLOCK_REFERENCE, owner_id or None)
            return
        if depth + 1 > self.limits.max_depth:
            self.warn(WarningCode.NESTING_TOO_DEEP, owner_id or None)
            return
        child_ctx = _Ctx(
            matrix=world,
            layer=layer,
            color=color,
            visible=visible,
            owner=owner,
            ancestors=ancestors,
            path=path,
            depth=depth + 1,
            block_stack=(*ctx.block_stack, name),
        )
        if visible:
            self.walk_block(block, child_ctx, create_objects=create_objects)
        else:
            # Still discover nested objects (traceability) but render nothing.
            for entity in block:
                if entity.dxftype() == "INSERT":
                    self.process_insert(entity, child_ctx, create_objects=create_objects)

    def process_modelspace_entity(self, entity: Any, root: _Ctx) -> None:
        etype = entity.dxftype()
        self.entity_types[etype] += 1
        if etype == "INSERT":
            self.process_insert(entity, root, create_objects=True)
            return
        handle = str(entity.dxf.get("handle") or "anon")
        layer = str(entity.dxf.get("layer", "0"))
        visible = self.layer_visible(layer)
        obj_id = self.make_id((handle,))
        text: str | None = None
        if etype == "MTEXT":
            text = str(entity.plain_text())
        elif etype in ("TEXT", "ATTRIB"):
            text = str(entity.dxf.get("text", ""))
        length: float | None = None
        if etype in LENGTH_TYPES:
            length = _length(entity)
        obj = SourceObject(
            id=obj_id,
            drawing_id=self.drawing_id,
            raw_handle=handle,
            insert_path=[handle],
            parent_id=None,
            depth=0,
            entity_type=etype,
            layer=layer,
            visible=visible,
            text=text,
            geometric_length=length,
            warnings=[] if visible else [WarningCode.HIDDEN_LAYER],
        )
        if not self.add_object(obj):
            return
        ctx = _Ctx(
            matrix=_IDENTITY, layer=None, color="#ffffff", visible=visible, owner=obj,
            ancestors=(obj_id,), path=(handle,), depth=0, block_stack=(),
        )
        if visible:
            self.render_entity(entity, ctx, obj_id, layer)


_IDENTITY = Matrix44()


def _length(entity: Any) -> float | None:
    try:
        etype = entity.dxftype()
        if etype == "LINE":
            return _r(Vec3(entity.dxf.start).distance(Vec3(entity.dxf.end)))
        p = ezpath.make_path(entity)
        bb = ezpath.bbox([p], fast=True)
        size = max(bb.size.x, bb.size.y) if bb.has_data else 0.0
        pts = list(p.flattening(max(size * 1e-5, 1e-9)))
        return _r(sum(a.distance(b) for a, b in itertools.pairwise(pts)))
    except (TypeError, ValueError, ZeroDivisionError, AttributeError):
        return None


def drawing_id_from_bytes(data: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(data).hexdigest()
    return digest, f"d{digest[:16]}"


def normalize(
    loaded: LoadedDxf,
    *,
    filename: str,
    data: bytes,
    limits: Limits | None = None,
) -> NormalizedDrawing:
    started = time.perf_counter()
    doc = loaded.doc
    sha, drawing_id = drawing_id_from_bytes(data)
    n = _Normalizer(doc=doc, drawing_id=drawing_id, limits=limits or Limits())

    layers: list[LayerInfo] = []
    for layer in doc.layers:
        name = str(layer.dxf.name)
        aci = abs(int(layer.dxf.get("color", 7))) or 7
        off, frozen = bool(layer.is_off()), bool(layer.is_frozen())
        n.layer_state[name] = (not off and not frozen, aci)
        layers.append(
            LayerInfo(
                name=name, color=aci, is_off=off, is_frozen=frozen, is_locked=bool(layer.is_locked())
            )
        )

    msp = doc.modelspace()
    root = _Ctx(
        matrix=_IDENTITY, layer=None, color="#ffffff", visible=True, owner=None,
        ancestors=(), path=(), depth=0, block_stack=(),
    )
    ms_count = 0
    for entity in msp:
        ms_count += 1
        n.process_modelspace_entity(entity, root)
        if n.object_limit_hit:
            break

    # Bubble nested bboxes into SourceObjects.
    for obj in n.objects:
        obj.bbox = n.bounds[obj.id].to_bbox()

    ps_count = 0
    for layout in doc.layouts:
        if layout.is_modelspace:
            continue
        ps_count += sum(1 for e in layout if e.dxftype() != "VIEWPORT")

    # ---- document-level warnings
    insunits = int(doc.header.get("$INSUNITS", 0))
    if insunits == 0:
        n.warn(WarningCode.UNITS_UNDEFINED)
    if ps_count:
        n.warn(WarningCode.PAPER_SPACE_IGNORED)
        n.warn_details[WarningCode.PAPER_SPACE_IGNORED] = {"entities": ps_count}
    if ms_count == 0:
        n.warn(WarningCode.EMPTY_MODELSPACE)
    if n.unsupported:
        n.warn(WarningCode.UNSUPPORTED_ENTITY)
        n.warn_details[WarningCode.UNSUPPORTED_ENTITY] = dict(n.unsupported)
    if loaded.audit_fixes:
        n.warn(WarningCode.AUDIT_FIXES_APPLIED)
        n.warn_details[WarningCode.AUDIT_FIXES_APPLIED] = {"fixes": loaded.audit_fixes}
    if loaded.audit_errors:
        n.warn(WarningCode.AUDIT_ERRORS)
        n.warn_details[WarningCode.AUDIT_ERRORS] = {"errors": loaded.audit_errors}
    if n.primitive_limit_hit or n.object_limit_hit:
        n.warn(WarningCode.PRIMITIVE_LIMIT_REACHED)
    # XREF definitions present even if never inserted
    for block in doc.blocks:
        if block.block is not None and block.block.is_xref:
            n.warn(WarningCode.XREF_UNRESOLVED)
            n.warn_details.setdefault(WarningCode.XREF_UNRESOLVED, {})[str(block.name)] = str(
                block.block.dxf.get("xref_path", "")
            )

    warnings = [
        DrawingWarning(
            code=code,
            severity=_MESSAGES[code][0],
            message=_MESSAGES[code][1],
            object_ids=sorted(set(ids)),
            details=n.warn_details.get(code, {}),
        )
        for code, ids in sorted(n.warn_objects.items(), key=lambda kv: kv[0].value)
    ]

    # ---- per-layer / per-block stats
    layer_counts = Counter(o.layer for o in n.objects if o.depth == 0)
    for li in layers:
        li.object_count = layer_counts.get(li.name, 0)
    top_counts = Counter(o.block_name for o in n.objects if o.entity_type == "INSERT" and o.depth == 0)
    nested_counts = Counter(o.block_name for o in n.objects if o.entity_type == "INSERT" and o.depth > 0)
    blocks: list[BlockInfo] = []
    for block in doc.blocks:
        if block.is_any_layout:
            continue
        name = str(block.name)
        if name.startswith("*D"):
            continue  # dimension geometry blocks: implementation detail
        bp = Vec3(block.block.dxf.get("base_point", (0, 0, 0)))
        blocks.append(
            BlockInfo(
                name=name,
                effective_name=n.effective_block_name(name),
                is_xref=bool(block.block.is_xref),
                is_anonymous=name.startswith("*"),
                is_dynamic_reference=name.startswith("*") and n.effective_block_name(name) != name,
                base_point=(_r(bp.x), _r(bp.y), _r(bp.z)),
                entity_count=len(block),
                top_level_insert_count=top_counts.get(name, 0),
                nested_insert_count=nested_counts.get(name, 0),
            )
        )
    blocks.sort(key=lambda b: b.name)

    dxf_info = DxfInfo(
        version=str(doc.dxfversion),
        release=str(doc.acad_release),
        encoding=str(doc.encoding),
        insunits=insunits,
        units_name=UNIT_NAMES.get(insunits, f"Unknown({insunits})"),
        units_defined=insunits != 0,
        measurement=doc.header.get("$MEASUREMENT"),
    )
    stats = ParseStats(
        modelspace_entities=ms_count,
        paperspace_entities=ps_count,
        source_objects=len(n.objects),
        primitives=len(n.primitives),
        primitive_points=n.point_count,
        entity_types=dict(sorted(n.entity_types.items())),
        unsupported_types=dict(sorted(n.unsupported.items())),
        parse_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return NormalizedDrawing(
        drawing_id=drawing_id,
        source=SourceInfo(filename=filename, sha256=sha, size_bytes=len(data)),
        dxf=dxf_info,
        extents=n.extents.to_bbox(),
        layers=sorted(layers, key=lambda li: li.name),
        blocks=blocks,
        objects=n.objects,
        primitives=n.primitives,
        warnings=warnings,
        stats=stats,
    )
