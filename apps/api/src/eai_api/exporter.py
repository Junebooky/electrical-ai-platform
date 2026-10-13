"""CSV and XLSX export engines adhering to PRD §7 contracts."""

from __future__ import annotations

import csv
import io

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from .models import TakeoffResult


def sanitize_cell(value: object) -> object:
    """Sanitize cell against CSV/Formula Injection (OWASP).

    If a text cell starts with '=', '+', '-', '@', '\\t', or '\\r', prefix with
    a single quote so spreadsheets treat it strictly as a string literal.
    """
    if isinstance(value, str) and value:
        if value[0] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{value}"
    return value


def export_csv_summary(result: TakeoffResult) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Header from PRD §7.1
    writer.writerow([
        "item_code",
        "item_name",
        "specification",
        "unit",
        "quantity",
        "quantity_method",
        "review_status",
        "drawing_name",
        "drawing_revision",
        "notes",
    ])
    for row in result.summary:
        writer.writerow([
            sanitize_cell(row.item_code),
            sanitize_cell(row.item_name),
            sanitize_cell(row.specification),
            sanitize_cell(row.unit),
            row.quantity,
            row.quantity_method.value,
            row.review_status.value,
            sanitize_cell(row.drawing_name),
            sanitize_cell(row.drawing_revision),
            sanitize_cell(row.notes),
        ])
    return buf.getvalue().encode("utf-8-sig")


def export_csv_evidence(result: TakeoffResult) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Header from PRD §7.2
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
    ])
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
        "검수 수량 (quantity)",
        "산출방식 (quantity_method)",
        "검수상태 (review_status)",
        "도면명 (drawing_name)",
        "REV",
        "비고 (notes)",
    ]
    ws_sum.append(summary_headers)
    for col_num in range(1, len(summary_headers) + 1):
        cell = ws_sum.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center

    for r in result.summary:
        ws_sum.append([
            sanitize_cell(r.item_code),
            sanitize_cell(r.item_name),
            sanitize_cell(r.specification),
            sanitize_cell(r.unit),
            r.quantity,
            r.quantity_method.value,
            r.review_status.value,
            sanitize_cell(r.drawing_name),
            sanitize_cell(r.drawing_revision),
            sanitize_cell(r.notes),
        ])
        curr_row = ws_sum.max_row
        for col_num in range(1, len(summary_headers) + 1):
            c = ws_sum.cell(row=curr_row, column=col_num)
            c.font = data_font
            if col_num in (4, 6, 7, 9):
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
        ])
        curr_row = ws_ev.max_row
        for col_num in range(1, len(evidence_headers) + 1):
            c = ws_ev.cell(row=curr_row, column=col_num)
            c.font = data_font
            if col_num in (6, 9, 10, 11):
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

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
