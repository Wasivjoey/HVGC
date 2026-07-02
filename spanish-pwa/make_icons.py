"""Generate PWA icons at build time (pure stdlib, no Pillow needed).

Encodes small RGBA PNGs by hand. Design: a rose background with a warm amber
"sun" disc and short rays — friendly and legible at any size.
"""

import os
import zlib
import struct
import math

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "icons")
os.makedirs(OUT_DIR, exist_ok=True)


def _chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(size, painter):
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type 0
        for x in range(size):
            raw.extend(painter(x, y))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # RGBA, 8-bit
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )
    return png


def painter(size, maskable):
    cx = cy = size / 2
    pad = size * 0.12 if maskable else 0
    r_outer = size * 0.30 - pad * 0.2
    r_inner = size * 0.20 - pad * 0.2
    bg = (225, 29, 72, 255)      # rose-600
    sun = (251, 191, 36, 255)    # amber-400
    core = (254, 243, 199, 255)  # amber-100

    def paint(x, y):
        dx, dy = x - cx, y - cy
        d = math.hypot(dx, dy)
        if d < r_inner:
            return core
        if d < r_outer:
            return sun
        ang = math.atan2(dy, dx)
        if math.cos(ang * 12) > 0.55 and d < r_outer * 1.45:
            return sun
        return bg

    return paint


TARGETS = [
    ("icon-192.png", 192, False),
    ("icon-512.png", 512, False),
    ("icon-maskable-512.png", 512, True),
    ("apple-touch-icon.png", 180, False),
]

if __name__ == "__main__":
    for name, size, maskable in TARGETS:
        with open(os.path.join(OUT_DIR, name), "wb") as f:
            f.write(encode_png(size, painter(size, maskable)))
    print("Generated PWA icons in", OUT_DIR)
