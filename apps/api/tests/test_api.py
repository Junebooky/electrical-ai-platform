"""Integration tests for the FastAPI service and Takeoff workflows."""

from __future__ import annotations

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
