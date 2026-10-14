"""Tests for PR A: PNG/JPG 2D raster image drawing upload, manual takeoff, and export (Issue #12)."""

from pathlib import Path

import pytest
from eai_api.app import app
from eai_api.image_parser import inspect_image
from eai_api.storage import Storage
from fastapi.testclient import TestClient

FIXTURE_IMAGE_PATH = Path("fixtures/images/floorplan_sample.png")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    from eai_api import app as app_module

    app_module.storage = Storage(root=tmp_path)
    return TestClient(app)


def test_inspect_valid_png() -> None:
    raw = FIXTURE_IMAGE_PATH.read_bytes()
    meta = inspect_image(raw, "floorplan_sample.png")
    assert meta.file_type == "PNG"
    assert meta.width == 1000
    assert meta.height == 800
    assert meta.size_bytes == len(raw)
    assert len(meta.sha256) == 64


def test_inspect_invalid_or_corrupt_images() -> None:
    # 0 bytes
    with pytest.raises(ValueError, match="비어 있습니다"):
        inspect_image(b"", "empty.png")

    # Corrupt PNG header
    with pytest.raises(ValueError, match="지원하지 않거나 손상된"):
        inspect_image(b"\x89PNG\r\n\x1a\x00truncated", "corrupt.png")

    # Truncated PNG (too short for IHDR)
    with pytest.raises(ValueError, match="IHDR 청크가 너무 짧습니다"):
        inspect_image(b"\x89PNG\r\n\x1a\n1234", "short.png")

    # Not an image
    with pytest.raises(ValueError, match="지원하지 않거나 손상된"):
        inspect_image(b"SECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n", "fake.png")


def test_upload_image_drawing(client: TestClient) -> None:
    # 1. Create project
    proj_res = client.post("/api/projects", json={"name": "이미지 도면 테스트 프로젝트"})
    assert proj_res.status_code == 200
    proj_id = proj_res.json()["id"]

    # 2. Upload PNG
    raw_bytes = FIXTURE_IMAGE_PATH.read_bytes()
    upload_res = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", raw_bytes, "image/png")},
    )
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    drawing_id = upload_data["drawing_id"]
    assert upload_data["source_type"] == "IMAGE"
    assert upload_data["file_type"] == "PNG"
    assert upload_data["coordinate_space"] == "IMAGE_PIXEL"
    assert upload_data["dimensions"] == {"width": 1000, "height": 800}
    assert upload_data["objects_count"] == 0
    assert upload_data["warnings_count"] >= 1

    # 3. Get drawing detail
    dwg_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}")
    assert dwg_res.status_code == 200
    dwg = dwg_res.json()
    assert dwg["source_type"] == "IMAGE"
    assert dwg["file_type"] == "PNG"
    assert dwg["coordinate_space"] == "IMAGE_PIXEL"
    assert dwg["extents"]["min"] == [0.0, 0.0]
    assert dwg["extents"]["max"] == [1000.0, 800.0]
    assert dwg["dxf"]["units_name"] == "PIXEL"
    # Informational warning that manual EA marker mode is active and scale is uncalibrated
    assert "픽셀 좌표계(IMAGE_PIXEL)" in dwg["warnings"][0]["message"]
    assert "FR-016" in dwg["warnings"][0]["message"]

    # 4. Image serving endpoint
    img_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/image")
    assert img_res.status_code == 200
    assert img_res.headers["content-type"] == "image/png"
    assert img_res.content == raw_bytes

    # 5. Raw download endpoint
    raw_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/raw")
    assert raw_res.status_code == 200
    assert raw_res.headers["content-type"] == "image/png"
    assert "floorplan_sample.png" in raw_res.headers["content-disposition"]
    assert raw_res.content == raw_bytes


def test_reject_dwg_upload(client: TestClient) -> None:
    proj_res = client.post("/api/projects", json={"name": "DWG 거부 테스트"})
    proj_id = proj_res.json()["id"]

    res = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("drawing.dwg", b"AC1032binarydwgdata", "application/octet-stream")},
    )
    assert res.status_code == 400
    assert "DWG 직접 업로드는 지원하지 않습니다" in res.json()["detail"]


def test_image_manual_takeoff_workflow_and_exports(client: TestClient) -> None:
    proj_res = client.post("/api/projects", json={"name": "수동 적산 프로젝트"})
    proj_id = proj_res.json()["id"]

    raw_bytes = FIXTURE_IMAGE_PATH.read_bytes()
    upload_res = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", raw_bytes, "image/png")},
    )
    drawing_id = upload_res.json()["drawing_id"]

    # Initial takeoff: 0 items
    t0_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff")
    assert t0_res.status_code == 200
    t0 = t0_res.json()
    assert len(t0["summary"]) == 0
    assert len(t0["evidence"]) == 0

    # Add 4 LIGHT markers, 2 OUTLET markers, 2 SWITCH markers at fixture pixel coords
    markers = [
        {"id": "man_lt_1", "drawing_id": drawing_id, "x": 250, "y": 250, "item_code": "LIGHT", "item_name": "다운라이트", "unit": "EA"},
        {"id": "man_lt_2", "drawing_id": drawing_id, "x": 750, "y": 250, "item_code": "LIGHT", "item_name": "다운라이트", "unit": "EA"},
        {"id": "man_lt_3", "drawing_id": drawing_id, "x": 250, "y": 550, "item_code": "LIGHT", "item_name": "다운라이트", "unit": "EA"},
        {"id": "man_lt_4", "drawing_id": drawing_id, "x": 750, "y": 550, "item_code": "LIGHT", "item_name": "다운라이트", "unit": "EA"},
        {"id": "man_ot_1", "drawing_id": drawing_id, "x": 120, "y": 250, "item_code": "OUTLET", "item_name": "2구 콘센트", "unit": "EA"},
        {"id": "man_ot_2", "drawing_id": drawing_id, "x": 880, "y": 250, "item_code": "OUTLET", "item_name": "2구 콘센트", "unit": "EA"},
        {"id": "man_sw_1", "drawing_id": drawing_id, "x": 460, "y": 380, "item_code": "SWITCH", "item_name": "1구 스위치", "unit": "EA"},
        {"id": "man_sw_2", "drawing_id": drawing_id, "x": 540, "y": 380, "item_code": "SWITCH", "item_name": "1구 스위치", "unit": "EA"},
    ]

    for m in markers:
        add_res = client.post(
            f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
            json=m,
        )
        assert add_res.status_code == 200

    # Verify P0 M-UNIT-01 defense: non-EA manual item must be rejected
    bad_res = client.post(
        f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects",
        json={"id": "bad_unit", "drawing_id": drawing_id, "x": 100, "y": 100, "item_code": "CABLE", "unit": "M"},
    )
    assert bad_res.status_code == 400
    assert "M-UNIT-01" in bad_res.json()["detail"]

    # Re-fetch takeoff
    t1_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff")
    assert t1_res.status_code == 200
    t1 = t1_res.json()

    # Summary checks: 3 items (LIGHT: 4 EA, OUTLET: 2 EA, SWITCH: 2 EA)
    sum_by_code = {row["item_code"]: row for row in t1["summary"]}
    assert set(sum_by_code.keys()) == {"LIGHT", "OUTLET", "SWITCH"}

    assert sum_by_code["LIGHT"]["quantity"] == 4
    assert sum_by_code["LIGHT"]["unit"] == "EA"
    assert sum_by_code["LIGHT"]["quantity_method"] == "MANUAL"

    assert sum_by_code["OUTLET"]["quantity"] == 2
    assert sum_by_code["OUTLET"]["unit"] == "EA"
    assert sum_by_code["OUTLET"]["quantity_method"] == "MANUAL"

    assert sum_by_code["SWITCH"]["quantity"] == 2
    assert sum_by_code["SWITCH"]["unit"] == "EA"
    assert sum_by_code["SWITCH"]["quantity_method"] == "MANUAL"

    # Evidence checks: 8 rows, entity_type="MANUAL_POINT", pixel coords preserved
    assert len(t1["evidence"]) == 8
    ev_by_id = {row["source_object_id"]: row for row in t1["evidence"]}
    assert ev_by_id["man_lt_1"]["x"] == 250.0
    assert ev_by_id["man_lt_1"]["y"] == 250.0
    assert ev_by_id["man_lt_1"]["entity_type"] == "MANUAL_POINT"
    assert ev_by_id["man_lt_1"]["block_name"] == "[MANUAL]"
    assert ev_by_id["man_lt_1"]["inclusion_status"] == "MANUAL_ADDED"

    # Export CSV Summary
    csv_sum = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/export/csv?type=summary")
    assert csv_sum.status_code == 200
    text_sum = csv_sum.content.decode("utf-8-sig")
    assert "LIGHT,다운라이트,,EA,4,MANUAL" in text_sum
    assert "OUTLET,2구 콘센트,,EA,2,MANUAL" in text_sum
    assert "SWITCH,1구 스위치,,EA,2,MANUAL" in text_sum

    # Export CSV Evidence
    csv_ev = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/export/csv?type=evidence")
    assert csv_ev.status_code == 200
    text_ev = csv_ev.content.decode("utf-8-sig")
    assert "man_lt_1" in text_ev
    assert "MANUAL_POINT" in text_ev
    assert "250" in text_ev

    # Export XLSX
    xlsx_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/export/xlsx")
    assert xlsx_res.status_code == 200
    assert len(xlsx_res.content) > 1000

    # Delete one marker (man_lt_4)
    del_res = client.delete(f"/api/projects/{proj_id}/drawings/{drawing_id}/manual-objects/man_lt_4")
    assert del_res.status_code == 200

    # Recheck takeoff: LIGHT should now be 3 EA
    t2_res = client.get(f"/api/projects/{proj_id}/drawings/{drawing_id}/takeoff")
    t2 = t2_res.json()
    sum_by_code_2 = {row["item_code"]: row for row in t2["summary"]}
    assert sum_by_code_2["LIGHT"]["quantity"] == 3
    assert len(t2["evidence"]) == 7
