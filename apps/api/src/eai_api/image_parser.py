"""Image drawing parser and inspector for Electrical AI Platform (Issue #12 / PR A).

Provides zero-dependency format inspection (PNG and JPG/JPEG) using Python stdlib struct,
hashlib, and deterministic schema normalization for raster 2D electrical drawings.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

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
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MiB (FR-002, QA-DEF-02)
MAX_IMAGE_DIMENSION = 10000  # 10,000 px max per axis
MAX_IMAGE_PIXELS = 40_000_000  # 40 MP max total pixels (decompression defense)


@dataclass(frozen=True)
class ImageMetadata:
    filename: str
    file_type: str  # "PNG" | "JPG"
    width: int
    height: int
    size_bytes: int
    sha256: str


def inspect_image(content: bytes, filename: str) -> ImageMetadata:
    """Validate image format, integrity, decode safety, dimensions, and size.

    Uses Pillow for full decompression verification, CRC validation, and memory bounds defense.
    Raises ValueError on invalid, corrupted, out-of-bound, or rotated images.
    """
    size_bytes = len(content)
    if size_bytes == 0:
        raise ValueError("업로드된 이미지 파일이 비어 있습니다 (0 바이트).")
    if size_bytes > MAX_IMAGE_BYTES:
        raise ValueError(
            f"파일 크기({size_bytes // (1024 * 1024)} MiB)가 허용 한도({MAX_IMAGE_BYTES // (1024 * 1024)} MiB)를 초과했습니다."
        )

    # Magic byte pre-filter
    is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = content.startswith(b"\xff\xd8\xff")
    if not (is_png or is_jpeg):
        raise ValueError(
            "지원하지 않거나 손상된 이미지 파일입니다. PNG 또는 JPG/JPEG 2D 도면 파일만 업로드할 수 있습니다."
        )

    file_type = "PNG" if is_png else "JPG"
    sha256 = hashlib.sha256(content).hexdigest()

    # Configure Pillow memory bomb threshold
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

    try:
        with Image.open(io.BytesIO(content)) as img:
            # 1. Format check
            if file_type == "PNG" and img.format != "PNG":
                raise ValueError(f"PNG 헤더와 실제 이미지 형식({img.format})이 일치하지 않습니다.")
            if file_type == "JPG" and img.format != "JPEG":
                raise ValueError(f"JPEG 헤더와 실제 이미지 형식({img.format})이 일치하지 않습니다.")

            # 2. Dimensions check
            width, height = img.size
            if width <= 0 or height <= 0:
                raise ValueError(f"유효하지 않은 이미지 해상도({width}x{height})입니다.")
            if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                raise ValueError(
                    f"이미지 해상도({width}x{height})가 단일 축 최대 한도({MAX_IMAGE_DIMENSION}px)를 초과했습니다."
                )
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"이미지 총 픽셀 수({width * height:,}px)가 디코딩 한도({MAX_IMAGE_PIXELS:,}px)를 초과했습니다."
                )

            # 3. EXIF orientation check (Orientation != 1 means rotated/mirrored)
            try:
                exif = img.getexif()
                orientation = exif.get(0x0112)
                if orientation is not None and orientation != 1:
                    raise ValueError(
                        f"EXIF 회전 메타데이터(Orientation: {orientation})가 감지되었습니다. "
                        "2D 도면 픽셀 좌표(IMAGE_PIXEL) 정합성을 위해 올바른 방향(0도)으로 회전 저장된 PNG/JPEG 이미지를 업로드해 주세요."
                    )
            except Exception as e:
                if isinstance(e, ValueError):
                    raise
                # Non-fatal if EXIF parsing fails on non-EXIF images

            # 4. Full decode of raster scanlines to catch truncated IDAT, corrupted CRC, broken JPEG SOS
            img.load()

    except Image.DecompressionBombError:
        raise ValueError(
            f"압축 해제 시 메모리 한도를 초과하는 과대 이미지입니다 (최대 {MAX_IMAGE_PIXELS:,} 픽셀)."
        ) from None
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise ValueError(f"손상되었거나 읽을 수 없는 이미지 파일입니다: {e}") from e

    return ImageMetadata(
        filename=filename,
        file_type=file_type,
        width=width,
        height=height,
        size_bytes=size_bytes,
        sha256=sha256,
    )


def build_image_drawing(meta: ImageMetadata, drawing_id: str) -> NormalizedDrawing:
    """Build a deterministic NormalizedDrawing container for an image drawing.

    In PR A:
    - coordinate_space is IMAGE_PIXEL: (0, 0) is top-left, extents are (0, 0) to (width, height)
    - CAD objects and primitives are empty
    - Warnings inform user that manual EA marker mode is active and scale is not calibrated (FR-015/FR-018)
    """
    return NormalizedDrawing(
        schema_version=SCHEMA_VERSION,
        drawing_id=drawing_id,
        source=SourceInfo(
            filename=meta.filename,
            sha256=meta.sha256,
            size_bytes=meta.size_bytes,
        ),
        dxf=DxfInfo(
            version="IMAGE-1.0",
            release=meta.file_type,
            encoding="binary",
            insunits=0,
            units_name="PIXEL",
            units_defined=False,
            measurement=None,
        ),
        extents=BBox(
            min=(0.0, 0.0),
            max=(float(meta.width), float(meta.height)),
        ),
        layers=[
            LayerInfo(
                name="IMAGE",
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
                    f"2D 이미지 도면({meta.file_type}, {meta.width}x{meta.height}px): "
                    "픽셀 좌표계(IMAGE_PIXEL) 기준 사용자 수동 기구 마커(EA)를 등록하여 적산합니다. "
                    "자동 기호 인식은 지원되지 않으며(FR-016), 축척 미정의 상태에서는 실제 선 길이(M) 산출이 불가합니다(FR-018)."
                ),
                object_ids=[],
                details={"file_type": meta.file_type, "width": meta.width, "height": meta.height},
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
            parse_ms=0.5,
        ),
        source_type="IMAGE",
        file_type=meta.file_type,
        coordinate_space="IMAGE_PIXEL",
        dimensions={"width": meta.width, "height": meta.height},
    )
