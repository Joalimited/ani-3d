"""The open book, built to behave like a real one.

It leans back on a lectern. Pages curve down into the gutter, the stacks are made of stacked curved layers (so the edge
looks like paper), the leaf being turned is a chain of strips whose free edge trails and settles, and the page text is
mapped across those strips so it bends with the paper. Manga use the same engine with the binding mirrored (spine on the
right, pages turn left to right) and image pages instead of an episode list.

Long-strip chapters (manhwa / webtoons, whose pages are far taller than they are wide) are not a book at all: once the
first pages show that shape the book becomes a hanging scroll between two wooden rollers, read by scrolling down.
"""
import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import mathx
from .renderer import Renderer
from .scene import box, ease
from .text import find_font

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bookart")  # page art is drawn here, off the render thread
S = 2.4  # scale of the held book relative to the one on the shelf


def book_thickness(b):
    """How thick the opened book is: from how long the series is (b["thick"], set by the library layout), not from how
    wide the book stands on the shelf - a face-out volume is wide on the shelf but must not open into a towering block."""
    return max(2.6, min(b.get("thick", 1.0) * S, 3.6))
TOTAL = 2.9  # seconds until the opening animation (cover + riffle) is done
NR = 5  # leaves riffled during the opening
T = 0.2  # cover board thickness
STRIPS = 12  # strips per turning leaf / resting page
TAU = -0.34  # the book leans back this far (radians)
CREAM, CREAM2, RED, GOLD = (0.95, 0.91, 0.79), (0.89, 0.84, 0.71), (0.62, 0.08, 0.08), (0.87, 0.70, 0.27)
INK, INK_L, INK_RED = (45, 30, 20, 255), (170, 150, 125, 255), (150, 28, 22, 255)
PER, ROWS = 24, 12  # chapters/episodes per page
GX, GY, ROWH, COLW = 56, 150, 70, 272  # grid layout inside a 640-wide page texture
STRIP_ASPECT = 1.8  # pages at least this much taller than wide are a long strip (manhwa / webtoon): read as a scroll
SW, SVH = 5.4, 8.6  # scroll: paper width and the height unrolled between the rollers (world units)
TILE_W, TILE_H = 720, 2048  # strip pages are cut into textures of at most this size
WOOD, WOOD_D = (0.45, 0.27, 0.13), (0.30, 0.17, 0.08)


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def lerp(a, b, f):
    return a + (b - a) * f


def tilt_for(u):
    """How far the book has leaned back at animation time u (it settles onto the lectern while it slides out)."""
    return TAU * (ease(u / 0.9) if u < 0.9 else 1.0)


class BookView:
    def __init__(self, app, book, kind="anime", rtl=False):
        self.app, self.b, self.kind = app, book, kind
        self.manga = kind == "manga"
        self.rtl = self.manga and rtl  # right-to-left binding: spine on the right, pages turn left to right (opt-in)
        self.rest = -1 if self.rtl else 1  # side the unread pages rest on (+1 right, -1 left)
        self.LP, self.HL = (5.5, 7.9) if self.manga else (4.65, 8.1)
        self.WP, self.HP = self.LP + 0.15, self.HL + 0.3
        self.WC, self.HC = self.WP + 0.1, self.HP + 0.15  # a slim cover overhang, like a real hardback
        self.PW = 880 if self.manga else 640
        self.PH = round(self.PW * self.HL / self.LP)
        # page layouts are designed on a 640x1115 sheet; kx/ky stretch that design onto this book's (differently shaped) pages
        self.kx, self.ky = self.PW / 640, self.PH / 1115
        self.spread = self.target = 0
        self.flip = None  # {"dir": +1 next / -1 previous, "t0", "dur"}
        self.mode = "toc"  # manga: "toc" (chapter list) or "read"
        self.chapter, self.pages_urls, self.chapter_pages = None, [], 0
        self.art, self.fonts, self.imgs, self.requested = {}, {}, {}, set()
        self.font_path = find_font()
        self.geom = self.hover = self.cover_tex = None
        self.pending, self._cover_fut, self._placeholder = {}, None, None
        self.TM = np.eye(4)
        self._prof = {}
        # long-strip scroll: strip = None until the first pages are measured, then True (scroll) / False (book)
        self.strip, self.sy, self.sy_goal, self.unroll_t0, self._t = None, 0.0, 0.0, None, None
        self.aspect, self.tiles, self.tile_pending = {}, {}, {}  # url -> height/width, url -> [(tex, world h)], url -> future

    # ---------- content ----------
    def eps(self):
        return self.b.get("all_eps") or []

    def n_items(self):
        return len(self.pages_urls) if self.mode == "read" else len(self.eps())

    def pages(self):
        return math.ceil(self.n_items() / PER) if self.mode == "toc" else len(self.pages_urls)

    def n_spreads(self):
        return 1 + math.ceil(self.pages() / 2)

    def watched(self):
        return set(self.b["episodes"])

    def next_ep(self):
        eps, w = self.eps(), self.watched()
        nums = [float(e) for e in w if _isnum(e)]
        if nums and eps:
            later = [e for e in eps if _isnum(e) and float(e) > max(nums)]
            if later:
                return later[0]
        if not eps:
            return str(int(max(nums)) + 1) if nums else "1"
        return next((e for e in eps if e not in w), eps[-1])

    def first_side(self):
        return "R" if self.rtl else "L"  # which page of a spread comes first in reading order

    def page_key(self, side, s):
        if s == 0:
            if self.mode == "read":
                return ("poster",) if side == "L" else ("chapcard",)
            return ("poster",) if side == "L" else ("info",)
        idx = 2 * (s - 1) + (0 if side == self.first_side() else 1)
        if self.mode == "read":
            return ("img", idx) if idx < len(self.pages_urls) else ("blank", side)
        return ("eps", idx) if idx < self.pages() else ("blank", side)

    def side_of(self, key):
        if key[0] in ("poster",):
            return "L"
        if key[0] in ("info", "chapcard"):
            return "R"
        if key[0] == "blank":
            return key[1]
        first = self.first_side()
        other = "L" if first == "R" else "R"
        return first if key[1] % 2 == 0 else other

    # ---------- manga reading state ----------
    def set_chapter(self, chapter, urls):
        self.mode, self.chapter, self.pages_urls = "read", chapter, urls
        self.spread = self.target = 0
        self.flip = None
        self.strip = strip_pref(self.b)  # a series already known to be a long strip opens straight into the scroll
        self.sy = self.sy_goal = 0.0
        self.unroll_t0 = None
        self.tiles, self.tile_pending = {}, {}
        self.aspect = {u: a for u, a in self.aspect.items() if u in urls}
        self.art = {k: v for k, v in self.art.items() if k[0] in ("poster",)}
        self.pending.clear()
        self.imgs = {u: i for u, i in self.imgs.items() if u in urls}

    def set_direction(self, rtl):
        """Switch between left-to-right and right-to-left binding (manga only). The layout restarts at the first spread."""
        self.rtl = self.manga and rtl
        self.rest = -1 if self.rtl else 1
        self.spread = self.target = 0
        self.flip = None
        self.art = {k: v for k, v in self.art.items() if k[0] in ("poster",)}
        self.pending.clear()
        self.cover_tex, self._cover_fut = None, None

    def back_to_toc(self):
        self.mode, self.chapter, self.pages_urls = "toc", None, []
        self.tiles, self.tile_pending = {}, {}
        self.spread = self.target = 0
        self.flip = None
        self.pending.clear()
        self.art = {k: v for k, v in self.art.items() if k[0] in ("poster",)}

    def chapter_index(self):
        eps = self.eps()
        return eps.index(self.chapter) if self.chapter in eps else -1

    # ---------- long-strip scroll ----------
    def scrolling(self):
        return self.manga and self.mode == "read" and bool(self.strip)

    def set_strip(self, on, remember=True):
        """Switch this chapter between the scroll and the book. The choice is remembered for the series."""
        self.strip = bool(on)
        self.sy = self.sy_goal = 0.0
        self.unroll_t0 = None
        self.spread = self.target = 0
        self.flip = None
        if remember:
            set_strip_pref(self.b, self.strip)

    def detect_strip(self):
        """Decide book or scroll from the shape of the first pages, once enough of them have loaded."""
        first = self.pages_urls[:4]
        known = [self.aspect[u] for u in first if u in self.aspect]
        if not first or len(known) < min(2, len(first)):
            return
        known.sort()
        self.set_strip(known[len(known) // 2] >= STRIP_ASPECT)
        if self.strip:
            self.app.status = f"Chapter {self.chapter} is a long strip (manhwa / webtoon) - it opens as a scroll: wheel, W/S or arrows to scroll down, V for the book"

    def strip_heights(self):
        """World height of every page on the scroll (pages not loaded yet use the typical shape so far)."""
        known = sorted(self.aspect.values())
        guess = known[len(known) // 2] if known else 3.0
        return [self.aspect.get(u, guess) * SW for u in self.pages_urls]

    def strip_page(self):
        """Index of the page in the middle of the window, and the heights it was worked out from."""
        hs = self.strip_heights()
        mid, y = self.sy + SVH / 2, 0.0
        for i, h in enumerate(hs):
            if y + h > mid:
                return i, hs
            y += h
        return max(0, len(hs) - 1), hs

    def strip_max(self):
        return max(0.0, sum(self.strip_heights()) - SVH)

    def scroll_by(self, d):
        self.sy_goal = min(max(self.sy_goal + d, 0.0), self.strip_max())

    def scroll_to_page(self, i):
        hs = self.strip_heights()
        self.sy_goal = min(max(sum(hs[:max(0, i)]), 0.0), self.strip_max())

    @staticmethod
    def _cut_tiles(src):
        """Worker thread: a strip page scaled to the scroll's width and cut into textures the GPU can hold."""
        w = min(src.width, TILE_W)
        img = src if w == src.width else src.resize((w, max(1, round(src.height * w / src.width))), Image.LANCZOS)
        out = []
        for y0 in range(0, img.height, TILE_H):
            part = img.crop((0, y0, w, min(img.height, y0 + TILE_H)))
            out.append((Renderer.build_levels(np.asarray(part.convert("RGBA")), True), part.height / w * SW))
        return out

    def strip_tiles(self, url):
        hit = self.tiles.get(url)
        if hit is not None:
            return hit
        if url in self.imgs and url not in self.tile_pending:
            self.tile_pending[url] = _POOL.submit(self._cut_tiles, self.imgs[url])
        return None

    def poll_tiles(self, keep, budget=3):
        for url, fut in list(self.tile_pending.items()):
            if budget <= 0:
                break
            if fut.done():
                del self.tile_pending[url]
                try:
                    self.tiles[url] = [(self.app.r.make_texture_levels(lv), h) for lv, h in fut.result()]
                except Exception:  # noqa: BLE001
                    pass
                budget -= 1
        for url in [u for u in self.tiles if u not in keep]:  # only the pages near the window stay on the GPU
            del self.tiles[url]

    def build_scroll(self, r, th, t, pos):
        """The hanging scroll: paper unrolled between two wooden rollers, the strip pages laid end to end on it."""
        dx, cy, cz = pos
        if self.unroll_t0 is None:
            self.unroll_t0 = t
        a = ease((t - self.unroll_t0) / 0.9)
        vh = max(SVH * a, 0.02)
        cur, hs = self.strip_page()
        total = max(sum(hs), 1e-6)
        keep = set(self.pages_urls[max(0, cur - 3):cur + 5])
        self.poll_tiles(keep)
        out = []
        top = cy + vh / 2
        # the paper behind the art (shows while a page is still loading)
        out.append(box(dx, cy, cz - 0.03, SW + 0.12, vh, 0.04, CREAM, 0.95, 0.0, 0.0, 0.0, 1.0))
        y = 0.0
        for i, (url, h) in enumerate(zip(self.pages_urls, hs)):
            if y > self.sy + vh:
                break
            if y + h >= self.sy and url in keep:
                tiles = self.strip_tiles(url)
                if tiles:
                    ty = y
                    for tex, th_ in tiles:
                        a0, a1 = max(ty, self.sy), min(ty + th_, self.sy + vh)
                        if a1 > a0:
                            v0, v1 = (a0 - ty) / th_, (a1 - ty) / th_
                            r.quad3d(tex, mathx.translate(dx - SW / 2, top - (a0 - self.sy), cz + 0.001) @ mathx.scale(SW, -(a1 - a0), 1), (1, 1, 1, 1), (0, v0, 1, v1))
                        ty += th_
            y += h
        # rollers: read paper winds onto the top one, unread paper waits on the bottom one, and they turn as you scroll
        done = min(max((self.sy + vh) / total, 0.0), 1.0)
        for side, frac in ((1, done), (-1, 1 - done)):
            rad = 0.2 + 0.28 * frac
            ry = top + rad if side > 0 else cy - vh / 2 - rad
            spin = -side * self.sy / max(rad, 0.1)
            for k in range(3):  # three rotated squares make a round-looking roll
                out.append(box(dx, ry, cz, SW + 0.06, 2 * rad, 2 * rad, CREAM if k % 2 == 0 else CREAM2, 0.9, 0.0, 0.0, 0.0, 1.0, 0.0, spin + k * math.pi / 6))
            for k in range(2):
                out.append(box(dx, ry, cz, SW + 1.1, 0.3, 0.3, WOOD, 0.4, 0.0, 0.2, 0.0, 1.0, 0.0, spin + k * math.pi / 4))
            for ex in (-1, 1):  # turned knobs on the ends
                kx = dx + ex * (SW / 2 + 0.62)
                out.append(box(kx, ry, cz, 0.22, 0.52, 0.52, WOOD_D, 0.4, 0.0, 0.2, 0.0, 1.0, 0.0, math.pi / 4))
                out.append(box(kx, ry, cz, 0.22, 0.52, 0.52, GOLD, 0.8, 0.0, 0.2, 0.0, 1.0))
        # a silk cord from the ends of the top roller up to a hook, so it reads as hanging
        ry = top + 0.2 + 0.28 * done
        hook = ry + 2.2
        for ex in (-1, 1):
            x0 = dx + ex * (SW / 2 + 0.45)
            mx, my = (x0 + dx) / 2, (ry + hook) / 2
            ln = math.hypot(x0 - dx, hook - ry)
            out.append(box(mx, my, cz, 0.06, ln, 0.06, RED, 0.6, 0.0, 0.0, 0.0, 1.0, math.atan2(dx - x0, hook - ry) * -1))
        out.append(box(dx, hook, cz, 0.3, 0.3, 0.3, GOLD, 1.0, 0.0, 0.2, 0.0, 1.0, 0.0, math.pi / 4))
        self.geom = self.hover = None
        return out

    # ---------- page art (Pillow -> mipmapped texture) ----------
    def font(self, px):
        px = int(round(px * self.kx))
        if px not in self.fonts:
            self.fonts[px] = ImageFont.truetype(self.font_path, px) if self.font_path else ImageFont.load_default()
        return self.fonts[px]

    def sig(self, key):
        base = (len(self.watched()), bool(self.b.get("poster_img")), len(self.eps()), bool(self.b.get("starred")), self.chapter)
        if key[0] == "img":
            return base + (key[1] < len(self.pages_urls) and self.pages_urls[key[1]] in self.imgs,)
        return base

    def placeholder(self):
        if self._placeholder is None:
            self._placeholder = self.app.r.make_texture(np.zeros((2, 2, 4), dtype=np.uint8))
        return self._placeholder

    def _render(self, key):
        """Runs on the worker thread: draw the page and build its mip chain. No GPU calls here."""
        fn = {"poster": self.art_poster, "info": self.art_info, "eps": self.art_eps, "blank": self.art_blank, "img": self.art_img, "chapcard": self.art_chapcard}[key[0]]
        img = self.gutter(fn(*key[1:]), self.side_of(key))
        return Renderer.build_levels(np.asarray(img), True)

    def texture(self, key):
        """The page texture for `key`. Never blocks: if it is not ready it is queued on the worker and the previous
        version (or a blank) is shown until the new one is uploaded by poll()."""
        sig = self.sig(key)
        hit = self.art.get(key)
        if hit and hit[0] == sig:
            return hit[1]
        pend = self.pending.get(key)
        if pend is None or pend[0] != sig:
            self.pending[key] = (sig, _POOL.submit(self._render, key))
        return hit[1] if hit else self.placeholder()

    def poll(self, budget=2):
        """Upload finished page textures (at most `budget` per frame so a flip never hitches)."""
        for key, (sig, fut) in list(self.pending.items()):
            if budget <= 0:
                break
            if not fut.done():
                continue
            del self.pending[key]
            try:
                levels = fut.result()
            except Exception:  # noqa: BLE001
                continue
            self.art[key] = (sig, self.app.r.make_texture_levels(levels))
            budget -= 1
        imgs = [k for k in self.art if k[0] == "img"]
        for old in imgs[:-14]:  # keep memory bounded while reading a long chapter
            del self.art[old]

    def warm(self, s0):
        """Queue the textures of the spreads around the current one so turning a page never waits on drawing."""
        for s in range(max(0, s0 - 1), min(self.n_spreads(), s0 + 3)):
            for side in ("L", "R"):
                self.texture(self.page_key(side, s))

    def gutter(self, img, side):
        """A soft shadow where the page curves down into the spine, plus a hint of the paper's outer edge."""
        w, h = img.size
        gw = int(w * 0.2)
        ramp = np.linspace(1.0, 0.0, gw) ** 1.6 * 120
        shade = np.zeros((h, w, 4), dtype=np.uint8)
        shade[:, :, 0], shade[:, :, 1], shade[:, :, 2] = 50, 32, 14
        a = np.zeros((h, w), dtype=np.float32)
        if side == "R":
            a[:, :gw] = ramp[None, :]
        else:
            a[:, w - gw:] = ramp[::-1][None, :]
        shade[:, :, 3] = a.astype(np.uint8)
        return Image.alpha_composite(img.convert("RGBA"), Image.fromarray(shade, "RGBA"))

    def blank_img(self):
        return Image.new("RGBA", (self.PW, self.PH), (0, 0, 0, 0))

    def art_blank(self, side="R"):
        img = self.blank_img()
        ImageDraw.Draw(img).line([(self.PW // 2 - 50, self.PH // 2), (self.PW // 2 + 50, self.PH // 2)], fill=INK_L, width=3)
        return img

    def art_poster(self):
        img = self.blank_img()
        d = ImageDraw.Draw(img)
        W, H, kx, ky = self.PW, self.PH, self.kx, self.ky
        d.rounded_rectangle((26 * kx, 30 * ky, W - 26 * kx, H - 30 * ky), 18 * kx, outline=(176, 138, 52, 255), width=int(5 * kx))
        d.rounded_rectangle((38 * kx, 42 * ky, W - 38 * kx, H - 42 * ky), 12 * kx, outline=(176, 138, 52, 255), width=int(2 * kx))
        poster = self.b.get("poster_img")
        if poster:
            p = poster.copy()
            p.thumbnail((int(W - 130 * kx), int(H - 190 * ky)), Image.LANCZOS)
            img.paste(p, ((W - p.width) // 2, int(70 * ky) + (int(H - 190 * ky) - p.height) // 2), p)
        else:
            d.text((W // 2, H // 2), "fetching cover...", font=self.font(34), fill=INK_L, anchor="mm")
        # caption under the poster: shrink to fit inside the frame, then wrap onto two lines if it is still too wide
        title, room = self.b["title"], W - 110 * kx
        for size in (30, 26, 22):
            if d.textlength(title, font=self.font(size)) <= room:
                d.text((W // 2, H - 82 * ky), title, font=self.font(size), fill=INK, anchor="mm")
                break
        else:
            lines = self.wrap(d, title, self.font(24), room, 2)
            for i, ln in enumerate(lines):
                d.text((W // 2, H - (100 - 28 * i) * ky), ln, font=self.font(24), fill=INK, anchor="mm")
        return img

    def wrap(self, d, text, font, width, max_lines):
        lines, cur = [], ""
        for w in text.split():
            t = (cur + " " + w).strip()
            if d.textlength(t, font=font) > width and cur:
                lines.append(cur)
                cur = w
            else:
                cur = t
        lines.append(cur)
        return lines[:max_lines]

    def art_info(self):
        img = self.blank_img()
        d = ImageDraw.Draw(img)
        W, kx, ky = self.PW, self.kx, self.ky
        gx = GX * kx
        f = self.font(58)
        y = 90 * ky
        for ln in self.wrap(d, self.b["title"], f, W - 2 * gx, 4):
            d.text((gx, y), ln, font=f, fill=INK)
            y += 74 * ky
        d.line([(gx, y + 6 * ky), (W - gx, y + 6 * ky)], fill=INK_L, width=3)
        unit = "chapters" if self.manga else "episodes"
        total = len(self.eps()) or self.b.get("total") or 0
        w = len(self.watched())
        y += 50 * ky
        d.text((gx, y), f"{'READ' if self.manga else 'WATCHED'} {w} / {total or '?'}", font=self.font(44), fill=INK)
        y += 78 * ky
        d.rounded_rectangle((gx, y, W - gx, y + 34 * ky), 10, fill=(70, 55, 40, 255))
        frac = min(1.0, w / total) if total else 0
        if frac > 0:
            d.rounded_rectangle((gx, y, gx + max(20, (W - 2 * gx) * frac), y + 34 * ky), 10, fill=(40, 150, 75, 255))
        y += 74 * ky
        if self.b.get("last"):
            d.text((gx, y), f"LAST {'READ' if self.manga else 'WATCHED'}  {self.b['last'][:10]}", font=self.font(32), fill=INK)
        if self.b.get("starred"):
            d.text((gx, y + 54 * ky), "* ON YOUR WATCH LIST", font=self.font(30), fill=(176, 120, 20, 255))
        d.text((gx, 880 * ky), f"NEXT: {'CHAPTER' if self.manga else 'EPISODE'} {self.next_ep()}", font=self.font(50), fill=INK_RED)
        d.text((gx, 950 * ky), "(click to read it)" if self.manga else "(click to play it)", font=self.font(28), fill=INK_L)
        arrow = "<<" if self.rtl else ">>"
        d.text((W // 2, self.PH - 70 * ky), f"turn the page for all {unit}  {arrow}", font=self.font(30), fill=INK_L, anchor="mm")
        return img

    def art_eps(self, idx):
        img = self.blank_img()
        d = ImageDraw.Draw(img)
        kx, ky = self.kx, self.ky
        chunk = self.eps()[idx * PER:(idx + 1) * PER]
        w, nxt = self.watched(), self.next_ep()
        unit = "CHAPTERS" if self.manga else "EPISODES"
        d.text((GX * kx, 56 * ky), f"{unit} {chunk[0]} - {chunk[-1]}", font=self.font(44), fill=INK)
        d.line([(GX * kx, 122 * ky), (self.PW - GX * kx, 122 * ky)], fill=INK_L, width=3)
        for i, ep in enumerate(chunk):
            row, col = divmod(i, 2)
            x0, y0 = (GX + col * COLW) * kx, (GY + row * ROWH) * ky
            seen, up = ep in w, ep == nxt
            d.text((x0 + 10 * kx, y0 + 12 * ky), f"{'CH' if self.manga else 'EP'} {ep}", font=self.font(38), fill=INK_RED if up else INK)
            cx, cy = x0 + 226 * kx, y0 + 34 * ky
            r_ = 16 * kx
            if seen:
                d.ellipse((cx - r_, cy - r_, cx + r_, cy + r_), fill=(40, 150, 75, 255))
                d.line([(cx - 8 * kx, cy), (cx - 2 * kx, cy + 7 * ky), (cx + 9 * kx, cy - 8 * ky)], fill=(255, 255, 255, 255), width=int(5 * kx))
            elif up:
                d.polygon([(cx - 11 * kx, cy - r_), (cx - 11 * kx, cy + r_), (cx + 17 * kx, cy)], fill=INK_RED)
            else:
                d.ellipse((cx - r_, cy - r_, cx + r_, cy + r_), outline=INK_L, width=int(3 * kx))
            d.line([(x0, y0 + (ROWH - 3) * ky), (x0 + (COLW - 12) * kx, y0 + (ROWH - 3) * ky)], fill=(220, 205, 180, 255), width=1)
        d.text((self.PW // 2, self.PH - 50 * ky), f"- {idx + 1} -", font=self.font(30), fill=INK_L, anchor="mm")
        return img

    def art_chapcard(self):
        img = self.blank_img()
        d = ImageDraw.Draw(img)
        W, kx, ky = self.PW, self.kx, self.ky
        d.text((W // 2, 300 * ky), "CHAPTER", font=self.font(46), fill=INK_L, anchor="mm")
        d.text((W // 2, 400 * ky), str(self.chapter), font=self.font(130), fill=INK_RED, anchor="mm")
        d.line([(120 * kx, 500 * ky), (W - 120 * kx, 500 * ky)], fill=INK_L, width=3)
        d.text((W // 2, 570 * ky), f"{len(self.pages_urls)} pages", font=self.font(40), fill=INK, anchor="mm")
        turn = "read right to left  <<<" if self.rtl else "read left to right  >>>"
        for i, ln in enumerate([turn, "arrows / A D turn the page", "[ ] previous / next chapter", "O chapter list", "G flip reading direction", "wheel zoom  -  Z fit page"]):
            d.text((W // 2, (700 + i * 48) * ky), ln, font=self.font(28), fill=INK_L, anchor="mm")
        return img

    def art_img(self, idx):
        img = self.blank_img()
        url = self.pages_urls[idx] if idx < len(self.pages_urls) else None
        src = self.imgs.get(url)
        if src is None:
            ImageDraw.Draw(img).text((self.PW // 2, self.PH // 2), f"page {idx + 1}\nloading...", font=self.font(40), fill=INK_L, anchor="mm", align="center")
            return img
        p = src.copy()
        p.thumbnail((self.PW, self.PH), Image.LANCZOS)
        img.paste(p, ((self.PW - p.width) // 2, (self.PH - p.height) // 2))
        return img

    def _render_cover(self):
        img = Image.new("RGBA", (512, 896), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        gold = (222, 178, 70, 255)
        d.rounded_rectangle((22, 22, 490, 874), 14, outline=gold, width=6)
        d.rounded_rectangle((38, 38, 474, 858), 10, outline=gold, width=2)
        f = ImageFont.truetype(self.font_path, 54) if self.font_path else ImageFont.load_default()
        lines = self.wrap(d, self.b["title"], f, 380, 4)
        y = 330 - 36 * len(lines)
        for ln in lines:
            d.text((256, y), ln, font=f, fill=gold, anchor="mm")
            y += 72
        d.line([(110, 640), (402, 640)], fill=gold, width=3)
        sub = ImageFont.truetype(self.font_path, 34) if self.font_path else ImageFont.load_default()
        d.text((256, 690), "MANGA" if self.manga else "WATCH LOG", font=sub, fill=gold, anchor="mm")
        return Renderer.build_levels(np.asarray(img), True)

    def cover_art(self):
        if self.cover_tex is None:
            if self._cover_fut is None:
                self._cover_fut = _POOL.submit(self._render_cover)
            elif self._cover_fut.done():
                self.cover_tex = self.app.r.make_texture_levels(self._cover_fut.result())
        return self.cover_tex or self.placeholder()

    # ---------- flipping ----------
    def left_delta(self):
        """Spread delta for a press of the LEFT arrow: next in manga (reading moves leftwards), previous otherwise."""
        return 1 if self.rtl else -1

    def key(self, k):
        if k == "v" and self.manga and self.mode == "read":
            self.set_strip(not self.strip)
            self.app.status = "Reading as a scroll (scroll down to read)" if self.strip else "Reading as a book (turn the pages)"
            return True
        if self.scrolling() and k not in ("o", "g", "[", "]"):
            step = {"ArrowDown": 1.6, "s": 1.6, "j": 1.6, "ArrowUp": -1.6, "w": -1.6, "k": -1.6, "ArrowRight": SVH * 0.85,
                    "d": SVH * 0.85, "PageDown": SVH * 0.85, " ": SVH * 0.85, "ArrowLeft": -SVH * 0.85, "a": -SVH * 0.85, "PageUp": -SVH * 0.85}.get(k)
            if k == "Home":
                self.sy_goal = 0.0
            elif k == "End":
                self.sy_goal = self.strip_max()
            elif step is not None:
                self.scroll_by(step)
            else:
                return False
            return True
        n = self.n_spreads() - 1
        ld = self.left_delta()
        delta = {"ArrowLeft": ld, "a": ld, "ArrowRight": -ld, "d": -ld, "ArrowUp": 5, "w": 5, "ArrowDown": -5, "s": -5, "PageDown": 5, "PageUp": -5}.get(k)
        if k == "Home":
            self.target = 0
        elif k == "End":
            self.target = n
        elif k == "c" and self.mode == "toc":
            eps = self.eps()
            nxt = self.next_ep()
            self.target = 1 + (eps.index(nxt) // PER) // 2 if nxt in eps else 0
        elif k == "o" and self.manga and self.mode == "read":
            self.back_to_toc()
        elif k == "g" and self.manga:
            self.app.toggle_manga_direction()
        elif k in ("[", "]") and self.manga and self.mode == "read":
            i = self.chapter_index() + (1 if k == "]" else -1)
            if 0 <= i < len(self.eps()):
                self.app.read_chapter(self.b, self.eps()[i])
        elif delta is not None:
            self.target = min(max(self.target + delta, 0), n)
        else:
            return False
        return True

    def go(self, delta):
        if self.scrolling():  # the screen-edge clicks and < > buttons move a window's height (left = back)
            return self.scroll_by(SVH * 0.85 * (-delta * self.left_delta()))
        self.target = min(max(self.target + delta, 0), self.n_spreads() - 1)

    def jump(self, first):
        if self.scrolling():
            self.sy_goal = 0.0 if first == (not self.rtl) else self.strip_max()  # the left-hand button goes to the top
            return
        self.target = 0 if first else self.n_spreads() - 1

    def update(self, t):
        dt, self._t = (t - self._t if self._t is not None else 0.0), t
        if self.mode == "read":
            for u in self.pages_urls:
                if u in self.imgs and u not in self.aspect:
                    im = self.imgs[u]
                    self.aspect[u] = im.height / max(1, im.width)
            if self.strip is None:
                self.detect_strip()
        if self.scrolling():
            self.sy_goal = min(self.sy_goal, self.strip_max())
            self.sy += (self.sy_goal - self.sy) * (1 - math.exp(-dt * 10))
            cur, _ = self.strip_page()
            for i in range(max(0, cur - 2), min(len(self.pages_urls), cur + 5)):  # fetch the pages around the window ahead
                url = self.pages_urls[i]
                if url not in self.imgs and url not in self.requested:
                    self.requested.add(url)
                    self.app.fetch_page_image(url, self)
            for i, url in enumerate(self.pages_urls):  # long chapters: let go of pages far behind or ahead
                if abs(i - cur) > 10 and url in self.imgs:
                    del self.imgs[url]
                    self.requested.discard(url)
            return
        if self.flip and t - self.flip["t0"] >= self.flip["dur"]:
            self.spread += self.flip["dir"]
            self.flip = None
        if not self.flip and self.spread != self.target:
            d = 1 if self.target > self.spread else -1
            self.flip = {"dir": d, "t0": t, "dur": 0.95 if abs(self.target - self.spread) == 1 else 0.32}
        if self.mode == "read":  # fetch the images around the current spread ahead of time
            for s in range(max(0, self.spread - 1), self.spread + 3):
                for side in ("L", "R"):
                    key = self.page_key(side, s)
                    if key[0] == "img":
                        url = self.pages_urls[key[1]]
                        if url not in self.imgs and url not in self.requested:
                            self.requested.add(url)
                            self.app.fetch_page_image(url, self)

    def spread_float(self, t):
        if not self.flip:
            return float(self.spread)
        return self.spread + self.flip["dir"] * smooth((t - self.flip["t0"]) / self.flip["dur"])

    # ---------- hit testing ----------
    def hit(self, origin, direction):
        """Ray -> (episode/chapter, side, rect) for the page cell under the mouse, or None."""
        g = self.geom
        if not g or self.flip or self.mode == "read":
            return None
        inv = np.linalg.inv(self.TM)  # the book is tilted: bring the ray into the book's own frame
        o = (inv @ np.append(origin, 1.0))[:3]
        d = inv[:3, :3] @ direction
        d = d / np.linalg.norm(d)
        LP, HL = self.LP, self.HL
        for side, key, x_left, z in (("L", g["lkey"], g["xh"] - 0.03 - LP, g["zl"]), ("R", g["rkey"], g["xh"] + 0.03, g["zr"])):
            if abs(d[2]) < 1e-6:
                continue
            t = (z + 0.02 - o[2]) / d[2]
            if t < 0:
                continue
            x, y = o[0] + t * d[0], o[1] + t * d[1]
            if not (x_left <= x <= x_left + LP and g["cy"] - HL / 2 <= y <= g["cy"] + HL / 2):
                continue
            px, py = (x - x_left) / LP * 640, (g["cy"] + HL / 2 - y) / HL * 1115
            if key[0] == "eps":
                col, row = int((px - GX) // COLW), int((py - GY) // ROWH)
                if 0 <= col < 2 and 0 <= row < ROWS and px >= GX:
                    i = key[1] * PER + row * 2 + col
                    if i < len(self.eps()):
                        return self.eps()[i], side, (GX + col * COLW, GY + row * ROWH, COLW - 12, ROWH - 4)
            elif key[0] == "info" and 870 <= py <= 990 and GX <= px <= 640 - GX:
                return self.next_ep(), side, (GX - 8, 872, 640 - 2 * GX + 16, 112)
        return None

    # ---------- drawing ----------
    def profile(self, R, n=STRIPS):
        """Resting-page curve: strip angles (negative = rising away from the gutter) and the page's exact rise.
        R scales the curvature: thick stacks fan out steeply from the spine, thin ones lie nearly flat."""
        key = (round(R, 3), n)
        hit = self._prof.get(key)
        if hit:
            return hit
        LP = self.LP
        l = LP / n
        ang, z = [], 0.0
        for j in range(n):
            x = (j + 0.5) * l
            slope = R * 3 / LP * (1 - x / LP) ** 2
            ang.append(-math.atan(slope))
            z += l * slope / math.sqrt(1 + slope * slope)
        self._prof[key] = (ang, z)
        return ang, z

    def prof_for_rise(self, rise, n=STRIPS):
        """Curvature that makes a page rise exactly `rise` from the gutter to its outer edge."""
        R = rise
        for _ in range(3):
            R *= rise / max(self.profile(R, n)[1], 1e-6)
        return self.profile(R, n) + (R,)

    @staticmethod
    def side_rise(thick):
        """How far a side's top page climbs from the gutter to its outer edge. Proportional to the stack's thickness (so the
        page can never dip below the cover board and get hidden), capped so the text near the spine stays readable."""
        return min(max(0.8 * thick, 0.05), 1.1)

    def build(self, r, text, th, t, u, pos):
        b = self.b
        dx, cy, cz = pos
        LP, HL, WP, HC, WC = self.LP, self.HL, self.WP, self.HC, self.WC
        rest = self.rest
        P = book_thickness(b)
        Pp = P - 2 * T
        out = []
        open_amt = smooth((u - 0.9) / 0.9)
        th_c = -math.pi * open_amt
        xh = dx - rest * WP / 2 * (1 - open_amt)  # the hinge slides toward centre as the book opens
        cover = tuple(c * 0.8 for c in b["color"])
        z0 = cz - P / 2 + T
        tau = TAU
        piv = np.array([dx, cy, cz])
        self.TM = mathx.translate(*piv) @ mathx.rot_x(tau) @ mathx.translate(*(-piv))

        def Q(tex, M, tint=(1, 1, 1, 1), uv=(0, 0, 1, 1)):
            r.quad3d(tex, self.TM @ M, tint, uv)

        interactive = u >= TOTAL
        if interactive and self.scrolling():
            return self.build_scroll(r, th, t, pos)
        self.poll()
        self.warm(self.spread if interactive else 0)
        if interactive:
            f = self.spread_float(t) / max(1, self.n_spreads() - 1)
            land_th = Pp * (0.12 + 0.76 * f)
        else:
            land_th = Pp * 0.12 * sum(smooth((u - (1.45 + 0.14 * k)) / (0.55 + 0.04 * k)) for k in range(NR)) / NR
        rest_th = Pp - land_th
        th_left, th_right = (rest_th, land_th) if rest < 0 else (land_th, rest_th)
        zl, zr = z0 + th_left, z0 + th_right

        # ----- lectern: a slim ledge and back board (dark, so they never read as extra frames around the page)
        grow = ease((u - 0.9) / 0.5)
        dark = tuple(c * 0.5 for c in th.wood)
        out.append(box(dx, cy - HC / 2 - 0.55, cz + 0.15, (2 * WP + 0.6) * grow, 0.34, 1.2, dark, 0.15, 0.0, 0.2))
        out.append(box(dx, cy, cz - P / 2 - 0.4, (2 * WC + 0.5) * grow, HC + 0.35, 0.3, dark, 0.1, 0.0, 0.2))

        # ----- covers and spine
        out.append(box(xh + rest * (self.WC / 2 - 0.08), cy, cz - P / 2 + T / 2, WC, HC, T, cover, 0.45, 0.0, 0.1))
        sp_x = xh - rest * 0.15
        # the spine is the binding: full height while closed, but once open it lies under the gutter so the pages fan out of it
        sp_th = lerp(P + 0.06, T, open_amt)
        sp_z = lerp(cz, cz - P / 2 + sp_th / 2, open_amt)
        out.append(box(sp_x, cy, sp_z, 0.34, HC, sp_th, cover, 0.5, 0.0, 0.1))
        if open_amt < 0.35:
            out.append(box(sp_x - rest * 0.2, cy, sp_z, 0.12, HC - 0.4, max(sp_th - 0.5, 0.2), tuple(c * 0.75 for c in cover), 0.4, 0.0, 0.1))
            for off in (-0.38, -0.30, 0.30, 0.38):  # gilt bands on the closed spine
                out.append(box(sp_x - rest * 0.01, cy + off * HC, sp_z, 0.38, 0.07, sp_th + 0.04, GOLD, 1.0, 0.0, 0.0))
        phi_c = th_c if not self.rtl else math.pi - th_c
        lx, lz = WC / 2 - 0.08, rest * (P / 2 - T / 2)
        fx = xh + lx * math.cos(phi_c) + lz * math.sin(phi_c)
        fz = cz - lx * math.sin(phi_c) + lz * math.cos(phi_c)
        out.append(box(fx, cy, fz, WC, HC, T, cover, 0.45, phi_c, 0.1))
        zo = (T / 2 + 0.006) * rest
        uv_c = (1, 0, 0, 1) if self.rtl else (0, 0, 1, 1)
        Q(self.cover_art(), mathx.translate(fx, cy, fz) @ mathx.rot_y(phi_c) @ mathx.translate(-WC / 2, HC / 2, zo) @ mathx.scale(WC, -HC, 1), (1, 1, 1, 1), uv_c)

        # ----- page blocks: thin curved layers fanning out of the spine (one bound block, not a pile of boards)
        l = LP / STRIPS

        def chain(side, z_outer, thick, glow, shade, tex=None, rise=0.5, n=STRIPS):
            """A page surface on `side`: strips that follow a curve rising `rise` from the gutter to the outer edge at z_outer."""
            ang, rs, _ = self.prof_for_rise(rise, n)
            ln = LP / n
            px, pz = xh + side * 0.03, z_outer - rs
            for j in range(n):
                phi = ang[j] if side > 0 else -math.pi - ang[j]
                cx_, cz_ = px + ln / 2 * math.cos(phi), pz - ln / 2 * math.sin(phi)
                out.append(box(cx_, cy, cz_ - thick / 2 + 0.02, ln + 0.012, HL, thick, shade, glow, phi, 0.0))
                if tex is not None:
                    zoff = (thick / 2 + 0.004) if side > 0 else -(thick / 2 + 0.004)
                    uv = (j / n, 0, (j + 1) / n, 1) if side > 0 else (1 - j / n, 0, 1 - (j + 1) / n, 1)
                    Q(tex[0], mathx.translate(cx_, cy, cz_ - thick / 2 + 0.02) @ mathx.rot_y(phi) @ mathx.translate(-ln / 2, HL / 2, zoff) @ mathx.scale(ln, -HL, 1), (1, 1, 1, tex[1]), uv)
                px, pz = px + ln * math.cos(phi), pz - ln * math.sin(phi)

        def stack(side, thick):
            if thick < 0.03:
                return  # no pages on this side yet (the book is still closed)
            n = int(min(64, max(3, thick / 0.07)))
            st = thick / n
            top_rise = self.side_rise(thick)
            for k in range(n):
                # low layers stay close to the spine, higher ones fan out - and none climbs higher than the top page, so
                # no layer can poke through the page that sits on top of it
                rise = max(top_rise * (k + 0.5) / n, 0.02)
                shade = CREAM if k % 2 == 0 else tuple(c * 0.965 for c in CREAM)
                chain(side, z0 + (k + 1) * st - 0.06, st * 1.05, 0.95, shade, None, rise, 8)

        stack(-1, th_left)
        stack(1, th_right)
        prof_l = self.prof_for_rise(self.side_rise(th_left))
        prof_r = self.prof_for_rise(self.side_rise(th_right))
        gzl, gzr = zl - prof_l[1], zr - prof_r[1]  # height of each side's top page at the gutter

        def leaf(start, end, p, theta, sgn, tex_a, tex_b, curl=1.0, settle=0.0):
            """The page being turned: strips from the gutter; it rises off one stack's curve, trails and settles on the other's."""
            (ps, gz0), (pe, gz1) = start, end
            px, pz = xh, lerp(gz0, gz1, smooth(p)) + 0.04 + 0.14 * math.sin(math.pi * p)
            amp = curl * math.sin(math.pi * p)
            for j in range(STRIPS):
                frac = (j + 0.5) / STRIPS
                off = sgn * (ps[j] * (1 - p) - pe[j] * p)
                lag = sgn * (amp * frac ** 1.6 + settle * frac)
                phi = theta + off + lag
                cx_, cz_ = px + l / 2 * math.cos(phi), pz - l / 2 * math.sin(phi)
                out.append(box(cx_, cy, cz_, l + 0.012, HL, 0.04, CREAM, 0.95, phi, 0.0))
                for tex, back in ((tex_a, False), (tex_b, True)):
                    if tex is None:
                        continue
                    zoff = -0.023 if back else 0.023
                    uv = (1 - j / STRIPS, 0, 1 - (j + 1) / STRIPS, 1) if back else (j / STRIPS, 0, (j + 1) / STRIPS, 1)
                    Q(tex, mathx.translate(cx_, cy, cz_) @ mathx.rot_y(phi) @ mathx.translate(-l / 2, HL / 2, zoff) @ mathx.scale(l, -HL, 1), (1, 1, 1, 1), uv)
                px, pz = px + l * math.cos(phi), pz - l * math.sin(phi)

        right_side, left_side = (prof_r[0], gzr), (prof_l[0], gzl)
        self.geom = None
        # direction the leaf travels: from the rest side to the other side when moving forward
        gdir_fwd = 1 if rest > 0 else -1
        if not interactive:  # opening: a few blank leaves riffle across
            for k in range(NR):
                p = (u - (1.45 + 0.14 * k)) / (0.55 + 0.04 * k)
                if 0 < p < 1:
                    curl = 0.8 + 0.12 * k
                    settle = 0.16 * math.exp(-9 * max(p - 0.82, 0)) * math.sin(40 * max(p - 0.82, 0)) if p > 0.82 else 0.0
                    if gdir_fwd > 0:
                        leaf(right_side, left_side, p, -math.pi * p, 1, None, None, curl, settle)
                    else:
                        leaf(left_side, right_side, p, -math.pi * (1 - p), -1, None, None, curl, settle)
            show = ease((u - (TOTAL - 0.5)) / 0.5)
        else:
            show = 1.0
        # top page of each stack (carries the text once the book has opened)
        s, fl = self.spread, self.flip
        if interactive:
            if fl:
                p = smooth((t - fl["t0"]) / fl["dur"])
                gdir = fl["dir"] if rest > 0 else -fl["dir"]
                before, after = s, s + fl["dir"]
                settle = 0.16 * math.exp(-9 * max(p - 0.82, 0)) * math.sin(40 * max(p - 0.82, 0)) if p > 0.82 else 0.0
                if gdir > 0:
                    lk, rk = self.page_key("L", before), self.page_key("R", after)
                    leaf(right_side, left_side, p, -math.pi * p, 1, self.texture(self.page_key("R", before)), self.texture(self.page_key("L", after)), 1.0, settle)
                else:
                    lk, rk = self.page_key("L", after), self.page_key("R", before)
                    leaf(left_side, right_side, p, -math.pi * (1 - p), -1, self.texture(self.page_key("R", after)), self.texture(self.page_key("L", before)), 1.0, settle)
            else:
                lk, rk = self.page_key("L", s), self.page_key("R", s)
        else:
            lk, rk = self.page_key("L", 0), self.page_key("R", 0)
        tl = (self.texture(lk), show) if show > 0.02 else None
        tr = (self.texture(rk), show) if show > 0.02 else None
        if th_left > 0.03:
            chain(-1, zl, 0.04, 0.95, CREAM, tl, self.side_rise(th_left))
        if th_right > 0.03:
            chain(1, zr, 0.04, 0.95, CREAM, tr, self.side_rise(th_right))
        if interactive:
            self.geom = {"xh": xh, "cy": cy, "zl": zl, "zr": zr, "lkey": lk, "rkey": rk}
            ray = getattr(self.app.lib, "ray", None)
            self.hover = self.hit(*ray) if ray else None
            if self.hover and not fl:
                ep, side, (rx, ry, rw, rh) = self.hover
                x_left = xh - 0.03 - LP if side == "L" else xh + 0.03
                z = zl if side == "L" else zr
                Q(r.white, mathx.translate(x_left + rx / 640 * LP, cy + HL / 2 - ry / 1115 * HL, z + 0.02) @ mathx.scale(rw / 640 * LP, -rh / 1115 * HL, 1), (0.9, 0.55, 0.1, 0.28))

        # ----- tilt every box about the book centre (the lectern angle), then add the column in world space
        arr = np.array(out, dtype=np.float32)
        v = arr[:, 0:3] - piv.astype(np.float32)
        c, s_ = math.cos(tau), math.sin(tau)
        arr[:, 1], arr[:, 2] = piv[1] + v[:, 1] * c - v[:, 2] * s_, piv[2] + v[:, 1] * s_ + v[:, 2] * c
        arr[:, 0] = piv[0] + v[:, 0]
        arr[:, 12] = tau
        arr[:, 13] = 1.0  # the whole book skips posterizing
        rows = arr.tolist()
        base = cy - HC / 2 - 0.6
        rows.append(box(dx, base / 2 - 0.2, cz - 0.6, 1.4 * grow, max(base, 0.5), 0.9, th.wood, 0.25, 0.0, 0.3, 0.0, 1.0))
        return rows


def strip_pref(b):
    """Remembered book/scroll choice for a series: True, False, or None (not known yet - measure the pages)."""
    if "_strip" not in b:
        from .themes import load_settings
        b["_strip"] = load_settings().get("strip_series", {}).get(str(b.get("id")))
    return b["_strip"]


def set_strip_pref(b, on):
    from .themes import load_settings, save_settings
    b["_strip"] = on
    prefs = load_settings().get("strip_series", {})
    prefs[str(b.get("id"))] = on
    save_settings(strip_series=prefs)


def _isnum(e):
    try:
        float(e)
        return True
    except (TypeError, ValueError):
        return False
