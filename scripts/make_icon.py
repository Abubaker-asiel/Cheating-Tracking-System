"""Draw the Invigil icon: an ink squircle, a viewfinder box (one corner flagged red) and an 'i'.
Writes invigil/assets/icon.png, icon.ico and icon.icns. Needs Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw

INK, PAPER, RED = (27, 31, 35, 255), (244, 241, 234, 255), (216, 67, 43, 255)
S = 2048  # draw at 2x, downscale for clean edges
k = S / 1024


def r(d, box, rad, fill):
    d.rounded_rectangle([int(v * k) for v in box], int(rad * k), fill=fill)


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r(d, (100, 100, 924, 924), 190, INK)
    L, T, R, B, arm, th = 250, 250, 774, 774, 170, 46
    for horiz, vert, col in [
        ((L, T, L + arm, T + th), (L, T, L + th, T + arm), PAPER),
        ((R - arm, T, R, T + th), (R - th, T, R, T + arm), RED),
        ((L, B - th, L + arm, B), (L, B - arm, L + th, B), PAPER),
        ((R - arm, B - th, R, B), (R - th, B - arm, R, B), PAPER),
    ]:
        r(d, horiz, th / 2, col)
        r(d, vert, th / 2, col)
    d.ellipse([int(v * k) for v in (462, 372, 562, 472)], fill=RED)
    r(d, (474, 505, 550, 665), 38, PAPER)
    return img.resize((1024, 1024), Image.LANCZOS)


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "invigil" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    img = draw()
    img.save(out / "icon.png")
    img.save(out / "icon.ico", sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
    img.save(out / "icon.icns")
    chev = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chev)
    cd.line([(22, 36), (48, 62), (74, 36)], fill=(27, 31, 35, 255), width=9, joint="curve")
    chev.resize((24, 24), Image.LANCZOS).save(out / "chevron.png")
    print("wrote", [p.name for p in sorted(out.iterdir())])
