"""Generate synthetic PDF fixtures for PR B multi-page tests and Issue #20 ground truth dataset.

Generates:
1. pdf_b_2page_electrical.pdf (and alias pdf_b_01_two_pages.pdf)
   - Matches QA_PDF_B_MATRIX PB-01 exact oracle:
     Page 0: 612.0 x 792.0 pt, ROT0, markers (100, 150), (300, 220), (500, 650) -> 3 LIGHT
     Page 1: 552.0 x 752.0 pt (CropBox [24, 24, 776, 576] on 800x600 pt, ROT90), markers (100, 150), (400, 500) -> 2 OUTLET
     Shared coordinate (100, 150) testing page_index isolation, total 5 provisional EA items.
2. pdf_b_rotated_cropbox.pdf (and alias pdf_b_02_rotated_cropbox.pdf)
   - 90-degree rotated page with non-zero CropBox [50, 60, 550, 740] -> display 680.0 x 500.0 pt.
3. pdf_b_scanned_mixed.pdf
   - Mixed raster-only scan (Page 0, 800x600 pt) + vector electrical (Page 1, 800x600 pt).
4. pdf_b_oversized_dimension.pdf
   - P0-03 DoS defense test: 12,000 x 12,000 pt (exceeds single-axis and total pixel budget).
5. corrupt.pdf
   - Invalid truncated PDF syntax for 400 rejection test.
6. encrypted.pdf
   - Password-protected PDF for 400 rejection test.
7. fixtures/pdf/expected.json & expected_takeoff.json
   - Deterministic ground truth dataset with sha256, dimensions, markers, and expected takeoff oracle.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
)


def generate_fixtures() -> None:
    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # 1. pdf_b_2page_electrical.pdf / pdf_b_01_two_pages.pdf (A04 exact geometry)
    # =========================================================================
    writer1 = PdfWriter()
    # Page 0: 612 x 792 pt, ROT0
    page1 = writer1.add_blank_page(width=612.0, height=792.0)
    stream1 = DecodedStreamObject()
    stream1.set_data(
        b"q\n"
        b"0.9 0.9 0.9 rg 20 20 572 752 re f\n"
        b"0 0 0 RG 2 w 40 40 532 712 re s\n"
        b"0.2 0.4 0.8 RG 1 w 100 100 200 200 re s\n"
        b"Q\n"
    )
    page1[NameObject("/Contents")] = writer1._add_object(stream1)

    # Page 1: MediaBox 800 x 600 pt, CropBox [24, 24, 776, 576] (752x552), rotate(90) -> display 552 x 752 pt
    page2 = writer1.add_blank_page(width=800.0, height=600.0)
    page2[NameObject("/CropBox")] = ArrayObject(
        [FloatObject(24), FloatObject(24), FloatObject(776), FloatObject(576)]
    )
    page2.rotate(90)
    stream2 = DecodedStreamObject()
    stream2.set_data(
        b"q\n"
        b"0.95 0.95 0.9 rg 30 30 740 540 re f\n"
        b"0 0 0 RG 2 w 50 50 700 500 re s\n"
        b"0.8 0.2 0.2 RG 1 w 150 150 300 200 re s\n"
        b"Q\n"
    )
    page2[NameObject("/Contents")] = writer1._add_object(stream2)

    buf1 = io.BytesIO()
    writer1.write(buf1)
    p1_bytes = buf1.getvalue()

    (fixtures_dir / "pdf_b_2page_electrical.pdf").write_bytes(p1_bytes)
    (fixtures_dir / "pdf_b_01_two_pages.pdf").write_bytes(p1_bytes)
    sha1 = hashlib.sha256(p1_bytes).hexdigest()
    print(f"Generated pdf_b_2page_electrical.pdf ({len(p1_bytes)} bytes, sha256={sha1[:8]}...)")

    # =========================================================================
    # 2. pdf_b_rotated_cropbox.pdf / pdf_b_02_rotated_cropbox.pdf
    # =========================================================================
    writer2 = PdfWriter()
    page_rot = writer2.add_blank_page(width=600.0, height=800.0)
    page_rot.rotate(90)
    page_rot[NameObject("/CropBox")] = ArrayObject(
        [FloatObject(50), FloatObject(60), FloatObject(550), FloatObject(740)]
    )
    stream_rot = DecodedStreamObject()
    stream_rot.set_data(
        b"q\n"
        b"0.8 0.9 0.8 rg 60 70 480 660 re f\n"
        b"0 0 0 RG 2 w 70 80 460 640 re s\n"
        b"Q\n"
    )
    page_rot[NameObject("/Contents")] = writer2._add_object(stream_rot)

    buf2 = io.BytesIO()
    writer2.write(buf2)
    p2_bytes = buf2.getvalue()

    (fixtures_dir / "pdf_b_rotated_cropbox.pdf").write_bytes(p2_bytes)
    (fixtures_dir / "pdf_b_02_rotated_cropbox.pdf").write_bytes(p2_bytes)
    sha2 = hashlib.sha256(p2_bytes).hexdigest()
    print(f"Generated pdf_b_rotated_cropbox.pdf ({len(p2_bytes)} bytes, sha256={sha2[:8]}...)")

    # =========================================================================
    # 3. pdf_b_scanned_mixed.pdf (Page 0: Scanned raster, Page 1: Vector)
    # =========================================================================
    img = Image.new("RGB", (800, 600), color=(252, 250, 245))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 760, 560], outline=(50, 50, 50), width=2)
    draw.rectangle([500, 480, 750, 550], outline=(50, 50, 50), width=1)
    draw.text((510, 490), "PLAN: SCANNED 1F POWER", fill=(0, 0, 0))
    draw.text((510, 510), "SCALE: 1/100 (RASTER ONLY)", fill=(0, 0, 0))
    draw.text((510, 530), "NOTICE: MANUAL TAKEOFF ONLY", fill=(180, 0, 0))
    draw.line([(100, 100), (450, 100), (450, 450), (100, 450), (100, 100)], fill=(80, 80, 80), width=2)
    draw.ellipse([200, 200, 230, 230], outline=(180, 0, 0), width=2)
    draw.text((208, 208), "S", fill=(180, 0, 0))
    draw.rectangle([350, 300, 380, 330], outline=(0, 100, 200), width=2)
    draw.text((358, 308), "O", fill=(0, 100, 200))

    raster_buf = io.BytesIO()
    img.save(raster_buf, format="PDF", resolution=72.0)
    raster_buf.seek(0)

    writer3 = PdfWriter()
    writer3.add_page(PdfReader(raster_buf).pages[0])

    page_vec = writer3.add_blank_page(width=800.0, height=600.0)
    stream_vec = DecodedStreamObject()
    stream_vec.set_data(
        b"q\n"
        b"0.98 0.98 0.98 rg 0 0 800 600 re f\n"
        b"0.2 0.2 0.2 RG 2 w 50 50 700 500 re s\n"
        b"0.1 0.5 0.8 RG 2 w 200 200 400 250 re s\n"
        b"0.9 0.1 0.1 RG 2 w 300 300 50 50 re s\n"
        b"Q\n"
    )
    page_vec[NameObject("/Contents")] = writer3._add_object(stream_vec)

    buf3 = io.BytesIO()
    writer3.write(buf3)
    p3_bytes = buf3.getvalue()

    p3_path = fixtures_dir / "pdf_b_scanned_mixed.pdf"
    p3_path.write_bytes(p3_bytes)
    sha3 = hashlib.sha256(p3_bytes).hexdigest()
    print(f"Generated pdf_b_scanned_mixed.pdf ({len(p3_bytes)} bytes, sha256={sha3[:8]}...)")

    # =========================================================================
    # 4. pdf_b_oversized_dimension.pdf (P0-03 DoS defense test: 12,000 x 12,000 pt)
    # =========================================================================
    writer_over = PdfWriter()
    writer_over.add_blank_page(width=12000.0, height=12000.0)
    buf_over = io.BytesIO()
    writer_over.write(buf_over)
    over_bytes = buf_over.getvalue()
    over_path = fixtures_dir / "pdf_b_oversized_dimension.pdf"
    over_path.write_bytes(over_bytes)
    sha_over = hashlib.sha256(over_bytes).hexdigest()
    print(f"Generated pdf_b_oversized_dimension.pdf ({len(over_bytes)} bytes, sha256={sha_over[:8]}...)")

    # =========================================================================
    # 5. corrupt.pdf
    # =========================================================================
    corrupt_bytes = (
        b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        b"This is a truncated corrupted PDF file with invalid syntax \x00\xff\xfe\x00trailer<<>>%%EOF"
    )
    corrupt_path = fixtures_dir / "corrupt.pdf"
    corrupt_path.write_bytes(corrupt_bytes)
    sha_corrupt = hashlib.sha256(corrupt_bytes).hexdigest()
    print(f"Generated corrupt.pdf ({len(corrupt_bytes)} bytes, sha256={sha_corrupt[:8]}...)")

    # =========================================================================
    # 6. encrypted.pdf
    # =========================================================================
    writer_enc = PdfWriter()
    writer_enc.add_blank_page(width=300, height=300)
    writer_enc.encrypt("password123")
    enc_buf = io.BytesIO()
    writer_enc.write(enc_buf)
    enc_bytes = enc_buf.getvalue()
    enc_path = fixtures_dir / "encrypted.pdf"
    enc_path.write_bytes(enc_bytes)
    sha_enc = hashlib.sha256(enc_bytes).hexdigest()
    print(f"Generated encrypted.pdf ({len(enc_bytes)} bytes, sha256={sha_enc[:8]}...)")

    # =========================================================================
    # 7. pdf_c_vector_features.pdf (PR C: Issue #22 Vector Text, Line, Shape features)
    # =========================================================================
    writer_c = PdfWriter()
    fonts_c = DictionaryObject()
    helv_c = DictionaryObject()
    helv_c[NameObject("/Type")] = NameObject("/Font")
    helv_c[NameObject("/Subtype")] = NameObject("/Type1")
    helv_c[NameObject("/BaseFont")] = NameObject("/Helvetica")
    fonts_c[NameObject("/F1")] = helv_c
    res_c = DictionaryObject()
    res_c[NameObject("/Font")] = fonts_c

    # Page 0: 612 x 792 pt, ROT0
    page_c0 = writer_c.add_blank_page(width=612.0, height=792.0)
    page_c0[NameObject("/Resources")] = res_c
    stream_c0 = DecodedStreamObject()
    stream_c0.set_data(
        b"q\n"
        b"0 0 0 RG 2 w\n"
        b"50 50 512 692 re s\n"
        b"100 100 200 150 re s\n"
        b"50 300 m 400 300 l s\n"
        b"Q\n"
        b"BT\n"
        b"/F1 14 Tf\n"
        b"100 700 Td\n"
        b"(L-01) Tj\n"
        b"0 -40 Td\n"
        b"(DB-1) Tj\n"
        b"150 0 Td\n"
        b"(EM-LIGHT) Tj\n"
        b"ET\n"
    )
    page_c0[NameObject("/Contents")] = writer_c._add_object(stream_c0)

    # Page 1: 800 x 600 pt, CropBox [24, 24, 776, 576] (552x752), ROT90
    page_c1 = writer_c.add_blank_page(width=800.0, height=600.0)
    page_c1[NameObject("/CropBox")] = ArrayObject(
        [FloatObject(24), FloatObject(24), FloatObject(776), FloatObject(576)]
    )
    page_c1.rotate(90)
    page_c1[NameObject("/Resources")] = res_c
    stream_c1 = DecodedStreamObject()
    stream_c1.set_data(
        b"q\n"
        b"0 0 0 RG 2 w\n"
        b"40 40 700 500 re s\n"
        b"100 100 m 500 100 l s\n"
        b"Q\n"
        b"BT\n"
        b"/F1 14 Tf\n"
        b"100 150 Td\n"
        b"(OUTLET-1) Tj\n"
        b"0 50 Td\n"
        b"(SWITCH-2) Tj\n"
        b"ET\n"
    )
    page_c1[NameObject("/Contents")] = writer_c._add_object(stream_c1)

    buf_c = io.BytesIO()
    writer_c.write(buf_c)
    c_bytes = buf_c.getvalue()
    c_path = fixtures_dir / "pdf_c_vector_features.pdf"
    c_path.write_bytes(c_bytes)
    sha_c = hashlib.sha256(c_bytes).hexdigest()
    print(f"Generated pdf_c_vector_features.pdf ({len(c_bytes)} bytes, sha256={sha_c[:8]}...)")

    # =========================================================================
    # 8. expected.json & expected_takeoff.json
    # =========================================================================
    expected_catalog: dict[str, Any] = {
        "version": "1.0.0",
        "generated_by": "scripts/generate_pdf_fixtures.py",
        "licensing": "SELF_GENERATED",
        "fixtures": {
            "pdf_b_2page_electrical.pdf": {
                "filename": "pdf_b_2page_electrical.pdf",
                "sha256": sha1,
                "file_size_bytes": len(p1_bytes),
                "page_count": 2,
                "licensing": "SELF_GENERATED",
                "test_scope": "Multi-page electrical plan (Page 0: 612x792 pt ROT0, Page 1: 552x752 pt ROT90 CropBox offset), page_index isolation, provisional manual takeoff",
                "pages": [
                    {
                        "page_index": 0,
                        "dimensions_pt": {"width": 612.0, "height": 792.0},
                        "rotation": 0,
                        "cropbox": [0.0, 0.0, 612.0, 792.0],
                        "manual_markers": [
                            {"id": "p0_lt_1", "item_code": "LIGHT", "item_name": "다운라이트", "x": 100.0, "y": 150.0, "unit": "EA"},
                            {"id": "p0_lt_2", "item_code": "LIGHT", "item_name": "다운라이트", "x": 300.0, "y": 220.0, "unit": "EA"},
                            {"id": "p0_lt_3", "item_code": "LIGHT", "item_name": "다운라이트", "x": 500.0, "y": 650.0, "unit": "EA"},
                        ],
                    },
                    {
                        "page_index": 1,
                        "dimensions_pt": {"width": 552.0, "height": 752.0},
                        "rotation": 90,
                        "cropbox": [24.0, 24.0, 776.0, 576.0],
                        "manual_markers": [
                            {"id": "p1_ot_1", "item_code": "OUTLET", "item_name": "콘센트", "x": 100.0, "y": 150.0, "unit": "EA"},
                            {"id": "p1_ot_2", "item_code": "OUTLET", "item_name": "콘센트", "x": 400.0, "y": 500.0, "unit": "EA"},
                        ],
                    },
                ],
                "expected_takeoff": {
                    "total_quantity": 5,
                    "is_provisional": True,
                    "items": {
                        "LIGHT": {"quantity": 3, "unit": "EA"},
                        "OUTLET": {"quantity": 2, "unit": "EA"},
                    },
                },
                "operations_expected": {
                    "exclude_marker_id": "p0_lt_1",
                    "quantity_after_exclude": 4,
                    "restore_marker_id": "p0_lt_1",
                    "quantity_after_restore": 5,
                    "reload_marker_count": 5,
                },
            },
            "pdf_b_rotated_cropbox.pdf": {
                "filename": "pdf_b_rotated_cropbox.pdf",
                "sha256": sha2,
                "file_size_bytes": len(p2_bytes),
                "page_count": 1,
                "licensing": "SELF_GENERATED",
                "test_scope": "Rotated (90 deg) page with non-zero CropBox, canonical point transform",
                "pages": [
                    {
                        "page_index": 0,
                        "dimensions_pt": {"width": 680.0, "height": 500.0},
                        "rotation": 90,
                        "cropbox": [50.0, 60.0, 550.0, 740.0],
                        "manual_markers": [
                            {"id": "rot_m1", "item_code": "LIGHT", "item_name": "다운라이트", "x": 340.0, "y": 250.0, "unit": "EA"},
                        ],
                    }
                ],
                "expected_takeoff": {
                    "total_quantity": 1,
                    "is_provisional": True,
                    "items": {
                        "LIGHT": {"quantity": 1, "unit": "EA"},
                    },
                },
            },
            "pdf_b_scanned_mixed.pdf": {
                "filename": "pdf_b_scanned_mixed.pdf",
                "sha256": sha3,
                "file_size_bytes": len(p3_bytes),
                "page_count": 2,
                "licensing": "SELF_GENERATED",
                "test_scope": "Mixed scanned raster page (Page 0) and vector electrical page (Page 1), OCR-unsupported disclaimer, manual marker support",
                "pages": [
                    {
                        "page_index": 0,
                        "page_type": "RASTER_SCAN",
                        "dimensions_pt": {"width": 800.0, "height": 600.0},
                        "rotation": 0,
                        "manual_markers": [
                            {"id": "scan_m1", "item_code": "SWITCH", "item_name": "스위치", "x": 215.0, "y": 215.0, "unit": "EA"},
                        ],
                    },
                    {
                        "page_index": 1,
                        "page_type": "VECTOR_ELECTRICAL",
                        "dimensions_pt": {"width": 800.0, "height": 600.0},
                        "rotation": 0,
                        "manual_markers": [
                            {"id": "vec_m1", "item_code": "LIGHT", "item_name": "조명", "x": 325.0, "y": 325.0, "unit": "EA"},
                        ],
                    },
                ],
                "expected_takeoff": {
                    "total_quantity": 2,
                    "is_provisional": True,
                    "items": {
                        "SWITCH": {"quantity": 1, "unit": "EA"},
                        "LIGHT": {"quantity": 1, "unit": "EA"},
                    },
                },
            },
        },
    }

    expected_path = fixtures_dir / "expected.json"
    expected_path.write_text(json.dumps(expected_catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {expected_path}")

    # Backward-compatible expected_takeoff.json for existing test_pdf_a04_matrix_scenario_with_expected_json
    takeoff_compat = {
        "scenario": "PDF-B-01 Multi-page manual takeoff ground truth",
        "document": "pdf_b_2page_electrical.pdf",
        "sha256": sha1,
        "page_count": 2,
        "pages": expected_catalog["fixtures"]["pdf_b_2page_electrical.pdf"]["pages"],
        "expected_summary": expected_catalog["fixtures"]["pdf_b_2page_electrical.pdf"]["expected_takeoff"],
    }
    takeoff_compat_path = fixtures_dir / "expected_takeoff.json"
    takeoff_compat_path.write_text(json.dumps(takeoff_compat, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {takeoff_compat_path}")


if __name__ == "__main__":
    generate_fixtures()
