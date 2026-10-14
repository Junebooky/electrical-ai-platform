"""Image drawing parser and inspector for Electrical AI Platform (Issue #12 / PR A).

Provides zero-dependency format inspection (PNG and JPG/JPEG) using Python stdlib struct,
hashlib, and deterministic schema normalization for raster 2D electrical drawings.
"""

from __future__ import annotations

import hashlib
import struct
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

MAX_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MiB
MAX_IMAGE_DIMENSION = 16384  # 16K max width/height defense


@dataclass(frozen=True)
class ImageMetadata:
    filename: str
    file_type: str  # "PNG" | "JPG"
    width: int
    height: int
    size_bytes: int
    sha256: str


def inspect_image(content: bytes, filename: str) -> ImageMetadata:
    """Validate image format, magic bytes, dimensions, and size.

    Raises ValueError on invalid or corrupted formats.
    """
    size_bytes = len(content)
    if size_bytes == 0:
        raise ValueError("업로드된 이미지 파일이 비어 있습니다 (0 바이트).")
    if size_bytes > MAX_IMAGE_BYTES:
        raise ValueError(f"파일 크기({size_bytes // (1024 * 1024)} MiB)가 허용 한도(50 MiB)를 초과했습니다.")

    sha256 = hashlib.sha256(content).hexdigest()

    # 1. PNG Check
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(content) < 24:
            raise ValueError("손상된 PNG 파일입니다: IHDR 청크가 너무 짧습니다.")
        # IHDR chunk data begins at index 16: width (4B), height (4B)
        width, height = struct.unpack(">II", content[16:24])
        if width <= 0 or height <= 0:
            raise ValueError(f"유효하지 않은 PNG 해상도({width}x{height})입니다.")
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            raise ValueError(f"이미지 해상도({width}x{height})가 최대 한도({MAX_IMAGE_DIMENSION}px)를 초과했습니다.")
        return ImageMetadata(
            filename=filename,
            file_type="PNG",
            width=width,
            height=height,
            size_bytes=size_bytes,
            sha256=sha256,
        )

    # 2. JPEG Check
    if content.startswith(b"\xff\xd8\xff"):
        width, height = _parse_jpeg_dimensions(content)
        if width <= 0 or height <= 0:
            raise ValueError(f"유효하지 않은 JPEG 해상도({width}x{height})입니다.")
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            raise ValueError(f"이미지 해상도({width}x{height})가 최대 한도({MAX_IMAGE_DIMENSION}px)를 초과했습니다.")
        return ImageMetadata(
            filename=filename,
            file_type="JPG",
            width=width,
            height=height,
            size_bytes=size_bytes,
            sha256=sha256,
        )

    raise ValueError(
        "지원하지 않거나 손상된 이미지 파일입니다. PNG 또는 JPG/JPEG 2D 도면 파일만 업로드할 수 있습니다."
    )


def _parse_jpeg_dimensions(content: bytes) -> tuple[int, int]:
    """Parse SOF0/SOF2 marker in JPEG binary to extract width and height."""
    offset = 2
    length = len(content)
    while offset < length:
        if content[offset] != 0xFF:
            offset += 1
            continue

        while offset < length and content[offset] == 0xFF:
            offset += 1
        if offset >= length:
            break

        marker = content[offset]
        offset += 1

        # Standalone markers without length
        if marker in (0xD8, 0xD9, 0x00) or (0xD0 <= marker <= 0xD7):
            continue

        if offset + 2 > length:
            break
        marker_len = struct.unpack(">H", content[offset : offset + 2])[0]
        if marker_len < 2:
            break

        # SOF0 (Baseline), SOF1 (Extended), SOF2 (Progressive), SOF3 (Lossless)
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF) and offset + 7 <= length:
            # payload: precision (1B), height (2B), width (2B)
            h, w = struct.unpack(">HH", content[offset + 3 : offset + 7])
            return w, h

        offset += marker_len

    raise ValueError("JPEG 프레임 헤더(SOF)를 찾을 수 없어 해상도를 읽지 못했습니다.")


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
