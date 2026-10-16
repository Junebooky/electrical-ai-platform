"""Evaluation engine for symbol detection accuracy (Issue #29 Workstream A).

Computes Precision, Recall, and F1-score against ground-truth labels.
Avoids exaggerated claims; provides honest, reproducible metrics across DXF, PDF, and Image fixtures.
"""

from __future__ import annotations

import math
from typing import Any

from .models import SymbolCandidate


def compute_iou(box1: list[float], box2: list[float]) -> float:
    """Compute Intersection over Union (IoU) between two [x1, y1, x2, y2] bounding boxes."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h

    area1 = max(0.0, box1[2] - box1[0]) * max(0.0, box1[3] - box1[1])
    area2 = max(0.0, box2[2] - box2[0]) * max(0.0, box2[3] - box2[1])
    union_area = area1 + area2 - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def evaluate_detection(
    ground_truth: list[dict[str, Any]],
    detected: list[SymbolCandidate],
    distance_threshold: float = 35.0,
    iou_threshold: float = 0.25,
) -> dict[str, Any]:
    """Evaluate detector candidates against ground-truth symbols.

    Matches if item_code matches AND (center Euclidean distance <= distance_threshold OR IoU >= iou_threshold).
    """
    matched_gt: set[int] = set()
    matched_det: set[int] = set()

    # Sort detected by confidence descending
    sorted_det = sorted(enumerate(detected), key=lambda x: float(x[1].confidence), reverse=True)

    matches: list[dict[str, Any]] = []

    for det_idx, cand in sorted_det:
        cand_code = cand.suggested_item_code or cand.reviewed_item_code
        cand_x, cand_y = cand.x, cand.y
        cand_page = cand.page_index

        best_gt_idx = -1
        best_dist = 1e9

        for gt_idx, gt in enumerate(ground_truth):
            if gt_idx in matched_gt:
                continue
            if gt.get("page_index", 0) != cand_page:
                continue
            if gt.get("item_code") != cand_code:
                continue

            gt_x, gt_y = gt["x"], gt["y"]
            dist = math.hypot(cand_x - gt_x, cand_y - gt_y)
            iou = compute_iou(cand.bbox, gt.get("bbox", [gt_x - 15, gt_y - 15, gt_x + 15, gt_y + 15]))

            if (dist <= distance_threshold or iou >= iou_threshold) and dist < best_dist:
                best_dist = dist
                best_gt_idx = gt_idx

        if best_gt_idx >= 0:
            matched_gt.add(best_gt_idx)
            matched_det.add(det_idx)
            matches.append({
                "candidate_id": cand.candidate_id,
                "item_code": cand_code,
                "distance": round(best_dist, 2),
            })

    tp = len(matched_gt)
    fp = len(detected) - tp
    fn = len(ground_truth) - tp

    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0

    # Per-item breakdown
    all_codes: set[str] = {str(gt["item_code"]) for gt in ground_truth} | {
        str(c.suggested_item_code or c.reviewed_item_code)
        for c in detected
        if (c.suggested_item_code or c.reviewed_item_code)
    }
    per_item: dict[str, dict[str, Any]] = {}
    for code in sorted(all_codes):
        gt_code_count = sum(1 for gt in ground_truth if gt.get("item_code") == code)
        det_code_count = sum(1 for c in detected if (c.suggested_item_code or c.reviewed_item_code) == code)
        item_tp = sum(1 for m in matches if m["item_code"] == code)
        item_fp = det_code_count - item_tp
        item_fn = gt_code_count - item_tp
        item_p = round(item_tp / (item_tp + item_fp), 4) if (item_tp + item_fp) > 0 else 0.0
        item_r = round(item_tp / (item_tp + item_fn), 4) if (item_tp + item_fn) > 0 else 0.0
        item_f1 = round(2 * item_p * item_r / (item_p + item_r), 4) if (item_p + item_r) > 0 else 0.0
        per_item[code] = {
            "ground_truth": gt_code_count,
            "detected": det_code_count,
            "tp": item_tp,
            "fp": item_fp,
            "fn": item_fn,
            "precision": item_p,
            "recall": item_r,
            "f1": item_f1,
        }

    return {
        "total_ground_truth": len(ground_truth),
        "total_detected": len(detected),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "per_item_breakdown": per_item,
    }
