"""Command line: ``eai-cad parse plan.dxf -o plan.json`` (local, offline)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import DxfLoadError, parse_dxf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eai-cad", description="Electrical AI CAD engine")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("parse", help="Normalize a DXF file to JSON")
    p.add_argument("file", type=Path)
    p.add_argument("-o", "--output", type=Path, help="Output JSON path (default: stdout)")
    p.add_argument("--no-primitives", action="store_true", help="Omit render primitives")
    p.add_argument("--summary", action="store_true", help="Print a short summary only")
    args = parser.parse_args(argv)

    data = args.file.read_bytes()
    try:
        drawing = parse_dxf(data, filename=args.file.name)
    except DxfLoadError as exc:
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return 2

    if args.summary:
        s = drawing.stats
        print(f"drawing_id : {drawing.drawing_id}")
        print(f"dxf        : {drawing.dxf.release} ({drawing.dxf.version}) {drawing.dxf.encoding}")
        print(f"units      : {drawing.dxf.units_name} (INSUNITS={drawing.dxf.insunits})")
        print(f"entities   : modelspace={s.modelspace_entities} paperspace={s.paperspace_entities}")
        print(f"objects    : {s.source_objects}  primitives={s.primitives} points={s.primitive_points}")
        print(f"parse_ms   : {s.parse_ms}")
        for b in drawing.blocks:
            if b.top_level_insert_count or b.nested_insert_count:
                print(f"  block {b.name!r}: top={b.top_level_insert_count} nested={b.nested_insert_count}")
        for w in drawing.warnings:
            print(f"  [{w.severity}] {w.code} ({len(w.object_ids)} objects)")
        return 0

    exclude = {"primitives"} if args.no_primitives else None
    payload = drawing.model_dump_json(indent=2, exclude=exclude)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
