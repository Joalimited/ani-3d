"""Text -> GPU texture via Pillow, cached. Also a digit atlas for the many episode numbers."""
import glob

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import paths

FONT_GLOBS = [
    paths.resource("fonts", "NotoSansMono-Bold.ttf"),  # bundled, so the exe looks the same everywhere
    "C:/Windows/Fonts/consolab.ttf",
    "/usr/share/fonts/google-noto/NotoSansMono-Bold.ttf",
    "/usr/share/fonts/**/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/**/NotoSansMono*.ttf",
    "/usr/share/fonts/**/*Mono*.ttf",
]


def find_font():
    for pattern in FONT_GLOBS:
        hits = sorted(glob.glob(pattern, recursive=True))
        if hits:
            return hits[0]
    return None


class TextCache:
    def __init__(self, renderer, ratio=1.0):
        self.r, self.ratio = renderer, ratio
        self.path = find_font()
        self.fonts = {}
        self.cache = {}
        self.digit_tex, self.digit_aspect = self._digits()

    def font(self, px):
        px = max(6, int(round(px)))
        if px not in self.fonts:
            self.fonts[px] = ImageFont.truetype(self.path, px) if self.path else ImageFont.load_default()
        return self.fonts[px]

    def get(self, text, px, color=(255, 255, 255)):
        """Returns (Tex, logical_width, logical_height). `px` is the logical font size."""
        key = (text, px, color, self.ratio)
        hit = self.cache.get(key)
        if hit:
            return hit
        font = self.font(px * self.ratio)
        l, t, rgt, b = font.getbbox(text or " ")
        pad = 3
        w, h = int(rgt - min(l, 0)) + pad * 2, int(b - min(t, 0)) + pad * 2
        img = Image.new("RGBA", (max(w, 2), max(h, 2)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pos = (pad - min(l, 0), pad - min(t, 0))
        d.text(pos, text, font=font, fill=color + (255,), stroke_width=max(1, int(self.ratio)), stroke_fill=(0, 6, 16, 235))
        tex = self.r.make_texture(np.asarray(img))
        if len(self.cache) > 600:
            self.cache.clear()
        out = self.cache[key] = (tex, img.width / self.ratio, img.height / self.ratio)
        return out

    def _digits(self):
        font = self.font(96)
        cw, ch = 64, 110
        img = Image.new("RGBA", (cw * 10, ch), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for i in range(10):
            w = d.textlength(str(i), font=font)
            d.text((i * cw + (cw - w) / 2, 2), str(i), font=font, fill=(255, 255, 255, 255))
        return self.r.make_texture(np.asarray(img)), cw / ch

    def digit_uv(self, digit):
        return (digit / 10, 0, (digit + 1) / 10, 1)
