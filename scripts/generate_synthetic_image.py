"""Generate synthetic electrical drawing PNG for Issue #12 testing.

Zero-dependency PNG writer using Python stdlib struct and zlib.
Produces a 1000x800 2D electrical floor plan drawing with:
- Dark CAD background (#0f172a)
- Outer & interior architectural walls (#334155)
- Room labels & dimensions
- 4 Ceiling Light fixtures (yellow circles with cross) at known coordinates:
  - LIGHT-1: (250, 250)
  - LIGHT-2: (750, 250)
  - LIGHT-3: (250, 550)
  - LIGHT-4: (750, 550)
- 2 Receptacle Outlets (cyan circles) at known coordinates:
  - OUTLET-1: (120, 250)
  - OUTLET-2: (880, 250)
- 2 Wall Switches (green squares) at known coordinates:
  - SWITCH-1: (460, 380)
  - SWITCH-2: (540, 380)
"""

import binascii
import struct
import zlib
from pathlib import Path


def create_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", binascii.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def create_png(width: int, height: int, pixels: bytearray) -> bytes:
    """pixels: RGBA bytearray of size width * height * 4"""
    # 1. Signature
    signature = b"\x89PNG\r\n\x1a\n"

    # 2. IHDR
    ihdr_data = struct.pack(
        ">IIBBBBB",
        width,
        height,
        8,  # bit depth
        6,  # color type: RGBA
        0,  # compression
        0,  # filter
        0,  # interlace
    )
    ihdr_chunk = create_png_chunk(b"IHDR", ihdr_data)

    # 3. IDAT (Scanlines with filter byte 0)
    raw_scanlines = bytearray()
    row_stride = width * 4
    for y in range(height):
        raw_scanlines.append(0)  # Filter byte: None
        start = y * row_stride
        raw_scanlines.extend(pixels[start : start + row_stride])

    compressed = zlib.compress(bytes(raw_scanlines), level=6)
    idat_chunk = create_png_chunk(b"IDAT", compressed)

    # 4. IEND
    iend_chunk = create_png_chunk(b"IEND", b"")

    return signature + ihdr_chunk + idat_chunk + iend_chunk


def draw_rect(
    pixels: bytearray,
    w: int,
    h: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: tuple[int, int, int, int],
    fill: bool = True,
    border_width: int = 1,
) -> None:
    x1, x2 = max(0, min(x1, x2)), min(w - 1, max(x1, x2))
    y1, y2 = max(0, min(y1, y2)), min(h - 1, max(y1, y2))
    for y in range(y1, y2 + 1):
        for x in range(x1, x2 + 1):
            is_border = (x - x1 < border_width) or (x2 - x < border_width) or (y - y1 < border_width) or (y2 - y < border_width)
            if fill or is_border:
                idx = (y * w + x) * 4
                pixels[idx : idx + 4] = bytes(color)


def draw_circle(
    pixels: bytearray,
    w: int,
    h: int,
    cx: int,
    cy: int,
    r: int,
    color: tuple[int, int, int, int],
    fill: bool = True,
    border_width: int = 2,
) -> None:
    r_sq = r * r
    inner_sq = max(0, (r - border_width)) ** 2
    for y in range(max(0, cy - r), min(h, cy + r + 1)):
        for x in range(max(0, cx - r), min(w, cx + r + 1)):
            d_sq = (x - cx) ** 2 + (y - cy) ** 2
            if d_sq <= r_sq and (fill or (d_sq >= inner_sq)):
                idx = (y * w + x) * 4
                pixels[idx : idx + 4] = bytes(color)


def draw_line(
    pixels: bytearray,
    w: int,
    h: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: tuple[int, int, int, int],
    width: int = 2,
) -> None:
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx - dy
    x, y = x1, y1
    hw = width // 2
    while True:
        draw_rect(pixels, w, h, x - hw, y - hw, x + hw, y + hw, color, fill=True)
        if x == x2 and y == y2:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


def generate_electrical_floorplan() -> bytes:
    W, H = 1000, 800
    pixels = bytearray([15, 23, 42, 255] * (W * H))  # #0f172a slate-900

    # Architectural Boundary Walls (#475569)
    draw_rect(pixels, W, H, 100, 100, 900, 700, (71, 85, 105, 255), fill=False, border_width=6)

    # Interior dividing wall between Room A (Left) and Room B (Right)
    draw_line(pixels, W, H, 500, 100, 500, 360, (71, 85, 105, 255), width=6)
    draw_line(pixels, W, H, 500, 440, 500, 700, (71, 85, 105, 255), width=6)  # Doorway at 360~440

    # Grid / Dimension guide lines (subtle #1e293b)
    for x in range(200, 900, 100):
        draw_line(pixels, W, H, x, 110, x, 690, (30, 41, 59, 120), width=1)
    for y in range(200, 700, 100):
        draw_line(pixels, W, H, 110, y, 890, y, (30, 41, 59, 120), width=1)

    # 4 Light fixtures (Yellow circles with cross)
    # LIGHT-1: (250, 250), LIGHT-2: (750, 250), LIGHT-3: (250, 550), LIGHT-4: (750, 550)
    lights = [(250, 250), (750, 250), (250, 550), (750, 550)]
    for lx, ly in lights:
        draw_circle(pixels, W, H, lx, ly, 22, (250, 204, 21, 255), fill=False, border_width=3)
        draw_line(pixels, W, H, lx - 22, ly, lx + 22, ly, (250, 204, 21, 255), width=2)
        draw_line(pixels, W, H, lx, ly - 22, lx, ly + 22, (250, 204, 21, 255), width=2)

    # 2 Receptacles / Outlets (Cyan half circles / circles)
    # OUTLET-1: (120, 250), OUTLET-2: (880, 250)
    outlets = [(120, 250), (880, 250)]
    for ox, oy in outlets:
        draw_circle(pixels, W, H, ox, oy, 16, (56, 189, 248, 255), fill=True)
        draw_line(pixels, W, H, ox - 16, oy, ox + 16, oy, (15, 23, 42, 255), width=2)

    # 2 Switches (Amber/Green squares near the interior doorway)
    # SWITCH-1: (460, 380), SWITCH-2: (540, 380)
    switches = [(460, 380), (540, 380)]
    for sx, sy in switches:
        draw_rect(pixels, W, H, sx - 12, sy - 12, sx + 12, sy + 12, (34, 197, 94, 255), fill=True)

    return create_png(W, H, pixels)


def main() -> None:
    png_bytes = generate_electrical_floorplan()
    out_path = Path("fixtures/images/floorplan_sample.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png_bytes)
    print(f"Generated synthetic image fixture: {out_path} ({len(png_bytes)} bytes, 1000x800)")


if __name__ == "__main__":
    main()
