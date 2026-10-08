"""Draws desktidy/icon.ico (Explorer menu, tray, notifications): a folder with a check mark on a rounded square.
Run it again only to change the icon:  python docs/make_icon.py"""

import os

from PIL import Image, ImageDraw

SIZE = 512
OUT = os.path.join(os.path.dirname(__file__), "..", "desktidy", "icon.ico")


def draw() -> Image.Image:
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    top, bottom = (59, 130, 246), (124, 58, 237)
    gradient = Image.new("RGBA", (SIZE, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        gradient.paste(tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,), (0, y, SIZE, y + 1))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((16, 16, SIZE - 16, SIZE - 16), radius=112, fill=255)
    im.paste(gradient, (0, 0), mask)
    d = ImageDraw.Draw(im)
    white = (255, 255, 255, 255)
    d.rounded_rectangle((104, 150, 250, 210), radius=22, fill=white)           # folder tab
    d.rounded_rectangle((104, 180, 408, 382), radius=30, fill=white)           # folder body
    d.line((176, 282, 236, 338, 342, 226), fill=(91, 94, 242, 255), width=38, joint="curve")  # check mark
    for x, y in ((176, 282), (342, 226)):
        d.ellipse((x - 19, y - 19, x + 19, y + 19), fill=(91, 94, 242, 255))
    return im


if __name__ == "__main__":
    draw().save(OUT, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128),
                            (256, 256)])
    print("written", os.path.abspath(OUT))
