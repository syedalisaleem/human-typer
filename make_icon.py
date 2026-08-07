#!/usr/bin/env python3
"""Generates app.ico for Human Typer — pure stdlib, no dependencies."""

import struct

SIZE = 256
BG = (0, 0, 0, 0)
PANEL = (23, 26, 33, 255)
KEY = (126, 231, 135, 255)
KEY_DARK = (62, 132, 90, 255)


def inside_rounded(x, y, cx, cy, hw, hh, r):
    dx = abs(x - cx) - (hw - r)
    dy = abs(y - cy) - (hh - r)
    if dx < 0:
        dx = 0
    if dy < 0:
        dy = 0
    return dx * dx + dy * dy <= r * r


def pixel(x, y):
    if not inside_rounded(x, y, 128, 128, 118, 118, 42):
        return BG
    if inside_rounded(x, y, 128, 118, 110, 104, 34):
        return PANEL
    col = KEY if y < 186 else KEY_DARK
    for row in range(3):
        for k in range(4):
            kx = 128 - 100 + k * 68
            ky = 60 + row * 44
            if inside_rounded(x, y, kx, ky, 28, 14, 8):
                return col
    if inside_rounded(x, y, 128, 192, 118, 16, 10):
        return KEY_DARK
    return BG


def build_icon():
    raw = bytearray()
    for y in range(SIZE):
        for x in range(SIZE):
            r, g, b, a = pixel(x, y)
            raw += bytes((b, g, r, a))
    mask_len = ((SIZE + 31) // 32) * 4
    mask = bytes(mask_len * SIZE)
    hdr = struct.pack("<IiiHHIIiiII", 40, SIZE, SIZE * 2, 1, 32, 0,
                      len(raw) + len(mask), 0, 0, 0, 0)
    icondir = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32,
                        len(hdr) + len(raw) + len(mask), 22)
    with open("app.ico", "wb") as f:
        f.write(icondir + entry + hdr + raw + mask)
    print("wrote app.ico")


if __name__ == "__main__":
    build_icon()
