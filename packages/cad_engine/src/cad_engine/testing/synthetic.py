"""Synthetic DXF fixture factory (PRD DEC-004, §11).

Every fixture is built programmatically and ships with an *expected result*
declared from the construction parameters — never derived from parser output —
so tests compare the parser against independent ground truth.

Regenerate committed fixtures::

    uv run python -m cad_engine.testing.synthetic --out fixtures/dxf

Symbols here are **synthetic placeholders**, not an authoritative Korean legend.
Item codes (LIGHT / OUTLET / SWITCH) are provisional until A05 (EAI-E001) review.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.enums import TextEntityAlignment

ezdxf.options.write_fixed_meta_data_for_testing = True  # deterministic header metadata


@dataclass
class Expected:
    description: str
    expect_error: str | None = None
    insunits: int | None = None
    encoding: str | None = None
    top_level_inserts: dict[str, int] = field(default_factory=dict)
    nested_inserts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    absent_warnings: list[str] = field(default_factory=list)
    mappings: list[dict[str, str]] = field(default_factory=list)
    expected_counts: dict[str, int] = field(default_factory=dict)
    expected_unresolved: int = 0
    expected_unmapped: int = 0
    insert_checks: list[dict[str, Any]] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    lengths: list[dict[str, Any]] = field(default_factory=list)
    allow_error_or_warning: bool = False


STD_MAPPINGS = [
    {"block_name": "LT-DL", "item_code": "LIGHT"},
    {"block_name": "OT-2P", "item_code": "OUTLET"},
    {"block_name": "SW-1", "item_code": "SWITCH"},
]


# --------------------------------------------------------------------------- helpers
def _new(version: str = "R2018", insunits: int = 4) -> Any:
    doc = ezdxf.new(version, setup=False)
    doc.header["$INSUNITS"] = insunits
    doc.header["$MEASUREMENT"] = 1
    for name, color in (("E-LIGHT", 2), ("E-POWER", 1), ("E-SWITCH", 3), ("A-WALL", 8)):
        doc.layers.add(name, color=color)
    _define_symbols(doc)
    return doc


def _define_symbols(doc: Any) -> None:
    """Downlight: circle + cross. Outlet: circle + 2 bars + CIRCUIT attdef. Switch: dot + stem."""
    lt = doc.blocks.new("LT-DL")
    lt.add_circle((0, 0), 150)
    lt.add_line((-150, 0), (150, 0))
    lt.add_line((0, -150), (0, 150))

    ot = doc.blocks.new("OT-2P")
    ot.add_circle((0, 0), 100)
    ot.add_line((-40, -60), (-40, 60))
    ot.add_line((40, -60), (40, 60))
    ot.add_attdef("CIRCUIT", (120, 0), dxfattribs={"height": 80})

    sw = doc.blocks.new("SW-1")
    sw.add_circle((0, 0), 60)
    sw.add_line((0, 60), (120, 200))


def _room(msp: Any) -> None:
    msp.add_lwpolyline(
        [(0, 0), (8000, 0), (8000, 6000), (0, 6000)], close=True, dxfattribs={"layer": "A-WALL"}
    )
    msp.add_line((4000, 0), (4000, 6000), dxfattribs={"layer": "A-WALL"})


# --------------------------------------------------------------------------- fixtures
def basic_devices() -> tuple[Any, Expected]:
    doc = _new()
    msp = doc.modelspace()
    _room(msp)
    msp.add_arc((4000, 0), 900, 0, 90, dxfattribs={"layer": "A-WALL"})  # door swing
    for i in range(3):
        for j in range(2):
            msp.add_blockref("LT-DL", (1000 + i * 1000, 2000 + j * 2000), dxfattribs={"layer": "E-LIGHT"})
    for k, (x, y) in enumerate([(200, 1000), (200, 5000), (3800, 3000), (7800, 3000)]):
        ref = msp.add_blockref("OT-2P", (x, y), dxfattribs={"layer": "E-POWER"})
        ref.add_auto_attribs({"CIRCUIT": f"P-{k + 1}"})
    for x, y in [(3800, 500), (4200, 500), (7500, 500)]:
        msp.add_blockref("SW-1", (x, y), dxfattribs={"layer": "E-SWITCH"})
    msp.add_text("거실", height=250, dxfattribs={"layer": "A-WALL"}).set_placement(
        (1500, 300), align=TextEntityAlignment.LEFT
    )
    msp.add_mtext("침실\\P조명 2개", dxfattribs={"layer": "A-WALL", "char_height": 200}).set_location(
        (5500, 5500)
    )
    return doc, Expected(
        description="정상 블록: 조명 6, 콘센트 4(회로 속성), 스위치 3, 벽체·문·한글 문자",
        insunits=4,
        top_level_inserts={"LT-DL": 6, "OT-2P": 4, "SW-1": 3},
        absent_warnings=["UNITS_UNDEFINED", "XREF_UNRESOLVED", "HIDDEN_LAYER", "NESTED_BLOCK"],
        mappings=STD_MAPPINGS,
        expected_counts={"LIGHT": 6, "OUTLET": 4, "SWITCH": 3},
        insert_checks=[
            {"block": "OT-2P", "x": 200, "y": 1000, "attributes": {"CIRCUIT": "P-1"}},
            {"block": "LT-DL", "x": 1000, "y": 2000, "bbox": [[850, 1850], [1150, 2150]]},
        ],
        texts=["거실", "침실\n조명 2개"],
        lengths=[
            {"entity_type": "ARC", "value": 1413.716694, "tol": 0.01},
            {"entity_type": "LINE", "value": 6000.0, "tol": 1e-6},
            {"entity_type": "LWPOLYLINE", "value": 28000.0, "tol": 1e-6},
        ],
    )


def transformed_blocks() -> tuple[Any, Expected]:
    doc = _new()
    arrow = doc.blocks.new("ARROW", base_point=(10, 0))
    arrow.add_line((10, 0), (110, 0))
    arrow.add_line((110, 0), (90, 10))
    msp = doc.modelspace()
    # base (10,0) -> tip (110,0) is +100 in x; scale 2 -> 200; rotate 90 -> (0,200)
    msp.add_blockref("ARROW", (1000, 500), dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2, "layer": "E-LIGHT"})
    msp.add_blockref("LT-DL", (2000, 0), dxfattribs={"xscale": 2, "yscale": 1, "layer": "E-LIGHT"})
    msp.add_blockref("LT-DL", (3000, 0), dxfattribs={"xscale": -1, "yscale": 1, "layer": "E-LIGHT"})
    msp.add_blockref("LT-DL", (4000, 0), dxfattribs={"rotation": 45, "xscale": 0.5, "yscale": 0.5, "layer": "E-LIGHT"})
    return doc, Expected(
        description="이동·회전·비균일 축척·대칭(음수 축척)·기준점 오프셋 블록",
        insunits=4,
        top_level_inserts={"ARROW": 1, "LT-DL": 3},
        mappings=[{"block_name": "LT-DL", "item_code": "LIGHT"}],
        expected_counts={"LIGHT": 3},
        expected_unmapped=1,
        insert_checks=[
            {"block": "ARROW", "x": 1000, "y": 500, "rotation": 90, "bbox": [[980, 500], [1000, 700]]},
            {"block": "LT-DL", "x": 2000, "y": 0, "bbox": [[1700, -150], [2300, 150]]},
            {"block": "LT-DL", "x": 3000, "y": 0, "rotation": 180, "bbox": [[2850, -150], [3150, 150]]},
            {"block": "LT-DL", "x": 4000, "y": 0, "rotation": 45, "bbox": [[3925, -75], [4075, 75]]},
        ],
    )


def nested_blocks() -> tuple[Any, Expected]:
    doc = _new()
    grp = doc.blocks.new("LT-GROUP")
    grp.add_blockref("LT-DL", (0, 0))
    grp.add_blockref("LT-DL", (600, 0))
    grp.add_line((0, 0), (600, 0))
    msp = doc.modelspace()
    msp.add_blockref("LT-GROUP", (0, 0), dxfattribs={"layer": "E-LIGHT"})
    msp.add_blockref("LT-GROUP", (0, 2000), dxfattribs={"layer": "E-LIGHT", "rotation": 90})
    msp.add_blockref("LT-DL", (3000, 3000), dxfattribs={"layer": "E-LIGHT"})
    return doc, Expected(
        description="중첩 블록: 그룹 2개(각 조명 2개) + 단독 조명 1개. 중첩 집계는 A05 확정 전 미확인",
        insunits=4,
        top_level_inserts={"LT-GROUP": 2, "LT-DL": 1},
        nested_inserts={"LT-DL": 4},
        warnings=["NESTED_BLOCK"],
        mappings=[{"block_name": "LT-DL", "item_code": "LIGHT"}],
        expected_counts={"LIGHT": 1},
        expected_unresolved=4,
        expected_unmapped=2,
        insert_checks=[
            {"block": "LT-DL", "depth": 1, "x": 0, "y": 2600},
            {"block": "LT-DL", "depth": 1, "x": 600, "y": 0},
            {"block": "LT-GROUP", "x": 0, "y": 2000, "bbox": [[-150, 1850], [150, 2750]]},
        ],
    )


def hidden_layers() -> tuple[Any, Expected]:
    doc = _new()
    doc.layers.add("E-LIGHT-OFF", color=2).off()
    doc.layers.add("E-LIGHT-FRZ", color=2).freeze()
    msp = doc.modelspace()
    for x in (0, 1000, 2000):
        msp.add_blockref("LT-DL", (x, 0), dxfattribs={"layer": "E-LIGHT"})
    msp.add_blockref("LT-DL", (3000, 0), dxfattribs={"layer": "E-LIGHT-OFF"})
    msp.add_blockref("LT-DL", (4000, 0), dxfattribs={"layer": "E-LIGHT-FRZ"})
    return doc, Expected(
        description="꺼짐·동결 레이어의 조명은 자동 확정하지 않고 미확인 분리",
        insunits=4,
        top_level_inserts={"LT-DL": 5},
        warnings=["HIDDEN_LAYER"],
        mappings=[{"block_name": "LT-DL", "item_code": "LIGHT"}],
        expected_counts={"LIGHT": 3},
        expected_unresolved=2,
    )


def units_undefined() -> tuple[Any, Expected]:
    doc = _new(insunits=0)
    msp = doc.modelspace()
    msp.add_blockref("LT-DL", (0, 0), dxfattribs={"layer": "E-LIGHT"})
    msp.add_blockref("LT-DL", (1000, 0), dxfattribs={"layer": "E-LIGHT"})
    return doc, Expected(
        description="INSUNITS=0(단위 미설정) 경고",
        insunits=0,
        top_level_inserts={"LT-DL": 2},
        warnings=["UNITS_UNDEFINED"],
        mappings=[{"block_name": "LT-DL", "item_code": "LIGHT"}],
        expected_counts={"LIGHT": 2},
    )


def xref_reference() -> tuple[Any, Expected]:
    doc = _new()
    doc.add_xref_def("arch_base.dxf", "ARCH_BASE")
    msp = doc.modelspace()
    msp.add_blockref("ARCH_BASE", (0, 0))
    msp.add_blockref("LT-DL", (500, 500), dxfattribs={"layer": "E-LIGHT"})
    return doc, Expected(
        description="외부참조(XREF) 포함: 경고 + 외부참조 블록은 집계 대상 아님",
        insunits=4,
        top_level_inserts={"ARCH_BASE": 1, "LT-DL": 1},
        warnings=["XREF_UNRESOLVED"],
        mappings=[
            {"block_name": "LT-DL", "item_code": "LIGHT"},
            {"block_name": "ARCH_BASE", "item_code": "LIGHT"},  # even if mis-mapped: unresolved
        ],
        expected_counts={"LIGHT": 1},
        expected_unresolved=1,
    )


def anonymous_and_dynamic() -> tuple[Any, Expected]:
    doc = _new()
    anon = doc.blocks.new_anonymous_block()  # "*U1"-style, no source block
    anon.add_circle((0, 0), 80)
    # Emulate an AutoCAD dynamic-block reference: anonymous block whose BLOCK_RECORD
    # points back to the original definition via XDATA "AcDbBlockRepBTag".
    original = doc.blocks.new("LT-DYN")
    original.add_circle((0, 0), 150)
    dyn = doc.blocks.new_anonymous_block()
    dyn.add_circle((0, 0), 150)
    dyn.add_line((-150, 0), (150, 0))
    if not doc.appids.has_entry("AcDbBlockRepBTag"):
        doc.appids.new("AcDbBlockRepBTag")
    dyn.block_record.set_xdata(
        "AcDbBlockRepBTag", [(1070, 1), (1005, original.block_record.dxf.handle)]
    )
    msp = doc.modelspace()
    msp.add_blockref(anon.name, (0, 0), dxfattribs={"layer": "E-LIGHT"})
    msp.add_blockref(anon.name, (500, 0), dxfattribs={"layer": "E-LIGHT"})
    msp.add_blockref(dyn.name, (1500, 0), dxfattribs={"layer": "E-LIGHT"})
    return doc, Expected(
        description="익명 블록 2개(원본명 없음) + 동적 블록 참조 1개(원본명 LT-DYN 추정)",
        insunits=4,
        top_level_inserts={anon.name: 2, dyn.name: 1},
        warnings=["ANONYMOUS_BLOCK", "DYNAMIC_BLOCK"],
        mappings=[{"block_name": "LT-DYN", "item_code": "LIGHT"}],
        expected_counts={"LIGHT": 1},
        expected_unmapped=2,
        insert_checks=[{"block": dyn.name, "x": 1500, "y": 0, "effective_block_name": "LT-DYN"}],
    )


def minsert_array() -> tuple[Any, Expected]:
    doc = _new()
    msp = doc.modelspace()
    ref = msp.add_blockref("OT-2P", (0, 0), dxfattribs={"layer": "E-POWER"})
    ref.grid(size=(2, 3), spacing=(1000, 500))  # 2 rows x 3 columns
    return doc, Expected(
        description="MINSERT 2x3 배열 → 콘센트 6개로 전개",
        insunits=4,
        top_level_inserts={"OT-2P": 6},
        warnings=["MINSERT_EXPANDED"],
        mappings=[{"block_name": "OT-2P", "item_code": "OUTLET"}],
        expected_counts={"OUTLET": 6},
        insert_checks=[{"block": "OT-2P", "x": 1000, "y": 1000}],
    )


def korean_r2000_cp949() -> tuple[Any, Expected]:
    doc = _new(version="R2000")
    # ezdxf derives $DWGCODEPAGE from doc.encoding on save (header edits are overwritten).
    doc.encoding = "cp949"
    doc.layers.add("전등", color=2)
    blk = doc.blocks.new("조명-매입")
    blk.add_circle((0, 0), 150)
    msp = doc.modelspace()
    msp.add_blockref("조명-매입", (0, 0), dxfattribs={"layer": "전등"})
    msp.add_blockref("조명-매입", (1000, 0), dxfattribs={"layer": "전등"})
    msp.add_text("주방", height=200, dxfattribs={"layer": "전등"}).set_placement((0, 500))
    return doc, Expected(
        description="R2000 + CP949(ANSI_949) 한글 레이어·블록·문자",
        insunits=4,
        encoding="cp949",
        top_level_inserts={"조명-매입": 2},
        mappings=[{"block_name": "조명-매입", "item_code": "LIGHT"}],
        expected_counts={"LIGHT": 2},
        texts=["주방"],
    )


def paperspace_content() -> tuple[Any, Expected]:
    doc = _new()
    doc.modelspace().add_blockref("SW-1", (0, 0), dxfattribs={"layer": "E-SWITCH"})
    psp = doc.layout("Layout1")
    psp.add_text("표제란 - 전기 평면도", height=5)
    psp.add_blockref("SW-1", (50, 50))
    return doc, Expected(
        description="Paper Space 객체는 표시·집계 제외(정보 경고)",
        insunits=4,
        top_level_inserts={"SW-1": 1},
        warnings=["PAPER_SPACE_IGNORED"],
        mappings=[{"block_name": "SW-1", "item_code": "SWITCH"}],
        expected_counts={"SWITCH": 1},
    )


def empty_modelspace() -> tuple[Any, Expected]:
    return _new(), Expected(
        description="Model Space 비어 있음", insunits=4, warnings=["EMPTY_MODELSPACE"]
    )


DOC_FIXTURES: dict[str, Callable[[], tuple[Any, Expected]]] = {
    "basic_devices": basic_devices,
    "transformed_blocks": transformed_blocks,
    "nested_blocks": nested_blocks,
    "hidden_layers": hidden_layers,
    "units_undefined": units_undefined,
    "xref_reference": xref_reference,
    "anonymous_and_dynamic": anonymous_and_dynamic,
    "minsert_array": minsert_array,
    "korean_r2000_cp949": korean_r2000_cp949,
    "paperspace_content": paperspace_content,
    "empty_modelspace": empty_modelspace,
}


def raw_fixtures(basic_bytes: bytes) -> dict[str, tuple[str, bytes, Expected]]:
    """Malformed inputs. Returns name -> (filename, bytes, expected)."""
    return {
        "not_a_dxf": (
            "not_a_dxf.dxf",
            "이것은 DXF가 아닙니다\nhello world\n".encode(),
            Expected(description="DXF가 아닌 텍스트", expect_error="NOT_A_DXF"),
        ),
        "fake_dwg": (
            "fake_dwg.dxf",
            b"AC1032\x00\x00\x00\x00\x00\x00binary-dwg-payload",
            Expected(description="확장자는 .dxf지만 DWG 시그니처", expect_error="DWG_NOT_SUPPORTED"),
        ),
        "truncated": (
            "truncated.dxf",
            basic_bytes[: len(basic_bytes) * 2 // 5],
            Expected(
                description="정상 파일의 앞 40%만 남긴 손상 파일 → 잘림 오류(빈 도면으로 오인 금지)",
                expect_error="TRUNCATED_FILE",
            ),
        ),
    }


def save_doc(doc: Any, path: Path) -> None:
    doc.saveas(path)


def build_large(n_inserts: int, *, cols: int = 200) -> Any:
    """Synthetic stress drawing for performance measurement (not committed)."""
    doc = _new()
    msp = doc.modelspace()
    names = ("LT-DL", "OT-2P", "SW-1")
    for i in range(n_inserts):
        x, y = (i % cols) * 500, (i // cols) * 500
        msp.add_blockref(names[i % 3], (x, y), dxfattribs={"layer": "E-LIGHT"})
        if i % 4 == 0:
            msp.add_line((x, y), (x + 500, y), dxfattribs={"layer": "A-WALL"})
    return doc


def generate(out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, factory in DOC_FIXTURES.items():
        doc, expected = factory()
        dxf_path = out / f"{name}.dxf"
        save_doc(doc, dxf_path)
        (out / f"{name}.expected.json").write_text(
            json.dumps(asdict(expected), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(dxf_path.name)
    basic = (out / "basic_devices.dxf").read_bytes()
    for name, (filename, data, expected) in raw_fixtures(basic).items():
        (out / filename).write_bytes(data)
        (out / f"{name}.expected.json").write_text(
            json.dumps({"filename": filename, **asdict(expected)}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        written.append(filename)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic DXF fixtures")
    parser.add_argument("--out", type=Path, default=Path("fixtures/dxf"))
    args = parser.parse_args()
    for name in generate(args.out):
        print(f"wrote {args.out / name}")


if __name__ == "__main__":
    main()
