"""Interactive visual symbol template search engine (Issue #29 Workstream B).

Allows users to crop an arbitrary symbol sample from an Image or PDF drawing,
and search for all matching or similar symbols across the entire drawing
using OpenCV normalized cross-correlation, multi-rotation matching, and Non-Maximum Suppression (NMS).
"""

from __future__ import annotations

import io
import math
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .detector import get_dxf_structural_block_reason
from .models import (
    CandidateStatus,
    DetectionSource,
    SymbolCandidate,
)

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None


def rotate_image(image: np.ndarray, angle: float) -> np.ndarray:
    """Rotate an image array by 90, 180, or 270 degrees cleanly without interpolation artifacts."""
    if angle == 90:
        return np.ascontiguousarray(cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE))
    elif angle == 180:
        return np.ascontiguousarray(cv2.rotate(image, cv2.ROTATE_180))
    elif angle == 270:
        return np.ascontiguousarray(cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE))
    return image


def non_max_suppression_boxes(
    boxes: list[list[float]],
    scores: list[float],
    overlap_thresh: float = 0.35,
) -> list[int]:
    """Pure numpy/Python or OpenCV Non-Maximum Suppression to filter duplicate overlapping boxes."""
    if not boxes:
        return []
    try:
        # OpenCV cv2.dnn.NMSBoxes expects boxes in [x, y, width, height] format
        xywh_boxes: list[list[float]] = []
        for b in boxes:
            bx1, by1, bx2, by2 = b[0], b[1], b[2], b[3]
            w = max(0.0, bx2 - bx1)
            h = max(0.0, by2 - by1)
            xywh_boxes.append([float(bx1), float(by1), float(w), float(h)])

        scores_arr = np.array(scores, dtype=np.float32)
        indices = cv2.dnn.NMSBoxes(
            xywh_boxes,
            scores_arr.tolist(),
            score_threshold=0.0,
            nms_threshold=overlap_thresh,
        )
        out_indices: list[int] = []
        for item in indices:
            idx = item[0] if isinstance(item, (list, tuple, np.ndarray)) else int(item)
            out_indices.append(idx)
        return out_indices
    except Exception:
        # Fallback greedy NMS
        pick = []
        arr_x1 = np.array([b[0] for b in boxes])
        arr_y1 = np.array([b[1] for b in boxes])
        arr_x2 = np.array([b[2] for b in boxes])
        arr_y2 = np.array([b[3] for b in boxes])
        s = np.array(scores)
        area = (arr_x2 - arr_x1) * (arr_y2 - arr_y1)
        order = s.argsort()[::-1]

        while order.size > 0:
            i = order[0]
            pick.append(int(i))
            xx1 = np.maximum(arr_x1[i], arr_x1[order[1:]])
            yy1 = np.maximum(arr_y1[i], arr_y1[order[1:]])
            xx2 = np.minimum(arr_x2[i], arr_x2[order[1:]])
            yy2 = np.minimum(arr_y2[i], arr_y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            iou = inter / (area[i] + area[order[1:]] - inter + 1e-6)
            inds = np.where(iou <= overlap_thresh)[0]
            order = order[inds + 1]
        return pick


def are_candidates_spatially_coincident(
    c1: SymbolCandidate,
    c2: SymbolCandidate,
    iou_thresh: float = 0.35,
) -> bool:
    """Check if two symbol candidates represent the exact same physical installation location (P0-02 & P0-REVIEW-02).

    Strict Invariants:
    1. Drawing ID and page_index must strictly match (different PDF pages are NEVER coincident).
    2. DXF: If both candidates link to a CAD source_object_id:
       - If source_object_id differs, they are distinct CAD entities and NEVER coincident.
       - If source_object_id matches, they are the same physical entity.
    3. If bboxes are present on both candidates:
       - If they do NOT intersect (inter_w <= 0 or inter_h <= 0, i.e. disjoint):
         They represent physically separated locations -> return False!
         (Prevents adjacent small symbols like [0,0,4,4] and [10,0,14,4] from being merged).
       - If they intersect:
         Check IoU >= iou_thresh OR containment (inter / min(area1, area2) >= 0.65
         with center distance <= max(2.0, min_dim * 0.40)).
         If neither condition is met, return False.
    4. If one or both candidates lack bounding boxes (len(bbox) < 4 or zero area):
       - Only then fall back to center distance <= 2.0.
    """
    if c1.drawing_id != c2.drawing_id:
        return False
    if getattr(c1, "page_index", 0) != getattr(c2, "page_index", 0):
        return False

    sid1 = c1.raw_evidence.get("source_object_id") if c1.raw_evidence else None
    sid2 = c2.raw_evidence.get("source_object_id") if c2.raw_evidence else None
    if sid1 is not None and sid2 is not None:
        return str(sid1) == str(sid2)

    b1 = getattr(c1, "bbox", None)
    b2 = getattr(c2, "bbox", None)
    has_b1 = bool(b1 and len(b1) == 4 and abs(b1[2] - b1[0]) > 0 and abs(b1[3] - b1[1]) > 0)
    has_b2 = bool(b2 and len(b2) == 4 and abs(b2[2] - b2[0]) > 0 and abs(b2[3] - b2[1]) > 0)

    if has_b1 and has_b2:
        assert b1 is not None and b2 is not None
        x1 = max(min(b1[0], b1[2]), min(b2[0], b2[2]))
        y1 = max(min(b1[1], b1[3]), min(b2[1], b2[3]))
        x2 = min(max(b1[0], b1[2]), max(b2[0], b2[2]))
        y2 = min(max(b1[1], b1[3]), max(b2[1], b2[3]))
        inter_w = max(0.0, x2 - x1)
        inter_h = max(0.0, y2 - y1)
        inter = inter_w * inter_h

        # Disjoint boxes represent separate physical installation spots (P0-REVIEW-02)
        if inter <= 0.0:
            return False

        area1 = abs((b1[2] - b1[0]) * (b1[3] - b1[1]))
        area2 = abs((b2[2] - b2[0]) * (b2[3] - b2[1]))
        union = area1 + area2 - inter

        # 1. Standard IoU overlap
        if union > 0 and (inter / union) >= iou_thresh:
            return True

        # 2. Containment / multi-scale crop match
        min_area = min(area1, area2)
        if min_area > 0 and (inter / min_area) >= 0.65:
            w_min = min(abs(b1[2] - b1[0]), abs(b2[2] - b2[0]))
            h_min = min(abs(b1[3] - b1[1]), abs(b2[3] - b2[1]))
            center_dist = math.hypot(c1.x - c2.x, c1.y - c2.y)
            if center_dist <= max(2.0, min(w_min, h_min) * 0.40):
                return True

        return False

    # Point-only candidates without bounding boxes
    dist = math.hypot(c1.x - c2.x, c1.y - c2.y)
    return dist <= 2.0


def merge_candidates_spatial(
    existing: list[SymbolCandidate],
    incoming: list[SymbolCandidate],
) -> list[SymbolCandidate]:
    """Merge incoming candidates with existing candidates, enforcing single-candidate per physical position.

    Crucial Invariants (P0-02 & P0-REVIEW-01):
    1. A single physical location NEVER produces multiple candidates.
    2. User-reviewed decisions (ACCEPTED or REJECTED) on existing candidates are strictly preserved,
       including their effective item codes, suggested names, reviewed_at, and review_notes.
       A re-search with a different item_code (e.g. OUTLET on an accepted LIGHT) MUST NEVER reclassify it.
    3. Different PDF pages remain distinct even if coordinates are identical.
    4. Only unreviewed PROPOSED candidates may be updated with higher confidence/better detection info.
    """
    merged: list[SymbolCandidate] = list(existing)

    for new_c in incoming:
        match_idx: int | None = None
        for idx, ex_c in enumerate(merged):
            if are_candidates_spatially_coincident(ex_c, new_c):
                match_idx = idx
                break

        if match_idx is not None:
            ex_c = merged[match_idx]

            # Case A: Existing candidate has been reviewed by the user (ACCEPTED or REJECTED)
            # P0-REVIEW-01: User review status, effective item code, and metadata MUST BE IMMUTABLE
            if ex_c.status in (CandidateStatus.ACCEPTED, CandidateStatus.REJECTED):
                updated = SymbolCandidate(
                    candidate_id=ex_c.candidate_id,
                    drawing_id=ex_c.drawing_id,
                    page_index=ex_c.page_index,
                    coordinate_space=ex_c.coordinate_space,
                    x=ex_c.x,
                    y=ex_c.y,
                    bbox=ex_c.bbox,
                    suggested_item_code=ex_c.suggested_item_code,
                    suggested_item_name=ex_c.suggested_item_name,
                    reviewed_item_code=ex_c.reviewed_item_code,
                    confidence=max(ex_c.confidence, new_c.confidence),
                    detection_source=ex_c.detection_source,
                    status=ex_c.status,
                    reviewed_at=ex_c.reviewed_at,
                    review_note=ex_c.review_note or "",
                    raw_evidence=dict(ex_c.raw_evidence or {}),
                )
                merged[match_idx] = updated

            # Case B: Incoming candidate is reviewed while existing candidate is unreviewed
            elif new_c.status in (CandidateStatus.ACCEPTED, CandidateStatus.REJECTED):
                updated = SymbolCandidate(
                    candidate_id=ex_c.candidate_id,
                    drawing_id=ex_c.drawing_id,
                    page_index=ex_c.page_index,
                    coordinate_space=ex_c.coordinate_space,
                    x=new_c.x,
                    y=new_c.y,
                    bbox=new_c.bbox,
                    suggested_item_code=new_c.suggested_item_code,
                    suggested_item_name=new_c.suggested_item_name,
                    reviewed_item_code=new_c.reviewed_item_code,
                    confidence=max(ex_c.confidence, new_c.confidence),
                    detection_source=new_c.detection_source,
                    status=new_c.status,
                    reviewed_at=new_c.reviewed_at,
                    review_note=new_c.review_note or "",
                    raw_evidence=dict(new_c.raw_evidence or {}),
                )
                merged[match_idx] = updated

            # Case C: Both candidates are PROPOSED (unreviewed). Safe to update with best proposal.
            else:
                if new_c.confidence >= ex_c.confidence:
                    best_c = new_c
                    other_c = ex_c
                else:
                    best_c = ex_c
                    other_c = new_c

                merged_evidence = dict(other_c.raw_evidence or {})
                merged_evidence.update(best_c.raw_evidence or {})

                updated = SymbolCandidate(
                    candidate_id=ex_c.candidate_id,
                    drawing_id=ex_c.drawing_id,
                    page_index=ex_c.page_index,
                    coordinate_space=ex_c.coordinate_space,
                    x=round((ex_c.x + new_c.x) / 2.0, 2),
                    y=round((ex_c.y + new_c.y) / 2.0, 2),
                    bbox=best_c.bbox or ex_c.bbox,
                    suggested_item_code=best_c.suggested_item_code or ex_c.suggested_item_code,
                    suggested_item_name=best_c.suggested_item_name or ex_c.suggested_item_name,
                    reviewed_item_code=None,
                    confidence=max(ex_c.confidence, new_c.confidence),
                    detection_source=best_c.detection_source or ex_c.detection_source,
                    status=CandidateStatus.PROPOSED,
                    reviewed_at=None,
                    review_note="",
                    raw_evidence=merged_evidence,
                )
                merged[match_idx] = updated
        else:
            merged.append(new_c)

    return merged


def match_template_multi_rotation(
    target_img: np.ndarray,
    template_patch: np.ndarray,
    threshold: float = 0.70,
    rotations: list[float] | None = None,
    overlap_thresh: float = 0.35,
    max_results: int = 150,
) -> list[dict[str, Any]]:
    """Perform multi-rotation template matching on target image using OpenCV.

    Supports:
    - TM_CCOEFF_NORMED for edge/line/text symbols.
    - TM_SQDIFF_NORMED multi-channel color difference fallback for low-contrast/solid colored symbols.
    """
    if rotations is None:
        rotations = [0.0, 90.0, 180.0, 270.0]

    h_target, w_target = target_img.shape[:2]
    is_color = len(target_img.shape) == 3 and target_img.shape[2] == 3

    if is_color:
        gray_target = cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY)
        gray_template = cv2.cvtColor(template_patch, cv2.COLOR_BGR2GRAY)
    else:
        gray_target = target_img
        gray_template = template_patch

    # Check if template has adequate variance (texture/lines) or is solid color
    tmpl_std = float(gray_template.std())
    use_color_sqdiff = (tmpl_std < 8.0) and is_color

    candidate_boxes: list[list[float]] = []
    candidate_scores: list[float] = []
    candidate_rotations: list[float] = []

    for rot in rotations:
        if rot == 0.0:
            rot_tmpl_gray = gray_template
            rot_tmpl_col = template_patch
        else:
            rot_tmpl_gray = rotate_image(gray_template, rot)
            rot_tmpl_col = rotate_image(template_patch, rot) if is_color else rot_tmpl_gray

        th, tw = rot_tmpl_gray.shape[:2]
        if th > h_target or tw > w_target or th < 4 or tw < 4:
            continue

        if use_color_sqdiff:
            # Color SQDIFF normalized across 3 channels
            diffs = []
            for ch in range(3):
                diff_ch = cv2.matchTemplate(target_img[:, :, ch], rot_tmpl_col[:, :, ch], cv2.TM_SQDIFF_NORMED)
                diffs.append(diff_ch)
            res_diff = (diffs[0] + diffs[1] + diffs[2]) / 3.0
            # Convert to similarity score where 1.0 is exact match
            res_score = np.maximum(0.0, 1.0 - res_diff)
            match_y, match_x = np.where(res_score >= threshold)
        else:
            res = cv2.matchTemplate(gray_target, rot_tmpl_gray, cv2.TM_CCOEFF_NORMED)
            # Replace NaNs/Infs that occur in completely blank white regions
            res = np.nan_to_num(res, nan=-1.0, posinf=1.0, neginf=-1.0)
            res_score = res
            match_y, match_x = np.where(res_score >= threshold)

        for y, x in zip(match_y, match_x, strict=False):
            score = float(res_score[y, x])
            candidate_boxes.append([float(x), float(y), float(x + tw), float(y + th)])
            candidate_scores.append(score)
            candidate_rotations.append(rot)

    if not candidate_boxes:
        return []

    # Non-Maximum Suppression to remove overlapping duplicate hits
    keep_indices = non_max_suppression_boxes(
        candidate_boxes,
        candidate_scores,
        overlap_thresh=overlap_thresh,
    )

    results: list[dict[str, Any]] = []
    for idx in keep_indices:
        b = candidate_boxes[idx]
        score = candidate_scores[idx]
        rot = candidate_rotations[idx]
        cx = (b[0] + b[2]) / 2.0
        cy = (b[1] + b[3]) / 2.0
        results.append({
            "bbox": b,
            "center": [cx, cy],
            "score": score,
            "rotation": rot,
        })

    # Sort descending by similarity score and truncate to max_results
    results.sort(key=lambda r: float(r["score"]), reverse=True)
    return results[:max_results]


def search_visual_symbols_image(
    image_bytes: bytes,
    drawing_id: str,
    sample_bbox: list[float],
    suggested_item_code: str = "LIGHT",
    suggested_item_name: str = "조명기구",
    threshold: float = 0.70,
    rotations: list[float] | None = None,
    max_results: int = 150,
) -> list[SymbolCandidate]:
    """Search for symbol candidates on a raster image drawing."""
    arr = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        # Fallback Pillow
        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)

    h_img, w_img = arr.shape[:2]
    x1, y1, x2, y2 = sample_bbox
    x_min = max(0, min(w_img - 1, math.floor(min(x1, x2))))
    y_min = max(0, min(h_img - 1, math.floor(min(y1, y2))))
    x_max = max(0, min(w_img, math.ceil(max(x1, x2))))
    y_max = max(0, min(h_img, math.ceil(max(y1, y2))))

    bw = x_max - x_min
    bh = y_max - y_min
    if bw < 4 or bh < 4:
        raise ValueError(f"선택한 기호 샘플 영역이 너무 작습니다 (폭: {bw}px, 높이: {bh}px, 최소 4px 필요)")

    template = arr[y_min:y_max, x_min:x_max]

    matches = match_template_multi_rotation(
        target_img=arr,
        template_patch=template,
        threshold=threshold,
        rotations=rotations,
        max_results=max_results,
    )

    candidates: list[SymbolCandidate] = []
    for m in matches:
        b = m["bbox"]
        cx, cy = m["center"]
        score = float(m["score"])
        rot = float(m["rotation"])
        cand = SymbolCandidate(
            candidate_id=f"cand_vis_img_{drawing_id}_{round(cx)}_{round(cy)}",
            drawing_id=drawing_id,
            page_index=0,
            coordinate_space="IMAGE_PIXEL",
            x=round(cx, 1),
            y=round(cy, 1),
            bbox=[round(b[0], 1), round(b[1], 1), round(b[2], 1), round(b[3], 1)],
            suggested_item_code=suggested_item_code,
            suggested_item_name=suggested_item_name,
            confidence=round(score, 3),
            detection_source=DetectionSource.VISUAL_TEMPLATE.value,
            status=CandidateStatus.PROPOSED,
            raw_evidence={
                "method": "VISUAL_TEMPLATE",
                "similarity_score": round(score, 3),
                "rotation_deg": rot,
                "template_bbox": [x_min, y_min, x_max, y_max],
            },
        )
        candidates.append(cand)

    return candidates


def search_visual_symbols_pdf(
    pdf_bytes: bytes,
    drawing_id: str,
    sample_bbox: list[float],
    page_index: int = 0,
    search_all_pages: bool = False,
    page_count: int = 1,
    suggested_item_code: str = "LIGHT",
    suggested_item_name: str = "조명기구",
    threshold: float = 0.70,
    rotations: list[float] | None = None,
    max_results: int = 150,
) -> list[SymbolCandidate]:
    """Search for symbol candidates on a vector/raster PDF drawing using high-resolution rendering."""
    if pdfium is None:
        raise RuntimeError("PDF 렌더링 라이브러리(pypdfium2)가 설치되어 있지 않습니다.")

    doc = pdfium.PdfDocument(pdf_bytes)
    total_pages = len(doc)
    pages_to_search = list(range(total_pages)) if search_all_pages else [min(page_index, total_pages - 1)]

    render_scale = 2.0  # 144 DPI equivalent for crisp vector lines
    src_page = doc[page_index]
    _src_pt_w, _src_pt_h = src_page.get_size()

    # Sample bbox in points
    x1, y1, x2, y2 = sample_bbox
    pt_xmin = min(x1, x2)
    pt_ymin = min(y1, y2)
    pt_xmax = max(x1, x2)
    pt_ymax = max(y1, y2)

    # Render source page to extract template
    src_pil = src_page.render(scale=render_scale).to_pil()
    src_arr = cv2.cvtColor(np.array(src_pil), cv2.COLOR_RGB2BGR)
    sh_px, sw_px = src_arr.shape[:2]

    px_xmin = max(0, min(sw_px - 1, math.floor(pt_xmin * render_scale)))
    px_ymin = max(0, min(sh_px - 1, math.floor(pt_ymin * render_scale)))
    px_xmax = max(0, min(sw_px, math.ceil(pt_xmax * render_scale)))
    px_ymax = max(0, min(sh_px, math.ceil(pt_ymax * render_scale)))

    bw = px_xmax - px_xmin
    bh = px_ymax - px_ymin
    if bw < 4 or bh < 4:
        raise ValueError(f"선택한 PDF 기호 샘플 영역이 너무 작습니다 (폭: {bw}px, 높이: {bh}px, 최소 4px 필요)")

    template = src_arr[px_ymin:px_ymax, px_xmin:px_xmax]

    candidates: list[SymbolCandidate] = []

    for p_idx in pages_to_search:
        page = doc[p_idx]
        _pt_w, _pt_h = page.get_size()
        pil_img = page.render(scale=render_scale).to_pil()
        arr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        matches = match_template_multi_rotation(
            target_img=arr,
            template_patch=template,
            threshold=threshold,
            rotations=rotations,
            max_results=max_results,
        )

        for m in matches:
            b_px = m["bbox"]
            cx_px, cy_px = m["center"]
            score = float(m["score"])
            rot = float(m["rotation"])

            # Map pixel bbox back to canonical PDF points
            cand_bbox = [
                round(b_px[0] / render_scale, 2),
                round(b_px[1] / render_scale, 2),
                round(b_px[2] / render_scale, 2),
                round(b_px[3] / render_scale, 2),
            ]
            cx_pt = round(cx_px / render_scale, 2)
            cy_pt = round(cy_px / render_scale, 2)

            cand = SymbolCandidate(
                candidate_id=f"cand_vis_pdf_p{p_idx}_{drawing_id}_{round(cx_pt)}_{round(cy_pt)}",
                drawing_id=drawing_id,
                page_index=p_idx,
                coordinate_space="PDF_PAGE_POINT",
                x=cx_pt,
                y=cy_pt,
                bbox=cand_bbox,
                suggested_item_code=suggested_item_code,
                suggested_item_name=suggested_item_name,
                confidence=round(score, 3),
                detection_source=DetectionSource.VISUAL_TEMPLATE.value,
                status=CandidateStatus.PROPOSED,
                raw_evidence={
                    "method": "VISUAL_TEMPLATE",
                    "similarity_score": round(score, 3),
                    "rotation_deg": rot,
                    "template_bbox": [round(pt_xmin, 2), round(pt_ymin, 2), round(pt_xmax, 2), round(pt_ymax, 2)],
                    "page_index": p_idx,
                },
            )
            candidates.append(cand)

    return candidates


def search_visual_symbols_dxf(
    drawing: Any,
    drawing_id: str,
    sample_bbox: list[float],
    suggested_item_code: str = "LIGHT",
    suggested_item_name: str = "조명기구",
    max_results: int = 150,
) -> list[SymbolCandidate]:
    """Search for symbol candidates on a DXF drawing by geometric block structure matching."""
    x1, y1, x2, y2 = sample_bbox
    xmin, xmax = min(x1, x2), max(x1, x2)
    ymin, ymax = min(y1, y2), max(y1, y2)

    objects = getattr(drawing, "objects", []) or []
    insert_objs = [o for o in objects if getattr(o, "entity_type", "") == "INSERT"]
    parent_ids = {o.parent_id for o in insert_objs if getattr(o, "parent_id", None) is not None}

    # 1. Find overlapping blocks in the sample bbox
    matched_block_names: set[str] = set()
    for o in insert_objs:
        pt = getattr(o, "insert_point", None)
        if pt:
            ox, oy = float(pt[0]), float(pt[1])
            if xmin <= ox <= xmax and ymin <= oy <= ymax:
                bname = getattr(o, "block_name", "")
                if bname:
                    matched_block_names.add(bname)

    candidates: list[SymbolCandidate] = []
    if matched_block_names:
        for idx, o in enumerate(insert_objs):
            bname = getattr(o, "block_name", "")
            if bname in matched_block_names:
                obj_id = str(getattr(o, "id", f"ins_{idx}"))
                struct_reason = get_dxf_structural_block_reason(o, parent_ids)
                is_blocked = struct_reason is not None

                pt = getattr(o, "insert_point", None)
                ox = float(pt[0]) if pt else 0.0
                oy = float(pt[1]) if pt else 0.0

                item_label = (
                    f"{suggested_item_name} (검수불가: {struct_reason})"
                    if is_blocked
                    else suggested_item_name
                )

                cand = SymbolCandidate(
                    candidate_id=f"cand_vis_dxf_{drawing_id}_{obj_id}",
                    drawing_id=drawing_id,
                    page_index=0,
                    coordinate_space="WORLD",
                    x=round(ox, 2),
                    y=round(oy, 2),
                    bbox=[round(ox - 15.0, 2), round(oy - 15.0, 2), round(ox + 15.0, 2), round(oy + 15.0, 2)],
                    suggested_item_code=suggested_item_code,
                    suggested_item_name=item_label,
                    confidence=0.0 if is_blocked else 0.95,
                    detection_source=DetectionSource.VISUAL_TEMPLATE.value,
                    status=CandidateStatus.PROPOSED,
                    raw_evidence={
                        "source_object_id": obj_id,
                        "block_name": bname,
                        "layer": getattr(o, "layer", "") or "",
                        "is_structurally_blocked": is_blocked,
                        "structural_block_reason": struct_reason,
                        "method": "DXF_BLOCK_GEOMETRY",
                        "sample_bbox": [round(xmin, 2), round(ymin, 2), round(xmax, 2), round(ymax, 2)],
                    },
                )
                candidates.append(cand)
    return candidates[:max_results]


def search_visual_symbols(
    drawing: Any,
    raw_bytes: bytes,
    drawing_id: str,
    source_type: str,
    sample_bbox: list[float],
    page_index: int = 0,
    search_all_pages: bool = False,
    page_count: int = 1,
    suggested_item_code: str = "LIGHT",
    suggested_item_name: str = "조명기구",
    threshold: float = 0.70,
    rotations: list[float] | None = None,
    max_results: int = 150,
) -> list[SymbolCandidate]:
    """Unified visual symbol template matching dispatcher across IMAGE, PDF, and DXF."""
    norm_source = (source_type or "").upper()
    if norm_source == "IMAGE":
        return search_visual_symbols_image(
            image_bytes=raw_bytes,
            drawing_id=drawing_id,
            sample_bbox=sample_bbox,
            suggested_item_code=suggested_item_code,
            suggested_item_name=suggested_item_name,
            threshold=threshold,
            rotations=rotations,
            max_results=max_results,
        )
    elif norm_source == "PDF":
        return search_visual_symbols_pdf(
            pdf_bytes=raw_bytes,
            drawing_id=drawing_id,
            sample_bbox=sample_bbox,
            page_index=page_index,
            search_all_pages=search_all_pages,
            page_count=page_count,
            suggested_item_code=suggested_item_code,
            suggested_item_name=suggested_item_name,
            threshold=threshold,
            rotations=rotations,
            max_results=max_results,
        )
    elif norm_source == "DXF":
        return search_visual_symbols_dxf(
            drawing=drawing,
            drawing_id=drawing_id,
            sample_bbox=sample_bbox,
            suggested_item_code=suggested_item_code,
            suggested_item_name=suggested_item_name,
            max_results=max_results,
        )
    else:
        return []
