"""Generate synthetic PDF fixtures for PR B multi-page tests."""

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, FloatObject, NameObject


def generate_fixtures() -> None:
    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures" / "pdf"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # 1. pdf_b_01_two_pages.pdf
    writer1 = PdfWriter()
    # Page 0: A4 portrait (595.28 x 841.89 pt)
    page1 = writer1.add_blank_page(width=595.28, height=841.89)
    stream1 = DecodedStreamObject()
    stream1.set_data(
        b"q\n"
        b"0.9 0.9 0.9 rg 20 20 555 801 re f\n"
        b"0 0 0 RG 2 w 40 40 515 761 re s\n"
        b"0.2 0.4 0.8 RG 1 w 100 100 200 200 re s\n"
        b"Q\n"
    )
    page1[NameObject("/Contents")] = writer1._add_object(stream1)

    # Page 1: A4 landscape (841.89 x 595.28 pt)
    page2 = writer1.add_blank_page(width=841.89, height=595.28)
    stream2 = DecodedStreamObject()
    stream2.set_data(
        b"q\n"
        b"0.95 0.95 0.9 rg 30 30 781 535 re f\n"
        b"0 0 0 RG 2 w 50 50 741 495 re s\n"
        b"0.8 0.2 0.2 RG 1 w 150 150 300 200 re s\n"
        b"Q\n"
    )
    page2[NameObject("/Contents")] = writer1._add_object(stream2)

    p1_path = fixtures_dir / "pdf_b_01_two_pages.pdf"
    with open(p1_path, "wb") as f:
        writer1.write(f)
    print(f"Generated {p1_path} ({p1_path.stat().st_size} bytes)")

    # 2. pdf_b_02_rotated_cropbox.pdf
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

    p2_path = fixtures_dir / "pdf_b_02_rotated_cropbox.pdf"
    with open(p2_path, "wb") as f:
        writer2.write(f)
    print(f"Generated {p2_path} ({p2_path.stat().st_size} bytes)")

    # 3. corrupt.pdf
    corrupt_path = fixtures_dir / "corrupt.pdf"
    corrupt_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nThis is a truncated corrupted PDF file with invalid syntax \x00\xff\xfe\x00trailer<<>>%%EOF"
    corrupt_path.write_bytes(corrupt_bytes)
    print(f"Generated {corrupt_path} ({corrupt_path.stat().st_size} bytes)")

    # 4. encrypted.pdf
    writer_enc = PdfWriter()
    writer_enc.add_blank_page(width=300, height=300)
    writer_enc.encrypt("password123")
    enc_path = fixtures_dir / "encrypted.pdf"
    with open(enc_path, "wb") as f:
        writer_enc.write(f)
    print(f"Generated {enc_path} ({enc_path.stat().st_size} bytes)")


if __name__ == "__main__":
    generate_fixtures()
