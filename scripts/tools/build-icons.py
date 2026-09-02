"""Generate the PWA icon set from the square light-mode logo (SPEC §21 1.5a).

logo-dark.png is 309x433 (non-square) and unusable as an icon source - only
logo-light.png (600x600) works. Maskable icons need real padding (not just a
resize) because Android's adaptive-icon mask can crop up to ~20% off each
edge; compositing the glyph at 60% onto a solid accent square keeps it clear
of that safe-zone loss.

    uv run python scripts/tools/build-icons.py
"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

STATIC_IMG = Path(__file__).resolve().parent.parent.parent / "static" / "img"
SOURCE = STATIC_IMG / "logo-light.png"
ACCENT = (124, 58, 237)  # --color-accent-600, static/css/brand.css:36


def build():
    logo = Image.open(SOURCE).convert("RGBA")

    for size in (192, 512):
        logo.resize((size, size), Image.LANCZOS).save(STATIC_IMG / f"icon-{size}.png")

    # Maskable 512: accent-filled square, logo centered at 60% of the canvas
    # so nothing meaningful sits in the region Android's mask may clip.
    canvas = Image.new("RGBA", (512, 512), ACCENT + (255,))
    inner = 307  # 512 * 0.6, rounded
    glyph = logo.resize((inner, inner), Image.LANCZOS)
    offset = ((512 - inner) // 2, (512 - inner) // 2)
    canvas.alpha_composite(glyph, offset)
    canvas.save(STATIC_IMG / "icon-maskable-512.png")

    print(f"Wrote icon-192.png, icon-512.png, icon-maskable-512.png to {STATIC_IMG}")


if __name__ == "__main__":
    build()
