"""Tests for visual symbol template search engine and demo reseed idempotency (Issue #29)."""

from __future__ import annotations

from pathlib import Path

import pytest
from eai_api.app import app
from eai_api.models import CandidateBulkReviewRequest, CandidateReviewUpdate, CandidateStatus
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


def test_demo_reseed_idempotency_and_preservation(client: TestClient) -> None:
    """Verify P1-DEMO-RESEED: calling /api/demo/seed repeatedly does NOT accumulate drawings and preserves user reviews."""
    from eai_api import app as app_module

    # 1. Initial seed
    res1 = client.post("/api/demo/seed")
    assert res1.status_code == 200
    data1 = res1.json()
    proj_id = data1["project_id"]
    drawings1 = data1["drawings"]
    assert len(drawings1) == 3

    # Check total drawings in storage
    all_drawings_init = app_module.storage.list_drawings(proj_id)
    assert len(all_drawings_init) == 3

    # 2. Simulate user reviewing candidates on the image drawing
    img_dwg = next(d for d in drawings1 if d["source_type"] == "IMAGE")
    img_dwg_id = img_dwg["drawing_id"]
    cands_res = client.get(f"/api/projects/{proj_id}/drawings/{img_dwg_id}/candidates")
    cands = cands_res.json()["candidates"]
    assert len(cands) >= 2

    # Accept the first candidate and reject the second
    target_accept_id = cands[0]["candidate_id"]
    target_reject_id = cands[1]["candidate_id"]

    bulk_req = CandidateBulkReviewRequest(
        updates=[
            CandidateReviewUpdate(candidate_id=target_accept_id, status=CandidateStatus.ACCEPTED),
            CandidateReviewUpdate(candidate_id=target_reject_id, status=CandidateStatus.REJECTED),
        ]
    )
    rev_res = client.put(
        f"/api/projects/{proj_id}/drawings/{img_dwg_id}/candidates/review",
        json=bulk_req.model_dump(mode="json"),
    )
    assert rev_res.status_code == 200

    # 3. Second seed call with default reset=False (Idempotent No-op)
    res2 = client.post("/api/demo/seed")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["project_id"] == proj_id

    # Crucial assertions: drawings count must remain EXACTLY 3 (no duplication)
    all_drawings_after = app_module.storage.list_drawings(proj_id)
    assert len(all_drawings_after) == 3, f"Expected 3 drawings, but found {len(all_drawings_after)}"

    # Crucial assertion: user reviews MUST NOT be overwritten or lost
    cands_after_res = client.get(f"/api/projects/{proj_id}/drawings/{img_dwg_id}/candidates")
    cands_after = cands_after_res.json()["candidates"]
    c_map = {c["candidate_id"]: c["status"] for c in cands_after}
    assert c_map[target_accept_id] == "ACCEPTED", "User ACCEPTED review decision was overwritten!"
    assert c_map[target_reject_id] == "REJECTED", "User REJECTED review decision was overwritten!"

    # 4. Explicit reset=True wipes and re-seeds clean
    res3 = client.post("/api/demo/seed?reset=true")
    assert res3.status_code == 200
    all_drawings_reset = app_module.storage.list_drawings(proj_id)
    assert len(all_drawings_reset) == 3
    cands_reset_res = client.get(f"/api/projects/{proj_id}/drawings/{img_dwg_id}/candidates")
    cands_reset = cands_reset_res.json()["candidates"]
    c_reset_map = {c["candidate_id"]: c["status"] for c in cands_reset}
    assert c_reset_map[target_accept_id] == "PROPOSED"


def test_visual_search_image(client: TestClient) -> None:
    """Verify visual template matching on raster image drawing finds all instances of the cropped symbol."""
    p_resp = client.post("/api/projects", json={"name": "Visual Search Image Test"})
    proj_id = p_resp.json()["id"]

    img_bytes = IMAGE_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", img_bytes, "image/png")},
    )
    assert up_resp.status_code == 200
    dwg_id = up_resp.json()["drawing_id"]

    # Crop one of the 4 lights at [227, 227, 273, 273]
    search_req = {
        "sample_bbox": [227.0, 227.0, 273.0, 273.0],
        "page_index": 0,
        "suggested_item_code": "LIGHT",
        "suggested_item_name": "다운라이트 조명",
        "threshold": 0.80,
    }
    s_resp = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/search-symbol", json=search_req)
    assert s_resp.status_code == 200
    data = s_resp.json()

    assert data["drawing_id"] == dwg_id
    assert data["total_found"] == 4  # All 4 lights found
    assert len(data["candidates"]) == 4

    for c in data["candidates"]:
        assert c["suggested_item_code"] == "LIGHT"
        assert c["detection_source"] == "VISUAL_TEMPLATE"
        assert c["coordinate_space"] == "IMAGE_PIXEL"
        assert c["confidence"] >= 0.80
        assert "similarity_score" in c["raw_evidence"]
        assert c["status"] == "PROPOSED"

    # Verify candidates are persisted in storage
    all_cands = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates").json()["candidates"]
    assert any(c["detection_source"] == "VISUAL_TEMPLATE" for c in all_cands)


def test_visual_search_pdf(client: TestClient) -> None:
    """Verify visual template matching on vector PDF drawing finds rendered symbol in PDF points."""
    p_resp = client.post("/api/projects", json={"name": "Visual Search PDF Test"})
    proj_id = p_resp.json()["id"]

    pdf_bytes = PDF_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("pdf_c_vector_features.pdf", pdf_bytes, "application/pdf")},
    )
    assert up_resp.status_code == 200
    dwg_id = up_resp.json()["drawing_id"]

    # Search L-01 text/symbol patch on page 0
    search_req = {
        "sample_bbox": [95.0, 75.0, 130.0, 98.0],
        "page_index": 0,
        "suggested_item_code": "LIGHT",
        "suggested_item_name": "조명",
        "threshold": 0.75,
    }
    s_resp = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/search-symbol", json=search_req)
    assert s_resp.status_code == 200
    data = s_resp.json()

    assert data["total_found"] >= 1
    first_cand = data["candidates"][0]
    assert first_cand["detection_source"] == "VISUAL_TEMPLATE"
    assert first_cand["coordinate_space"] == "PDF_PAGE_POINT"
    assert first_cand["page_index"] == 0
    assert first_cand["confidence"] >= 0.75


def test_visual_search_dxf(client: TestClient) -> None:
    """Verify visual template matching on DXF finds block occurrences overlapping selection."""
    p_resp = client.post("/api/projects", json={"name": "Visual Search DXF Test"})
    proj_id = p_resp.json()["id"]

    dxf_bytes = DXF_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("basic_devices.dxf", dxf_bytes, "application/dxf")},
    )
    assert up_resp.status_code == 200
    dwg_id = up_resp.json()["drawing_id"]

    # BBox overlapping LT-DL block at (1000, 2000)
    search_req = {
        "sample_bbox": [950.0, 1950.0, 1050.0, 2050.0],
        "suggested_item_code": "LIGHT",
        "suggested_item_name": "조명기구",
    }
    s_resp = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/search-symbol", json=search_req)
    assert s_resp.status_code == 200
    data = s_resp.json()

    assert data["total_found"] == 6  # All 6 LT-DL blocks in drawing
    assert all(c["detection_source"] == "VISUAL_TEMPLATE" for c in data["candidates"])


def test_visual_search_validation_errors(client: TestClient) -> None:
    """Verify input validation: sample bbox too small, or non-existent drawing."""
    p_resp = client.post("/api/projects", json={"name": "Validation Test"})
    proj_id = p_resp.json()["id"]

    img_bytes = IMAGE_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", img_bytes, "image/png")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    # 1. Bbox too small (width < 4px)
    too_small_req = {
        "sample_bbox": [10.0, 10.0, 12.0, 12.0],
        "suggested_item_code": "LIGHT",
    }
    bad_resp = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/search-symbol", json=too_small_req)
    assert bad_resp.status_code == 400
    assert "너무 작습니다" in bad_resp.json()["detail"]

    # 2. Non-existent drawing
    not_found = client.post(
        f"/api/projects/{proj_id}/drawings/dwg_non_existent/search-symbol",
        json={"sample_bbox": [10.0, 10.0, 50.0, 50.0]},
    )
    assert not_found.status_code == 404
