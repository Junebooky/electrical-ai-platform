"""Multi-format electrical symbol candidate detection engine (Issue #23).

Supports:
1. DXF: Scans INSERT block references with mapping rules or layer/block naming heuristics.
2. Vector PDF: Scans text annotations (e.g. L-01, OUTLET, SW) and vector path footprints.
3. Raster Image (PNG/JPG): Scans color-coded and geometric symbol clusters.
"""

from __future__ import annotations

import io
import re
from typing import Any

import numpy as np
from cad_engine.schema import WarningCode
from PIL import Image

from .models import (
    CandidateStatus,
    DetectionSource,
    ItemMappingRule,
    SymbolCandidate,
)
from .pdf_features import extract_pdf_page_features


# ---------------------------------------------------------------------------
# 1. DXF Symbol Detection & Structural Eligibility (P0-QTY-02)
# ---------------------------------------------------------------------------
def get_dxf_structural_block_reason(
    obj: Any,
    parent_ids: set[str] | None = None,
) -> str | None:
    """Fail-closed structural eligibility check sharing aggregate/storage invariants (P0-QTY-02)."""
    warnings = getattr(obj, "warnings", []) or []
    for code in (
        WarningCode.XREF_UNRESOLVED,
        WarningCode.MISSING_BLOCK_DEFINITION,
        WarningCode.CIRCULAR_BLOCK_REFERENCE,
    ):
        if code in warnings:
            return "구조적 결함(외부참조/블록정의 누락/순환참조)"
    for code in (
        WarningCode.DYNAMIC_BLOCK,
        WarningCode.ANONYMOUS_BLOCK,
    ):
        if code in warnings:
            return "동적/익명 블록: 가시성·구조 검수 필요"
    if parent_ids and getattr(obj, "id", None) in parent_ids:
        return "중첩 블록 계층(상위 어셈블리): 집계 기준 미확정(A05)"
    if (
        getattr(obj, "depth", 0) > 0
        or WarningCode.NESTED_BLOCK in warnings
        or getattr(obj, "parent_id", None) is not None
    ):
        return "중첩 블록: 집계 기준 미확정(A05)"
    if not getattr(obj, "visible", True):
        return "꺼짐/동결 레이어"
    if not getattr(obj, "is_count_candidate", True) and getattr(obj, "depth", 0) == 0:
        return "비집계 대상 객체(is_count_candidate=False)"
    return None


def detect_dxf_candidates(
    drawing: Any,
    drawing_id: str,
    mapping_rules: list[ItemMappingRule] | None = None,
) -> list[SymbolCandidate]:
    """Detect electrical symbol candidates from DXF drawing INSERT blocks."""
    candidates: list[SymbolCandidate] = []
    rule_map: dict[str, ItemMappingRule] = {}
    if mapping_rules:
        for r in mapping_rules:
            rule_map[r.block_name] = r

    objects = getattr(drawing, "objects", []) or []
    cad_objects = [obj for obj in objects if getattr(obj, "entity_type", "") == "INSERT"]
    parent_ids = {o.parent_id for o in cad_objects if getattr(o, "parent_id", None) is not None}

    for idx, obj in enumerate(cad_objects):
        block_name = getattr(obj, "block_name", "") or ""
        layer = getattr(obj, "layer", "") or ""
        pt = getattr(obj, "insert_point", None)
        x = float(pt[0]) if pt else 0.0
        y = float(pt[1]) if pt else 0.0
        obj_id = getattr(obj, "id", f"ins_{idx}")

        struct_reason = get_dxf_structural_block_reason(obj, parent_ids)
        is_blocked = struct_reason is not None

        # Check existing mapping rule first
        if block_name in rule_map:
            rule = rule_map[block_name]
            if rule.item_code in ("EXCLUDE", "UNMAPPED"):
                continue
            item_code = rule.item_code
            item_name = rule.item_name or rule.item_code
            confidence = 0.98 if not is_blocked else 0.0
        else:
            # Heuristic classification based on block name and layer
            combined = f"{block_name} {layer}"
            if re.search(r"(?:LIGHT|LT[-_]?|DL|전등|조명|다운라이트)", combined, re.I):
                item_code = "LIGHT"
                item_name = "조명기구"
                confidence = 0.95 if not is_blocked else 0.0
            elif re.search(r"(?:OUTLET|CON(?:SOLET)?|전열|콘센트)", combined, re.I):
                item_code = "OUTLET"
                item_name = "전열 콘센트"
                confidence = 0.95 if not is_blocked else 0.0
            elif re.search(r"(?:SW(?:ITCH)?|스위치)", combined, re.I):
                item_code = "SWITCH"
                item_name = "스위치"
                confidence = 0.95 if not is_blocked else 0.0
            elif re.search(r"(?:PANEL|DB[-_]?|DIST|분전반|배전반)", combined, re.I):
                item_code = "PANEL"
                item_name = "분전반"
                confidence = 0.95 if not is_blocked else 0.0
            else:
                item_code = "MISC_ELEC"
                item_name = block_name or "기타 전기설비"
                confidence = 0.75 if not is_blocked else 0.0

        if is_blocked:
            item_name = f"{item_name} (검수불가: {struct_reason})"

        cand = SymbolCandidate(
            candidate_id=f"cand_dxf_{drawing_id}_{obj_id}",
            drawing_id=drawing_id,
            page_index=0,
            coordinate_space="WORLD",
            x=round(x, 2),
            y=round(y, 2),
            bbox=[round(x - 15.0, 2), round(y - 15.0, 2), round(x + 15.0, 2), round(y + 15.0, 2)],
            suggested_item_code=item_code,
            suggested_item_name=item_name,
            confidence=confidence,
            detection_source=DetectionSource.DXF_BLOCK.value,
            status=CandidateStatus.PROPOSED,
            raw_evidence={
                "source_object_id": obj_id,
                "block_name": block_name,
                "layer": layer,
                "is_structurally_blocked": is_blocked,
                "structural_block_reason": struct_reason,
            },
        )
        candidates.append(cand)

    return candidates


# ---------------------------------------------------------------------------
# 2. Vector PDF Symbol Detection
# ---------------------------------------------------------------------------
def detect_pdf_candidates(
    pdf_bytes: bytes,
    drawing_id: str,
    page_count: int = 1,
) -> list[SymbolCandidate]:
    """Detect electrical symbol candidates from Vector PDF text annotations."""
    candidates: list[SymbolCandidate] = []

    for page_idx in range(page_count):
        try:
            feats = extract_pdf_page_features(pdf_bytes, page_idx, drawing_id)
        except Exception:
            continue

        for t in feats.texts:
            text = t.text.strip()
            if not text:
                continue

            item_code: str | None = None
            item_name: str | None = None
            confidence = 0.90

            # Match electrical tags
            if re.search(r"\b(?:L-\d+|DL\d*|LIGHT|조명|다운라이트|형광등|LED|EM-LIGHT)\b", text, re.I):
                item_code = "LIGHT"
                item_name = "조명기구"
            elif re.search(r"\b(?:OUTLET(?:-\d+)?|CON(?:SOLET)?|2구|콘센트|전열)\b", text, re.I):
                item_code = "OUTLET"
                item_name = "전열 콘센트"
            elif re.search(r"\b(?:SW(?:ITCH)?(?:-\d+)?|1P|2P|스위치)\b", text, re.I):
                item_code = "SWITCH"
                item_name = "스위치"
            elif re.search(r"\b(?:DB(?:-\d+)?|분전반|배전반|PANEL)\b", text, re.I):
                item_code = "PANEL"
                item_name = "분전반"

            if item_code and item_name:
                cand = SymbolCandidate(
                    candidate_id=f"cand_pdf_{drawing_id}_p{page_idx}_{t.source_object_id}",
                    drawing_id=drawing_id,
                    page_index=page_idx,
                    coordinate_space="PDF_PAGE_POINT",
                    x=round(t.x, 2),
                    y=round(t.y, 2),
                    bbox=[round(b, 2) for b in t.bbox],
                    suggested_item_code=item_code,
                    suggested_item_name=item_name,
                    confidence=confidence,
                    detection_source=DetectionSource.PDF_VECTOR_RULE.value,
                    status=CandidateStatus.PROPOSED,
                    raw_evidence={
                        "text": text,
                        "source_object_id": t.source_object_id,
                        "extraction_method": t.extraction_method,
                    },
                )
                candidates.append(cand)

    return candidates


# ---------------------------------------------------------------------------
# 3. Raster Image Symbol Detection (P0-STAB-04)
# ---------------------------------------------------------------------------
def _cluster_image_points(
    mask: np.ndarray[Any, Any],
    min_pixels: int = 10,
    max_dist: int = 30,
    max_pixels: int = 100_000,
) -> list[dict[str, Any]]:
    """Cluster binary mask points using incremental union-find and spatial hashing.

    Complexity: O(N) where N <= max_pixels with O(1) centroid and bounding box accumulation,
    preventing quadratic CPU blowup on dense masks (P0-STAB-04).
    """
    ys, xs = np.where(mask)
    n = len(xs)
    if n == 0:
        return []

    step = max(1, n // max_pixels)
    xs_sampled = xs[::step]
    ys_sampled = ys[::step]

    cell_size = max_dist
    grid: dict[tuple[int, int], int] = {}
    parent: list[int] = []

    def find(i: int) -> int:
        path: list[int] = []
        while parent[i] != i:
            path.append(i)
            i = parent[i]
        for node in path:
            parent[node] = i
        return i

    def union(i: int, j: int) -> int:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri
            return ri
        return ri

    clusters: list[dict[str, Any]] = []

    for x_i, y_i in zip(xs_sampled, ys_sampled, strict=False):
        x = int(x_i)
        y = int(y_i)
        cx_cell = x // cell_size
        cy_cell = y // cell_size

        touching_clusters: set[int] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                c_idx = grid.get((cx_cell + dx, cy_cell + dy))
                if c_idx is not None:
                    touching_clusters.add(find(c_idx))

        if not touching_clusters:
            new_idx = len(clusters)
            parent.append(new_idx)
            clusters.append({
                "sum_x": x,
                "sum_y": y,
                "count": 1,
                "min_x": x,
                "max_x": x,
                "min_y": y,
                "max_y": y,
            })
            grid[(cx_cell, cy_cell)] = new_idx
        else:
            root: int | None = None
            for tc in touching_clusters:
                root = tc if root is None else union(root, tc)

            assert root is not None
            c = clusters[root]
            c["sum_x"] += x
            c["sum_y"] += y
            c["count"] += 1
            if x < c["min_x"]:
                c["min_x"] = x
            if x > c["max_x"]:
                c["max_x"] = x
            if y < c["min_y"]:
                c["min_y"] = y
            if y > c["max_y"]:
                c["max_y"] = y
            grid[(cx_cell, cy_cell)] = root

    merged: dict[int, dict[str, Any]] = {}
    for idx, c in enumerate(clusters):
        root = find(idx)
        if root not in merged:
            merged[root] = {
                "sum_x": 0,
                "sum_y": 0,
                "count": 0,
                "min_x": 10**9,
                "max_x": -(10**9),
                "min_y": 10**9,
                "max_y": -(10**9),
            }
        m = merged[root]
        m["sum_x"] += c["sum_x"]
        m["sum_y"] += c["sum_y"]
        m["count"] += c["count"]
        if c["min_x"] < m["min_x"]:
            m["min_x"] = c["min_x"]
        if c["max_x"] > m["max_x"]:
            m["max_x"] = c["max_x"]
        if c["min_y"] < m["min_y"]:
            m["min_y"] = c["min_y"]
        if c["max_y"] > m["max_y"]:
            m["max_y"] = c["max_y"]

    results: list[dict[str, Any]] = []
    for m in merged.values():
        if m["count"] * step >= min_pixels:
            cnt = m["count"]
            results.append({
                "cx": round(m["sum_x"] / cnt, 1),
                "cy": round(m["sum_y"] / cnt, 1),
                "bbox": [float(m["min_x"]), float(m["min_y"]), float(m["max_x"]), float(m["max_y"])],
                "count": m["count"] * step,
            })
    return results


def detect_image_candidates(
    image_bytes: bytes,
    drawing_id: str,
) -> list[SymbolCandidate]:
    """Detect electrical symbol candidates from 2D raster image drawing (PNG/JPG)."""
    candidates: list[SymbolCandidate] = []
    im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.array(im)

    # 1. Color-coded electrical masks (Standard CAD/BIM floor plan presets)
    color_configs: list[dict[str, Any]] = [
        # Yellow: Lighting fixtures
        {
            "mask": (arr[:, :, 0] > 200) & (arr[:, :, 1] > 180) & (arr[:, :, 2] < 50),
            "item_code": "LIGHT",
            "item_name": "조명기구",
            "color_tag": "yellow",
            "confidence": 0.88,
        },
        # Sky Blue: Power Outlets / Receptacles
        {
            "mask": (arr[:, :, 0] < 80) & (arr[:, :, 1] > 160) & (arr[:, :, 2] > 200),
            "item_code": "OUTLET",
            "item_name": "전열 콘센트",
            "color_tag": "sky",
            "confidence": 0.88,
        },
        # Emerald Green: Wall Switches
        {
            "mask": (arr[:, :, 0] < 50) & (arr[:, :, 1] > 170) & (arr[:, :, 2] < 120),
            "item_code": "SWITCH",
            "item_name": "스위치",
            "color_tag": "green",
            "confidence": 0.88,
        },
    ]

    total_color_detected = 0
    for cfg in color_configs:
        clusters = _cluster_image_points(cfg["mask"], min_pixels=10, max_dist=30)
        for idx, cl in enumerate(clusters):
            total_color_detected += 1
            cand = SymbolCandidate(
                candidate_id=f"cand_img_{drawing_id}_{cfg['color_tag']}_{idx + 1}",
                drawing_id=drawing_id,
                page_index=0,
                coordinate_space="IMAGE_PIXEL",
                x=cl["cx"],
                y=cl["cy"],
                bbox=cl["bbox"],
                suggested_item_code=cfg["item_code"],
                suggested_item_name=cfg["item_name"],
                confidence=cfg["confidence"],
                detection_source=DetectionSource.IMAGE_TEMPLATE.value,
                status=CandidateStatus.PROPOSED,
                raw_evidence={
                    "color_tag": cfg["color_tag"],
                    "pixel_count": cl["count"],
                },
            )
            candidates.append(cand)

    # 2. Fallback for grayscale / non-color raster drawings:
    # If no colored symbols found, detect compact dark component shapes
    if total_color_detected == 0:
        gray = arr.mean(axis=2)
        dark_mask = gray < 60  # dark lines/shapes
        dark_clusters = _cluster_image_points(dark_mask, min_pixels=25, max_dist=20)
        for idx, cl in enumerate(dark_clusters):
            bw = cl["bbox"][2] - cl["bbox"][0]
            bh = cl["bbox"][3] - cl["bbox"][1]
            if 8 <= bw <= 60 and 8 <= bh <= 60:
                cand = SymbolCandidate(
                    candidate_id=f"cand_img_{drawing_id}_sym_{idx + 1}",
                    drawing_id=drawing_id,
                    page_index=0,
                    coordinate_space="IMAGE_PIXEL",
                    x=cl["cx"],
                    y=cl["cy"],
                    bbox=cl["bbox"],
                    suggested_item_code="MISC_ELEC",
                    suggested_item_name="기호 후보",
                    confidence=0.65,
                    detection_source=DetectionSource.IMAGE_TEMPLATE.value,
                    status=CandidateStatus.PROPOSED,
                    raw_evidence={"pixel_count": cl["count"], "dimensions": [bw, bh]},
                )
                candidates.append(cand)

    return candidates


# ---------------------------------------------------------------------------
# 4. Master Unified Detection Entry Point
# ---------------------------------------------------------------------------
def detect_candidates(
    drawing: Any,
    raw_bytes: bytes,
    drawing_id: str,
    source_type: str,
    page_count: int = 1,
    mapping_rules: list[ItemMappingRule] | None = None,
) -> list[SymbolCandidate]:
    """Unified detector dispatching to DXF, PDF, or Image detection engine."""
    norm_source = (source_type or "").upper()
    if norm_source == "DXF":
        return detect_dxf_candidates(drawing, drawing_id, mapping_rules)
    elif norm_source == "PDF":
        return detect_pdf_candidates(pdf_bytes=raw_bytes, drawing_id=drawing_id, page_count=page_count)
    elif norm_source == "IMAGE":
        return detect_image_candidates(image_bytes=raw_bytes, drawing_id=drawing_id)
    else:
        return []
