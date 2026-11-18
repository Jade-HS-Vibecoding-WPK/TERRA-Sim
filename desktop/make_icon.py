"""Zeichnet das Programmsymbol (desktop/icon.ico, icon.png) nach assets/icon.svg – nur mit Pillow.

Aufruf:  python desktop/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 512
S = SIZE / 48                                       # SVG-Raster 48 × 48 -> Pixel


def _p(x, y):
    return (x + 2) * S, (y + 2) * S                 # translate(2 2) wie im SVG


def _wave() -> list:
    """M6 13 q4 -4 8 0 t8 0 t8 0 t8 0 – vier Bögen, abwechselnd nach oben und unten."""
    points = []
    for k in range(4):
        x0, sign = 6 + 8 * k, -1 if k % 2 == 0 else 1
        for i in range(21):
            t = i / 20
            # quadratische Bézierkurve: Start (x0, 13), Kontrollpunkt (x0 + 4, 13 ± 4), Ende (x0 + 8, 13)
            x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * (x0 + 4) + t ** 2 * (x0 + 8)
            y = 13 + 2 * (1 - t) * t * 4 * sign
            points.append(_p(x, y))
    return points


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([_p(0, 0), _p(44, 44)], radius=10 * S, fill="#1f7a4d")
    d.polygon([_p(*xy) for xy in ((6, 31), (15, 23), (22, 28), (30, 19), (38, 26), (38, 38), (6, 38))],
              fill="#9fd6b3")
    d.rectangle([_p(12, 25), _p(18, 38)], fill="#ffffff")
    d.rectangle([_p(20, 20), _p(27, 38)], fill="#e2f3e6")
    d.rectangle([_p(29, 23), _p(34, 38)], fill="#ffffff")
    d.line(_wave(), fill="#ffffff", width=round(2.6 * S), joint="curve")
    return img


if __name__ == "__main__":
    icon = draw()
    icon.resize((256, 256), Image.LANCZOS).save(HERE / "icon.png")
    icon.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon.ico und icon.png geschrieben")
