"""Comprehensive tests for multi-format symbol candidate detection and bulk review (Issue #23).

Verifies:
1. DXF symbol detection (block INSERTs, layer heuristics).
2. Vector PDF symbol detection (text labels across multiple pages).
3. Raster Image symbol detection (color-coded and geometric clusters).
4. CRITICAL DOMAIN INVARIANT: Unreviewed (PROPOSED) candidates MUST NEVER contribute to Takeoff EA.
5. Bulk and individual review workflows (ACCEPT_ALL, REJECT_ALL, item remapping).
6. Takeoff aggregation & Excel/CSV export integration with verified candidates.
"""

from pathlib import Path

import pytest
from eai_api.app import app
from eai_api.storage import Storage
from fastapi.testclient import TestClient

DXF_FIXTURE_PATH = Path("fixtures/dxf/basic_devices.dxf")
PDF_FIXTURE_PATH = Path("fixtures/pdf/pdf_c_vector_features.pdf")
IMAGE_FIXTURE_PATH = Path("fixtures/images/floorplan_sample.png")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    from eai_api import app as app_module

    app_module.storage = Storage(root=tmp_path)
    return TestClient(app)


def test_detect_dxf_candidates(client: TestClient) -> None:
    """Verify DXF block INSERTs are detected as electrical candidates."""
    # 1. Create project & upload DXF
    p_resp = client.post("/api/projects", json={"name": "DXF Detection Test"})
    proj_id = p_resp.json()["id"]

    dxf_bytes = DXF_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("basic_devices.dxf", dxf_bytes, "application/dxf")},
    )
    assert up_resp.status_code == 200
    dwg_id = up_resp.json()["drawing_id"]

    # 2. Run detection
    det_resp = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")
    assert det_resp.status_code == 200
    data = det_resp.json()

    assert data["drawing_id"] == dwg_id
    assert data["summary"]["total"] > 0
    assert data["summary"]["proposed"] == data["summary"]["total"]
    assert data["summary"]["accepted"] == 0
    assert data["summary"]["rejected"] == 0

    # LT-DL blocks on layer E-LIGHT should be classified as LIGHT
    light_cands = [c for c in data["candidates"] if c["suggested_item_code"] == "LIGHT"]
    assert len(light_cands) >= 2
    for c in light_cands:
        assert c["coordinate_space"] == "WORLD"
        assert c["status"] == "PROPOSED"
        assert c["confidence"] >= 0.90
        assert c["detection_source"] == "DXF_BLOCK"


def test_detect_pdf_candidates(client: TestClient) -> None:
    """Verify Vector PDF text features across multiple pages are detected as candidates."""
    # 1. Create project & upload PDF
    p_resp = client.post("/api/projects", json={"name": "PDF Detection Test"})
    proj_id = p_resp.json()["id"]

    pdf_bytes = PDF_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("pdf_c_vector_features.pdf", pdf_bytes, "application/pdf")},
    )
    assert up_resp.status_code == 200
    dwg_id = up_resp.json()["drawing_id"]

    # 2. Run detection
    det_resp = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")
    assert det_resp.status_code == 200
    data = det_resp.json()

    assert data["summary"]["total"] >= 5
    cands = data["candidates"]

    # Verify Page 0 candidates: L-01, DB-1, EM-LIGHT
    p0_cands = [c for c in cands if c["page_index"] == 0]
    p0_codes = {c["suggested_item_code"] for c in p0_cands}
    assert "LIGHT" in p0_codes
    assert "PANEL" in p0_codes

    # Verify Page 1 candidates: OUTLET-1, SWITCH-2
    p1_cands = [c for c in cands if c["page_index"] == 1]
    p1_codes = {c["suggested_item_code"] for c in p1_cands}
    assert "OUTLET" in p1_codes
    assert "SWITCH" in p1_codes

    for c in cands:
        assert c["coordinate_space"] == "PDF_PAGE_POINT"
        assert c["detection_source"] == "PDF_VECTOR_RULE"
        assert c["status"] == "PROPOSED"


def test_detect_image_candidates(client: TestClient) -> None:
    """Verify raster image color clusters (yellow, sky, green) are detected with 100% precision."""
    # 1. Create project & upload image
    p_resp = client.post("/api/projects", json={"name": "Image Detection Test"})
    proj_id = p_resp.json()["id"]

    img_bytes = IMAGE_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", img_bytes, "image/png")},
    )
    assert up_resp.status_code == 200
    dwg_id = up_resp.json()["drawing_id"]

    # 2. Run detection
    det_resp = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")
    assert det_resp.status_code == 200
    data = det_resp.json()

    assert data["summary"]["total"] == 8
    assert data["summary"]["proposed"] == 8

    # 4 yellow lights, 2 sky outlets, 2 green switches
    counts: dict[str, int] = {}
    for c in data["candidates"]:
        counts[c["suggested_item_code"]] = counts.get(c["suggested_item_code"], 0) + 1
        assert c["coordinate_space"] == "IMAGE_PIXEL"
        assert c["page_index"] == 0
        assert c["detection_source"] == "IMAGE_TEMPLATE"
        assert c["status"] == "PROPOSED"

    assert counts["LIGHT"] == 4
    assert counts["OUTLET"] == 2
    assert counts["SWITCH"] == 2


def test_domain_invariant_unreviewed_candidates_produce_zero_takeoff(client: TestClient) -> None:
    """CRITICAL DOMAIN INVARIANT: Unreviewed candidates MUST NEVER pollute Takeoff EA quantities."""
    p_resp = client.post("/api/projects", json={"name": "Domain Invariant Test"})
    proj_id = p_resp.json()["id"]

    # Upload image drawing (which has no base CAD blocks)
    img_bytes = IMAGE_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", img_bytes, "image/png")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    # Run detection (finds 8 candidates)
    client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")

    # Fetch Takeoff
    t_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff")
    assert t_resp.status_code == 200
    takeoff = t_resp.json()

    # Total quantity must be strictly 0 EA
    total_qty = sum(r["quantity"] for r in takeoff["summary"])
    assert total_qty == 0
    # Evidence rows must contain 0 included items
    included_ev = [e for e in takeoff["evidence"] if e["inclusion_status"] == "INCLUDED"]
    assert len(included_ev) == 0


def test_candidate_bulk_review_and_takeoff_reflection(client: TestClient) -> None:
    """Verify ACCEPT_ALL bulk review immediately populates Takeoff Summary and Evidence."""
    p_resp = client.post("/api/projects", json={"name": "Bulk Review Test"})
    proj_id = p_resp.json()["id"]

    img_bytes = IMAGE_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", img_bytes, "image/png")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    # Detect 8 candidates
    client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")

    # Bulk Accept All
    rev_resp = client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={"action": "ACCEPT_ALL"},
    )
    assert rev_resp.status_code == 200
    rev_data = rev_resp.json()
    assert rev_data["summary"]["accepted"] == 8
    assert rev_data["summary"]["proposed"] == 0

    # Fetch Takeoff: now all 8 accepted candidates contribute to takeoff EA!
    t_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff")
    takeoff = t_resp.json()

    summary_map = {r["item_code"]: r["quantity"] for r in takeoff["summary"]}
    assert summary_map["LIGHT"] == 4
    assert summary_map["OUTLET"] == 2
    assert summary_map["SWITCH"] == 2
    assert sum(summary_map.values()) == 8

    # Verify evidence rows contain SYMBOL_CANDIDATE items with correct review reasons
    cand_evs = [e for e in takeoff["evidence"] if e["entity_type"] == "SYMBOL_CANDIDATE"]
    assert len(cand_evs) == 8
    for ev in cand_evs:
        assert ev["inclusion_status"] == "INCLUDED"
        assert ev["review_status"] == "REVIEWED"
        assert "IMAGE_PIXEL" in ev["coordinate_space"]

    # Verify Excel and CSV export include the accepted candidates
    csv_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/export/csv?type=evidence")
    assert csv_resp.status_code == 200
    assert "SYMBOL_CANDIDATE" in csv_resp.text

    xlsx_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/export/xlsx")
    assert xlsx_resp.status_code == 200
    assert len(xlsx_resp.content) > 1000


def test_candidate_selective_review_and_filtering(client: TestClient) -> None:
    """Verify selective review (filter by item code and REJECT_ALL)."""
    p_resp = client.post("/api/projects", json={"name": "Selective Review Test"})
    proj_id = p_resp.json()["id"]

    img_bytes = IMAGE_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", img_bytes, "image/png")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")

    # Accept only LIGHT candidates
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={"action": "ACCEPT_ALL", "filter_item_code": "LIGHT"},
    )

    # Reject OUTLET candidates
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={"action": "REJECT_ALL", "filter_item_code": "OUTLET"},
    )

    cand_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates")
    summary = cand_resp.json()["summary"]
    assert summary["accepted"] == 4  # 4 LIGHT accepted
    assert summary["rejected"] == 2  # 2 OUTLET rejected
    assert summary["proposed"] == 2  # 2 SWITCH still proposed

    # Takeoff should only include the 4 accepted LIGHTs
    t_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff")
    takeoff = t_resp.json()
    summary_map = {r["item_code"]: r["quantity"] for r in takeoff["summary"]}
    assert summary_map.get("LIGHT") == 4
    assert summary_map.get("OUTLET", 0) == 0
    assert summary_map.get("SWITCH", 0) == 0


def test_candidate_individual_reclassification(client: TestClient) -> None:
    """Verify modifying a candidate's item_code and status individually."""
    p_resp = client.post("/api/projects", json={"name": "Individual Review Test"})
    proj_id = p_resp.json()["id"]

    img_bytes = IMAGE_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", img_bytes, "image/png")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    det = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect").json()
    first_cand = det["candidates"][0]

    # Reclassify first candidate to EMERGENCY_LIGHT
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={
            "updates": [
                {
                    "candidate_id": first_cand["candidate_id"],
                    "status": "ACCEPTED",
                    "reviewed_item_code": "EM_LIGHT",
                    "review_note": "비상유도등으로 수동 재분류 승인",
                }
            ]
        },
    )

    t_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff")
    takeoff = t_resp.json()
    summary_map = {r["item_code"]: r["quantity"] for r in takeoff["summary"]}
    assert summary_map.get("EM_LIGHT") == 1


def test_candidate_preservation_on_redetect(client: TestClient) -> None:
    """Verify that re-running detection preserves existing user review decisions."""
    p_resp = client.post("/api/projects", json={"name": "Preservation Test"})
    proj_id = p_resp.json()["id"]

    img_bytes = IMAGE_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", img_bytes, "image/png")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    # Detect & bulk accept
    client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={"action": "ACCEPT_ALL"},
    )

    # Re-run detection
    det2 = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect").json()
    assert det2["summary"]["accepted"] == 8
    assert det2["summary"]["proposed"] == 0

