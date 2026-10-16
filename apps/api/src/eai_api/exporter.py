"""CSV and XLSX export engines adhering to PRD §7 contracts and security hardening."""

from __future__ import annotations

import csv
import io

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from .models import (
    ManualMeasuredRoute,
    ProjectTakeoffResult,
    RevisionComparisonResult,
    TakeoffResult,
)


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


def export_xlsx(
    result: TakeoffResult,
    routes: list[ManualMeasuredRoute] | None = None,
) -> bytes:
    """Generate Excel workbook with Takeoff Summary, Takeoff Evidence, and optional Route Measurements."""
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

    sheets_to_process = [ws_sum, ws_ev]
    if routes:
        ws_routes = wb.create_sheet(title="Route Measurements")
        fill_routes = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        route_headers = [
            "순번 (No)",
            "경로 ID (route_id)",
            "페이지 (page_index)",
            "분류 (category)",
            "품목코드 (item_code)",
            "품목명 (item_name)",
            "규격 (spec)",
            "원시 길이 (raw_length)",
            "보정 여부 (is_calibrated)",
            "2D 계획 길이 (length_2d_m)",
            "검수 상태 (status)",
            "검수/메모 (review_note)",
            "좌표계 (coordinate_space)",
            "생성일시 (created_at)",
        ]
        ws_routes.append(route_headers)
        for col_num in range(1, len(route_headers) + 1):
            c = ws_routes.cell(row=1, column=col_num)
            c.fill = fill_routes
            c.font = header_font
            c.alignment = align_center

        for idx, route in enumerate(routes, start=1):
            ws_routes.append([
                idx,
                sanitize_cell(route.id),
                route.page_index,
                sanitize_cell(route.category.value if hasattr(route.category, "value") else str(route.category)),
                sanitize_cell(route.item_code),
                sanitize_cell(route.item_name),
                sanitize_cell(route.spec),
                route.raw_length,
                "보정완료" if route.is_calibrated else "미보정",
                route.length_2d_m if route.length_2d_m is not None else 0.0,
                sanitize_cell(route.status.value if hasattr(route.status, "value") else str(route.status)),
                sanitize_cell(route.review_note),
                sanitize_cell(route.coordinate_space),
                sanitize_cell(route.created_at.isoformat()),
            ])
            curr_row = ws_routes.max_row
            for col_idx in range(1, len(route_headers) + 1):
                cell = ws_routes.cell(row=curr_row, column=col_idx)
                cell.font = data_font
                if isinstance(cell.value, str) and cell.value.startswith("'"):
                    cell.data_type = "s"
                if col_idx in (1, 3, 4, 9, 11, 13):
                    cell.alignment = align_center
                elif col_idx in (8, 10):
                    cell.alignment = align_right
                else:
                    cell.alignment = align_left
        sheets_to_process.append(ws_routes)

    # Adjust column widths
    for sheet in sheets_to_process:
        for col in sheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            sheet.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Invariant assertion: absolute zero formula cells allowed in exported spreadsheets
    for sheet in sheets_to_process:
        for row_cells in sheet.iter_rows():
            for c in row_cells:
                assert c.data_type != "f", f"Formula injection vulnerability at {c.coordinate}: {c.value}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Project-Level Consolidated Exporters (Issue #35 Workstream C)
# ---------------------------------------------------------------------------
def export_project_xlsx(
    result: ProjectTakeoffResult,
    revision_deltas: list[RevisionComparisonResult] | None = None,
    active_takeoffs: list[TakeoffResult] | None = None,
    active_routes: list[ManualMeasuredRoute] | None = None,
) -> bytes:
    """Generate comprehensive multi-sheet Excel workbook for project takeoff.

    Sheet 1: Project Summary (프로젝트 총괄 집계표)
    Sheet 2: Drawing Breakdown (도면별 물량 내역)
    Sheet 3: Revision Delta (설계변경 비교 집계)
    Sheet 4: Evidence (산출 근거 상세)
    Sheet 5: Route Measurements (경로 측정 근거 상세, 선택적)
    """
    wb = openpyxl.Workbook()

    # Styling tokens
    header_font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
    data_font = Font(name="맑은 고딕", size=10)
    fill_summary = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    fill_breakdown = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
    fill_delta = PatternFill(start_color="312E81", end_color="312E81", fill_type="solid")
    fill_evidence = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    # -------------------------------------------------- Sheet 1: Project Summary
    ws_sum = wb.active
    assert ws_sum is not None
    ws_sum.title = "Project Summary"

    sum_headers = [
        "순번 (No)",
        "품목코드 (item_code)",
        "품목명 (item_name)",
        "규격 (specification)",
        "단위 (unit)",
        "총 산출 수량 (total_qty)",
        "활성 도면 수 (drawings)",
        "산출 방식 (method)",
        "검수 상태 (review_status)",
        "비고 (notes)",
    ]
    ws_sum.append(sum_headers)
    for col_idx in range(1, len(sum_headers) + 1):
        c = ws_sum.cell(row=1, column=col_idx)
        c.fill = fill_summary
        c.font = header_font
        c.alignment = align_center

    for idx, row in enumerate(result.summary, start=1):
        ws_sum.append([
            idx,
            sanitize_cell(row.item_code),
            sanitize_cell(row.item_name),
            sanitize_cell(row.specification),
            sanitize_cell(row.unit),
            row.total_quantity,
            row.active_drawings_count,
            row.quantity_method.value,
            row.review_status.value,
            sanitize_cell(row.notes),
        ])
        curr_row = ws_sum.max_row
        for col_idx in range(1, len(sum_headers) + 1):
            cell = ws_sum.cell(row=curr_row, column=col_idx)
            cell.font = data_font
            if isinstance(cell.value, str) and cell.value.startswith("'"):
                cell.data_type = "s"
            if col_idx in (1, 5, 7, 8, 9):
                cell.alignment = align_center
            elif col_idx == 6:
                cell.alignment = align_right
            else:
                cell.alignment = align_left

    # ------------------------------------------------ Sheet 2: Drawing Breakdown
    ws_bd = wb.create_sheet(title="Drawing Breakdown")
    bd_headers = [
        "도면 그룹 (sheet_key)",
        "층/구역 (floor/zone)",
        "공종 (discipline)",
        "REV",
        "시트 역할 (sheet_role)",
        "활성 여부 (active)",
        "도면명 (drawing_name)",
        "품목코드 (item_code)",
        "품목명 (item_name)",
        "규격 (specification)",
        "산출 수량 (quantity)",
        "단위 (unit)",
        "검수 상태 (review_status)",
    ]
    ws_bd.append(bd_headers)
    for col_idx in range(1, len(bd_headers) + 1):
        c = ws_bd.cell(row=1, column=col_idx)
        c.fill = fill_breakdown
        c.font = header_font
        c.alignment = align_center

    for dwg in result.drawings_breakdown:
        for itm in dwg.items:
            ws_bd.append([
                sanitize_cell(dwg.sheet_key),
                sanitize_cell(dwg.floor),
                sanitize_cell(dwg.discipline),
                sanitize_cell(dwg.revision),
                sanitize_cell(dwg.sheet_role.value),
                "활성(O)" if dwg.active_for_takeoff else "비활성(X)",
                sanitize_cell(dwg.filename),
                sanitize_cell(itm.item_code),
                sanitize_cell(itm.item_name),
                sanitize_cell(itm.specification),
                itm.quantity,
                sanitize_cell(itm.unit),
                itm.review_status.value,
            ])
            curr_row = ws_bd.max_row
            for col_idx in range(1, len(bd_headers) + 1):
                cell = ws_bd.cell(row=curr_row, column=col_idx)
                cell.font = data_font
                if isinstance(cell.value, str) and cell.value.startswith("'"):
                    cell.data_type = "s"
                if col_idx in (1, 2, 3, 4, 5, 6, 12, 13):
                    cell.alignment = align_center
                elif col_idx == 11:
                    cell.alignment = align_right
                else:
                    cell.alignment = align_left

    # -------------------------------------------------- Sheet 3: Revision Delta
    ws_delta = wb.create_sheet(title="Revision Delta")
    delta_headers = [
        "비교 대상 (comparison)",
        "도면 그룹 (sheet_key)",
        "층 (floor)",
        "공종 (discipline)",
        "품목코드 (item_code)",
        "품목명 (item_name)",
        "규격 (specification)",
        "단위 (unit)",
        "기준 REV 수량 (base_qty)",
        "변경 REV 수량 (compare_qty)",
        "증감 (delta)",
        "변경 유형 (change_type)",
        "검토 의견 (notes)",
    ]
    ws_delta.append(delta_headers)
    for col_idx in range(1, len(delta_headers) + 1):
        c = ws_delta.cell(row=1, column=col_idx)
        c.fill = fill_delta
        c.font = header_font
        c.alignment = align_center

    deltas_list = revision_deltas or []
    for cmp_res in deltas_list:
        base_title = f"{cmp_res.base_drawing.get('sheet_key', '')} ({cmp_res.base_drawing.get('revision', '')})"
        cmp_title = f"{cmp_res.compare_drawing.get('sheet_key', '')} ({cmp_res.compare_drawing.get('revision', '')})"
        pair_str = f"{base_title} vs {cmp_title}"

        for d_item in cmp_res.items_delta:
            ws_delta.append([
                sanitize_cell(pair_str),
                sanitize_cell(cmp_res.compare_drawing.get("sheet_key", "")),
                sanitize_cell(cmp_res.compare_drawing.get("floor", "")),
                sanitize_cell(cmp_res.compare_drawing.get("discipline", "")),
                sanitize_cell(d_item.item_code),
                sanitize_cell(d_item.item_name),
                sanitize_cell(d_item.specification),
                sanitize_cell(d_item.unit),
                d_item.base_quantity,
                d_item.compare_quantity,
                d_item.delta,
                sanitize_cell(d_item.change_type),
                sanitize_cell(d_item.notes),
            ])
            curr_row = ws_delta.max_row
            for col_idx in range(1, len(delta_headers) + 1):
                cell = ws_delta.cell(row=curr_row, column=col_idx)
                cell.font = data_font
                if isinstance(cell.value, str) and cell.value.startswith("'"):
                    cell.data_type = "s"
                if col_idx in (2, 3, 4, 8, 12):
                    cell.alignment = align_center
                elif col_idx in (9, 10, 11):
                    cell.alignment = align_right
                else:
                    cell.alignment = align_left

    # ------------------------------------------------------- Sheet 4: Evidence
    ws_ev = wb.create_sheet(title="Evidence")
    evidence_headers = [
        "도면 ID (drawing_id)",
        "도면명 (drawing_name)",
        "REV",
        "객체 ID (source_object_id)",
        "CAD 블록명 (block_name)",
        "레이어명 (layer_name)",
        "객체 유형 (entity_type)",
        "X 좌표",
        "Y 좌표",
        "매핑 품목코드 (mapped_item_code)",
        "포함 여부 (inclusion_status)",
        "검수 상태 (review_status)",
        "검수 메모 (review_reason)",
    ]
    ws_ev.append(evidence_headers)
    for col_idx in range(1, len(evidence_headers) + 1):
        c = ws_ev.cell(row=1, column=col_idx)
        c.fill = fill_evidence
        c.font = header_font
        c.alignment = align_center

    takeoffs_list = active_takeoffs or []
    for t_res in takeoffs_list:
        for ev in t_res.evidence:
            ws_ev.append([
                sanitize_cell(t_res.drawing_id),
                sanitize_cell(t_res.drawing_name),
                sanitize_cell(t_res.drawing_revision),
                sanitize_cell(ev.source_object_id),
                sanitize_cell(ev.block_name),
                sanitize_cell(ev.layer_name),
                sanitize_cell(ev.entity_type),
                round(ev.x, 2),
                round(ev.y, 2),
                sanitize_cell(ev.mapped_item_code),
                ev.inclusion_status.value,
                ev.review_status.value,
                sanitize_cell(ev.review_reason),
            ])
            curr_row = ws_ev.max_row
            for col_idx in range(1, len(evidence_headers) + 1):
                cell = ws_ev.cell(row=curr_row, column=col_idx)
                cell.font = data_font
                if isinstance(cell.value, str) and cell.value.startswith("'"):
                    cell.data_type = "s"
                if col_idx in (3, 7, 10, 11, 12):
                    cell.alignment = align_center
                elif col_idx in (8, 9):
                    cell.alignment = align_right
                else:
                    cell.alignment = align_left

    sheets_to_process = [ws_sum, ws_bd, ws_delta, ws_ev]
    if active_routes:
        ws_routes = wb.create_sheet(title="Route Measurements")
        fill_routes = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        route_headers = [
            "순번 (No)",
            "도면 ID (drawing_id)",
            "시트 키 (sheet_key)",
            "리비전 (revision)",
            "페이지 (page_index)",
            "경로 ID (route_id)",
            "분류 (category)",
            "품목코드 (item_code)",
            "품목명 (item_name)",
            "규격 (spec)",
            "원시 길이 (raw_length)",
            "보정 여부 (is_calibrated)",
            "2D 계획 길이 (length_2d_m)",
            "검수 상태 (status)",
            "검수/메모 (review_note)",
            "좌표계 (coordinate_space)",
            "생성일시 (created_at)",
        ]
        ws_routes.append(route_headers)
        for col_idx in range(1, len(route_headers) + 1):
            c = ws_routes.cell(row=1, column=col_idx)
            c.fill = fill_routes
            c.font = header_font
            c.alignment = align_center

        for idx, act_route in enumerate(active_routes, start=1):
            ws_routes.append([
                idx,
                sanitize_cell(act_route.drawing_id),
                sanitize_cell(act_route.sheet_key or ""),
                sanitize_cell(act_route.revision or ""),
                act_route.page_index,
                sanitize_cell(act_route.id),
                sanitize_cell(act_route.category.value if hasattr(act_route.category, "value") else str(act_route.category)),
                sanitize_cell(act_route.item_code),
                sanitize_cell(act_route.item_name),
                sanitize_cell(act_route.spec),
                act_route.raw_length,
                "보정완료" if act_route.is_calibrated else "미보정",
                act_route.length_2d_m if act_route.length_2d_m is not None else 0.0,
                sanitize_cell(act_route.status.value if hasattr(act_route.status, "value") else str(act_route.status)),
                sanitize_cell(act_route.review_note),
                sanitize_cell(act_route.coordinate_space),
                sanitize_cell(act_route.created_at.isoformat()),
            ])
            curr_row = ws_routes.max_row
            for col_idx in range(1, len(route_headers) + 1):
                cell = ws_routes.cell(row=curr_row, column=col_idx)
                cell.font = data_font
                if isinstance(cell.value, str) and cell.value.startswith("'"):
                    cell.data_type = "s"
                if col_idx in (1, 3, 4, 5, 7, 12, 14, 16):
                    cell.alignment = align_center
                elif col_idx in (11, 13):
                    cell.alignment = align_right
                else:
                    cell.alignment = align_left
        sheets_to_process.append(ws_routes)

    # Auto-adjust column widths across all sheets
    for sheet in sheets_to_process:
        for col in sheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            sheet.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Invariant assertion: absolute zero formula cells allowed
    for sheet in sheets_to_process:
        for row_cells in sheet.iter_rows():
            for c in row_cells:
                assert c.data_type != "f", f"Formula injection vulnerability at {c.coordinate}: {c.value}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_project_csv_summary(result: ProjectTakeoffResult) -> bytes:
    """RFC 4180 CSV export for consolidated project summary."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "item_code",
        "item_name",
        "specification",
        "unit",
        "total_quantity",
        "active_drawings_count",
        "quantity_method",
        "review_status",
        "completeness_status",
        "notes",
    ])
    comp_status = "잠정 / 검수 진행 중" if result.is_provisional else "확정 (검수 완료)"
    for r in result.summary:
        writer.writerow([
            sanitize_cell(r.item_code),
            sanitize_cell(r.item_name),
            sanitize_cell(r.specification),
            sanitize_cell(r.unit),
            r.total_quantity,
            r.active_drawings_count,
            r.quantity_method.value,
            r.review_status.value,
            sanitize_cell(comp_status),
            sanitize_cell(r.notes),
        ])
    return buf.getvalue().encode("utf-8-sig")


def export_project_csv_breakdown(result: ProjectTakeoffResult) -> bytes:
    """RFC 4180 CSV export for drawing breakdown."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "sheet_key",
        "floor",
        "discipline",
        "revision",
        "sheet_role",
        "active_for_takeoff",
        "drawing_id",
        "drawing_name",
        "item_code",
        "item_name",
        "specification",
        "quantity",
        "unit",
        "review_status",
    ])
    for dwg in result.drawings_breakdown:
        for itm in dwg.items:
            writer.writerow([
                sanitize_cell(dwg.sheet_key),
                sanitize_cell(dwg.floor),
                sanitize_cell(dwg.discipline),
                sanitize_cell(dwg.revision),
                sanitize_cell(dwg.sheet_role.value),
                "TRUE" if dwg.active_for_takeoff else "FALSE",
                sanitize_cell(dwg.drawing_id),
                sanitize_cell(dwg.filename),
                sanitize_cell(itm.item_code),
                sanitize_cell(itm.item_name),
                sanitize_cell(itm.specification),
                itm.quantity,
                sanitize_cell(itm.unit),
                itm.review_status.value,
            ])
    return buf.getvalue().encode("utf-8-sig")


def export_project_csv_delta(deltas: list[RevisionComparisonResult]) -> bytes:
    """RFC 4180 CSV export for revision comparison delta."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "comparison_pair",
        "sheet_key",
        "floor",
        "discipline",
        "item_code",
        "item_name",
        "specification",
        "unit",
        "base_quantity",
        "compare_quantity",
        "delta",
        "change_type",
        "notes",
    ])
    for cmp_res in deltas:
        pair_str = f"{cmp_res.base_drawing.get('revision', '')} -> {cmp_res.compare_drawing.get('revision', '')}"
        for d_item in cmp_res.items_delta:
            writer.writerow([
                sanitize_cell(pair_str),
                sanitize_cell(cmp_res.compare_drawing.get("sheet_key", "")),
                sanitize_cell(cmp_res.compare_drawing.get("floor", "")),
                sanitize_cell(cmp_res.compare_drawing.get("discipline", "")),
                sanitize_cell(d_item.item_code),
                sanitize_cell(d_item.item_name),
                sanitize_cell(d_item.specification),
                sanitize_cell(d_item.unit),
                d_item.base_quantity,
                d_item.compare_quantity,
                d_item.delta,
                sanitize_cell(d_item.change_type),
                sanitize_cell(d_item.notes),
            ])
    return buf.getvalue().encode("utf-8-sig")

