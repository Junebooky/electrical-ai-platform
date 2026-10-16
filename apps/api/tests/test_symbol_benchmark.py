"""Reproducible Ground-Truth Benchmark Evaluation for Symbol Detection (Issue #29 Workstream A).

Measures Precision, Recall, and F1-score across DXF, PDF, and Image fixtures against verifiable ground truth.
Honest, evidence-based reporting without marketing exaggerations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from cad_engine import parse_dxf
from eai_api.detector import detect_candidates
from eai_api.evaluator import evaluate_detection
from eai_api.image_parser import build_image_drawing, inspect_image
from eai_api.models import ItemMappingRule
from eai_api.pdf_parser import build_pdf_drawing, parse_pdf_document

BENCHMARK_GROUND_TRUTH_PATH = Path("fixtures/benchmark/ground_truth_labels.json")


def load_ground_truth() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(BENCHMARK_GROUND_TRUTH_PATH.read_text(encoding="utf-8")))


def test_symbol_detection_accuracy_benchmark() -> None:
    """Run full ground-truth benchmark evaluation across Image, DXF, and PDF fixtures."""
    gt_data = load_ground_truth()
    fixtures = gt_data["fixtures"]

    results_summary: list[dict[str, Any]] = []

    # 1. Raster Image Benchmark (floorplan_sample.png)
    img_gt = fixtures["floorplan_sample.png"]
    img_bytes = Path("fixtures/images/floorplan_sample.png").read_bytes()
    img_info = inspect_image(img_bytes, filename="floorplan_sample.png")
    img_dwg = build_image_drawing(img_info, "dwg_bm_img")
    detected_img = detect_candidates(img_dwg, img_bytes, "dwg_bm_img", source_type="IMAGE")

    eval_img = evaluate_detection(img_gt["symbols"], detected_img, distance_threshold=25.0, iou_threshold=0.3)
    results_summary.append({
        "fixture": "floorplan_sample.png (IMAGE)",
        "metrics": eval_img,
    })

    # Exact precision on standard electrical color clusters
    assert eval_img["precision"] >= 0.95, f"Image Precision {eval_img['precision']} < 0.95"
    assert eval_img["recall"] >= 0.95, f"Image Recall {eval_img['recall']} < 0.95"
    assert eval_img["f1_score"] >= 0.95, f"Image F1 {eval_img['f1_score']} < 0.95"

    # 2. DXF Vector Benchmark (basic_devices.dxf)
    dxf_gt = fixtures["basic_devices.dxf"]
    dxf_bytes = Path("fixtures/dxf/basic_devices.dxf").read_bytes()
    dxf_dwg = parse_dxf(dxf_bytes, filename="basic_devices.dxf")
    mapping_rules = [
        ItemMappingRule(block_name="LT-DL", item_code="LIGHT", unit="EA"),
        ItemMappingRule(block_name="OT-2P", item_code="OUTLET", unit="EA"),
        ItemMappingRule(block_name="SW-1", item_code="SWITCH", unit="EA"),
    ]
    detected_dxf = detect_candidates(dxf_dwg, dxf_bytes, "dwg_bm_dxf", source_type="DXF", mapping_rules=mapping_rules)

    eval_dxf = evaluate_detection(dxf_gt["symbols"], detected_dxf, distance_threshold=50.0, iou_threshold=0.1)
    results_summary.append({
        "fixture": "basic_devices.dxf (DXF)",
        "metrics": eval_dxf,
    })

    assert eval_dxf["precision"] >= 0.95, f"DXF Precision {eval_dxf['precision']} < 0.95"
    assert eval_dxf["recall"] >= 0.95, f"DXF Recall {eval_dxf['recall']} < 0.95"
    assert eval_dxf["f1_score"] >= 0.95, f"DXF F1 {eval_dxf['f1_score']} < 0.95"

    # 3. Vector PDF Benchmark (pdf_c_vector_features.pdf)
    pdf_gt = fixtures["pdf_c_vector_features.pdf"]
    pdf_bytes = Path("fixtures/pdf/pdf_c_vector_features.pdf").read_bytes()
    doc_info = parse_pdf_document(pdf_bytes)
    pdf_dwg = build_pdf_drawing(doc_info, "dwg_bm_pdf", filename="pdf_c_vector_features.pdf")
    detected_pdf = detect_candidates(pdf_dwg, pdf_bytes, "dwg_bm_pdf", source_type="PDF", page_count=doc_info.page_count)

    eval_pdf = evaluate_detection(pdf_gt["symbols"], detected_pdf, distance_threshold=35.0, iou_threshold=0.2)
    results_summary.append({
        "fixture": "pdf_c_vector_features.pdf (PDF)",
        "metrics": eval_pdf,
    })

    assert eval_pdf["precision"] >= 0.80, f"PDF Precision {eval_pdf['precision']} < 0.80"
    assert eval_pdf["recall"] >= 0.80, f"PDF Recall {eval_pdf['recall']} < 0.80"
    assert eval_pdf["f1_score"] >= 0.80, f"PDF F1 {eval_pdf['f1_score']} < 0.80"

    # Print summary report
    print("\n=======================================================")
    print("  ELECTRICAL SYMBOL DETECTION ACCURACY BENCHMARK REPORT")
    print("=======================================================")
    for item in results_summary:
        m = item["metrics"]
        print(f"\nFixture: {item['fixture']}")
        print(f"  Ground Truth: {m['total_ground_truth']} | Detected: {m['total_detected']} | TP: {m['true_positives']} | FP: {m['false_positives']} | FN: {m['false_negatives']}")
        print(f"  Precision: {m['precision'] * 100:.1f}% | Recall: {m['recall'] * 100:.1f}% | F1-Score: {m['f1_score'] * 100:.1f}%")
        print("  Per-item breakdown:")
        for code, stats in m["per_item_breakdown"].items():
            print(f"    - {code}: GT={stats['ground_truth']} Det={stats['detected']} TP={stats['tp']} FP={stats['fp']} FN={stats['fn']} P={stats['precision']*100:.1f}% R={stats['recall']*100:.1f}%")
    print("=======================================================\n")
