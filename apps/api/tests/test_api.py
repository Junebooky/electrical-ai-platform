"""Integration tests for the FastAPI service and Takeoff workflows."""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

import openpyxl
import pytest
from eai_api.app import app
from fastapi.testclient import TestClient

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "dxf"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("EAI_DATA_DIR", str(tmp_path / "data"))
    # Re-init storage with the temporary path
    from eai_api import app as app_module
    from eai_api.storage import Storage

    app_module.storage = Storage(root=tmp_path / "data")
    return TestClient(app)


def test_health(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": "0.1.0"}


def test_parse_direct_and_errors(client: TestClient) -> None:
    # 1. Reject fake DWG
    fake_dwg = FIXTURES_DIR / "fake_dwg.dxf"
    res = client.post(
        "/api/dxf/parse-direct",
        files={"file": (fake_dwg.name, fake_dwg.read_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "DWG_NOT_SUPPORTED"

    # 2. Reject non-DXF
    not_dxf = FIXTURES_DIR / "not_a_dxf.dxf"
    res = client.post(
        "/api/dxf/parse-direct",
        files={"file": (not_dxf.name, not_dxf.read_bytes(), "text/plain")},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "NOT_A_DXF"

    # 3. Direct parse valid basic_devices
    valid = FIXTURES_DIR / "basic_devices.dxf"
    res = client.post(
        "/api/dxf/parse-direct",
        files={"file": (valid.name, valid.read_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["source"]["filename"] == "basic_devices.dxf"
    assert len(data["objects"]) == 18


def test_full_takeoff_lifecycle(client: TestClient) -> None:
    # 1. Create project
    proj_res = client.post("/api/projects", json={"name": "테스트 전기공사 프로젝트"})
    assert proj_res.status_code == 200
    project_id = proj_res.json()["id"]

    # 2. Upload drawing
    dxf_file = FIXTURES_DIR / "basic_devices.dxf"
    upload_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": (dxf_file.name, dxf_file.read_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 200
    drawing_id = upload_res.json()["drawing_id"]

    # 3. Get normalized drawing
    get_dxf_res = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}")
    assert get_dxf_res.status_code == 200
    drawing_data = get_dxf_res.json()
    assert len(drawing_data["objects"]) == 18

    # 4. Set mappings
    mappings = [
        {"block_name": "LT-DL", "item_code": "LIGHT", "item_name": "다운라이트 LED 6인치", "unit": "EA"},
        {"block_name": "OT-2P", "item_code": "OUTLET", "item_name": "매입 2구 콘센트", "unit": "EA"},
        {"block_name": "SW-1", "item_code": "SWITCH", "item_name": "1로 텀블러 스위치", "unit": "EA"},
    ]
    map_res = client.put(f"/api/projects/{project_id}/drawings/{drawing_id}/mappings", json=mappings)
    assert map_res.status_code == 200

    # 5. Check Takeoff results: LIGHT=6, OUTLET=4, SWITCH=3
    takeoff_res = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff")
    assert takeoff_res.status_code == 200
    takeoff_data = takeoff_res.json()
    sum_map = {row["item_code"]: row["quantity"] for row in takeoff_data["summary"]}
    assert sum_map == {"LIGHT": 6, "OUTLET": 4, "SWITCH": 3}

    # 6. User Review Override: exclude 1 LIGHT object
    light_evidence = [e for e in takeoff_data["evidence"] if e["mapped_item_code"] == "LIGHT"]
    target_obj_id = light_evidence[0]["source_object_id"]

    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/reviews",
        json=[
            {
                "source_object_id": target_obj_id,
                "inclusion_status": "EXCLUDED",
                "review_status": "REVIEWED",
                "reason": "오탐 제외 (도면 표기 불일치)",
            }
        ],
    )

    # Check updated Takeoff: LIGHT is now 5
    takeoff_res2 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff")
    sum_map2 = {row["item_code"]: row["quantity"] for row in takeoff_res2.json()["summary"]}
    assert sum_map2["LIGHT"] == 5

    # 7. Add Manual Object: 1 missing LIGHT
    client.post(
        f"/api/projects/{project_id}/drawings/{drawing_id}/manual-objects",
        json={
            "id": "manual_lt_1",
            "drawing_id": drawing_id,
            "x": 2500.0,
            "y": 2500.0,
            "item_code": "LIGHT",
            "item_name": "다운라이트 LED 6인치",
            "note": "누락 기구 현장 추가",
        },
    )

    # Check updated Takeoff: LIGHT is back to 6, method is MIXED
    takeoff_res3 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff")
    light_row = next(r for r in takeoff_res3.json()["summary"] if r["item_code"] == "LIGHT")
    assert light_row["quantity"] == 6
    assert light_row["quantity_method"] == "MIXED"

    # 8. Export CSV summary & evidence
    csv_sum = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/export/csv?type=summary")
    assert csv_sum.status_code == 200
    assert "item_code,item_name" in csv_sum.text
    assert "LIGHT" in csv_sum.text

    csv_ev = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/export/csv?type=evidence")
    assert csv_ev.status_code == 200
    assert "source_object_id,drawing_id" in csv_ev.text
    assert target_obj_id in csv_ev.text

    # 9. Export XLSX
    xlsx_res = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/export/xlsx")
    assert xlsx_res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_res.content))
    assert "Takeoff Summary" in wb.sheetnames
    assert "Takeoff Evidence" in wb.sheetnames

    # Check that summary quantity in Excel matches
    ws_sum = wb["Takeoff Summary"]
    found_light = False
    for row in ws_sum.iter_rows(values_only=True):
        if row[0] == "LIGHT":
            assert row[4] == 6  # quantity
            found_light = True
    assert found_light


def test_list_drawings_and_reopen(client: TestClient) -> None:
    # 1. Create project
    proj_res = client.post("/api/projects", json={"name": "도면 목록 테스트"})
    assert proj_res.status_code == 200
    project_id = proj_res.json()["id"]

    # 2. Upload first drawing
    dxf1 = FIXTURES_DIR / "basic_devices.dxf"
    res1 = client.post(
        f"/api/projects/{project_id}/drawings?revision=REV0",
        files={"file": (dxf1.name, dxf1.read_bytes(), "application/octet-stream")},
    )
    assert res1.status_code == 200
    d1_id = res1.json()["drawing_id"]

    # 3. Upload second drawing
    dxf2 = FIXTURES_DIR / "hidden_layers.dxf"
    res2 = client.post(
        f"/api/projects/{project_id}/drawings?revision=REV1",
        files={"file": (dxf2.name, dxf2.read_bytes(), "application/octet-stream")},
    )
    assert res2.status_code == 200
    d2_id = res2.json()["drawing_id"]

    # 4. List drawings
    list_res = client.get(f"/api/projects/{project_id}/drawings")
    assert list_res.status_code == 200
    drawings = list_res.json()
    assert len(drawings) == 2
    drawing_ids = [d["id"] for d in drawings]
    assert d1_id in drawing_ids
    assert d2_id in drawing_ids

    # 5. Reopen saved drawing
    reopened = client.get(f"/api/projects/{project_id}/drawings/{d1_id}")
    assert reopened.status_code == 200
    data = reopened.json()
    assert data["drawing_id"] == d1_id
    assert len(data["objects"]) == 18


def test_structural_blocking_defense_ac_06(client: TestClient) -> None:
    # AC-06: Structurally invalid objects (XREF, missing block definitions, circular)
    # MUST NEVER be forcefully included into CAD counts even if user sets INCLUDED.
    proj_res = client.post("/api/projects", json={"name": "XREF 방어 테스트"})
    project_id = proj_res.json()["id"]

    xref_file = FIXTURES_DIR / "xref_reference.dxf"
    upload_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": (xref_file.name, xref_file.read_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 200
    drawing_id = upload_res.json()["drawing_id"]

    # Map both LT-DL and ARCH_BASE (which is an XREF) to LIGHT
    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/mappings",
        json=[
            {"block_name": "LT-DL", "item_code": "LIGHT", "unit": "EA"},
            {"block_name": "ARCH_BASE", "item_code": "LIGHT", "unit": "EA"},
        ],
    )

    # Initial takeoff: ARCH_BASE is blocked, so LIGHT is only 1 (from LT-DL)
    t1 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    sum1 = {row["item_code"]: row["quantity"] for row in t1["summary"]}
    assert sum1["LIGHT"] == 1

    # Find ARCH_BASE object
    xref_ev = next(e for e in t1["evidence"] if e["block_name"] == "ARCH_BASE")
    assert xref_ev["inclusion_status"] == "EXCLUDED"
    assert xref_ev["review_status"] == "UNRESOLVED"

    # Attempt to forcefully override with INCLUDED
    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/reviews",
        json=[
            {
                "source_object_id": xref_ev["source_object_id"],
                "inclusion_status": "INCLUDED",
                "review_status": "REVIEWED",
                "mapped_item_code": "LIGHT",
                "reason": "강제 포함 시도",
            }
        ],
    )

    # Re-check takeoff: LIGHT must STILL be 1, defense active!
    t2 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    sum2 = {row["item_code"]: row["quantity"] for row in t2["summary"]}
    assert sum2["LIGHT"] == 1

    xref_ev2 = next(e for e in t2["evidence"] if e["source_object_id"] == xref_ev["source_object_id"])
    assert xref_ev2["inclusion_status"] == "EXCLUDED"
    assert xref_ev2["review_status"] == "UNRESOLVED"
    assert "구조적 결함" in xref_ev2["review_reason"]

    # AC-06/FR-011: Verify summary row explicitly marks LIGHT as UNRESOLVED due to unresolved XREF
    light_sum = next(r for r in t2["summary"] if r["item_code"] == "LIGHT")
    assert light_sum["review_status"] == "UNRESOLVED"
    assert "미해결 객체" in light_sum["notes"]


def test_binary_dxf_direct_parse_and_upload(client: TestClient) -> None:
    # 1. Direct parse real AutoCAD binary DXF
    bin_file = FIXTURES_DIR / "binary_devices.dxf"
    res = client.post(
        "/api/dxf/parse-direct",
        files={"file": (bin_file.name, bin_file.read_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["objects"]) == 18
    assert data["source"]["filename"] == "binary_devices.dxf"

    # 2. Upload to project and calculate takeoff
    proj_res = client.post("/api/projects", json={"name": "바이너리 DXF 프로젝트"})
    project_id = proj_res.json()["id"]

    upload_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": (bin_file.name, bin_file.read_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 200
    drawing_id = upload_res.json()["drawing_id"]

    # Map blocks
    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/mappings",
        json=[
            {"block_name": "LT-DL", "item_code": "LIGHT", "unit": "EA"},
            {"block_name": "OT-2P", "item_code": "OUTLET", "unit": "EA"},
            {"block_name": "SW-1", "item_code": "SWITCH", "unit": "EA"},
        ],
    )

    takeoff = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    sum_map = {row["item_code"]: row["quantity"] for row in takeoff["summary"]}
    assert sum_map == {"LIGHT": 6, "OUTLET": 4, "SWITCH": 3}


def test_manual_object_override_and_delete(client: TestClient) -> None:
    proj_res = client.post("/api/projects", json={"name": "수동 기구 관리 테스트"})
    project_id = proj_res.json()["id"]

    dxf_file = FIXTURES_DIR / "basic_devices.dxf"
    upload_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": (dxf_file.name, dxf_file.read_bytes(), "application/octet-stream")},
    )
    drawing_id = upload_res.json()["drawing_id"]

    # Map LT-DL to LIGHT
    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/mappings",
        json=[{"block_name": "LT-DL", "item_code": "LIGHT", "unit": "EA"}],
    )

    # 1. Add manual object as LIGHT
    manual_id = "manual_test_100"
    client.post(
        f"/api/projects/{project_id}/drawings/{drawing_id}/manual-objects",
        json={
            "id": manual_id,
            "drawing_id": drawing_id,
            "x": 100.0,
            "y": 200.0,
            "item_code": "LIGHT",
            "item_name": "수동 추가 조명",
            "note": "현장 추가",
        },
    )

    t1 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    assert next(r for r in t1["summary"] if r["item_code"] == "LIGHT")["quantity"] == 7

    # 2. Apply review override to manual object (change item_code to OUTLET)
    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/reviews",
        json=[
            {
                "source_object_id": manual_id,
                "inclusion_status": "MANUAL_ADDED",
                "review_status": "REVIEWED",
                "mapped_item_code": "OUTLET",
                "reason": "조명이 아닌 콘센트로 정정",
            }
        ],
    )

    t2 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    assert next(r for r in t2["summary"] if r["item_code"] == "LIGHT")["quantity"] == 6
    assert next(r for r in t2["summary"] if r["item_code"] == "OUTLET")["quantity"] == 1

    # 3. Delete manual object
    del_res = client.delete(f"/api/projects/{project_id}/drawings/{drawing_id}/manual-objects/{manual_id}")
    assert del_res.status_code == 200

    t3 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    assert next(r for r in t3["summary"] if r["item_code"] == "LIGHT")["quantity"] == 6
    outlet_row = next((r for r in t3["summary"] if r["item_code"] == "OUTLET"), None)
    assert outlet_row is None or outlet_row["quantity"] == 0


def test_review_confirm_preserves_included_quantity(client: TestClient) -> None:
    # Verifies the "검수 확인" workflow: marking INCLUDED as REVIEWED preserves quantity
    proj_res = client.post("/api/projects", json={"name": "검수 확인 테스트"})
    project_id = proj_res.json()["id"]

    dxf_file = FIXTURES_DIR / "basic_devices.dxf"
    upload_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": (dxf_file.name, dxf_file.read_bytes(), "application/octet-stream")},
    )
    drawing_id = upload_res.json()["drawing_id"]

    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/mappings",
        json=[{"block_name": "LT-DL", "item_code": "LIGHT", "unit": "EA"}],
    )

    t1 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    assert next(r for r in t1["summary"] if r["item_code"] == "LIGHT")["quantity"] == 6

    # Select first LIGHT evidence row
    first_light = next(e for e in t1["evidence"] if e["mapped_item_code"] == "LIGHT")
    assert first_light["review_status"] == "UNREVIEWED"

    # Confirm review
    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/reviews",
        json=[
            {
                "source_object_id": first_light["source_object_id"],
                "inclusion_status": "INCLUDED",
                "review_status": "REVIEWED",
                "reason": "현장 확인 완료",
            }
        ],
    )

    t2 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    assert next(r for r in t2["summary"] if r["item_code"] == "LIGHT")["quantity"] == 6
    updated_ev = next(e for e in t2["evidence"] if e["source_object_id"] == first_light["source_object_id"])
    assert updated_ev["review_status"] == "REVIEWED"
    assert updated_ev["inclusion_status"] == "INCLUDED"
    assert updated_ev["review_reason"] == "현장 확인 완료"


def test_export_formula_injection_defense(client: TestClient) -> None:
    # Verifies Issue #7 defense: OWASP CSV & Excel formula injection
    proj_res = client.post("/api/projects", json={"name": "수식 인젝션 방어 테스트"})
    project_id = proj_res.json()["id"]

    dxf_file = FIXTURES_DIR / "basic_devices.dxf"
    upload_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": (dxf_file.name, dxf_file.read_bytes(), "application/octet-stream")},
    )
    drawing_id = upload_res.json()["drawing_id"]

    # Inject formula characters (=, +, -, @) in mappings and review notes
    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/mappings",
        json=[
            {
                "block_name": "LT-DL",
                "item_code": "=cmd|' /C calc'!A0",
                "item_name": "@SUM(1,1)",
                "unit": "EA",
            }
        ],
    )

    t1 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    first_ev = t1["evidence"][0]

    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/reviews",
        json=[
            {
                "source_object_id": first_ev["source_object_id"],
                "inclusion_status": "INCLUDED",
                "review_status": "REVIEWED",
                "reason": "+cmd|' /C calc'!A0",
            }
        ],
    )

    # 1. Check CSV Summary parsed line-by-line via csv.reader
    csv_sum_res = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/export/csv?type=summary")
    assert csv_sum_res.status_code == 200
    reader_sum = list(csv.reader(io.StringIO(csv_sum_res.content.decode("utf-8-sig"))))
    assert len(reader_sum) >= 2
    header_sum = reader_sum[0]
    assert header_sum == [
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
        "notes",
    ]
    # Check row 1 fields
    row_sum = reader_sum[1]
    assert row_sum[0].startswith("'=")
    assert row_sum[1].startswith("'@")
    assert row_sum[7] == drawing_id
    assert row_sum[9] == "REV0"

    # 2. Check CSV Evidence parsed line-by-line via csv.reader
    csv_ev_res = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/export/csv?type=evidence")
    assert csv_ev_res.status_code == 200
    reader_ev = list(csv.reader(io.StringIO(csv_ev_res.content.decode("utf-8-sig"))))
    assert len(reader_ev) >= 2
    header_ev = reader_ev[0]
    assert header_ev == [
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
    ]
    # First row reason must have leading quote escape
    row_ev = reader_ev[1]
    assert row_ev[11].startswith("'+")

    # 3. Check Excel XLSX deep structure and cell.data_type != 'f'
    xlsx_res = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/export/xlsx")
    assert xlsx_res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_res.content))
    assert "Takeoff Summary" in wb.sheetnames
    assert "Takeoff Evidence" in wb.sheetnames

    for sheet_name in ("Takeoff Summary", "Takeoff Evidence"):
        ws = wb[sheet_name]
        for row_cells in ws.iter_rows():
            for c in row_cells:
                assert c.data_type != "f", f"Formula cell detected in {sheet_name} at {c.coordinate}: {c.value}"

    ws_sum = wb["Takeoff Summary"]
    assert str(ws_sum.cell(row=2, column=1).value).startswith("'=")
    assert str(ws_sum.cell(row=2, column=2).value).startswith("'@")


def test_raw_dxf_preservation_and_download(client: TestClient) -> None:
    """Issue #5 / QA-DEF-01: Raw DXF bytes must be preserved and retrievable byte-for-byte."""
    proj = client.post("/api/projects", json={"name": "원본 보존 검증 프로젝트"}).json()
    project_id = proj["id"]

    dxf_file = FIXTURES_DIR / "basic_devices.dxf"
    original_bytes = dxf_file.read_bytes()
    expected_hash = hashlib.sha256(original_bytes).hexdigest()

    upload_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": (dxf_file.name, original_bytes, "application/octet-stream")},
    )
    assert upload_res.status_code == 200
    drawing_info = upload_res.json()
    assert drawing_info["raw_saved"] is True
    assert drawing_info["file_size_bytes"] == len(original_bytes)
    drawing_id = drawing_info["drawing_id"]

    # Download raw drawing via API
    raw_res = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/raw")
    assert raw_res.status_code == 200
    assert raw_res.content == original_bytes
    assert hashlib.sha256(raw_res.content).hexdigest() == expected_hash
    assert "attachment" in raw_res.headers.get("content-disposition", "")


def test_streaming_upload_boundary_and_413(client: TestClient) -> None:
    """Issue #5 / QA-DEF-02: Bounded streaming upload must reject files > 50 MiB with HTTP 413."""
    proj = client.post("/api/projects", json={"name": "용량 제한 검증"}).json()
    project_id = proj["id"]

    # 1. 0 bytes -> returns HTTP 400 (empty file rejected by loader)
    zero_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": ("empty.dxf", b"", "application/octet-stream")},
    )
    assert zero_res.status_code == 400
    assert zero_res.json()["code"] == "EMPTY_FILE"

    # 2. 50 MiB + 1 byte -> returns HTTP 413 Payload Too Large
    oversized_len = 50 * 1024 * 1024 + 1
    # Use generator-like stream of dummy bytes to simulate oversized stream
    oversized_data = b"0\nSECTION\n" + b" " * (oversized_len - 10)
    over_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": ("huge.dxf", oversized_data, "application/octet-stream")},
    )
    assert over_res.status_code == 413
    assert "50 MiB" in over_res.json()["detail"]


def test_provisional_and_unresolved_contracts(client: TestClient) -> None:
    """Issue #9 / DEC-010~014: Provisional quantity and unresolved items contract."""
    proj = client.post("/api/projects", json={"name": "잠정 산출 검증"}).json()
    project_id = proj["id"]

    dxf_file = FIXTURES_DIR / "basic_devices.dxf"
    upload_res = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": (dxf_file.name, dxf_file.read_bytes(), "application/octet-stream")},
    )
    drawing_id = upload_res.json()["drawing_id"]

    # No mappings yet: all items are UNMAPPED -> must be provisional with unresolved_count > 0
    t0 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    assert t0["is_provisional"] is True
    assert t0["unresolved_count"] > 0

    # Map LT-DL to LIGHT, but others unmapped
    client.put(
        f"/api/projects/{project_id}/drawings/{drawing_id}/mappings",
        json=[{"block_name": "LT-DL", "item_code": "LIGHT", "item_name": "다운라이트", "unit": "EA"}],
    )
    t1 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff").json()
    # Still provisional because other blocks (OT-2P, SW-1, etc.) remain unmapped
    assert t1["is_provisional"] is True
    assert t1["unresolved_count"] > 0


