"""PDF parser and raster renderer for the Electrical AI Platform (PR B: Issue #12 / #17)."""

from __future__ import annotations

import hashlib
import io
from dataclasses import asdict, dataclass

import pypdf
import pypdfium2 as pdfium
from cad_engine.schema import (
    SCHEMA_VERSION,
    BBox,
    DrawingWarning,
    DxfInfo,
    LayerInfo,
    NormalizedDrawing,
    ParseStats,
    Severity,
    SourceInfo,
    WarningCode,
)

MAX_PDF_FILE_SIZE = 50 * 1024 * 1024  # 50 MiB
MAX_PDF_PAGES = 100  # P0 DoS prevention limit
DEFAULT_RENDER_DPI = 144  # 144 DPI (scale 2.0x, crystal clear for electrical symbol markers)
MAX_RENDER_AXIS_PX = 10_000  # P0-03: Max 10,000 px on any single axis
MAX_RENDER_TOTAL_PIXELS = 40_000_000  # P0-03: Max 40 MP per page (~160MB raw bitmap budget)


class PdfError(Exception):
    """Base error for PDF parsing."""


class PdfCorruptError(PdfError):
    """Raised when PDF bytes cannot be parsed or are corrupted."""


class PdfEncryptedError(PdfError):
    """Raised when PDF is encrypted or password-protected."""


class PdfPageLimitExceededError(PdfError):
    """Raised when PDF page count exceeds security limit."""


@dataclass
class PdfPageInfo:
    page_index: int
    display_width_pt: float
    display_height_pt: float
    rotation: int
    cropbox: list[float]  # [cx0, cy0, cx1, cy1]
    mediabox: list[float]  # [mx0, my0, mx1, my1]
    rendered_width_px: int | None = None
    rendered_height_px: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class PdfDocumentInfo:
    page_count: int
    pages: list[PdfPageInfo]
    file_size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "page_count": self.page_count,
            "pages": [p.to_dict() for p in self.pages],
            "file_size_bytes": self.file_size_bytes,
            "sha256": self.sha256,
        }


def validate_pdf_bytes(pdf_bytes: bytes) -> None:
    """Validate PDF header and file size."""
    if len(pdf_bytes) > MAX_PDF_FILE_SIZE:
        raise PdfCorruptError(
            f"PDF 파일 용량({len(pdf_bytes) / (1024 * 1024):.1f}MB)이 최대 허용 용량(50MB)을 초과했습니다."
        )
    # PDF magic byte check: %PDF-
    if not pdf_bytes.startswith(b"%PDF-") and b"%PDF-" not in pdf_bytes[:1024]:
        raise PdfCorruptError("유효한 PDF 파일 형식이 아닙니다 (PDF 매직 바이트 누락).")


def parse_pdf_document(pdf_bytes: bytes) -> PdfDocumentInfo:
    """Parse PDF document structure, validate integrity and extract page metadata.

    Licensing note (ADR-001):
    Uses pypdf (BSD-3-Clause) and pypdfium2 (Apache-2.0 / BSD-3-Clause).
    Strictly avoids AGPLv3 (PyMuPDF) and GPLv3 libraries.
    """
    validate_pdf_bytes(pdf_bytes)

    # 1. Inspect using pypdf for encryption and boxes
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            raise PdfEncryptedError("암호화된 PDF 파일은 보안 정책상 지원하지 않습니다. 암호 해제 후 업로드해 주세요.")
        page_count = len(reader.pages)
        if page_count == 0:
            raise PdfCorruptError("PDF 파일에 유효한 페이지가 0개입니다.")
        if page_count > MAX_PDF_PAGES:
            raise PdfPageLimitExceededError(
                f"PDF 페이지 수({page_count}페이지)가 최대 허용 한도({MAX_PDF_PAGES}페이지)를 초과했습니다."
            )
    except (PdfEncryptedError, PdfPageLimitExceededError, PdfCorruptError):
        raise
    except Exception as e:
        raise PdfCorruptError(f"PDF 파일 헤더/구조 분석 실패: {e}") from e

    # 2. Inspect with pypdfium2 for display size and rendering
    try:
        doc = pdfium.PdfDocument(pdf_bytes)
        if len(doc) != page_count:
            # Fallback to pdfium page count if mismatch
            page_count = len(doc)
            if page_count > MAX_PDF_PAGES:
                raise PdfPageLimitExceededError(
                    f"PDF 페이지 수({page_count}페이지)가 최대 허용 한도({MAX_PDF_PAGES}페이지)를 초과했습니다."
                )
    except (PdfEncryptedError, PdfPageLimitExceededError, PdfCorruptError):
        raise
    except pdfium.PdfiumError as e:
        msg = str(e)
        if "password" in msg.lower():
            raise PdfEncryptedError("암호화된 PDF 파일은 지원하지 않습니다.") from e
        raise PdfCorruptError(f"PDFium 엔진 문서 로드 실패: {msg}") from e
    except Exception as e:
        raise PdfCorruptError(f"PDF 파일 디코딩 오류: {e}") from e

    pages_info: list[PdfPageInfo] = []
    scale = DEFAULT_RENDER_DPI / 72.0

    for idx in range(page_count):
        pdfium_page = doc[idx]
        display_w, display_h = pdfium_page.get_size()
        rot = pdfium_page.get_rotation()

        # Fallback mediabox / cropbox from pypdf
        try:
            pypdf_page = reader.pages[idx]
            mb = [
                float(pypdf_page.mediabox.left),
                float(pypdf_page.mediabox.bottom),
                float(pypdf_page.mediabox.right),
                float(pypdf_page.mediabox.top),
            ]
            cb = [
                float(pypdf_page.cropbox.left),
                float(pypdf_page.cropbox.bottom),
                float(pypdf_page.cropbox.right),
                float(pypdf_page.cropbox.top),
            ]
        except Exception:
            mb = [0.0, 0.0, float(display_w), float(display_h)]
            cb = [0.0, 0.0, float(display_w), float(display_h)]

        rendered_w = round(display_w * scale)
        rendered_h = round(display_h * scale)

        # P0-03: Resource/dimension DoS defense (single-axis and total pixel budget)
        if rendered_w > MAX_RENDER_AXIS_PX or rendered_h > MAX_RENDER_AXIS_PX:
            raise PdfCorruptError(
                f"PDF {idx}페이지 렌더링 해상도({rendered_w}x{rendered_h} px)가 단일 축 상한({MAX_RENDER_AXIS_PX} px)을 초과했습니다."
            )
        if rendered_w * rendered_h > MAX_RENDER_TOTAL_PIXELS:
            raise PdfCorruptError(
                f"PDF {idx}페이지 렌더링 총 픽셀 수({rendered_w * rendered_h:,} px)가 최대 안전 허용량({MAX_RENDER_TOTAL_PIXELS:,} px)을 초과했습니다."
            )

        pages_info.append(
            PdfPageInfo(
                page_index=idx,
                display_width_pt=float(display_w),
                display_height_pt=float(display_h),
                rotation=int(rot),
                cropbox=cb,
                mediabox=mb,
                rendered_width_px=rendered_w,
                rendered_height_px=rendered_h,
            )
        )

    file_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    return PdfDocumentInfo(
        page_count=page_count,
        pages=pages_info,
        file_size_bytes=len(pdf_bytes),
        sha256=file_sha256,
    )


def render_pdf_page_image(
    pdf_bytes: bytes,
    page_index: int,
    dpi: int = DEFAULT_RENDER_DPI,
) -> tuple[bytes, int, int]:
    """Render a single PDF page into PNG raster image bytes.

    Memory-safety: Decodes only the requested page on-demand with bounded pixel budget.
    """
    scale = dpi / 72.0
    try:
        doc = pdfium.PdfDocument(pdf_bytes)
    except Exception as e:
        raise PdfCorruptError(f"PDFium 렌더러 로드 실패: {e}") from e

    if page_index < 0 or page_index >= len(doc):
        raise IndexError(f"PDF 페이지 인덱스 {page_index}가 유효 범위 [0, {len(doc)})를 벗어났습니다.")

    page = doc[page_index]
    display_w, display_h = page.get_size()
    rendered_w = round(display_w * scale)
    rendered_h = round(display_h * scale)

    # P0-03: Pre-render dimension and memory allocation budget checks
    if rendered_w > MAX_RENDER_AXIS_PX or rendered_h > MAX_RENDER_AXIS_PX:
        raise PdfCorruptError(
            f"PDF {page_index}페이지 렌더링 해상도({rendered_w}x{rendered_h} px)가 단일 축 상한({MAX_RENDER_AXIS_PX} px)을 초과했습니다."
        )
    if rendered_w * rendered_h > MAX_RENDER_TOTAL_PIXELS:
        raise PdfCorruptError(
            f"PDF {page_index}페이지 렌더링 총 픽셀 수({rendered_w * rendered_h:,} px)가 최대 안전 허용량({MAX_RENDER_TOTAL_PIXELS:,} px)을 초과했습니다."
        )

    pil_image = page.render(scale=scale).to_pil()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), pil_image.width, pil_image.height


def canonical_to_pdf_native(
    x_pt: float,
    y_pt: float,
    cropbox: list[float],
    rotation: int,
) -> tuple[float, float]:
    """Convert display canonical point (x_pt, y_pt) to PDF native point (u_pdf, v_pdf).

    Canonical space: origin (0, 0) is top-left of displayed cropbox, +x right, +y down.
    PDF native space: origin (0, 0) is bottom-left of mediabox, +u right, +v up.
    """
    cx0, cy0, cx1, cy1 = cropbox
    rot = rotation % 360
    if rot == 0:
        return (cx0 + x_pt, cy1 - y_pt)
    elif rot == 90:
        return (cx0 + y_pt, cy0 + x_pt)
    elif rot == 180:
        return (cx1 - x_pt, cy0 + y_pt)
    elif rot == 270:
        return (cx1 - y_pt, cy1 - x_pt)
    return (cx0 + x_pt, cy1 - y_pt)


def pdf_native_to_canonical(
    u_pdf: float,
    v_pdf: float,
    cropbox: list[float],
    rotation: int,
) -> tuple[float, float]:
    """Convert PDF native point (u_pdf, v_pdf) to display canonical point (x_pt, y_pt)."""
    cx0, cy0, cx1, cy1 = cropbox
    rot = rotation % 360
    if rot == 0:
        return (u_pdf - cx0, cy1 - v_pdf)
    elif rot == 90:
        return (v_pdf - cy0, u_pdf - cx0)
    elif rot == 180:
        return (cx1 - u_pdf, v_pdf - cy0)
    elif rot == 270:
        return (cy1 - v_pdf, cx1 - u_pdf)
    return (u_pdf - cx0, cy1 - v_pdf)


def build_pdf_drawing(meta: PdfDocumentInfo, drawing_id: str, filename: str) -> NormalizedDrawing:
    """Build a deterministic NormalizedDrawing container for a PDF drawing.

    In PR B:
    - coordinate_space is PDF_PAGE_POINT: (0, 0) is top-left of displayed cropbox in pt
    - CAD objects and primitives are empty in PR B (vector extraction deferred to PR C)
    - Warnings inform user that manual EA marker mode is active and multi-page navigation is enabled
    """
    first_page = meta.pages[0] if meta.pages else None
    pw = first_page.display_width_pt if first_page else 595.0
    ph = first_page.display_height_pt if first_page else 842.0

    return NormalizedDrawing(
        schema_version=SCHEMA_VERSION,
        drawing_id=drawing_id,
        source=SourceInfo(
            filename=filename,
            sha256=meta.sha256,
            size_bytes=meta.file_size_bytes,
        ),
        dxf=DxfInfo(
            version="PDF-1.7",
            release="PDF",
            encoding="binary",
            insunits=0,
            units_name="POINT",
            units_defined=False,
            measurement=None,
        ),
        extents=BBox(
            min=(0.0, 0.0),
            max=(float(pw), float(ph)),
        ),
        layers=[
            LayerInfo(
                name="PDF",
                color=7,
                is_off=False,
                is_frozen=False,
                is_locked=False,
                object_count=0,
            )
        ],
        blocks=[],
        objects=[],
        primitives=[],
        warnings=[
            DrawingWarning(
                code=WarningCode.UNITS_UNDEFINED,
                severity=Severity.INFO,
                message=(
                    f"PDF 도면({meta.page_count}페이지): "
                    "페이지 좌표계(PDF_PAGE_POINT, 단위 pt) 기준 사용자 수동 기구 마커(EA)를 등록하여 적산합니다. "
                    "기구 위치를 직접 표시해 주세요. 벡터 기호 자동 추출은 PR C에서 지원 예정입니다."
                ),
                object_ids=[],
                details={"page_count": meta.page_count, "display_width_pt": round(pw), "display_height_pt": round(ph)},
            )
        ],
        stats=ParseStats(
            modelspace_entities=0,
            paperspace_entities=0,
            source_objects=0,
            primitives=0,
            primitive_points=0,
            entity_types={},
            unsupported_types={},
            parse_ms=1.0,
        ),
        source_type="PDF",
        file_type="PDF",
        coordinate_space="PDF_PAGE_POINT",
        dimensions={"width": int(pw), "height": int(ph)},
        page_count=meta.page_count,
        pages=[p.to_dict() for p in meta.pages],
    )
