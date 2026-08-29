"""Generuj assets/icon.ico — ikona zegara dla aplikacji i instalatora.

Uruchom: python scripts/make_icon.py
Tworzy assets/icon.ico z wieloma rozmiarami (16, 32, 48, 64, 128, 256).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICON_ICO = ASSETS / "icon.ico"
ICON_PNG = ASSETS / "icon.png"


def _draw_clock(size: int):
    """Narysuj ikonę zegara o danym rozmiarze."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    margin = max(2, size // 16)
    # tarcza (niebieska obwódka)
    d.ellipse([margin, margin, size - margin, size - margin], fill=(79, 156, 249, 255))
    # wewnętrzne koło (ciemne)
    inner = margin + max(2, size // 10)
    d.ellipse([inner, inner, size - inner, size - inner], fill=(15, 17, 21, 255))
    # wskazówki
    cx = cy = size // 2
    hand_len = (size // 2) - inner - max(1, size // 32)
    hand_w = max(1, size // 32)
    # do góry (12)
    d.line([cx, cy, cx, cy - hand_len], fill=(230, 233, 239, 255), width=hand_w)
    # w prawo (3)
    d.line([cx, cy, cx + hand_len, cy], fill=(110, 231, 183, 255), width=hand_w)
    # środek
    dot_r = max(2, size // 32)
    d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=(230, 233, 239, 255))
    return img


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Błąd: Pillow nie zainstalowane. Uruchom: pip install pillow", file=sys.stderr)
        return 1

    ASSETS.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 48, 64, 128, 256]
    # Narysuj największy i pozwól PIL zmniejszyć dla .ico
    big = _draw_clock(256)

    # Zapisz .ico (wielorozmiarowy — PIL automatycznie resize'uje)
    big.save(str(ICON_ICO), format="ICO", sizes=[(s, s) for s in sizes])
    print(f"OK: {ICON_ICO} ({ICON_ICO.stat().st_size} bytes)")

    # Zapisz też .png 256px (do użycia w README/instalatorze)
    big.save(str(ICON_PNG), format="PNG")
    print(f"OK: {ICON_PNG} ({ICON_PNG.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
