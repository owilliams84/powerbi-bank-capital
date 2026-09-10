"""Crop Desktop's page captures to the report canvas.

`powerbi-desktop screenshot` returns the whole Desktop window - ribbon, filter pane and all.
Every page here opens with the navy brand band across the full canvas width, which makes the
canvas easy to find: the first row with a long run of band-coloured pixels is the top edge, the
run's extent is the width, and the height follows from the 1440 x 900 canvas.

    python etl/crop_screenshots.py [--site <path to assets/work/bank-capital.png>]

Reads screenshots/raw_<page>.png, writes screenshots/<page>.png.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "screenshots"
BAND = (0x0A, 0x09, 0x17)
PAGES = {"pgCapital": "capital", "pgRisk": "risk-weights", "pgQuality": "asset-quality",
         "pgProfit": "profitability", "pgBanks": "banks"}

# The capital page carries the report's argument - the sector ratio against the average of
# banks - so it is what the site's work card shows.
SITE_PAGE = "capital"


def find_canvas(im: Image.Image) -> tuple[int, int, int, int]:
    px = im.load()
    w, h = im.size
    for y in range(h):
        run_start, best = None, (0, 0, 0)
        for x in range(w):
            close = all(abs(px[x, y][i] - BAND[i]) <= 6 for i in range(3))
            if close and run_start is None:
                run_start = x
            elif not close and run_start is not None:
                if x - run_start > best[0]:
                    best = (x - run_start, run_start, x)
                run_start = None
        if run_start is not None and w - run_start > best[0]:
            best = (w - run_start, run_start, w)
        if best[0] > w * 0.6:
            left, right = best[1], best[2]
            width = right - left
            return left, y, right, y + round(width * 900 / 1440)
    raise SystemExit("no brand band found - is this a capture of the report?")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", help=f"also write the {SITE_PAGE} page, resized, to this path")
    args = ap.parse_args()

    for page, name in PAGES.items():
        src = SHOTS / f"raw_{page}.png"
        if not src.exists():
            print(f"  missing {src.name}, skipped")
            continue
        im = Image.open(src).convert("RGB")
        box = find_canvas(im)
        out = im.crop(box)
        out.save(SHOTS / f"{name}.png", optimize=True)
        print(f"  {name}.png {out.size[0]}x{out.size[1]} (from {src.name}, box {box})")
        if name == SITE_PAGE and args.site:
            site = out.resize((2560, 1600), Image.LANCZOS)
            Path(args.site).parent.mkdir(parents=True, exist_ok=True)
            site.save(args.site, optimize=True)
            print(f"  site card image -> {args.site} ({Path(args.site).stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
