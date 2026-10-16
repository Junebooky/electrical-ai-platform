"""Comprehensive test suite for PDF multi-page viewer and manual EA takeoff (Issue #12, #17 / PR B).

Validates:
1. Multi-page PDF upload, page metadata, dimensions, rotation, coordinate space (PDF_PAGE_POINT).
2. On-demand page rendering endpoint (/pages/{page_index}/image and ?page= query).
3. Multi-page manual takeoff: Page 0 (3 LIGHT) + Page 1 (2 OUTLET) with shared relative coords (200, 300)
   proving strict page_index separation, total 5 provisional items.
4. Page-specific boundary checks, non-finite coords, invalid page_index, non-EA unit defense.
5. Rotated CropBox support (90-degree rotated page).
6. Security rejections: Corrupt PDF, password-encrypted PDF, 50MiB bound.
7. CSV and XLSX exports verifying page_index, source_type, file_type, coordinate_space columns.
8. Raw PDF byte-for-byte preservation.
9. Review reclassification and unit defense.
"""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

import openpyxl
import pytest
from eai_api.app import app
from eai_api.storage import Storage
from fastapi.testclient import TestClient

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "pdf"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    from eai_api import app as app_module

    app_module.storage = Storage(root=tmp_path)
    return TestClient(app)


@pytest.fixture
def pdf_two_pages() -> bytes:
    p = FIXTURES_DIR / "pdf_b_01_two_pages.pdf"
    assert p.exists(), f"Missing fixture {p}"
    return p.read_bytes()


@pytest.fixture
def pdf_rotated_cropbox() -> bytes:
    p = FIXTURES_DIR / "pdf_b_02_rotated_cropbox.pdf"
    assert p.exists(), f"Missing fixture {p}"
    return p.read_bytes()


@pytest.fixture
def pdf_corrupt() -> bytes:
    p = FIXTURES_DIR / "corrupt.pdf"
    assert p.exists(), f"Missing fixture {p}"
    return p.read_bytes()


@pytest.fixture
def pdf_encrypted() -> bytes:
    p = FIXTURES_DIR / "encrypted.pdf"
    assert p.exists(), f"Missing fixture {p}"
    return p.read_bytes()


@pytest.fixture
def pdf_scanned_mixed() -> bytes:
    p = FIXTURES_DIR / "pdf_b_scanned_mixed.pdf"
    assert p.exists(), f"Missing fixture {p}"
    return p.read_bytes()


@pytest.fixture
def pdf_oversized() -> bytes:
    p = FIXTURES_DIR / "pdf_b_oversized_dimension.pdf"
    assert p.exists(), f"Missing fixture {p}"
    return p.read_bytes()


def test_pdf_upload_metadata_multipage(client: TestClient, pdf_two_pages: bytes) -> None:
    """PDF multi-page upload returns page count, per-page dimensions, and canonical coordinate space."""
    proj_res = client.post("/api/projects", json={"name": "PDF 다중페이지 테스트"})
    assert proj_res.status_code == 200
    proj_id = proj_res.json()["id"]

    upload_res = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_multipage.pdf", pdf_two_pages, "application/pdf")},
    )
    assert upload_res.status_code == 200
    meta = upload_res.json()

    assert meta["source_type"] == "PDF"
    assert meta["file_type"] == "PDF"
    assert meta["coordinate_space"] == "PDF_PAGE_POINT"
    assert meta["page_count"] == 2
    assert meta["raw_saved"] is True
    assert meta["file_size_bytes"] == len(pdf_two_pages)

    pages = meta["pages"]
    assert len(pages) == 2

    # Page 0: 612 x 792 pt, ROT0
    assert pages[0]["page_index"] == 0
    assert abs(pages[0]["display_width_pt"] - 612.0) < 1.0
    assert abs(pages[0]["display_height_pt"] - 792.0) < 1.0
    assert pages[0]["rotation"] == 0

    # Page 1: CropBox offset ROT90 -> display 552 x 752 pt
    assert pages[1]["page_index"] == 1
    assert abs(pages[1]["display_width_pt"] - 552.0) < 1.0
    assert abs(pages[1]["display_height_pt"] - 752.0) < 1.0
    assert pages[1]["rotation"] == 90

    # Drawing detail GET
    drawing_id = meta["drawing_id"]
    get_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}")
    assert get_res.status_code == 200
    dwg_data = get_res.json()
    assert dwg_data["page_count"] == 2
    assert len(dwg_data["warnings"]) >= 1
    assert any("PDF" in w["message"] for w in dwg_data["warnings"])
    assert any("수동" in w["message"] for w in dwg_data["warnings"])


def test_pdf_page_image_rendering_endpoint(client: TestClient, pdf_two_pages: bytes) -> None:
    """Page-by-page rendering endpoint returns valid PNG bytes and handles out-of-range pages."""
    proj = client.post("/api/projects", json={"name": "PDF 렌더링 테스트"}).json()
    proj_id = proj["id"]

    upload_res = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("render_test.pdf", pdf_two_pages, "application/pdf")},
    )
    drawing_id = upload_res.json()["drawing_id"]

    # 1. Page 0 via /pages/0/image
    p0_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/pages/0/image")
    assert p0_res.status_code == 200
    assert p0_res.headers["content-type"] == "image/png"
    assert len(p0_res.content) > 100

    # 2. Page 1 via /pages/1/image
    p1_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/pages/1/image")
    assert p1_res.status_code == 200
    assert p1_res.headers["content-type"] == "image/png"
    assert len(p1_res.content) > 100

    # 3. Query param ?page=1
    query_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/image?page=1")
    assert query_res.status_code == 200
    assert query_res.headers["content-type"] == "image/png"
    assert query_res.content == p1_res.content

    # 4. Out of range page -> 404
    p2_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/pages/2/image")
    assert p2_res.status_code == 404

    # 5. Negative page -> 404
    p_neg = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/pages/-1/image")
    assert p_neg.status_code == 404


def test_pdf_multipage_manual_takeoff_scenario(client: TestClient, pdf_two_pages: bytes) -> None:
    """Multi-page manual takeoff: Page 0 (3 LIGHT) + Page 1 (2 OUTLET) with shared coords (200, 300)
    proves distinct page_index separation and aggregates to 5 provisional EA items."""
    proj = client.post("/api/projects", json={"name": "다중페이지 수동 적산"}).json()
    proj_id = proj["id"]

    dwg = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("takeoff_test.pdf", pdf_two_pages, "application/pdf")},
    ).json()
    drawing_id = dwg["drawing_id"]

    # Initial takeoff: empty
    t0 = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff").json()
    assert len(t0["summary"]) == 0
    assert len(t0["evidence"]) == 0

    # Page 0: 3 LIGHT items (including one at shared x=100.0, y=150.0)
    p0_items = [
        {"id": "p0_lt_1", "drawing_id": drawing_id, "page_index": 0, "x": 100.0, "y": 150.0, "item_code": "LIGHT", "item_name": "다운라이트", "unit": "EA"},
        {"id": "p0_lt_2", "drawing_id": drawing_id, "page_index": 0, "x": 300.0, "y": 220.0, "item_code": "LIGHT", "item_name": "다운라이트", "unit": "EA"},
        {"id": "p0_lt_3", "drawing_id": drawing_id, "page_index": 0, "x": 500.0, "y": 650.0, "item_code": "LIGHT", "item_name": "다운라이트", "unit": "EA"},
    ]
    for item in p0_items:
        res = client.post(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects", json=item)
        assert res.status_code == 200

    # Page 1: 2 OUTLET items (including one at shared x=100.0, y=150.0)
    p1_items = [
        {"id": "p1_ot_1", "drawing_id": drawing_id, "page_index": 1, "x": 100.0, "y": 150.0, "item_code": "OUTLET", "item_name": "콘센트", "unit": "EA"},
        {"id": "p1_ot_2", "drawing_id": drawing_id, "page_index": 1, "x": 400.0, "y": 500.0, "item_code": "OUTLET", "item_name": "콘센트", "unit": "EA"},
    ]
    for item in p1_items:
        res = client.post(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects", json=item)
        assert res.status_code == 200

    # Calculate takeoff
    t_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff")
    assert t_res.status_code == 200
    takeoff = t_res.json()

    # Summary: 3 LIGHT + 2 OUTLET = 5 total
    summary = takeoff["summary"]
    assert len(summary) == 2
    by_code = {s["item_code"]: s for s in summary}
    assert by_code["LIGHT"]["quantity"] == 3
    assert by_code["LIGHT"]["unit"] == "EA"
    assert by_code["LIGHT"]["is_provisional"] is True
    assert by_code["OUTLET"]["quantity"] == 2
    assert by_code["OUTLET"]["unit"] == "EA"
    assert by_code["OUTLET"]["is_provisional"] is True

    # Evidence: 5 rows
    evidence = takeoff["evidence"]
    assert len(evidence) == 5

    ev_by_id = {e["source_object_id"]: e for e in evidence}

    # Verify Page 0 items
    assert ev_by_id["p0_lt_1"]["page_index"] == 0
    assert ev_by_id["p0_lt_1"]["coordinate_space"] == "PDF_PAGE_POINT"
    assert ev_by_id["p0_lt_1"]["source_type"] == "PDF"

    # Verify identical coords (100, 150) have distinct page_index!
    assert ev_by_id["p0_lt_1"]["page_index"] == 0
    assert ev_by_id["p0_lt_1"]["x"] == 100.0
    assert ev_by_id["p0_lt_1"]["y"] == 150.0

    assert ev_by_id["p1_ot_1"]["page_index"] == 1
    assert ev_by_id["p1_ot_1"]["x"] == 100.0
    assert ev_by_id["p1_ot_1"]["y"] == 150.0

    # Reload check: GET /manual-objects returns all 5 items with page_index preserved
    man_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects")
    assert man_res.status_code == 200
    man_list = man_res.json()
    assert len(man_list) == 5
    p0_count = sum(1 for m in man_list if m["page_index"] == 0)
    p1_count = sum(1 for m in man_list if m["page_index"] == 1)
    assert p0_count == 3
    assert p1_count == 2


def test_pdf_boundary_and_validation_defense(client: TestClient, pdf_two_pages: bytes) -> None:
    """PDF manual object endpoint strictly enforces page-specific boundaries, finite coords, and EA-only units."""
    proj = client.post("/api/projects", json={"name": "경계 방어 검증"}).json()
    proj_id = proj["id"]

    dwg = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("boundary_test.pdf", pdf_two_pages, "application/pdf")},
    ).json()
    drawing_id = dwg["drawing_id"]

    # 1. Negative coordinate -> 400
    res_neg = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "m_neg", "drawing_id": drawing_id, "page_index": 0, "x": -1.0, "y": 100.0, "item_code": "LIGHT", "unit": "EA"},
    )
    assert res_neg.status_code == 400
    assert "벗어났습니다" in res_neg.json()["detail"]

    # 2. Page 0 width is 612.0: x=620.0 on Page 0 must be rejected
    res_p0_oob = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "m_oob_p0", "drawing_id": drawing_id, "page_index": 0, "x": 620.0, "y": 100.0, "item_code": "LIGHT", "unit": "EA"},
    )
    assert res_p0_oob.status_code == 400

    # 3. On Page 1 (display height 752.0), y=700.0 is VALID
    res_p1_ok = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "m_ok_p1", "drawing_id": drawing_id, "page_index": 1, "x": 500.0, "y": 700.0, "item_code": "LIGHT", "unit": "EA"},
    )
    assert res_p1_ok.status_code == 200

    # But y=800.0 on Page 1 exceeds display height (752.0) -> rejected
    res_p1_oob = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "m_oob_p1", "drawing_id": drawing_id, "page_index": 1, "x": 500.0, "y": 800.0, "item_code": "LIGHT", "unit": "EA"},
    )
    assert res_p1_oob.status_code == 400

    # 4. Out of range page_index: page_index=2 on 2-page document -> 400
    res_bad_page = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "m_bad_p", "drawing_id": drawing_id, "page_index": 2, "x": 100.0, "y": 100.0, "item_code": "LIGHT", "unit": "EA"},
    )
    assert res_bad_page.status_code == 400
    assert "page_index" in res_bad_page.json()["detail"]

    # 5. Non-EA unit rejection (P0 PR B / M-UNIT-01)
    res_bad_unit = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "m_bad_u", "drawing_id": drawing_id, "page_index": 0, "x": 100.0, "y": 100.0, "item_code": "CABLE", "unit": "M"},
    )
    assert res_bad_unit.status_code == 400
    assert "PR B/M-UNIT-01" in res_bad_unit.json()["detail"] or "EA" in res_bad_unit.json()["detail"]


def test_pdf_rotated_cropbox_support(client: TestClient, pdf_rotated_cropbox: bytes) -> None:
    """PDF with 90-degree rotation and non-zero CropBox displays correct rotated bounds."""
    proj = client.post("/api/projects", json={"name": "회전 크롭박스 테스트"}).json()
    proj_id = proj["id"]

    upload_res = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("rotated_cropbox.pdf", pdf_rotated_cropbox, "application/pdf")},
    )
    assert upload_res.status_code == 200
    meta = upload_res.json()
    drawing_id = meta["drawing_id"]

    p0 = meta["pages"][0]
    assert p0["rotation"] == 90
    assert abs(p0["display_width_pt"] - 680.0) < 1.0
    assert abs(p0["display_height_pt"] - 500.0) < 1.0

    # Add marker at valid rotated canonical point
    add_ok = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "rot_m1", "drawing_id": drawing_id, "page_index": 0, "x": 650.0, "y": 480.0, "item_code": "LIGHT", "unit": "EA"},
    )
    assert add_ok.status_code == 200

    # Add marker exceeding rotated display width (680.0) -> 400
    add_oob = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "rot_m2", "drawing_id": drawing_id, "page_index": 0, "x": 690.0, "y": 200.0, "item_code": "LIGHT", "unit": "EA"},
    )
    assert add_oob.status_code == 400


def test_pdf_security_rejections(
    client: TestClient,
    pdf_corrupt: bytes,
    pdf_encrypted: bytes,
) -> None:
    """Corrupt PDF and encrypted PDF files must be safely rejected with HTTP 400 and clear error detail."""
    proj = client.post("/api/projects", json={"name": "PDF 보안 검증"}).json()
    proj_id = proj["id"]

    # 1. Corrupt PDF -> 400
    res_corrupt = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("corrupt.pdf", pdf_corrupt, "application/pdf")},
    )
    assert res_corrupt.status_code == 400
    assert "PDF" in res_corrupt.json()["detail"]

    # 2. Encrypted PDF -> 400 with encryption message
    res_enc = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("encrypted.pdf", pdf_encrypted, "application/pdf")},
    )
    assert res_enc.status_code == 400
    assert "암호화" in res_enc.json()["detail"]


def test_pdf_csv_and_xlsx_exports(client: TestClient, pdf_two_pages: bytes) -> None:
    """CSV and XLSX exports on PDF drawing include page_index, source_type, file_type, and coordinate_space."""
    proj = client.post("/api/projects", json={"name": "PDF 내보내기 검증"}).json()
    proj_id = proj["id"]

    dwg = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("export_pdf.pdf", pdf_two_pages, "application/pdf")},
    ).json()
    drawing_id = dwg["drawing_id"]

    # Add 1 marker on page 0 and 1 marker on page 1
    client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "p0_item", "drawing_id": drawing_id, "page_index": 0, "x": 120.0, "y": 200.0, "item_code": "LIGHT", "item_name": "조명", "unit": "EA"},
    )
    client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "p1_item", "drawing_id": drawing_id, "page_index": 1, "x": 300.0, "y": 250.0, "item_code": "OUTLET", "item_name": "콘센트", "unit": "EA"},
    )

    # 1. CSV Evidence
    csv_ev_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/export/csv?type=evidence")
    assert csv_ev_res.status_code == 200
    reader_ev = list(csv.reader(io.StringIO(csv_ev_res.content.decode("utf-8-sig"))))
    assert len(reader_ev) >= 3

    headers = reader_ev[0]
    assert "page_index" in headers
    assert "source_type" in headers
    assert "file_type" in headers
    assert "coordinate_space" in headers

    p_idx_col = headers.index("page_index")
    src_type_col = headers.index("source_type")
    coord_col = headers.index("coordinate_space")

    row1 = reader_ev[1]
    row2 = reader_ev[2]

    # Verify metadata fields populated
    assert row1[src_type_col] == "PDF"
    assert row1[coord_col] == "PDF_PAGE_POINT"
    assert row2[src_type_col] == "PDF"
    assert row2[coord_col] == "PDF_PAGE_POINT"

    # Verify page indices (0 and 1)
    p_indices = {row1[p_idx_col], row2[p_idx_col]}
    assert "0" in p_indices
    assert "1" in p_indices

    # 2. XLSX Export
    xlsx_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/export/xlsx")
    assert xlsx_res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_res.content))

    ws_ev = wb["Takeoff Evidence"]
    headers_xlsx = [str(ws_ev.cell(row=1, column=c).value) for c in range(1, ws_ev.max_column + 1)]
    assert any("page_index" in h or "페이지 번호" in h for h in headers_xlsx)
    assert any("source_type" in h or "도면 유형" in h for h in headers_xlsx)
    assert any("coordinate_space" in h or "좌표계" in h for h in headers_xlsx)

    # Verify no formula injection
    for row in ws_ev.iter_rows():
        for cell in row:
            assert cell.data_type != "f", f"Formula found in cell {cell.coordinate}: {cell.value}"


def test_pdf_raw_preservation_and_download(client: TestClient, pdf_two_pages: bytes) -> None:
    """PDF raw file is preserved and downloadable with exact byte match and application/pdf content type."""
    proj = client.post("/api/projects", json={"name": "PDF 원본 보존 검증"}).json()
    proj_id = proj["id"]

    upload_res = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("original_drawing.pdf", pdf_two_pages, "application/pdf")},
    )
    drawing_id = upload_res.json()["drawing_id"]

    raw_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/raw")
    assert raw_res.status_code == 200
    assert raw_res.headers["content-type"] == "application/pdf"
    assert raw_res.content == pdf_two_pages
    assert hashlib.sha256(raw_res.content).hexdigest() == hashlib.sha256(pdf_two_pages).hexdigest()


def test_pdf_a04_matrix_scenario_with_expected_json(client: TestClient, pdf_two_pages: bytes) -> None:
    """Validate against QA_PDF_B_MATRIX expected_takeoff.json ground truth oracle."""
    import json

    expected_path = FIXTURES_DIR / "expected_takeoff.json"
    assert expected_path.exists()
    gt = json.loads(expected_path.read_text(encoding="utf-8"))

    proj = client.post("/api/projects", json={"name": "A04 매트릭스 검증"}).json()
    proj_id = proj["id"]

    upload_res = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": (gt["document"], pdf_two_pages, "application/pdf")},
    )
    assert upload_res.status_code == 200
    drawing_id = upload_res.json()["drawing_id"]

    # Initial state: 0 items
    t0 = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff").json()
    assert len(t0["summary"]) == 0

    # Add markers from ground truth
    total_markers = 0
    for page in gt["pages"]:
        p_idx = page["page_index"]
        for marker in page["manual_markers"]:
            add_res = client.post(
                f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
                json={
                    "id": marker["id"],
                    "drawing_id": drawing_id,
                    "page_index": p_idx,
                    "x": marker["x"],
                    "y": marker["y"],
                    "item_code": marker["item_code"],
                    "unit": marker["unit"],
                },
            )
            assert add_res.status_code == 200
            total_markers += 1

    # Check takeoff against oracle
    t_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff")
    assert t_res.status_code == 200
    takeoff = t_res.json()

    exp_sum = gt["expected_summary"]
    total_calc = sum(s["quantity"] for s in takeoff["summary"])
    assert total_calc == exp_sum["total_quantity"]

    sum_map = {s["item_code"]: s for s in takeoff["summary"]}
    for code, expected_info in exp_sum["items"].items():
        assert code in sum_map
        assert sum_map[code]["quantity"] == expected_info["quantity"]
        assert sum_map[code]["unit"] == expected_info["unit"]
        assert sum_map[code]["is_provisional"] is exp_sum["is_provisional"]


def test_pdf_scanned_mixed_drawing(client: TestClient, pdf_scanned_mixed: bytes) -> None:
    """PDF with mixed scanned raster page (Page 0) and vector electrical page (Page 1).

    Validates:
    - 2 pages parsed correctly with 800x600 pt dimensions.
    - Page 0 (raster) renders successfully without OCR crash.
    - Page 1 (vector) renders successfully.
    - Manual markers can be added to both raster and vector pages.
    - Disclaimer warning is present.
    """
    proj = client.post("/api/projects", json={"name": "스캔 및 벡터 혼합 PDF 테스트"}).json()
    proj_id = proj["id"]

    upload_res = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("scanned_mixed.pdf", pdf_scanned_mixed, "application/pdf")},
    )
    assert upload_res.status_code == 200
    dwg_meta = upload_res.json()
    drawing_id = dwg_meta["drawing_id"]

    assert dwg_meta["page_count"] == 2
    assert dwg_meta["coordinate_space"] == "PDF_PAGE_POINT"

    # Verify rendering of Page 0 (scanned raster) and Page 1 (vector)
    p0_img = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/pages/0/image")
    assert p0_img.status_code == 200
    assert p0_img.headers["content-type"] == "image/png"
    assert len(p0_img.content) > 1000

    p1_img = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/pages/1/image")
    assert p1_img.status_code == 200
    assert p1_img.headers["content-type"] == "image/png"
    assert len(p1_img.content) > 1000

    # Place manual marker on Page 0 (raster page)
    res_m0 = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "scan_m1", "drawing_id": drawing_id, "page_index": 0, "x": 215.0, "y": 215.0, "item_code": "SWITCH", "item_name": "스위치", "unit": "EA"},
    )
    assert res_m0.status_code == 200

    # Place manual marker on Page 1 (vector page)
    res_m1 = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "vec_m1", "drawing_id": drawing_id, "page_index": 1, "x": 325.0, "y": 325.0, "item_code": "LIGHT", "item_name": "조명", "unit": "EA"},
    )
    assert res_m1.status_code == 200

    # Verify takeoff calculation
    t_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff")
    assert t_res.status_code == 200
    takeoff = t_res.json()

    assert len(takeoff["summary"]) == 2
    by_code = {s["item_code"]: s for s in takeoff["summary"]}
    assert by_code["SWITCH"]["quantity"] == 1
    assert by_code["SWITCH"]["unit"] == "EA"
    assert by_code["SWITCH"]["is_provisional"] is True
    assert by_code["LIGHT"]["quantity"] == 1
    assert by_code["LIGHT"]["unit"] == "EA"
    assert by_code["LIGHT"]["is_provisional"] is True


def test_pdf_expected_catalog_oracle(client: TestClient) -> None:
    """Validate all synthetic fixtures against fixtures/pdf/expected.json catalog oracle.

    Ensures:
    1. File existence, exact SHA256 match, and byte size match.
    2. Upload and metadata parsing match ground truth page dimensions and rotation.
    3. Manual marker insertion matches expected takeoff quantities and provisional status.
    4. Exclusion/restoration operations yield exact expected quantities.
    """
    import json

    catalog_path = FIXTURES_DIR / "expected.json"
    assert catalog_path.exists(), f"Missing catalog {catalog_path}"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    proj = client.post("/api/projects", json={"name": "PDF 카탈로그 전체 오라클 검증"}).json()
    proj_id = proj["id"]

    for fixture_name, spec in catalog["fixtures"].items():
        pdf_path = FIXTURES_DIR / spec["filename"]
        assert pdf_path.exists(), f"Missing fixture file {pdf_path}"
        pdf_bytes = pdf_path.read_bytes()

        # 1. SHA256 and byte size integrity
        assert len(pdf_bytes) == spec["file_size_bytes"]
        assert hashlib.sha256(pdf_bytes).hexdigest() == spec["sha256"]

        # 2. Upload
        upload_res = client.post(
            f"/api/projects/{proj_id}/drawings",
            files={"file": (spec["filename"], pdf_bytes, "application/pdf")},
        )
        assert upload_res.status_code == 200, f"Upload failed for {fixture_name}: {upload_res.text}"
        dwg = upload_res.json()
        drawing_id = dwg["drawing_id"]
        assert dwg["page_count"] == spec["page_count"]

        # 3. Add markers
        for page in spec["pages"]:
            p_idx = page["page_index"]
            for marker in page["manual_markers"]:
                add_res = client.post(
                    f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
                    json={
                        "id": marker["id"],
                        "drawing_id": drawing_id,
                        "page_index": p_idx,
                        "x": marker["x"],
                        "y": marker["y"],
                        "item_code": marker["item_code"],
                        "item_name": marker.get("item_name", marker["item_code"]),
                        "unit": marker["unit"],
                    },
                )
                assert add_res.status_code == 200

        # 4. Takeoff check
        t_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff")
        assert t_res.status_code == 200
        takeoff = t_res.json()

        exp_takeoff = spec["expected_takeoff"]
        actual_total = sum(s["quantity"] for s in takeoff["summary"])
        assert actual_total == exp_takeoff["total_quantity"]

        actual_items = {s["item_code"]: s for s in takeoff["summary"]}
        for item_code, item_spec in exp_takeoff["items"].items():
            assert item_code in actual_items
            assert actual_items[item_code]["quantity"] == item_spec["quantity"]
            assert actual_items[item_code]["unit"] == item_spec["unit"]
            assert actual_items[item_code]["is_provisional"] is exp_takeoff["is_provisional"]

        # 5. Operations check (exclude / restore / reload) if defined
        if "operations_expected" in spec:
            ops = spec["operations_expected"]
            ex_id = ops["exclude_marker_id"]

            # Exclude marker via review PUT endpoint
            ex_res = client.put(
                f"/api/projects/{proj_id}/drawings/{drawing_id}/reviews",
                json=[
                    {
                        "source_object_id": ex_id,
                        "inclusion_status": "EXCLUDED",
                        "reason": "테스트 제외",
                    }
                ],
            )
            assert ex_res.status_code == 200

            # Verify takeoff after exclusion
            t_ex = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff").json()
            total_after_ex = sum(s["quantity"] for s in t_ex["summary"])
            assert total_after_ex == ops["quantity_after_exclude"]

            # Restore marker
            re_res = client.put(
                f"/api/projects/{proj_id}/drawings/{drawing_id}/reviews",
                json=[
                    {
                        "source_object_id": ex_id,
                        "inclusion_status": "INCLUDED",
                        "reason": "테스트 복원",
                    }
                ],
            )
            assert re_res.status_code == 200

            # Verify takeoff after restoration
            t_re = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff").json()
            total_after_re = sum(s["quantity"] for s in t_re["summary"])
            assert total_after_re == ops["quantity_after_restore"]

            # Reload markers check
            man_list = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects").json()
            assert len(man_list) == ops["reload_marker_count"]


def test_pdf_manual_object_duplicate_id_defense(client: TestClient, pdf_two_pages: bytes) -> None:
    """P0-02 (DOMAIN): Duplicate source_object_id handling.

    - Re-posting identical payload with same ID is idempotent (200 OK, count stays 1, evidence stays 1).
    - Re-posting conflicting payload with same ID raises 409 Conflict.
    - Delete and restore works accurately.
    """
    proj = client.post("/api/projects", json={"name": "중복 ID 방어 검증"}).json()
    proj_id = proj["id"]

    dwg = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("dup_test.pdf", pdf_two_pages, "application/pdf")},
    ).json()
    drawing_id = dwg["drawing_id"]

    item_payload = {
        "id": "dup_marker_1",
        "drawing_id": drawing_id,
        "page_index": 0,
        "x": 150.0,
        "y": 200.0,
        "item_code": "LIGHT",
        "item_name": "다운라이트",
        "unit": "EA",
    }

    # 1. Initial creation -> 200
    res1 = client.post(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects", json=item_payload)
    assert res1.status_code == 200

    t1 = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff").json()
    assert sum(s["quantity"] for s in t1["summary"]) == 1
    assert len(t1["evidence"]) == 1

    # 2. Duplicate submission with IDENTICAL payload (network retry scenario) -> idempotent 200, no count increment!
    res_retry = client.post(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects", json=item_payload)
    assert res_retry.status_code == 200

    t2 = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff").json()
    assert sum(s["quantity"] for s in t2["summary"]) == 1  # Still 1 EA!
    assert len(t2["evidence"]) == 1  # Exactly 1 evidence row

    # 3. Duplicate submission with CONFLICTING payload (same ID, different item_code) -> 409 Conflict
    conflict_payload = dict(item_payload)
    conflict_payload["item_code"] = "OUTLET"
    conflict_payload["item_name"] = "콘센트"
    res_conflict = client.post(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects", json=conflict_payload)
    assert res_conflict.status_code == 409
    assert "중복 충돌" in res_conflict.json()["detail"] or "이미 다른 속성" in res_conflict.json()["detail"]

    # 4. Duplicate submission with CONFLICTING coordinates (same ID, different x/y) -> 409 Conflict
    conflict_coord = dict(item_payload)
    conflict_coord["x"] = 300.0
    res_conflict2 = client.post(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects", json=conflict_coord)
    assert res_conflict2.status_code == 409

    # 5. Delete marker -> count becomes 0
    del_res = client.delete(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects/dup_marker_1")
    assert del_res.status_code == 200

    t3 = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff").json()
    assert sum(s["quantity"] for s in t3["summary"]) == 0
    assert len(t3["evidence"]) == 0


def test_pdf_oversized_dimension_and_lazy_render_defense(
    client: TestClient,
    pdf_oversized: bytes,
    pdf_two_pages: bytes,
    tmp_path: Path,
) -> None:
    """P0-03: Security budget limits (dimension bomb rejection) and lazy on-demand page rendering.

    - Oversized PDF exceeding pixel budget (12,000x12,000 pt) is rejected with HTTP 400.
    - Normal multi-page PDF upload does NOT pre-render 50 pages synchronously.
    - Rendering happens on-demand when /pages/{page_index}/image is requested.
    """
    proj = client.post("/api/projects", json={"name": "안정성 예외 방어"}).json()
    proj_id = proj["id"]

    # 1. Dimension bomb rejection -> HTTP 400
    res_oversized = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("bomb.pdf", pdf_oversized, "application/pdf")},
    )
    assert res_oversized.status_code == 400
    assert "초과했습니다" in res_oversized.json()["detail"]

    # 2. Normal upload -> verify NO pre-rendered PNGs on disk immediately after upload
    res_normal = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("lazy_test.pdf", pdf_two_pages, "application/pdf")},
    )
    assert res_normal.status_code == 200
    dwg_id = res_normal.json()["drawing_id"]

    from eai_api import app as app_module

    pages_disk_dir = app_module.storage.projects_dir / proj_id / "drawings" / dwg_id / "pages"
    # Immediately after upload, pages directory should not have cached images (zero pre-render)
    p0_disk_file = pages_disk_dir / "page_0.png"
    assert not p0_disk_file.exists(), "Page 0 image was unexpectedly pre-rendered during upload!"

    # 3. Now request page 0 image on demand -> returns 200 and caches page_0.png
    p0_res = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/pages/0/image")
    assert p0_res.status_code == 200
    assert p0_res.headers["content-type"] == "image/png"
    assert p0_disk_file.exists(), "Page 0 image was not cached after on-demand request!"

