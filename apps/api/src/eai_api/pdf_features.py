"""Vector PDF text, line, and path feature extraction module (PR C: Issue #22).

Licensing note (ADR-001):
Uses pypdfium2 (Apache-2.0 / BSD-3-Clause) and pypdf (BSD-3-Clause).
Strictly avoids AGPLv3 (PyMuPDF) and GPLv3 dependencies.
"""

from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from .pdf_parser import PdfCorruptError, pdf_native_to_canonical

MAX_PAGE_TEXTS = 5_000
MAX_PAGE_PATHS = 10_000
MAX_TEXT_LEN = 1_000


@dataclass
class PdfTextFeature:
    source_object_id: str
    text: str
    bbox: list[float]  # [min_x, min_y, max_x, max_y] in canonical display pt
    x: float
    y: float
    page_index: int
    extraction_method: str = "PDF_TEXT"
    confidence: str = "RAW_VECTOR"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PdfPathFeature:
    source_object_id: str
    type: str  # "line", "rect", "path"
    bbox: list[float]  # [min_x, min_y, max_x, max_y] in canonical display pt
    x: float
    y: float
    page_index: int
    extraction_method: str = "PDF_PATH"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PdfPageFeatures:
    drawing_id: str
    page_index: int
    coordinate_space: str
    display_width_pt: float
    display_height_pt: float
    rotation: int
    cropbox: list[float]
    texts: list[PdfTextFeature]
    paths: list[PdfPathFeature]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "drawing_id": self.drawing_id,
            "page_index": self.page_index,
            "coordinate_space": self.coordinate_space,
            "display_width_pt": self.display_width_pt,
            "display_height_pt": self.display_height_pt,
            "rotation": self.rotation,
            "cropbox": self.cropbox,
            "texts": [t.to_dict() for t in self.texts],
            "paths": [p.to_dict() for p in self.paths],
            "warnings": self.warnings,
        }


def extract_pdf_page_features(
    pdf_bytes: bytes,
    page_index: int,
    drawing_id: str,
    cropbox: list[float] | None = None,
    rotation: int | None = None,
) -> PdfPageFeatures:
    """Extract text and basic vector path/line bounding boxes for a single PDF page.

    Coordinates are mapped from native PDF space to canonical display space (PDF_PAGE_POINT).
    Domain invariant: Extracted features are purely evidence references and MUST NOT be
    equated with electrical takeoff quantities (automatic EA = 0).
    """
    try:
        doc = pdfium.PdfDocument(pdf_bytes)
    except Exception as e:
        raise PdfCorruptError(f"PDF 파일 디코딩 오류: {e}") from e

    if page_index < 0 or page_index >= len(doc):
        raise IndexError(f"페이지 인덱스({page_index})가 유효 범위 [0, {len(doc)})를 벗어났습니다.")

    page = doc[page_index]
    display_w, display_h = page.get_size()
    rot = int(page.get_rotation() if rotation is None else rotation)

    if cropbox is not None:
        cb = [float(x) for x in cropbox]
    else:
        try:
            page_cb = page.get_cropbox()
            if page_cb and any(v > 0 for v in page_cb):
                cb = [float(v) for v in page_cb]
            else:
                cb = [0.0, 0.0, float(display_w), float(display_h)]
        except Exception:
            cb = [0.0, 0.0, float(display_w), float(display_h)]

    text_features: list[PdfTextFeature] = []
    path_features: list[PdfPathFeature] = []
    warnings: list[str] = []

    # 1. Extract Text Features
    try:
        tp = page.get_textpage()
        rect_count = tp.count_rects()
        for r_idx in range(min(rect_count, MAX_PAGE_TEXTS)):
            rect = tp.get_rect(r_idx)
            raw_text = tp.get_text_bounded(*rect)
            cleaned = raw_text.strip()
            if not cleaned:
                continue
            if len(cleaned) > MAX_TEXT_LEN:
                cleaned = cleaned[:MAX_TEXT_LEN] + "..."

            left, bottom, right, top = rect
            pts = [
                pdf_native_to_canonical(left, bottom, cb, rot),
                pdf_native_to_canonical(left, top, cb, rot),
                pdf_native_to_canonical(right, bottom, cb, rot),
                pdf_native_to_canonical(right, top, cb, rot),
            ]
            min_x = round(min(p[0] for p in pts), 2)
            max_x = round(max(p[0] for p in pts), 2)
            min_y = round(min(p[1] for p in pts), 2)
            max_y = round(max(p[1] for p in pts), 2)

            text_features.append(
                PdfTextFeature(
                    source_object_id=f"txt_p{page_index}_{len(text_features)}",
                    text=cleaned,
                    bbox=[min_x, min_y, max_x, max_y],
                    x=min_x,
                    y=min_y,
                    page_index=page_index,
                    extraction_method="PDF_TEXT",
                    confidence="RAW_VECTOR",
                )
            )

        if rect_count > MAX_PAGE_TEXTS:
            warnings.append(
                f"텍스트 추출 건수({rect_count}건)가 안전 상한({MAX_PAGE_TEXTS}건)을 초과하여 일부 항목이 생략되었습니다."
            )
    except Exception as e:
        warnings.append(f"텍스트 추출 중 오류가 발생했습니다: {e}")

    # 2. Extract Vector Line/Path/Rect Features
    try:
        objs = list(page.get_objects())
        for obj in objs:
            if len(path_features) >= MAX_PAGE_PATHS:
                warnings.append(
                    f"경로/도형 추출 건수({len(objs)}건)가 안전 상한({MAX_PAGE_PATHS}건)을 초과하여 일부 항목이 생략되었습니다."
                )
                break

            if obj.type == pdfium_c.FPDF_PAGEOBJ_PATH:
                left, bottom, right, top = obj.get_bounds()
                pts = [
                    pdf_native_to_canonical(left, bottom, cb, rot),
                    pdf_native_to_canonical(left, top, cb, rot),
                    pdf_native_to_canonical(right, bottom, cb, rot),
                    pdf_native_to_canonical(right, top, cb, rot),
                ]
                min_x = round(min(p[0] for p in pts), 2)
                max_x = round(max(p[0] for p in pts), 2)
                min_y = round(min(p[1] for p in pts), 2)
                max_y = round(max(p[1] for p in pts), 2)

                seg_count = 0
                with contextlib.suppress(Exception):
                    seg_count = pdfium_c.FPDFPath_CountSegments(obj.raw)

                w = max_x - min_x
                h = max_y - min_y
                if seg_count <= 3 or w <= 0.5 or h <= 0.5:
                    path_type = "line"
                elif seg_count == 5:
                    path_type = "rect"
                else:
                    path_type = "path"

                path_features.append(
                    PdfPathFeature(
                        source_object_id=f"path_p{page_index}_{len(path_features)}",
                        type=path_type,
                        bbox=[min_x, min_y, max_x, max_y],
                        x=min_x,
                        y=min_y,
                        page_index=page_index,
                        extraction_method="PDF_PATH",
                    )
                )
    except Exception as e:
        warnings.append(f"경로/도형 추출 중 오류가 발생했습니다: {e}")

    return PdfPageFeatures(
        drawing_id=drawing_id,
        page_index=page_index,
        coordinate_space="PDF_PAGE_POINT",
        display_width_pt=float(display_w),
        display_height_pt=float(display_h),
        rotation=rot,
        cropbox=cb,
        texts=text_features,
        paths=path_features,
        warnings=warnings,
    )
