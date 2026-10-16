"""Tests for Issue #37: Scale Calibration, 2D Route Measurement, and Provisional Meter Quantities."""

from __future__ import annotations

import io
import math

import openpyxl
from eai_api.app import app
from eai_api.models import (
    RouteCategory,
    RouteStatus,
)
from fastapi.testclient import TestClient

client = TestClient(app)


def test_route_oracle_7m_verification() -> None:
    """Workstream D: Test synthetic oracle fixture where 100px = 10m and a 70px path yields exactly 7.00m."""
    seed_res = client.post("/api/demo/seed-route-oracle?reset=true")
    assert seed_res.status_code == 200, seed_res.text
    data = seed_res.json()
    assert data["status"] == "seeded"
    proj_id = data["project_id"]
    dwg_id = data["drawing_id"]
    assert data["expected_length_m"] == 7.0

    # 1. Verify Calibration Data
    calib_res = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/calibration?page_index=0")
    assert calib_res.status_code == 200
    calib = calib_res.json()
    assert calib["is_calibrated"] is True
    # 100px = 10m -> scale_ratio = 0.1 m/px
    assert math.isclose(calib["scale_ratio_m_per_unit"], 0.1, abs_tol=1e-5)
    assert calib["real_world_distance_m"] == 10.0
    assert calib["pixel_distance"] == 100.0

    # 2. Verify Route Data
    routes_res = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/routes")
    assert routes_res.status_code == 200
    routes = routes_res.json()
    assert len(routes) == 1
    r = routes[0]
    assert r["category"] == RouteCategory.WIRING
    assert r["is_calibrated"] is True
    assert math.isclose(r["raw_length"], 70.0, abs_tol=1e-3)
    assert r["length_2d_m"] == 7.0  # Exactly 7.00 m (distinct from hypotenuse diagonal 50px = 5.0m)
    assert r["status"] == RouteStatus.PROVISIONAL_CONFIRMED

    # 3. Verify Single Drawing Takeoff
    takeoff_res = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff")
    assert takeoff_res.status_code == 200
    t_data = takeoff_res.json()
    assert t_data["is_provisional"] is True  # 2D routes are always provisional plans

    wiring_rows = [row for row in t_data["summary"] if row["item_code"] == "WIRING_POWER"]
    assert len(wiring_rows) == 1
    w_row = wiring_rows[0]
    assert w_row["unit"] == "m"  # Explicitly 'm'
    assert w_row["quantity"] == 7.0
    assert w_row["quantity_method"] == "MANUAL"
    assert w_row["review_status"] == "REVIEWED"

    # 4. Verify Project Takeoff
    proj_takeoff_res = client.get(f"/api/projects/{proj_id}/takeoff")
    assert proj_takeoff_res.status_code == 200
    p_data = proj_takeoff_res.json()
    assert p_data["total_route_length_m"] == 7.0
    assert p_data["total_equipment_ea"] == 0

    p_summary = {row["item_code"]: row for row in p_data["summary"]}
    assert "WIRING_POWER" in p_summary
    assert p_summary["WIRING_POWER"]["total_quantity"] == 7.0
    assert p_summary["WIRING_POWER"]["unit"] == "m"


def test_calibration_two_point_manual_and_route_recalculation() -> None:
    """Workstream A & B: Uncalibrated drawing gives 0m warning; calibration recalculates routes."""
    # Seed oracle first to have a base project
    seed_res = client.post("/api/demo/seed-route-oracle?reset=true")
    proj_id = seed_res.json()["project_id"]
    dwg_id = seed_res.json()["drawing_id"]

    # Delete existing calibration to simulate uncalibrated drawing
    del_res = client.delete(f"/api/projects/{proj_id}/drawings/{dwg_id}/calibration?page_index=0")
    assert del_res.status_code == 200

    # Route should now be uncalibrated (length_2d_m is None)
    routes = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/routes").json()
    assert len(routes) == 1
    assert routes[0]["is_calibrated"] is False
    assert routes[0]["length_2d_m"] is None

    # Takeoff should report 0.0m with UNRESOLVED status
    t_data = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/takeoff").json()
    w_row = next(r for r in t_data["summary"] if r["item_code"] == "WIRING_POWER")
    assert w_row["quantity"] == 0.0
    assert w_row["review_status"] == "UNRESOLVED"

    # Now apply new calibration: 50px = 25m -> ratio = 0.5 m/px
    new_calib_res = client.post(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/calibration",
        json={
            "page_index": 0,
            "point_a": {"x": 0.0, "y": 0.0},
            "point_b": {"x": 50.0, "y": 0.0},
            "real_distance": 25.0,
            "unit": "m",
            "notes": "50px = 25m 보정",
        },
    )
    assert new_calib_res.status_code == 200
    calib = new_calib_res.json()
    assert calib["is_calibrated"] is True
    assert math.isclose(calib["scale_ratio_m_per_unit"], 0.5, abs_tol=1e-5)

    # Route automatically recalculated: 70px * 0.5 = 35.00m!
    routes_after = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/routes").json()
    assert routes_after[0]["is_calibrated"] is True
    assert routes_after[0]["length_2d_m"] == 35.0


def test_calibration_invalid_inputs_rejected() -> None:
    """Workstream A: Zero, negative, NaN distances or coincident points are rejected."""
    seed_res = client.post("/api/demo/seed-route-oracle?reset=true")
    proj_id = seed_res.json()["project_id"]
    dwg_id = seed_res.json()["drawing_id"]

    # 1. Zero or negative distance
    res1 = client.post(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/calibration",
        json={
            "page_index": 0,
            "point_a": {"x": 0.0, "y": 0.0},
            "point_b": {"x": 100.0, "y": 0.0},
            "real_distance": 0.0,
            "unit": "m",
        },
    )
    assert res1.status_code in (400, 422)

    res2 = client.post(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/calibration",
        json={
            "page_index": 0,
            "point_a": {"x": 0.0, "y": 0.0},
            "point_b": {"x": 100.0, "y": 0.0},
            "real_distance": -5.0,
            "unit": "m",
        },
    )
    assert res2.status_code in (400, 422)

    # 2. Coincident points (distance = 0)
    res3 = client.post(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/calibration",
        json={
            "page_index": 0,
            "point_a": {"x": 50.0, "y": 50.0},
            "point_b": {"x": 50.0, "y": 50.0},
            "real_distance": 10.0,
            "unit": "m",
        },
    )
    assert res3.status_code == 400


def test_route_crud_and_status_filtering() -> None:
    """Workstream B & C: CRUD operations, draft exclusion, and deletion returns to 0m."""
    seed_res = client.post("/api/demo/seed-route-oracle?reset=true")
    proj_id = seed_res.json()["project_id"]
    dwg_id = seed_res.json()["drawing_id"]

    # 1. Reject route with fewer than 2 points
    bad_route_res = client.post(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/routes",
        json={
            "page_index": 0,
            "points": [{"x": 10.0, "y": 10.0}],
            "category": "CONDUIT",
        },
    )
    assert bad_route_res.status_code in (400, 422)

    # 2. Create conduit route with 2 points: (0,0) -> (40,0) = 40px -> 4.00m (since 100px=10m)
    c_route_res = client.post(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/routes",
        json={
            "page_index": 0,
            "points": [{"x": 0.0, "y": 0.0}, {"x": 40.0, "y": 0.0}],
            "category": "CONDUIT",
            "item_code": "CONDUIT_PVC",
            "item_name": "전선관 (2D 계획 경로)",
            "spec": "HI-PVC 16C",
            "status": "PROVISIONAL_CONFIRMED",
        },
    )
    assert c_route_res.status_code == 201
    c_route = c_route_res.json()
    c_id = c_route["id"]
    assert c_route["length_2d_m"] == 4.0

    # Verify both routes are in takeoff: 7m WIRING + 4m CONDUIT = 11.0m total
    p_takeoff = client.get(f"/api/projects/{proj_id}/takeoff").json()
    assert p_takeoff["total_route_length_m"] == 11.0

    # 3. Change conduit status to DRAFT -> should be excluded from takeoff sum
    update_res = client.put(
        f"/api/projects/{proj_id}/drawings/{dwg_id}/routes/{c_id}",
        json={"status": "DRAFT"},
    )
    assert update_res.status_code == 200
    p_takeoff2 = client.get(f"/api/projects/{proj_id}/takeoff").json()
    assert p_takeoff2["total_route_length_m"] == 7.0

    # 4. Delete conduit route
    del_res = client.delete(f"/api/projects/{proj_id}/drawings/{dwg_id}/routes/{c_id}")
    assert del_res.status_code == 200

    # 5. Delete wiring route -> total becomes 0.0m
    w_id = seed_res.json()["route"]["id"]
    client.delete(f"/api/projects/{proj_id}/drawings/{dwg_id}/routes/{w_id}")
    p_takeoff_zero = client.get(f"/api/projects/{proj_id}/takeoff").json()
    assert p_takeoff_zero["total_route_length_m"] == 0.0


def test_ea_and_m_unit_isolation_in_project_takeoff() -> None:
    """Workstream C: Equipment EA counts and route meter lengths must NEVER be mixed."""
    # Seed 4-drawing project: 1F REV0 (6 LIGHT) + 2F REV0 (8 LIGHT) = 14 LIGHT EA
    multi_res = client.post("/api/demo/seed-multi-drawing?reset=true")
    assert multi_res.status_code == 200
    proj_id = multi_res.json()["project_id"]
    drawings = multi_res.json()["drawings"]
    f1_id = drawings[0]["drawing_id"]

    # Calibrate 1F: 100 units = 10m
    client.post(
        f"/api/projects/{proj_id}/drawings/{f1_id}/calibration",
        json={
            "page_index": 0,
            "point_a": {"x": 0.0, "y": 0.0},
            "point_b": {"x": 100.0, "y": 0.0},
            "real_distance": 10.0,
            "unit": "m",
        },
    )

    # Add 7m route to 1F: (0,0) -> (30,0) -> (30,40)
    client.post(
        f"/api/projects/{proj_id}/drawings/{f1_id}/routes",
        json={
            "page_index": 0,
            "points": [{"x": 0.0, "y": 0.0}, {"x": 30.0, "y": 0.0}, {"x": 30.0, "y": 40.0}],
            "category": "WIRING",
            "item_code": "WIRING_LIGHT",
            "item_name": "전등 배선 (2D 계획)",
            "spec": "HFIX 2.5sq",
            "status": "PROVISIONAL_CONFIRMED",
        },
    )

    p_data = client.get(f"/api/projects/{proj_id}/takeoff").json()

    # Invariant: total_equipment_ea is 14 (6+8 LIGHT) + 8 OUTLET + 6 SWITCH = 28 EA
    summary = {row["item_code"]: row for row in p_data["summary"]}
    assert summary["LIGHT"]["unit"] == "EA"
    assert summary["LIGHT"]["total_quantity"] == 14
    assert summary["WIRING_LIGHT"]["unit"] == "m"
    assert summary["WIRING_LIGHT"]["total_quantity"] == 7.0

    assert p_data["total_equipment_ea"] == 28
    assert p_data["total_route_length_m"] == 7.0


def test_excel_export_contains_route_measurements_sheet() -> None:
    """Workstream C: XLSX export includes Route Measurements sheet with formula injection protection."""
    seed_res = client.post("/api/demo/seed-route-oracle?reset=true")
    proj_id = seed_res.json()["project_id"]
    dwg_id = seed_res.json()["drawing_id"]

    # 1. Single drawing XLSX
    dwg_xlsx_res = client.get(f"/api/projects/{proj_id}/drawings/{dwg_id}/export/xlsx")
    assert dwg_xlsx_res.status_code == 200
    wb_dwg = openpyxl.load_workbook(io.BytesIO(dwg_xlsx_res.content))
    assert "Takeoff Summary" in wb_dwg.sheetnames
    assert "Takeoff Evidence" in wb_dwg.sheetnames
    assert "Route Measurements" in wb_dwg.sheetnames

    ws_r = wb_dwg["Route Measurements"]
    assert ws_r.max_row >= 2
    # Verify row 2 contains 7.0m
    found_7m = any(ws_r.cell(row=2, column=c).value == 7.0 for c in range(1, ws_r.max_column + 1))
    assert found_7m

    # 2. Project XLSX
    proj_xlsx_res = client.get(f"/api/projects/{proj_id}/export/xlsx")
    assert proj_xlsx_res.status_code == 200
    wb_proj = openpyxl.load_workbook(io.BytesIO(proj_xlsx_res.content))
    assert "Project Summary" in wb_proj.sheetnames
    assert "Drawing Breakdown" in wb_proj.sheetnames
    assert "Revision Delta" in wb_proj.sheetnames
    assert "Evidence" in wb_proj.sheetnames
    assert "Route Measurements" in wb_proj.sheetnames

    # Formula injection defense check across all sheets
    for sheet in wb_proj.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                assert cell.data_type != "f", f"Formula injection vulnerability at {cell.coordinate}: {cell.value}"
