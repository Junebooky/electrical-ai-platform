"""Independent verification tests comparing cad_engine output against declared fixture expectations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cad_engine import DxfLoadError, parse_dxf
from cad_engine.takeoff import BlockMapping, Disposition, aggregate

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "dxf"


def test_fixtures_dir_exists() -> None:
    assert FIXTURES_DIR.exists()


def get_expected_files() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.expected.json"))


@pytest.mark.parametrize("expected_file", get_expected_files(), ids=lambda p: p.stem)
def test_fixture_against_expectation(expected_file: Path) -> None:
    expected_data = json.loads(expected_file.read_text(encoding="utf-8"))
    base_name = expected_file.name.replace(".expected.json", "")
    filename = expected_data.get("filename", f"{base_name}.dxf")
    dxf_path = FIXTURES_DIR / filename
    assert dxf_path.exists(), f"Missing fixture file: {dxf_path}"

    raw_bytes = dxf_path.read_bytes()

    # Check for expected errors (e.g. malformed inputs)
    expect_error = expected_data.get("expect_error")
    if expect_error:
        with pytest.raises(DxfLoadError) as exc_info:
            parse_dxf(raw_bytes, filename=filename)
        assert exc_info.value.code == expect_error
        return

    # Normal parse
    drawing = parse_dxf(raw_bytes, filename=filename)
    assert drawing.source.filename == filename
    assert drawing.source.size_bytes == len(raw_bytes)

    # 1. Check INSUNITS
    if "insunits" in expected_data and expected_data["insunits"] is not None:
        assert drawing.dxf.insunits == expected_data["insunits"]

    # 2. Check top-level inserts
    expected_top = expected_data.get("top_level_inserts", {})
    actual_top = {
        b.name: b.top_level_insert_count
        for b in drawing.blocks
        if b.top_level_insert_count > 0
    }
    for b_name, count in expected_top.items():
        assert actual_top.get(b_name, 0) == count, f"Mismatch in top-level inserts for {b_name}"

    # 3. Check nested inserts
    expected_nested = expected_data.get("nested_inserts", {})
    actual_nested = {
        b.name: b.nested_insert_count
        for b in drawing.blocks
        if b.nested_insert_count > 0
    }
    for b_name, count in expected_nested.items():
        assert actual_nested.get(b_name, 0) == count, f"Mismatch in nested inserts for {b_name}"

    # 4. Check expected warnings
    expected_warnings = set(expected_data.get("warnings", []))
    actual_warnings = {w.code.value for w in drawing.warnings}
    for w in expected_warnings:
        assert w in actual_warnings, f"Expected warning '{w}' not found in actual: {actual_warnings}"

    # 5. Check absent warnings
    absent_warnings = set(expected_data.get("absent_warnings", []))
    for w in absent_warnings:
        assert w not in actual_warnings, f"Warning '{w}' was unexpectedly present in: {actual_warnings}"

    # 6. Check insert_checks (coordinates, rotation, attributes, bbox)
    for check in expected_data.get("insert_checks", []):
        target_block = check["block"]
        target_x = check.get("x")
        target_y = check.get("y")
        target_depth = check.get("depth", 0)

        # find matching object
        candidates = [
            o for o in drawing.objects
            if (o.block_name == target_block or o.effective_block_name == target_block)
            and o.depth == target_depth
        ]
        if target_x is not None and target_y is not None:
            candidates = [
                o for o in candidates
                if o.insert_point and abs(o.insert_point[0] - target_x) < 1e-3 and abs(o.insert_point[1] - target_y) < 1e-3
            ]
        assert len(candidates) > 0, f"No matching object found for check: {check}"
        matched = candidates[0]

        if "rotation" in check:
            assert matched.rotation_deg is not None
            assert abs(matched.rotation_deg - check["rotation"]) < 1e-2

        if "attributes" in check:
            for k, v in check["attributes"].items():
                assert matched.attributes.get(k) == v

        if "bbox" in check:
            exp_min, exp_max = check["bbox"]
            assert matched.bbox is not None
            assert abs(matched.bbox.min[0] - exp_min[0]) < 1.0
            assert abs(matched.bbox.min[1] - exp_min[1]) < 1.0
            assert abs(matched.bbox.max[0] - exp_max[0]) < 1.0
            assert abs(matched.bbox.max[1] - exp_max[1]) < 1.0

        if "effective_block_name" in check:
            assert matched.effective_block_name == check["effective_block_name"]

    # 7. Check aggregation results
    mappings_cfg = expected_data.get("mappings")
    if mappings_cfg:
        mappings = [BlockMapping(**m) for m in mappings_cfg]
        agg_result = aggregate(drawing, mappings)
        expected_counts = expected_data.get("expected_counts", {})
        assert agg_result.counts == expected_counts, f"Counts mismatch: {agg_result.counts} != {expected_counts}"

        if "expected_unresolved" in expected_data:
            unresolved = len(agg_result.ids(Disposition.UNRESOLVED))
            assert unresolved == expected_data["expected_unresolved"]

        if "expected_unmapped" in expected_data:
            unmapped = len(agg_result.ids(Disposition.UNMAPPED))
            assert unmapped == expected_data["expected_unmapped"]

    # 8. Check texts
    for exp_text in expected_data.get("texts", []):
        all_texts = [o.text for o in drawing.objects if o.text] + [p.text for p in drawing.primitives if p.text]
        assert any(exp_text in (t or "") for t in all_texts), f"Text '{exp_text}' not found in drawing"


def test_layer_specific_mapping_priority_and_order_invariance() -> None:
    """Issue #9 / DEC-013: Layer-specific rule takes precedence over general rule regardless of mapping order."""
    dxf_path = FIXTURES_DIR / "basic_devices.dxf"
    drawing = parse_dxf(dxf_path.read_bytes(), filename=dxf_path.name)

    # In basic_devices.dxf, LT-DL objects are on layer "E-LIGHT"
    general_rule = BlockMapping(block_name="LT-DL", layer=None, item_code="GENERAL_ITEM")
    layer_rule = BlockMapping(block_name="LT-DL", layer="E-LIGHT", item_code="LAYER_LIGHT")

    # Order A: [General, Layer]
    res_a = aggregate(drawing, [general_rule, layer_rule])
    assert res_a.counts.get("LAYER_LIGHT") == 6
    assert "GENERAL_ITEM" not in res_a.counts

    # Order B: [Layer, General] (order inversion)
    res_b = aggregate(drawing, [layer_rule, general_rule])
    assert res_b.counts.get("LAYER_LIGHT") == 6
    assert "GENERAL_ITEM" not in res_b.counts

    # Ensure result A and B are identical
    assert res_a.counts == res_b.counts
    assert res_a.ids(Disposition.INCLUDED) == res_b.ids(Disposition.INCLUDED)


def test_mapping_tie_collision_fails_closed_unresolved() -> None:
    """Issue #9 / DEC-013: Multiple matching rules with equal specificity map to conflicting items -> UNRESOLVED."""
    dxf_path = FIXTURES_DIR / "basic_devices.dxf"
    drawing = parse_dxf(dxf_path.read_bytes(), filename=dxf_path.name)

    # Two conflicting layer-specific rules for same block and layer
    layer_rule_1 = BlockMapping(block_name="LT-DL", layer="E-LIGHT", item_code="LIGHT_TYPE_A")
    layer_rule_2 = BlockMapping(block_name="LT-DL", layer="E-LIGHT", item_code="LIGHT_TYPE_B")

    # Regardless of order, collision must produce UNRESOLVED with zero automatic count
    res_1 = aggregate(drawing, [layer_rule_1, layer_rule_2])
    assert len(res_1.counts) == 0
    unresolved_1 = [o for o in res_1.objects if o.disposition == Disposition.UNRESOLVED]
    assert len(unresolved_1) == 6
    assert all("매핑 충돌" in o.reason for o in unresolved_1)

    # Inverted order
    res_2 = aggregate(drawing, [layer_rule_2, layer_rule_1])
    assert res_2.counts == res_1.counts
    assert len(res_2.ids(Disposition.UNRESOLVED)) == 6

    # Two conflicting general rules for OT-2P
    gen_rule_1 = BlockMapping(block_name="OT-2P", layer=None, item_code="OUTLET_A")
    gen_rule_2 = BlockMapping(block_name="OT-2P", layer=None, item_code="OUTLET_B")
    res_gen = aggregate(drawing, [gen_rule_1, gen_rule_2])
    ot_unresolved = [o for o in res_gen.objects if o.disposition == Disposition.UNRESOLVED]
    assert len(ot_unresolved) == 4
    assert all("매핑 충돌" in o.reason for o in ot_unresolved)


def test_dynamic_and_anonymous_block_blocking_dec_014() -> None:
    """Issue #9 / DEC-014: DYNAMIC_BLOCK and ANONYMOUS_BLOCK must be blocked as UNRESOLVED."""
    dxf_path = FIXTURES_DIR / "anonymous_and_dynamic.dxf"
    drawing = parse_dxf(dxf_path.read_bytes(), filename=dxf_path.name)

    # Map LT-DYN (which has DYNAMIC_BLOCK warning)
    mapping = BlockMapping(block_name="LT-DYN", item_code="LIGHT")
    res = aggregate(drawing, [mapping])

    # Dynamic block must NOT be automatically counted
    assert "LIGHT" not in res.counts
    assert res.counts == {}

    # Must be marked UNRESOLVED with specific explanation
    dyn_unresolved = [o for o in res.objects if o.disposition == Disposition.UNRESOLVED]
    assert len(dyn_unresolved) == 1
    assert "동적/익명 블록: 가시성·구조 검수 필요" in dyn_unresolved[0].reason
