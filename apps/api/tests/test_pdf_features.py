"""Tests for PR C Vector PDF text, line, and path feature extraction (Issue #22)."""

from __future__ import annotations

from pathlib import Path

import pytest
from eai_api.app import app
from eai_api.pdf_features import extract_pdf_page_features
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_pdf_features_extraction_direct() -> None:
    """Test extract_pdf_page_features directly against pdf_c_vector_features.pdf."""
    pdf_path = Path("fixtures/pdf/pdf_c_vector_features.pdf")
    assert pdf_path.exists(), "pdf_c_vector_features.pdf must exist"
    pdf_bytes = pdf_path.read_bytes()

    # Page 0: ROT 0, 612x792
    f0 = extract_pdf_page_features(pdf_bytes, 0, "test_doc")
    assert f0.page_index == 0
    assert f0.rotation == 0
    assert f0.coordinate_space == "PDF_PAGE_POINT"
    assert len(f0.texts) == 3
    texts_p0 = [t.text for t in f0.texts]
    assert "L-01" in texts_p0
    assert "DB-1" in texts_p0
    assert "EM-LIGHT" in texts_p0
    assert len(f0.paths) >= 3
    assert any(p.type == "rect" for p in f0.paths)
    assert any(p.type == "line" for p in f0.paths)

    # Page 1: ROT 90, CropBox [24, 24, 776, 576]
    f1 = extract_pdf_page_features(pdf_bytes, 1, "test_doc")
    assert f1.page_index == 1
    assert f1.rotation == 90
    assert len(f1.texts) == 2
    texts_p1 = [t.text for t in f1.texts]
    assert "OUTLET-1" in texts_p1
    assert "SWITCH-2" in texts_p1
    assert len(f1.paths) >= 2


def test_pdf_features_scanned_page_no_text_ocr() -> None:
    """Requirement 5: Scanned raster PDF must extract 0 texts (strictly no OCR)."""
    pdf_path = Path("fixtures/pdf/pdf_b_scanned_mixed.pdf")
    assert pdf_path.exists()
    pdf_bytes = pdf_path.read_bytes()

    f_scanned = extract_pdf_page_features(pdf_bytes, 0, "test_scanned")
    assert len(f_scanned.texts) == 0, "Raster scan page must have 0 extracted vector texts"


def test_pdf_features_api_endpoint_and_cache(client: TestClient) -> None:
    """Test GET /api/projects/{p}/drawings/{d}/pages/{idx}/features end-to-end."""
    # 1. Create project & upload pdf_c_vector_features.pdf
    p_resp = client.post("/api/projects", json={"name": "PR C Test Project"})
    assert p_resp.status_code == 200
    project_id = p_resp.json()["id"]

    pdf_bytes = Path("fixtures/pdf/pdf_c_vector_features.pdf").read_bytes()
    up_resp = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": ("features.pdf", pdf_bytes, "application/pdf")},
    )
    assert up_resp.status_code == 200
    drawing_id = up_resp.json()["drawing_id"]

    # 2. Extract features Page 0
    resp_p0 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/pages/0/features")
    assert resp_p0.status_code == 200
    data_p0 = resp_p0.json()
    assert data_p0["drawing_id"] == drawing_id
    assert data_p0["page_index"] == 0
    assert data_p0["coordinate_space"] == "PDF_PAGE_POINT"
    assert len(data_p0["texts"]) == 3
    assert data_p0["texts"][0]["extraction_method"] == "PDF_TEXT"
    assert data_p0["texts"][0]["confidence"] == "RAW_VECTOR"

    # 3. Extract features Page 1
    resp_p1 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/pages/1/features")
    assert resp_p1.status_code == 200
    data_p1 = resp_p1.json()
    assert data_p1["page_index"] == 1
    assert data_p1["rotation"] == 90
    assert len(data_p1["texts"]) == 2

    # 4. Out of bounds page index returns 404
    resp_err = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/pages/99/features")
    assert resp_err.status_code == 404

    resp_neg = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/pages/-1/features")
    assert resp_neg.status_code == 404

    # 5. Verify caching: second call returns same payload
    resp_cached = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/pages/0/features")
    assert resp_cached.status_code == 200
    assert resp_cached.json() == data_p0


def test_pdf_features_domain_invariant_zero_ea_takeoff(client: TestClient) -> None:
    """Requirement 4: Domain Invariant - Extracted features must NEVER pollute Takeoff.

    Without human manual markers, Takeoff summary MUST be total_quantity = 0 EA.
    """
    p_resp = client.post("/api/projects", json={"name": "PR C Takeoff Invariant"})
    assert p_resp.status_code == 200
    project_id = p_resp.json()["id"]

    pdf_bytes = Path("fixtures/pdf/pdf_c_vector_features.pdf").read_bytes()
    up_resp = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": ("features.pdf", pdf_bytes, "application/pdf")},
    )
    drawing_id = up_resp.json()["drawing_id"]

    # Extract features for both pages
    client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/pages/0/features")
    client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/pages/1/features")

    # Inspect Takeoff: MUST be 0 EA
    t_resp = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff")
    assert t_resp.status_code == 200
    t_data = t_resp.json()
    assert len(t_data["summary"]) == 0
    assert len(t_data["evidence"]) == 0

    # Add 1 human manual marker: Takeoff becomes exactly 1 EA
    m_resp = client.post(
        f"/api/projects/{project_id}/drawings/{drawing_id}/manual-objects",
        json={
            "id": "manual_single_light",
            "drawing_id": drawing_id,
            "x": 100.0,
            "y": 150.0,
            "item_code": "LIGHT",
            "item_name": "다운라이트",
            "unit": "EA",
            "note": "사용자 수동 지정",
            "page_index": 0,
        },
    )
    assert m_resp.status_code == 200

    t_resp2 = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/takeoff")
    assert t_resp2.status_code == 200
    t_data2 = t_resp2.json()
    assert len(t_data2["summary"]) == 1
    assert t_data2["summary"][0]["item_code"] == "LIGHT"
    assert t_data2["summary"][0]["quantity"] == 1


def test_pdf_features_dxf_drawing_rejection(client: TestClient) -> None:
    """Non-PDF drawings must reject feature extraction with 400 Bad Request."""
    p_resp = client.post("/api/projects", json={"name": "DXF Rejection Test"})
    project_id = p_resp.json()["id"]

    dxf_bytes = Path("fixtures/dxf/basic_devices.dxf").read_bytes()
    up_resp = client.post(
        f"/api/projects/{project_id}/drawings",
        files={"file": ("basic_devices.dxf", dxf_bytes, "application/dxf")},
    )
    drawing_id = up_resp.json()["drawing_id"]

    f_resp = client.get(f"/api/projects/{project_id}/drawings/{drawing_id}/pages/0/features")
    assert f_resp.status_code == 400
    assert "PDF 도면만" in f_resp.json()["detail"]
