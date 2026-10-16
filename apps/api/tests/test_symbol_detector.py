"""Comprehensive tests for multi-format symbol candidate detection and bulk review (Issue #23).

Verifies:
1. DXF symbol detection (block INSERTs, layer heuristics).
2. Vector PDF symbol detection (text labels across multiple pages).
3. Raster Image symbol detection (color-coded and geometric clusters).
4. CRITICAL DOMAIN INVARIANT: Unreviewed (PROPOSED) candidates MUST NEVER contribute to Takeoff EA.
5. Bulk and individual review workflows (ACCEPT_ALL, REJECT_ALL, item remapping).
6. Takeoff aggregation & Excel/CSV export integration with verified candidates.
"""

import time
from pathlib import Path

import numpy as np
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


def test_p0_qty_01_no_duplicate_ea_for_mapped_cad_objects(client: TestClient) -> None:
    """[P0-QTY-01] Mapped DXF INSERT must not be double counted when candidate is accepted.
    Oracle: mapped LIGHT 1EA -> detect/approve -> still 1EA, Evidence included 1건, CSV/XLSX 1EA.
    """
    p_resp = client.post("/api/projects", json={"name": "P0-QTY-01 Test"})
    proj_id = p_resp.json()["id"]

    dxf_bytes = DXF_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("basic_devices.dxf", dxf_bytes, "application/dxf")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    # 1. Add block mapping: map LT-DL to LIGHT
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/mappings",
        json=[{"block_name": "LT-DL", "item_code": "LIGHT", "item_name": "다운라이트"}],
    )

    # Base takeoff before detection: 6 LT-DL blocks mapped to LIGHT -> 6 EA
    t_before = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff").json()
    summary_before = {r["item_code"]: r["quantity"] for r in t_before["summary"]}
    assert summary_before.get("LIGHT") == 6
    included_before = [e for e in t_before["evidence"] if e["inclusion_status"] == "INCLUDED" and e["mapped_item_code"] == "LIGHT"]
    assert len(included_before) == 6

    # 2. Run detection (finds candidates for LT-DL and unmapped OT-2P, SW-1)
    det_resp = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")
    assert det_resp.status_code == 200

    # 3. Accept all candidates
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={"action": "ACCEPT_ALL"},
    )

    # 4. Takeoff after approval: LIGHT MUST STILL BE EXACTLY 6 EA, NOT 12 EA! (P0-QTY-01)
    t_after = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff").json()
    summary_after = {r["item_code"]: r["quantity"] for r in t_after["summary"]}
    assert summary_after.get("LIGHT") == 6, f"Expected 6 EA but got {summary_after.get('LIGHT')}"

    included_after = [e for e in t_after["evidence"] if e["inclusion_status"] == "INCLUDED" and e["mapped_item_code"] == "LIGHT"]
    assert len(included_after) == 6, f"Expected exactly 6 included evidence rows, got {len(included_after)}"

    # 5. CSV and XLSX export must show 6 EA
    csv_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/export/csv?type=summary")
    assert csv_resp.status_code == 200
    assert "LIGHT,다운라이트,,EA,6" in csv_resp.text.replace(" ", "")

    xlsx_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/export/xlsx")
    assert xlsx_resp.status_code == 200
    assert len(xlsx_resp.content) > 1000


def test_p0_qty_02_blocked_dxf_cannot_be_revived_by_candidate_approval(client: TestClient) -> None:
    """[P0-QTY-02] Structurally blocked DXF INSERT (dynamic/anonymous) must not be revived by candidate approval.
    Oracle: blocked INSERT -> detector -> ACCEPT_ALL -> 0 included EA + UNRESOLVED warning.
    """
    p_resp = client.post("/api/projects", json={"name": "P0-QTY-02 Test"})
    proj_id = p_resp.json()["id"]

    anon_dxf_path = Path("fixtures/dxf/anonymous_and_dynamic.dxf")
    dxf_bytes = anon_dxf_path.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("anonymous_and_dynamic.dxf", dxf_bytes, "application/dxf")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    # 1. Run detection on dynamic/anonymous block drawing
    det_resp = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect")
    assert det_resp.status_code == 200
    cands = det_resp.json()["candidates"]
    assert len(cands) > 0
    # Every detected candidate from dynamic/anonymous blocks must be flagged as structurally blocked
    for c in cands:
        assert c["raw_evidence"].get("is_structurally_blocked") is True
        assert c["confidence"] == 0.0
        assert "검수불가" in c["suggested_item_name"]

    # 2. Call ACCEPT_ALL
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={"action": "ACCEPT_ALL"},
    )

    # 3. Takeoff must enforce 0 included EA and report UNRESOLVED
    t_resp = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff")
    takeoff = t_resp.json()

    included_ev = [e for e in takeoff["evidence"] if e["inclusion_status"] == "INCLUDED"]
    assert len(included_ev) == 0, f"Expected 0 included evidence rows, got {len(included_ev)}"

    for row in takeoff["summary"]:
        assert row["quantity"] == 0
        assert row["review_status"] == "UNRESOLVED"


def test_p0_qty_03_bulk_accept_reject_preserves_existing_decisions(client: TestClient) -> None:
    """[P0-QTY-03] Bulk ACCEPT_ALL/REJECT_ALL must only modify status == PROPOSED.
    Oracle: 1 accepted, 1 rejected, 1 proposed -> ACCEPT_ALL -> 2 accepted, 1 rejected;
    subsequent REJECT_ALL does not change previously decided 2 accepted and 1 rejected.
    """
    p_resp = client.post("/api/projects", json={"name": "P0-QTY-03 Test"})
    proj_id = p_resp.json()["id"]

    img_bytes = IMAGE_FIXTURE_PATH.read_bytes()
    up_resp = client.post(
        f"/api/projects/{proj_id}/drawings",
        files={"file": ("floorplan_sample.png", img_bytes, "image/png")},
    )
    dwg_id = up_resp.json()["drawing_id"]

    # 1. Detect candidates (8 candidates)
    det = client.post(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/detect").json()
    cands = det["candidates"]
    c1, c2 = cands[0], cands[1]

    # Pre-set 1 ACCEPTED, 1 REJECTED, and leave the remaining 6 as PROPOSED
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={
            "updates": [
                {"candidate_id": c1["candidate_id"], "status": "ACCEPTED", "review_note": "수동 승인 1"},
                {"candidate_id": c2["candidate_id"], "status": "REJECTED", "review_note": "수동 거부 2"},
            ]
        },
    )

    pre_check = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates").json()["summary"]
    assert pre_check["accepted"] == 1
    assert pre_check["rejected"] == 1
    assert pre_check["proposed"] == 6

    # 2. Call ACCEPT_ALL -> only the 6 PROPOSED items become ACCEPTED
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={"action": "ACCEPT_ALL"},
    )
    after_accept = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates").json()["summary"]
    assert after_accept["accepted"] == 7  # 1 pre-accepted + 6 newly accepted
    assert after_accept["rejected"] == 1  # 1 pre-rejected MUST REMAIN REJECTED!
    assert after_accept["proposed"] == 0

    # 3. Call REJECT_ALL -> since proposed is 0, nothing should change!
    client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates/review",
        json={"action": "REJECT_ALL"},
    )
    after_reject = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/candidates").json()["summary"]
    assert after_reject["accepted"] == 7, "ACCEPTED candidates must not be overridden by REJECT_ALL"
    assert after_reject["rejected"] == 1, "REJECTED candidates must remain 1"
    assert after_reject["proposed"] == 0


def test_p0_stab_04_image_clustering_complexity_and_large_block() -> None:
    """[P0-STAB-04] Verify O(1) incremental clustering on dense 100x100 mask + adjacent symbol.
    Oracle: finishes well under budget, outputs exactly 2 distinct clusters with no duplicates.
    """
    from eai_api.detector import _cluster_image_points

    # 500x500 binary mask with a 100x100 solid block (10,000 px) and a 20x20 block (400 px)
    mask = np.zeros((500, 500), dtype=bool)
    mask[50:150, 50:150] = True
    mask[300:320, 300:320] = True

    t0 = time.perf_counter()
    clusters = _cluster_image_points(mask, min_pixels=10, max_dist=30)
    elapsed = time.perf_counter() - t0

    # Must complete fast (under 100ms) with incremental complexity
    assert elapsed < 0.1, f"Clustering took too long: {elapsed * 1000:.1f}ms"
    assert len(clusters) == 2, f"Expected exactly 2 clusters, got {len(clusters)}"

    # Sort clusters by pixel count
    clusters.sort(key=lambda c: c["count"], reverse=True)
    large_c = clusters[0]
    small_c = clusters[1]

    assert large_c["count"] == 10000
    assert 95.0 <= large_c["cx"] <= 105.0
    assert 95.0 <= large_c["cy"] <= 105.0

    assert small_c["count"] == 400
    assert 305.0 <= small_c["cx"] <= 315.0
    assert 305.0 <= small_c["cy"] <= 315.0

