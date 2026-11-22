"""Generates the application icon (scripts/build/icon.ico).

Renders a simple deterministic grocery-basket mark so the installer and EXE
ship a real icon instead of the PyInstaller default. Re-run any time a
rebrand is needed: python scripts/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = (16, 24, 32, 48, 64, 128, 256)
GREEN = (24, 132, 82)
DARK = (18, 60, 44)
CREAM = (247, 243, 233)


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 64
    draw.rounded_rectangle((6 * s, 20 * s, 58 * s, 56 * s), radius=8 * s, fill=GREEN)
    draw.line((24 * s, 8 * s, 34 * s, 24 * s), fill=DARK, width=max(2, int(4 * s)))
    draw.line((42 * s, 6 * s, 34 * s, 24 * s), fill=DARK, width=max(2, int(4 * s)))
    draw.arc((14 * s, 22 * s, 50 * s, 54 * s), start=200, end=340,
             fill=CREAM, width=max(2, int(5 * s)))
    return img


def main() -> None:
    out_dir = Path("scripts/build")
    out_dir.mkdir(parents=True, exist_ok=True)
    icons = [render(size) for size in SIZES]
    target = out_dir / "icon.ico"
    icons[-1].save(target, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"icon written: {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
