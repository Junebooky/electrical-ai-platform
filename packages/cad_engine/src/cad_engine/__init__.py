"""Deterministic DXF parsing engine for the Electrical AI Platform.

Public entry point::

    from cad_engine import parse_dxf
    drawing = parse_dxf(data, filename="plan.dxf")
"""

from __future__ import annotations

from .loader import DEFAULT_MAX_FILE_BYTES, DxfLoadError, LoadErrorCode, load_dxf_bytes
from .normalize import Limits, normalize
from .schema import SCHEMA_VERSION, NormalizedDrawing

__all__ = [
    "DEFAULT_MAX_FILE_BYTES",
    "SCHEMA_VERSION",
    "DxfLoadError",
    "Limits",
    "LoadErrorCode",
    "NormalizedDrawing",
    "parse_dxf",
]


def parse_dxf(
    data: bytes,
    *,
    filename: str,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    limits: Limits | None = None,
) -> NormalizedDrawing:
    """Validate, load and normalize DXF bytes. Raises :class:`DxfLoadError`."""
    from .loader import validate_filename

    validate_filename(filename)
    loaded = load_dxf_bytes(data, max_bytes=max_bytes)
    return normalize(loaded, filename=filename, data=data, limits=limits)
