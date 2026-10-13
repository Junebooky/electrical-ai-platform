"""Safe loading of untrusted DXF bytes.

Responsibilities:
* size / emptiness / file-type checks *before* handing bytes to the parser
* explicit rejection of DWG (PRD DEC-001: P0 supports DXF only)
* tolerant parsing via ``ezdxf.recover`` with structured, user-facing errors

This module never touches the filesystem; callers pass bytes. That keeps path
traversal out of the parsing layer entirely.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import ezdxf
from ezdxf import recover

DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MiB; revisit after A02-T002 measurements

_DWG_MAGIC_PREFIX = b"AC10"
_BINARY_DXF_SENTINEL = b"AutoCAD Binary DXF\r\n\x1a\x00"


class LoadErrorCode(StrEnum):
    EMPTY_FILE = "EMPTY_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_EXTENSION = "INVALID_EXTENSION"
    DWG_NOT_SUPPORTED = "DWG_NOT_SUPPORTED"
    NOT_A_DXF = "NOT_A_DXF"
    DXF_STRUCTURE_ERROR = "DXF_STRUCTURE_ERROR"
    TRUNCATED_FILE = "TRUNCATED_FILE"


_MESSAGES: dict[LoadErrorCode, str] = {
    LoadErrorCode.EMPTY_FILE: "빈 파일입니다.",
    LoadErrorCode.FILE_TOO_LARGE: "파일 용량이 허용 한도를 초과했습니다.",
    LoadErrorCode.INVALID_EXTENSION: "DXF(.dxf) 파일만 업로드할 수 있습니다.",
    LoadErrorCode.DWG_NOT_SUPPORTED: (
        "DWG 파일은 현재 지원하지 않습니다. 사용 중인 CAD 프로그램에서 DXF로 저장한 뒤 "
        "업로드해 주세요."
    ),
    LoadErrorCode.NOT_A_DXF: "DXF 형식으로 인식할 수 없는 파일입니다.",
    LoadErrorCode.DXF_STRUCTURE_ERROR: "DXF 구조가 손상되어 읽을 수 없습니다.",
    LoadErrorCode.TRUNCATED_FILE: (
        "파일 끝(EOF)이 없어 전송 중 잘렸거나 손상된 파일로 보입니다. 원본을 다시 저장해 업로드해 주세요."
    ),
}


class DxfLoadError(Exception):
    """Raised for any file that must not proceed to normalization."""

    def __init__(self, code: LoadErrorCode, detail: str | None = None) -> None:
        self.code = code
        self.message = _MESSAGES[code]
        self.detail = detail
        super().__init__(f"{code}: {self.message}" + (f" ({detail})" if detail else ""))


@dataclass(frozen=True, slots=True)
class LoadedDxf:
    doc: Any  # ezdxf.document.Drawing (ezdxf ships no stable public typing for it)
    audit_fixes: int
    audit_errors: int


def validate_filename(filename: str) -> None:
    if not filename.lower().endswith(".dxf"):
        if filename.lower().endswith(".dwg"):
            raise DxfLoadError(LoadErrorCode.DWG_NOT_SUPPORTED)
        raise DxfLoadError(LoadErrorCode.INVALID_EXTENSION)


def sniff(data: bytes) -> None:
    """Cheap content sniffing; does not trust the file extension."""
    if not data:
        raise DxfLoadError(LoadErrorCode.EMPTY_FILE)
    if data.startswith(_DWG_MAGIC_PREFIX):
        raise DxfLoadError(LoadErrorCode.DWG_NOT_SUPPORTED)
    if data.startswith(_BINARY_DXF_SENTINEL):
        return
    head = data[:4096].lstrip(b"\xef\xbb\xbf")  # tolerate UTF-8 BOM
    # ASCII DXF must start with group code 0 (SECTION) or 999 (comment).
    first = head.lstrip().split(b"\n", 1)[0].strip()
    if first not in (b"0", b"999"):
        raise DxfLoadError(LoadErrorCode.NOT_A_DXF)
    if b"SECTION" not in head:
        raise DxfLoadError(LoadErrorCode.NOT_A_DXF)
    # Every conforming ASCII DXF ends with group code 0 / "EOF". Without it the
    # tolerant parser would happily return a partial (possibly empty) drawing.
    tail = data[-256:].rstrip(b"\x00\x1a \t\r\n")
    if not tail.endswith(b"EOF"):
        raise DxfLoadError(LoadErrorCode.TRUNCATED_FILE)


def load_dxf_bytes(data: bytes, *, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> LoadedDxf:
    if len(data) > max_bytes:
        raise DxfLoadError(
            LoadErrorCode.FILE_TOO_LARGE, f"{len(data)} bytes > limit {max_bytes} bytes"
        )
    sniff(data)
    try:
        if data.startswith(_BINARY_DXF_SENTINEL):
            # recover.read() handles ASCII only; binary DXF goes through the strict loader.
            doc = ezdxf.read(io.BytesIO(data))  # type: ignore[arg-type]
            return LoadedDxf(doc=doc, audit_fixes=0, audit_errors=0)
        doc, auditor = recover.read(io.BytesIO(data))
    except ezdxf.DXFStructureError as exc:
        raise DxfLoadError(LoadErrorCode.DXF_STRUCTURE_ERROR, str(exc)) from exc
    except (ValueError, UnicodeDecodeError, EOFError, IndexError, KeyError) as exc:
        raise DxfLoadError(LoadErrorCode.DXF_STRUCTURE_ERROR, type(exc).__name__) from exc
    return LoadedDxf(
        doc=doc,
        audit_fixes=len(auditor.fixes),
        audit_errors=len(auditor.errors),
    )
