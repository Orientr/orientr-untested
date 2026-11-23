# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
"""Makes the shortcut icon orientr-logo.ico and the PNG icons in assets\\icons from the logo design ("Orientr
logo-project (3)", 2026-11-22: Main.dc.html and the small sizes of Variants.dc.html). Run it again after a change to
the design: python assets\\make_icons.py (needs Pillow). A changed icon needs a new file name (here and in
install.ps1): Windows keeps shortcut icons by path and goes on showing the old picture (the earlier orientr.ico kept
its blue arrow on the desktop, also after restarting Explorer).

The design has its own drawing per size, so the logo stays clear when small: 64 px (nozzle a bit bigger, plate edge
5), 40 px (nozzle bigger still, plate edge 7) and 20 px (no nozzle, the plate filled light), each on a dark circle.
Every icon size takes the drawing meant for it; 256 px the full logo of the avatar (with the plate's grid lines).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
INK, RING, PLATE = "#0E1A2B", "#E8EDF3", "#1C2E46"
TOP, LEFT, RIGHT = "#FF9A73", "#FF6B3D", "#C94A22"
PLATE_PTS = [(8, 70), (50, 49), (92, 70), (50, 91)]
CUBE = [([(30, 48), (50, 58), (50, 80), (30, 70)], LEFT), ([(50, 58), (70, 48), (70, 70), (50, 80)], RIGHT),
        ([(30, 48), (50, 38), (70, 48), (50, 58)], TOP)]

# The design's drawings (viewBox 0..100): nozzle body (x, y, w, h, corner), nozzle tip, plate edge, mark size in the
# circle (svg size / circle size), grid lines.
VARIANTS = {
    "main": dict(body=(43, 12, 14, 10, 1.5), tip=[(45, 22), (55, 22), (50, 30)], edge=3, mark=46 / 64, grid=True),   # as big in its circle as at 64 px
    "64": dict(body=(42, 10, 16, 12, 2), tip=[(44, 22), (56, 22), (50, 31)], edge=5, mark=46 / 64, grid=False),
    "40": dict(body=(41, 8, 18, 14, 2), tip=[(43, 22), (57, 22), (50, 32)], edge=7, mark=30 / 40, grid=False),
    "20": dict(body=None, tip=None, edge=0, mark=16 / 20, grid=False),
}
SIZES = {16: "20", 20: "20", 24: "20", 32: "40", 40: "40", 48: "64", 64: "64", 256: "main"}
SS = 8                                                    # supersampling: drawn 8x larger, then scaled down


def draw_icon(size: int, variant: str) -> Image.Image:
    v = VARIANTS[variant]
    n = size * SS
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, n - 1, n - 1), fill=INK)
    k = n * v["mark"] / 100                               # mark units -> pixels
    o = (n - 100 * k) / 2

    def p(pts):
        return [(o + x * k, o + y * k) for x, y in pts]

    if v["edge"]:
        d.polygon(p(PLATE_PTS), fill=PLATE)
        if v["grid"]:                                     # the plate's grid lines: ring colour at 35 %
            layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
            ImageDraw.Draw(layer).line(p([(29, 59.5), (71, 80.5)]), fill=RING, width=round(1.5 * k))
            ImageDraw.Draw(layer).line(p([(71, 59.5), (29, 80.5)]), fill=RING, width=round(1.5 * k))
            layer.putalpha(layer.getchannel("A").point(lambda a: a * 35 // 100))
            im.alpha_composite(layer)
            d = ImageDraw.Draw(im)
        w = round(v["edge"] * k)
        pts = p(PLATE_PTS)
        d.line(pts + [pts[0]], fill=RING, width=w, joint="curve")
        for x, y in pts:                                  # round corners (stroke-linejoin: round)
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=RING)
    else:
        d.polygon(p(PLATE_PTS), fill=RING)                # 20 px: the plate filled light, no edge
    for pts, colour in CUBE:
        d.polygon(p(pts), fill=colour)
    if v["body"]:
        x, y, w, h, r = v["body"]
        d.rounded_rectangle((o + x * k, o + y * k, o + (x + w) * k, o + (y + h) * k), radius=r * k, fill=RING)
        d.polygon(p(v["tip"]), fill=RING)
    return im.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = HERE / "icons"
    out.mkdir(exist_ok=True)
    images = {s: draw_icon(s, var) for s, var in SIZES.items()}
    for s, im in images.items():
        im.save(out / f"orientr-{s}.png")
    big = images[256]
    ico = HERE.parent / "orientr-logo.ico"
    big.save(ico, sizes=[(s, s) for s in SIZES], append_images=[images[s] for s in SIZES])
    print("written:", ico, "and", out)


if __name__ == "__main__":
    main()
