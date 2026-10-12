"""Reproduce Hearth's rune-and-flame PNG/ICO with Python's standard library."""
from pathlib import Path
import math
import struct
import zlib

HERE = Path(__file__).resolve().parent
OUTER = [(128, 5), (233, 65), (233, 191), (128, 251), (23, 191), (23, 65)]
INNER = [(128, 16), (224, 71), (224, 185), (128, 240), (32, 185), (32, 71)]
FLAME = [(125, 42), (141, 73), (135, 103), (160, 82), (185, 116), (194, 145), (186, 174), (164, 195), (127, 204), (88, 195), (65, 169), (60, 138), (75, 111), (99, 93), (107, 68)]
CORE = [(125, 99), (134, 126), (158, 135), (166, 160), (151, 180), (127, 187), (102, 176), (94, 155), (101, 135)]
RUNE = [[(111, 125), (119, 125), (119, 181), (111, 181)], [(140, 125), (148, 125), (148, 181), (140, 181)], [(113, 139), (117, 131), (146, 155), (142, 163)], [(113, 163), (117, 171), (146, 147), (142, 139)]]

def inside(x, y, polygon):
    result = False
    previous = polygon[-1]
    for point in polygon:
        ax, ay = previous
        bx, by = point
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            result = not result
        previous = point
    return result

def color(x, y):
    if not inside(x, y, OUTER):
        return (0, 0, 0, 0)
    if not inside(x, y, INNER):
        return (231, 190, 118, 255)
    if any(inside(x, y, p) for p in RUNE):
        return (24, 39, 31, 255)
    if inside(x, y, CORE):
        return (255, 225, 160, 255)
    if inside(x, y, FLAME):
        return (231, 153, 68, 255)
    return (24, 39, 31, 255)

def png(size):
    scale = 4
    data = bytearray()
    for y in range(size):
        data.append(0)
        for x in range(size):
            samples = [color((x + (sx + .5) / scale) * 256 / size,
                             (y + (sy + .5) / scale) * 256 / size)
                       for sy in range(scale) for sx in range(scale)]
            alpha = sum(p[3] for p in samples)
            data.extend(tuple(round(sum(p[c] * p[3] for p in samples) / alpha) if alpha else 0 for c in range(3))
                        + (round(alpha / len(samples)),))
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(data, 9)) + chunk(b"IEND", b"")

def main():
    sizes = (16, 32, 48, 64, 128, 256)
    frames = [png(size) for size in sizes]
    (HERE / "hearth.png").write_bytes(frames[-1])
    offset = 6 + len(sizes) * 16
    index = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    for size, frame in zip(sizes, frames):
        index.extend(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    (HERE / "hearth.ico").write_bytes(index + b"".join(frames))
    def points(value):
        return " ".join(f"{x},{y}" for x, y in value)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">\n'
    for shape, fill in [(OUTER, "#e7be76"), (INNER, "#18271f"), (FLAME, "#e79944"), (CORE, "#ffe1a0")]:
        svg += f'  <polygon points="{points(shape)}" fill="{fill}"/>\n'
    for shape in RUNE:
        svg += f'  <polygon points="{points(shape)}" fill="#18271f"/>\n'
    (HERE / "hearth.svg").write_text(svg + "</svg>\n", encoding="utf-8")
    print("Generated Hearth SVG, 256px PNG, and six-size Windows ICO.")

if __name__ == "__main__":
    main()
