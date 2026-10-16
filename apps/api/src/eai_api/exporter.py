"""CSV and XLSX export engines adhering to PRD §7 contracts and security hardening."""

from __future__ import annotations

import csv
import io

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from .models import TakeoffResult


def sanitize_cell(value: object) -> object:
    """Sanitize cell against CSV/Formula Injection (OWASP).

    If a text cell starts with '=', '+', '-', '@', '\\t', '\\r', or '\\n', or control chars,
    or has leading whitespace followed by these characters, prefix with a single quote
    so spreadsheets treat it strictly as a string literal.
    Numbers (int, float), None, and booleans are preserved without alteration.
    """
    if not isinstance(value, str) or not value:
        return value
    if value.startswith("'"):
        return value
    stripped = value.lstrip()
    if not stripped:
        return value
    if stripped[0] in ("=", "+", "-", "@", "\t", "\r", "\n") or ord(stripped[0]) < 32:
        return f"'{value}"
    return value


def export_csv_summary(result: TakeoffResult) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Header from PRD §7.1 and Issue #7/#9
    writer.writerow([
        "item_code",
        "item_name",
        "specification",
        "unit",
        "quantity",
        "quantity_method",
        "review_status",
        "drawing_id",
        "drawing_name",
        "drawing_revision",
        "exported_at",
        "completeness_status",
        "notes",
    ])
    exported_at_str = result.exported_at.isoformat()
    comp_status = (
        f"잠정 (미해결 {result.unresolved_count}건)"
        if result.is_provisional
        else "확정 (검수 완료)"
    )
    for row in result.summary:
        notes_val = (
            row.notes
            if row.notes
            else (f"잠정 산출표 (미해결 {result.unresolved_count}건 - 도면 범위 미검증)" if result.is_provisional else "")
        )
        writer.writerow([
            sanitize_cell(row.item_code),
            sanitize_cell(row.item_name),
            sanitize_cell(row.specification),
            sanitize_cell(row.unit),
            row.quantity,
            row.quantity_method.value,
            row.review_status.value,
            sanitize_cell(result.drawing_id),
            sanitize_cell(row.drawing_name),
            sanitize_cell(row.drawing_revision),
            sanitize_cell(exported_at_str),
            sanitize_cell(comp_status),
            sanitize_cell(notes_val),
        ])
    return buf.getvalue().encode("utf-8-sig")


def export_csv_evidence(result: TakeoffResult) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Header from PRD §7.2 and Issue #7/#9
    writer.writerow([
        "source_object_id",
        "drawing_id",
        "parent_source_id",
        "block_name",
        "layer_name",
        "entity_type",
        "x",
        "y",
        "mapped_item_code",
        "inclusion_status",
        "review_status",
        "review_reason",
        "drawing_revision",
        "exported_at",
        "page_index",
        "source_type",
        "file_type",
        "coordinate_space",
    ])
    exported_at_str = result.exported_at.isoformat()
    for row in result.evidence:
        writer.writerow([
            sanitize_cell(row.source_object_id),
            sanitize_cell(row.drawing_id),
            sanitize_cell(row.parent_source_id or ""),
            sanitize_cell(row.block_name),
            sanitize_cell(row.layer_name),
            sanitize_cell(row.entity_type),
            round(row.x, 3),
            round(row.y, 3),
            sanitize_cell(row.mapped_item_code),
            row.inclusion_status.value,
            row.review_status.value,
            sanitize_cell(row.review_reason),
            sanitize_cell(result.drawing_revision),
            sanitize_cell(exported_at_str),
            row.page_index if row.page_index is not None else "",
            sanitize_cell(row.source_type or ""),
            sanitize_cell(row.file_type or ""),
            sanitize_cell(row.coordinate_space or ""),
        ])
    return buf.getvalue().encode("utf-8-sig")


def export_xlsx(result: TakeoffResult) -> bytes:
    """Generate Excel workbook with 2 sheets: Takeoff Summary and Takeoff Evidence."""
    wb = openpyxl.Workbook()
    # Sheet 1: Summary
    ws_sum = wb.active
    assert ws_sum is not None
    ws_sum.title = "Takeoff Summary"

    # Styling
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
    data_font = Font(name="맑은 고딕", size=10)
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    summary_headers = [
        "품목코드 (item_code)",
        "품목명 (item_name)",
        "규격 (specification)",
        "단위 (unit)",
        "산출 수량 (quantity)",
        "산출방식 (quantity_method)",
        "검수상태 (review_status)",
        "도면 ID (drawing_id)",
        "도면명 (drawing_name)",
        "REV",
        "내보내기 시각 (exported_at)",
        "산출 상태 (completeness_status)",
        "비고 (notes)",
    ]
    ws_sum.append(summary_headers)
    for col_num in range(1, len(summary_headers) + 1):
        cell = ws_sum.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center

    exported_at_str = result.exported_at.isoformat()
    comp_status = (
        f"잠정 / 검수 진행 중 (미해결 {result.unresolved_count}건)"
        if result.is_provisional
        else "확정 (검수 완료)"
    )

    for r in result.summary:
        notes_val = (
            r.notes
            if r.notes
            else (f"잠정 산출표 (미해결 {result.unresolved_count}건 - 도면 범위 미검증)" if result.is_provisional else "")
        )
        ws_sum.append([
            sanitize_cell(r.item_code),
            sanitize_cell(r.item_name),
            sanitize_cell(r.specification),
            sanitize_cell(r.unit),
            r.quantity,
            r.quantity_method.value,
            r.review_status.value,
            sanitize_cell(result.drawing_id),
            sanitize_cell(r.drawing_name),
            sanitize_cell(r.drawing_revision),
            sanitize_cell(exported_at_str),
            sanitize_cell(comp_status),
            sanitize_cell(notes_val),
        ])
        curr_row = ws_sum.max_row
        for col_num in range(1, len(summary_headers) + 1):
            c = ws_sum.cell(row=curr_row, column=col_num)
            c.font = data_font
            if isinstance(c.value, str) and c.value.startswith("'"):
                c.data_type = "s"
            if col_num in (4, 6, 7, 10, 11, 12):
                c.alignment = align_center
            elif col_num == 5:
                c.alignment = align_right
            else:
                c.alignment = align_left

    # Sheet 2: Evidence
    ws_ev = wb.create_sheet(title="Takeoff Evidence")
    evidence_headers = [
        "객체 ID (source_object_id)",
        "도면 ID (drawing_id)",
        "상위 참조 ID (parent_source_id)",
        "CAD 블록명 (block_name)",
        "레이어명 (layer_name)",
        "객체 유형 (entity_type)",
        "X 좌표",
        "Y 좌표",
        "연결 품목 (mapped_item_code)",
        "포함 여부 (inclusion_status)",
        "검수 상태 (review_status)",
        "검수·산출 사유 (review_reason)",
        "REV",
        "내보내기 시각 (exported_at)",
        "페이지 번호 (page_index)",
        "도면 유형 (source_type)",
        "파일 유형 (file_type)",
        "좌표계 (coordinate_space)",
    ]
    ws_ev.append(evidence_headers)
    for col_num in range(1, len(evidence_headers) + 1):
        cell = ws_ev.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center

    for ev in result.evidence:
        ws_ev.append([
            sanitize_cell(ev.source_object_id),
            sanitize_cell(ev.drawing_id),
            sanitize_cell(ev.parent_source_id or ""),
            sanitize_cell(ev.block_name),
            sanitize_cell(ev.layer_name),
            sanitize_cell(ev.entity_type),
            round(ev.x, 3),
            round(ev.y, 3),
            sanitize_cell(ev.mapped_item_code),
            ev.inclusion_status.value,
            ev.review_status.value,
            sanitize_cell(ev.review_reason),
            sanitize_cell(result.drawing_revision),
            sanitize_cell(exported_at_str),
            ev.page_index if ev.page_index is not None else "",
            sanitize_cell(ev.source_type or ""),
            sanitize_cell(ev.file_type or ""),
            sanitize_cell(ev.coordinate_space or ""),
        ])
        curr_row = ws_ev.max_row
        for col_num in range(1, len(evidence_headers) + 1):
            c = ws_ev.cell(row=curr_row, column=col_num)
            c.font = data_font
            if isinstance(c.value, str) and c.value.startswith("'"):
                c.data_type = "s"
            if col_num in (6, 9, 10, 11, 13, 14, 15, 16, 17, 18):
                c.alignment = align_center
            elif col_num in (7, 8):
                c.alignment = align_right
            else:
                c.alignment = align_left

    # Adjust column widths
    for sheet in (ws_sum, ws_ev):
        for col in sheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            sheet.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Invariant assertion: absolute zero formula cells allowed in exported spreadsheets
    for sheet in (ws_sum, ws_ev):
        for row_cells in sheet.iter_rows():
            for c in row_cells:
                assert c.data_type != "f", f"Formula injection vulnerability at {c.coordinate}: {c.value}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
