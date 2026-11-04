#!/usr/bin/env python3
"""Generate icon.ico (dark rounded square + yellow lightning bolt) using only the stdlib."""

import struct
import zlib

SIZE = 256

BG_OUT = (26, 27, 38, 255)       # outside (transparent)
PANEL = (36, 40, 59, 255)        # rounded square
BOLT = (255, 212, 59, 255)       # yellow bolt

# Lightning bolt polygon (normalized coords)
BOLT_POLY = [
    (0.56, 0.06),
    (0.28, 0.56),
    (0.45, 0.56),
    (0.38, 0.94),
    (0.72, 0.44),
    (0.53, 0.44),
    (0.70, 0.06),
]


def point_in_poly(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_int = xi + (xj - xi) * (y - yi) / (yj - yi)
            if x < x_int:
                inside = not inside
        j = i
    return inside


def rounded_rect(x, y, w, h, r):
    if x < 0 or y < 0 or x > w or y > h:
        return False
    if r <= x <= w - r or r <= y <= h - r:
        return True if (0 <= x <= w and 0 <= y <= h) else False
    cx = min(max(x, r), w - r)
    cy = min(max(y, r), h - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2


def make_pixels():
    px = [[BG_OUT for _ in range(SIZE)] for _ in range(SIZE)]
    margin = SIZE * 0.04
    w = h = SIZE - 2 * margin
    r = SIZE * 0.22
    for y in range(SIZE):
        for x in range(SIZE):
            lx, ly = x - margin, y - margin
            if rounded_rect(lx, ly, w, h, r):
                px[y][x] = PANEL
            nx, ny = x / SIZE, y / SIZE
            if point_in_poly(nx, ny, BOLT_POLY):
                px[y][x] = BOLT
    return px


def png_bytes(px):
    h, w = len(px), len(px[0])
    raw = b"".join(b"\x00" + bytes(c for p in row for c in p) for row in px)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main():
    px = make_pixels()
    png = png_bytes(px)
    # ICO header: 1 image, PNG-compressed, 256x256
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
    with open("icon.ico", "wb") as fh:
        fh.write(header + entry + png)
    print("icon.ico written:", 6 + 16 + len(png), "bytes")


if __name__ == "__main__":
    main()
