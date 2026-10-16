"""Comprehensive tests for Mapping Templates, openpyxl cell-level Excel verification, and Demo Seed (Issue #23).

Verifies:
1. Built-in and custom Mapping Template CRUD (list, create, get, delete).
2. Merging vs Replacing mapping templates on drawings.
3. openpyxl cell-level Excel export verification (sheet names, column headers, exact quantity cells).
4. Full live demo project seeding (DXF, PDF, Image 3-format end-to-end integration).
"""

from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pytest
from eai_api.app import app
from eai_api.storage import Storage
from fastapi.testclient import TestClient

DXF_FIXTURE_PATH = Path("fixtures/dxf/basic_devices.dxf")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    from eai_api import app as app_module

    app_module.storage = Storage(root=tmp_path)
    return TestClient(app)


def test_list_builtin_templates(client: TestClient) -> None:
    """Verify built-in mapping templates are available out-of-the-box."""
    resp = client.get("/api/mapping-templates")
    assert resp.status_code == 200
    templates = resp.json()["templates"]

    tpl_ids = {t["id"] for t in templates}
    assert "tpl_standard_elec" in tpl_ids
    assert "tpl_kec_standard" in tpl_ids

    std_tpl = next(t for t in templates if t["id"] == "tpl_standard_elec")
    assert std_tpl["is_builtin"] is True
    assert len(std_tpl["rules"]) >= 8

    # Verify standard mappings: LT-DL -> LIGHT, OT-2P -> OUTLET, SW-1 -> SWITCH
    rule_map = {r["block_name"]: r["item_code"] for r in std_tpl["rules"]}
    assert rule_map.get("LT-DL") == "LIGHT"
    assert rule_map.get("OT-2P") == "OUTLET"
    assert rule_map.get("SW-1") == "SWITCH"


def test_create_and_delete_custom_template(client: TestClient) -> None:
    """Verify creating, retrieving, and deleting a custom mapping template."""
    # 1. Create custom template
    payload = {
        "name": "오피스 맞춤 전기 템플릿",
        "description": "사무실 전용 조명 및 바닥 콘센트 매핑 규칙",
        "rules": [
            {"block_name": "OFFICE-LT", "item_code": "LIGHT", "item_name": "사무실 조명", "unit": "EA"},
            {"block_name": "FL-CON", "item_code": "OUTLET", "item_name": "플로어 콘센트", "unit": "EA"},
        ],
    }
    c_resp = client.post("/api/mapping-templates", json=payload)
    assert c_resp.status_code == 200
    created = c_resp.json()
    tpl_id = created["id"]
    assert created["name"] == "오피스 맞춤 전기 템플릿"
    assert created["is_builtin"] is False
    assert len(created["rules"]) == 2

    # 2. Retrieve template by ID
    g_resp = client.get(f"/api/mapping-templates/{tpl_id}")
    assert g_resp.status_code == 200
    assert g_resp.json()["id"] == tpl_id

    # 3. Built-in templates cannot be deleted
    del_builtin = client.delete("/api/mapping-templates/tpl_standard_elec")
    assert del_builtin.status_code == 400

    # 4. Custom template can be deleted
    del_resp = client.delete(f"/api/mapping-templates/{tpl_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # Confirm it is gone
    assert client.get(f"/api/mapping-templates/{tpl_id}").status_code == 404


def test_apply_template_merge_and_replace(client: TestClient) -> None:
    """Verify applying templates to drawing with MERGE vs REPLACE strategies."""
    p_resp = client.post("/api/projects", json={"name": "Template Apply Test"})
    proj_id = p_resp.json()["id"]

    dxf_bytes = DXF_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("basic_devices.dxf", dxf_bytes, "application/dxf")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    # 1. Initial manual rule
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/mappings",
        json=[{"block_name": "MY_CUSTOM_BLOCK", "item_code": "PANEL", "unit": "EA"}],
    )

    # 2. Apply template with MERGE
    merge_resp = client.post(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/apply-template",
        json={"template_id": "tpl_standard_elec", "merge_strategy": "MERGE"},
    )
    assert merge_resp.status_code == 200
    merged_rules = merge_resp.json()
    rule_blocks = {r["block_name"] for r in merged_rules}
    assert "MY_CUSTOM_BLOCK" in rule_blocks  # Preserved from initial manual rule
    assert "LT-DL" in rule_blocks            # Added from template

    # 3. Apply template with REPLACE
    replace_resp = client.post(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/apply-template",
        json={"template_id": "tpl_kec_standard", "merge_strategy": "REPLACE"},
    )
    assert replace_resp.status_code == 200
    replaced_rules = replace_resp.json()
    rep_blocks = {r["block_name"] for r in replaced_rules}
    assert "MY_CUSTOM_BLOCK" not in rep_blocks  # Cleared by REPLACE
    assert "KEC-LT" in rep_blocks               # From KEC template


def test_openpyxl_exact_cell_value_verification(client: TestClient) -> None:
    """Verify actual cell values in exported XLSX workbook using openpyxl.

    Directly verifies A01's QA requirement: exact quantity cell values (e.g. 6 EA) and sheet integrity.
    """
    p_resp = client.post("/api/projects", json={"name": "Openpyxl XLSX Test"})
    proj_id = p_resp.json()["id"]

    dxf_bytes = DXF_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("basic_devices.dxf", dxf_bytes, "application/dxf")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    # 1. Apply standard template (maps LT-DL to LIGHT, OT-2P to OUTLET, SW-1 to SWITCH)
    client.post(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/apply-template",
        json={"template_id": "tpl_standard_elec", "merge_strategy": "REPLACE"},
    )

    # 2. Run detection and accept all candidates
    client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={"action": "ACCEPT_ALL"},
    )

    # 3. Download XLSX binary
    xlsx_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/export/xlsx")
    assert xlsx_resp.status_code == 200
    xlsx_bytes = xlsx_resp.content

    # 4. Parse workbook with openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    assert "Takeoff Summary" in wb.sheetnames
    assert "Takeoff Evidence" in wb.sheetnames

    # 5. Check 'Takeoff Summary' sheet cell values
    ws_summary = wb["Takeoff Summary"]
    headers = [str(cell.value) for cell in ws_summary[1]]
    assert any("item_code" in h for h in headers)
    assert any("quantity" in h for h in headers)
    assert any("unit" in h for h in headers)

    code_col = next(i + 1 for i, h in enumerate(headers) if "item_code" in h)
    qty_col = next(i + 1 for i, h in enumerate(headers) if "quantity" in h)
    unit_col = next(i + 1 for i, h in enumerate(headers) if "unit" in h)

    summary_data: dict[str, int] = {}
    for row in range(2, ws_summary.max_row + 1):
        code_val = ws_summary.cell(row=row, column=code_col).value
        qty_val = ws_summary.cell(row=row, column=qty_col).value
        unit_val = ws_summary.cell(row=row, column=unit_col).value
        if code_val:
            summary_data[str(code_val)] = int(qty_val)
            assert unit_val == "EA"

    # In basic_devices.dxf: 6 LT-DL -> LIGHT: 6 EA, 4 OT-2P -> OUTLET: 4 EA, 3 SW-1 -> SWITCH: 3 EA
    assert summary_data.get("LIGHT") == 6, f"Expected LIGHT to be 6 in XLSX cell, got {summary_data.get('LIGHT')}"
    assert summary_data.get("OUTLET") == 4, f"Expected OUTLET to be 4 in XLSX cell, got {summary_data.get('OUTLET')}"
    assert summary_data.get("SWITCH") == 3, f"Expected SWITCH to be 3 in XLSX cell, got {summary_data.get('SWITCH')}"

    # 6. Check 'Takeoff Evidence' sheet cell values
    ws_evidence = wb["Takeoff Evidence"]
    ev_headers = [str(cell.value) for cell in ws_evidence[1]]
    assert any("source_object_id" in h for h in ev_headers)
    assert any("inclusion_status" in h for h in ev_headers)

    inc_col = next(i + 1 for i, h in enumerate(ev_headers) if "inclusion_status" in h)
    included_count = 0
    for row in range(2, ws_evidence.max_row + 1):
        inc_val = ws_evidence.cell(row=row, column=inc_col).value
        if inc_val == "INCLUDED":
            included_count += 1

    # Total included rows must match total EA count: 6 + 4 + 3 = 13!
    assert included_count == 13, f"Expected 13 included evidence rows in XLSX, got {included_count}"


def test_seed_demo_project_workflow(client: TestClient) -> None:
    """Verify live demo project seeding with DXF, PDF, and Image drawings."""
    resp = client.post("/api/demo/seed")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "seeded"
    proj_id = data["project_id"]
    drawings = data["drawings"]
    assert len(drawings) == 3

    formats = {d["format"] for d in drawings}
    assert formats == {"DXF", "PDF", "IMAGE"}

    # Verify each seeded drawing has candidates and takeoff
    for d in drawings:
        dwg_id = d["id"]
        cands_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates")
        assert cands_resp.status_code == 200
        assert cands_resp.json()["summary"]["total"] > 0

        t_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff")
        assert t_resp.status_code == 200
        takeoff = t_resp.json()
        assert "summary" in takeoff
        assert "evidence" in takeoff
