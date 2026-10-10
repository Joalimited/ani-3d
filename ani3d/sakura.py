"""Sakura garden theme: cherry trees in full bloom, traditional houses with glowing shoji walls and tiled roofs, koi ponds
with a red arched bridge and stone lanterns, bamboo groves, a raked zen garden, a pagoda, torii gates and Mount Fuji on
the horizon. Petals drift down, paper lanterns sway and koi swim. The scenery is built once into a numpy block.
"""
import math
import random

import numpy as np

from . import models
from .scene import box

EDGE = 0.14
CLEAR = (-72.0, 72.0, -160.0, 22.0)  # x0, x1, z0, z1: where the pedestals live
PONDS = [(-104.0, -40.0, 16.0), (112.0, -18.0, 13.0)]  # x, z, radius
HOUSES = [(-118.0, -118.0, 0.7), (122.0, -96.0, -0.8), (-112.0, 62.0, 2.3), (108.0, 70.0, -2.4)]  # x, z, yaw (front faces the clearing)
PINKS = [(1.0, 0.74, 0.84), (1.0, 0.66, 0.8), (0.98, 0.82, 0.9), (0.95, 0.58, 0.74), (1.0, 0.88, 0.93)]
BARK, RED, BLACK = (0.24, 0.13, 0.11), (0.82, 0.16, 0.1), (0.06, 0.05, 0.06)
WOOD, DARKWOOD, PAPER, TILE, STONE = (0.46, 0.3, 0.18), (0.22, 0.13, 0.09), (1.0, 0.93, 0.78), (0.2, 0.21, 0.25), (0.5, 0.5, 0.48)
KOI = [((0.97, 0.96, 0.92), (0.9, 0.2, 0.08)), ((1.0, 0.5, 0.08), (1.0, 0.75, 0.3)), ((0.95, 0.8, 0.3), (1.0, 0.95, 0.6)),
       ((0.1, 0.1, 0.12), (0.92, 0.3, 0.1)), ((0.97, 0.96, 0.92), (0.1, 0.1, 0.12))]


def limb(p0, p1, th, col, glow=0.1, edge=EDGE):
    """A world-space box joining two points (its long y axis along p0 -> p1)."""
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    ln = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
    rz = -math.asin(max(-1.0, min(1.0, dx / ln)))
    rx = math.atan2(dz / ln, dy / ln)
    return box((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2, th, ln + th * 0.5, th, col, glow, 0.0, edge, 0.0, 0.0, rz, rx)


class Local:
    """Places boxes in a rotated local frame (x right, z toward the front) - used for houses, bridges, gates."""

    def __init__(self, out, x, z, yaw):
        self.out, self.x, self.z, self.yaw = out, x, z, yaw
        self.c, self.s = math.cos(yaw), math.sin(yaw)

    def p(self, lx, lz):
        return self.x + lx * self.c + lz * self.s, self.z - lx * self.s + lz * self.c

    def add(self, lx, y, lz, sx, sy, sz, col, glow=0.1, edge=EDGE, rz=0.0, rx=0.0):
        wx, wz = self.p(lx, lz)
        self.out.append(box(wx, y, wz, sx, sy, sz, col, glow, self.yaw, edge, 0.0, 0.0, rz, rx))


class Garden:
    def __init__(self, seed=5):
        self.rnd = random.Random(seed)
        self.blocked = []  # (x, z, r) of trunks and buildings, so scenery doesn't overlap
        self.lanterns = []  # (x, y, z, colour, phase): paper lanterns that sway
        self.meshes = None
        if models.available():  # Blender-made garden (tools/blender_models.py); the box-built one is the fallback
            self.meshes, extra = self._mesh_scenery()
            self.static = np.array(extra, dtype=np.float32).reshape(-1, 16)
        else:
            self.static = np.array(self._scenery(), dtype=np.float32)
        self.koi = []
        for pi, (px, pz, pr) in enumerate(PONDS):
            for k in range(7):
                self.koi.append({"pond": pi, "r": pr * self.rnd.uniform(0.3, 0.8), "w": self.rnd.uniform(0.12, 0.3) * self.rnd.choice((-1, 1)),
                                 "a": self.rnd.uniform(0, math.tau), "wob": self.rnd.uniform(0.2, 0.5), "pal": KOI[(k + pi) % len(KOI)],
                                 "size": self.rnd.uniform(1.6, 2.4)})
        self.platforms = []

    # ---------- placement ----------
    def _free(self, x, z, margin=0.0):
        x0, x1, z0, z1 = CLEAR
        if x0 - margin < x < x1 + margin and z0 - margin < z < z1 + margin:
            return False
        if any(math.hypot(x - px, z - pz) < pr + 3 + margin for px, pz, pr in PONDS):
            return False
        return all(math.hypot(x - bx, z - bz) > br + margin for bx, bz, br in self.blocked)

    def _spot(self, rnd, rmin, rmax, margin=0.0, tries=30):
        for _ in range(tries):
            a, rad = rnd.uniform(0, math.tau), rnd.uniform(rmin, rmax)
            x, z = math.sin(a) * rad, math.cos(a) * rad
            if self._free(x, z, margin):
                return x, z
        return None

    # ---------- pieces ----------
    def cherry(self, out, rnd, x, z, s):
        """A gnarled trunk that bends as it rises, branches fanning out and a cloud of blossom clusters."""
        p0 = (x, 0.0, z)
        lean = rnd.uniform(0, math.tau)
        p1 = (x + math.cos(lean) * 0.8 * s, 3.2 * s, z - math.sin(lean) * 0.8 * s)
        p2 = (p1[0] - math.cos(lean) * 0.6 * s, 5.6 * s, p1[2] + math.sin(lean) * 0.6 * s)
        out.append(limb(p0, p1, 1.1 * s, BARK))
        out.append(limb(p1, p2, 0.85 * s, BARK))
        for k in range(4):  # root flare
            a = k * math.pi / 2 + 0.3
            out.append(limb((x, 0.6 * s, z), (x + math.cos(a) * 1.3 * s, 0.0, z - math.sin(a) * 1.3 * s), 0.5 * s, BARK))
        tips = []
        for k in range(6):
            a = k / 6 * math.tau + rnd.uniform(-0.3, 0.3)
            ln = rnd.uniform(3.0, 4.8) * s
            mid = (p2[0] + math.cos(a) * ln * 0.5, p2[1] + rnd.uniform(0.8, 1.6) * s, p2[2] - math.sin(a) * ln * 0.5)
            tip = (p2[0] + math.cos(a) * ln, p2[1] + rnd.uniform(1.0, 2.6) * s, p2[2] - math.sin(a) * ln)
            out.append(limb(p2, mid, 0.5 * s, BARK))
            out.append(limb(mid, tip, 0.32 * s, BARK))
            tips += [mid, tip]
        for k in range(34):  # blossom clusters, soft and slightly luminous (many small ones read fluffier than a few cubes)
            bx, by, bz = rnd.choice(tips)
            cs = rnd.uniform(1.4, 2.6) * s
            out.append(box(bx + rnd.uniform(-1.4, 1.4) * s, by + rnd.uniform(-0.3, 1.2) * s, bz + rnd.uniform(-1.4, 1.4) * s,
                           cs, cs * 0.62, cs, rnd.choice(PINKS), 0.45, rnd.uniform(0, 1.5), 0.08))
        for k in range(6):  # fallen petals under the tree
            a, rr = rnd.uniform(0, math.tau), rnd.uniform(1.5, 6.5) * s
            ps = rnd.uniform(1.2, 2.8)
            out.append(box(x + math.cos(a) * rr, 0.03, z - math.sin(a) * rr, ps, 0.04, ps * 0.7, rnd.choice(PINKS), 0.3, rnd.uniform(0, 3), 0.0))
        self.blocked.append((x, z, 1.6 * s))

    def house(self, out, x, z, yaw):
        """A traditional house: stone footings, raised floor, veranda (engawa), dark posts, glowing shoji walls,
        a tiled hip-and-gable roof with a ridge, upturned eaves, a noren curtain and hanging lanterns."""
        L = Local(out, x, z, yaw)
        W, D = 14.0, 10.0
        for lx in (-W / 2 + 0.5, 0.0, W / 2 - 0.5):
            for lz in (-D / 2 + 0.5, D / 2 - 0.5):
                L.add(lx, 0.35, lz, 0.9, 0.7, 0.9, STONE)
        L.add(0, 0.85, 0, W, 0.3, D, WOOD, 0.1)
        L.add(0, 0.9, D / 2 + 1.0, W + 1.0, 0.16, 2.0, (0.55, 0.38, 0.22), 0.12)  # engawa
        L.add(0, 0.45, D / 2 + 2.3, 2.2, 0.3, 1.0, STONE)  # step stone
        post_x = [-W / 2, -W / 2 + 3.5, -1.0, 1.0, W / 2 - 3.5, W / 2]
        for lx in post_x:
            for lz in (-D / 2, D / 2):
                L.add(lx, 2.95, lz, 0.32, 4.0, 0.32, DARKWOOD)
        for lz in (-D / 2 + 3.3, D / 2 - 3.3):
            for lx in (-W / 2, W / 2):
                L.add(lx, 2.95, lz, 0.32, 4.0, 0.32, DARKWOOD)
        for k in range(len(post_x) - 1):  # front: shoji panels lit from inside, a paper grid on each
            a, b = post_x[k], post_x[k + 1]
            if b - a < 2.5:
                continue  # the doorway
            cx, pw = (a + b) / 2, b - a - 0.32
            L.add(cx, 2.95, D / 2, pw, 3.9, 0.12, PAPER, 0.95, 0.0)
            for gy in (1.9, 2.95, 4.0):
                L.add(cx, gy, D / 2 + 0.08, pw, 0.05, 0.04, DARKWOOD, 0.05, 0.0)
            for gx in (-pw / 3, 0.0, pw / 3):
                L.add(cx + gx, 2.95, D / 2 + 0.08, 0.05, 3.9, 0.04, DARKWOOD, 0.05, 0.0)
        L.add(0, 2.4, D / 2 - 0.4, 1.7, 2.9, 0.1, (0.15, 0.08, 0.05), 0.05, 0.0)  # dark doorway
        for k in (-0.45, 0.45):  # noren curtain over the door
            L.add(k, 4.25, D / 2 + 0.05, 0.85, 1.0, 0.05, (0.12, 0.18, 0.4), 0.2, 0.0)
        L.add(0, 4.4, D / 2 + 0.07, 0.4, 0.4, 0.04, (0.95, 0.95, 0.9), 0.4, 0.0)
        for lx in (-W / 2, W / 2):  # side walls: plaster panels between dark beams
            L.add(lx, 2.95, 0, 0.14, 3.9, D, (0.92, 0.9, 0.84), 0.2, 0.0)
            L.add(lx, 4.7, 0, 0.2, 0.3, D, DARKWOOD)
        L.add(0, 2.95, -D / 2, W, 3.9, 0.14, (0.4, 0.27, 0.17), 0.1)
        L.add(0, 4.95, 0, W + 0.4, 0.3, D + 0.4, DARKWOOD)  # wall plate
        # roof: front and back slopes, hipped ends, a ridge with end tiles, upturned corners and tile courses
        L.add(0, 6.2, D / 4 + 1.2, W + 3.2, 0.35, D / 2 + 3.4, TILE, 0.12, EDGE, 0.0, 0.48)
        L.add(0, 6.2, -D / 4 - 1.2, W + 3.2, 0.35, D / 2 + 3.4, TILE, 0.12, EDGE, 0.0, -0.48)
        for k in range(5):  # tile courses as faint ridges on the front slope
            f = (k + 0.5) / 5
            L.add(0, 7.25 - f * 2.3, 0.4 + f * (D / 2 + 2.4), W + 3.0, 0.08, 0.16, (0.14, 0.15, 0.18), 0.05, 0.0, 0.0, 0.48)
        for sx in (-1, 1):
            L.add(sx * (W / 2 + 0.3), 6.3, 0, 3.6, 0.35, D + 1.6, TILE, 0.12, EDGE, -sx * 0.55, 0.0)
        L.add(0, 7.55, 0, W * 0.62, 0.5, 0.75, (0.12, 0.12, 0.15), 0.12)  # ridge
        for sx in (-1, 1):
            L.add(sx * W * 0.31, 7.95, 0, 0.6, 0.9, 0.8, (0.12, 0.12, 0.15), 0.12)  # onigawara end tiles
            for sz in (-1, 1):  # eave corners curling up
                L.add(sx * (W / 2 + 1.4), 5.25, sz * (D / 2 + 1.6), 1.6, 0.25, 1.6, TILE, 0.12, EDGE, sx * 0.35, -sz * 0.35)
        for sx in (-1, 1):  # paper lanterns under the front eave (they sway; drawn every frame)
            wx, wz = L.p(sx * 3.2, D / 2 + 1.6)
            self.lanterns.append((wx, 4.4, wz, (1.0, 0.25, 0.15), wx * 0.3))
        self.blocked.append((x, z, 10.0))

    def pagoda(self, out, x, z, s):
        """Five tiers, each a body with a wide roof whose corners turn up, and a spire of rings on top."""
        y = 0.0
        out.append(box(x, 0.6 * s, z, 12 * s, 1.2 * s, 12 * s, STONE, 0.1, 0.0, EDGE))
        y = 1.2 * s
        for k in range(5):
            bw = (8.0 - k * 1.1) * s
            bh = 4.2 * s
            out.append(box(x, y + bh / 2, z, bw, bh, bw, (0.75, 0.2, 0.12), 0.25, 0.0, EDGE))
            out.append(box(x, y + bh / 2, z, bw * 0.6, bh * 0.7, bw + 0.05, PAPER, 0.6, 0.0, 0.0))
            rw = bw + 4.2 * s
            out.append(box(x, y + bh + 0.3 * s, z, rw, 0.6 * s, rw, TILE, 0.15, 0.0, EDGE))
            out.append(box(x, y + bh + 0.85 * s, z, rw * 0.62, 0.6 * s, rw * 0.62, TILE, 0.15, 0.0, EDGE))
            for sx in (-1, 1):
                for sz in (-1, 1):
                    out.append(box(x + sx * rw * 0.47, y + bh + 0.6 * s, z + sz * rw * 0.47, 1.6 * s, 0.3 * s, 1.6 * s, TILE, 0.15,
                                   math.pi / 4, EDGE, 0.0, 0.0, 0.0, 0.0))
            y += bh + 1.3 * s
        out.append(box(x, y + 4 * s, z, 0.5 * s, 8 * s, 0.5 * s, (0.75, 0.6, 0.25), 0.6, 0.0, EDGE))
        for k in range(6):
            out.append(box(x, y + 1.5 * s + k * 1.0 * s, z, 1.3 * s, 0.25 * s, 1.3 * s, (0.8, 0.65, 0.25), 0.6, 0.0, EDGE))
        self.blocked.append((x, z, 9 * s))

    def torii(self, out, x, z, yaw, s=1.0):
        L = Local(out, x, z, yaw)
        for sx in (-1, 1):
            L.add(sx * 4.5 * s, 5.0 * s, 0, 0.9 * s, 10 * s, 0.9 * s, RED, 0.45)
            L.add(sx * 4.5 * s, 0.4 * s, 0, 1.3 * s, 0.8 * s, 1.3 * s, BLACK, 0.1)
        L.add(0, 7.6 * s, 0, 11.5 * s, 0.6 * s, 0.6 * s, RED, 0.45)  # nuki
        L.add(0, 9.9 * s, 0, 12.5 * s, 0.6 * s, 1.0 * s, RED, 0.45)  # shimaki
        L.add(0, 10.5 * s, 0, 13.2 * s, 0.55 * s, 1.3 * s, BLACK, 0.15)  # kasagi
        for sx in (-1, 1):  # the kasagi's ends sweep upward
            L.add(sx * 7.2 * s, 10.75 * s, 0, 2.0 * s, 0.5 * s, 1.3 * s, BLACK, 0.15, EDGE, sx * 0.3)
        L.add(0, 8.8 * s, 0.1, 1.3 * s, 1.8 * s, 0.4 * s, BLACK, 0.2)  # gakuzuka plaque
        L.add(0, 8.8 * s, 0.32, 0.9 * s, 1.3 * s, 0.05, (0.85, 0.7, 0.3), 0.6, 0.0)

    def stone_lantern(self, out, x, z, s=1.0):
        out.append(box(x, 0.3 * s, z, 1.6 * s, 0.6 * s, 1.6 * s, STONE, 0.1, 0.4, EDGE))
        out.append(box(x, 1.4 * s, z, 0.6 * s, 1.8 * s, 0.6 * s, STONE, 0.1, 0.4, EDGE))
        out.append(box(x, 2.5 * s, z, 1.3 * s, 0.35 * s, 1.3 * s, STONE, 0.1, 0.4, EDGE))
        out.append(box(x, 3.2 * s, z, 1.0 * s, 1.0 * s, 1.0 * s, STONE, 0.1, 0.4, EDGE))
        out.append(box(x, 3.2 * s, z, 1.06 * s, 0.5 * s, 0.5 * s, (1.0, 0.8, 0.4), 1.8, 0.4, 0.0))  # lit windows
        out.append(box(x, 3.2 * s, z, 0.5 * s, 0.5 * s, 1.06 * s, (1.0, 0.8, 0.4), 1.8, 0.4, 0.0))
        out.append(box(x, 3.95 * s, z, 1.9 * s, 0.4 * s, 1.9 * s, STONE, 0.1, 0.4, EDGE))
        out.append(box(x, 4.35 * s, z, 0.9 * s, 0.4 * s, 0.9 * s, STONE, 0.1, 0.4, EDGE))
        out.append(box(x, 4.75 * s, z, 0.35 * s, 0.45 * s, 0.35 * s, STONE, 0.1, 0.4, EDGE))
        self.blocked.append((x, z, 1.2 * s))

    def pond(self, out, rnd, px, pz, pr):
        for k in range(3):
            out.append(box(px, 0.03, pz, pr * 2, 0.06, pr * 2 * 0.42, (0.06, 0.22, 0.27), 0.3, k * math.pi / 3, 0.0))
            out.append(box(px, 0.05, pz, pr * 1.65, 0.06, pr * 1.65 * 0.42, (0.08, 0.3, 0.36), 0.4, k * math.pi / 3 + 0.5, 0.0))
        for k in range(30):  # rounded rocks around the edge, some mossy
            a = k / 30 * math.tau + rnd.uniform(-0.05, 0.05)
            s = rnd.uniform(0.7, 1.5)
            col = STONE if k % 3 else (0.35, 0.45, 0.3)
            out.append(box(px + math.cos(a) * (pr + 0.6), 0.32 * s, pz - math.sin(a) * (pr + 0.6), 1.4 * s, 0.64 * s, 1.0 * s, col, 0.08, a, EDGE))
        for k in range(10):  # lily pads and petals floating on the water
            a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, pr * 0.85)
            lx, lz = px + math.cos(a) * rr, pz - math.sin(a) * rr
            if k % 2:
                for q in range(3):
                    out.append(box(lx, 0.1, lz, 1.3, 0.04, 0.55, (0.22, 0.5, 0.2), 0.2, q * math.pi / 3 + a, 0.0))
            else:
                out.append(box(lx, 0.09, lz, 0.5, 0.03, 0.35, rnd.choice(PINKS), 0.5, a, 0.0))
        for k in range(12):  # irises on the bank
            a = rnd.uniform(0, math.tau)
            rr = pr + rnd.uniform(1.4, 2.6)
            ix, iz = px + math.cos(a) * rr, pz - math.sin(a) * rr
            out.append(box(ix, 0.9, iz, 0.08, 1.8, 0.08, (0.25, 0.5, 0.2), 0.1, 0.0, 0.0))
            out.append(box(ix + 0.15, 0.7, iz, 0.12, 1.4, 0.04, (0.3, 0.55, 0.22), 0.1, a, 0.0, 0.0, 0.0, 0.2))
            for q in range(3):
                out.append(box(ix, 1.85, iz, 0.55, 0.06, 0.18, (0.5, 0.3, 0.85), 0.5, q * math.pi / 3, 0.0, 0.0, 0.0, 0.0, 0.3))

    def bridge(self, out, x, z, yaw, span=26.0, rise=3.2):
        """A red taiko (drum) bridge: planks following an arch, posts and a handrail that follow it too."""
        L = Local(out, x, z, yaw)
        n = 16
        pts = [(-span / 2 + span * k / n, 0.3 + rise * (1 - (2 * k / n - 1) ** 2)) for k in range(n + 1)]
        for k in range(n):
            (x0, y0), (x1, y1) = pts[k], pts[k + 1]
            ang = math.atan2(y1 - y0, x1 - x0)
            L.add((x0 + x1) / 2, (y0 + y1) / 2, 0, math.hypot(x1 - x0, y1 - y0) + 0.05, 0.3, 3.2, (0.55, 0.32, 0.18), 0.12, EDGE, ang)
            for sz in (-1, 1):  # side beams and the rail
                L.add((x0 + x1) / 2, (y0 + y1) / 2 - 0.25, sz * 1.65, math.hypot(x1 - x0, y1 - y0) + 0.05, 0.35, 0.25, RED, 0.45, EDGE, ang)
                L.add((x0 + x1) / 2, (y0 + y1) / 2 + 1.25, sz * 1.65, math.hypot(x1 - x0, y1 - y0) + 0.05, 0.18, 0.2, RED, 0.45, EDGE, ang)
        for k in range(0, n + 1, 2):
            px_, py_ = pts[k]
            for sz in (-1, 1):
                L.add(px_, py_ + 0.6, sz * 1.65, 0.25, 1.4 if 0 < k < n else 1.9, 0.25, RED, 0.45)
                if k in (0, n):
                    L.add(px_, py_ + 1.65, sz * 1.65, 0.35, 0.35, 0.35, (0.85, 0.7, 0.3), 0.8)  # brass caps

    def bamboo(self, out, rnd, x, z):
        for k in range(rnd.randint(12, 18)):
            a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, 3.0)
            bx, bz = x + math.cos(a) * rr, z - math.sin(a) * rr
            h = rnd.uniform(9, 15)
            lean = rnd.uniform(-0.06, 0.06)
            g = rnd.choice([(0.38, 0.6, 0.2), (0.45, 0.65, 0.22), (0.32, 0.55, 0.18)])
            out.append(box(bx, h / 2, bz, 0.3, h, 0.3, g, 0.15, a, 0.1, 0.0, 0.0, lean))
            for yy in np.arange(1.4, h, 1.5):  # nodes
                out.append(box(bx - math.sin(lean) * yy, yy, bz, 0.38, 0.08, 0.38, (0.6, 0.72, 0.35), 0.2, a, 0.0))
            for q in range(4):  # leaf sprays near the top
                la = rnd.uniform(0, math.tau)
                out.append(box(bx + math.cos(la) * 0.9, h - rnd.uniform(0, 2.5), bz - math.sin(la) * 0.9, 1.8, 0.05, 0.3,
                               (0.35, 0.6, 0.2), 0.2, la, 0.0, 0.0, 0.0, -0.3))
        self.blocked.append((x, z, 4.0))

    def zen(self, out, x, z, yaw):
        """A raked gravel garden: a framed bed of pale gravel with straight rake lines and rings around three rocks."""
        L = Local(out, x, z, yaw)
        W, D = 20.0, 13.0
        L.add(0, 0.06, 0, W, 0.12, D, (0.82, 0.8, 0.74), 0.15, 0.0)
        for sx in (-1, 1):
            L.add(sx * W / 2, 0.15, 0, 0.4, 0.3, D + 0.4, DARKWOOD)
        for sz in (-1, 1):
            L.add(0, 0.15, sz * D / 2, W + 0.4, 0.3, 0.4, DARKWOOD)
        rocks = [(-5.0, -1.5, 1.6), (3.5, 2.0, 1.1), (6.5, -3.0, 0.8)]
        for k in range(-11, 12):
            lz = k * 0.55
            L.add(0, 0.13, lz, W - 0.6, 0.03, 0.08, (0.68, 0.66, 0.6), 0.05, 0.0)
        for rx, rz, rs in rocks:
            for ring in (rs + 0.6, rs + 1.2, rs + 1.8):
                for q in range(24):
                    a = q / 24 * math.tau
                    L.add(rx + math.cos(a) * ring, 0.14, rz + math.sin(a) * ring, ring * 0.28, 0.03, 0.09, (0.86, 0.84, 0.78), 0.1, 0.0)
            L.add(rx, 0.7 * rs, rz, 2.0 * rs, 1.4 * rs, 1.6 * rs, (0.38, 0.38, 0.38), 0.08)
            L.add(rx + 0.2, 1.3 * rs, rz, 1.2 * rs, 0.6 * rs, 1.0 * rs, (0.34, 0.42, 0.3), 0.1)
        self.blocked.append((x, z, 12.0))

    def fuji(self, out):
        """Mount Fuji on the horizon: stepped blue-grey slopes and a snow cap."""
        x, z = 60.0, -330.0
        n = 30
        for k in range(n):  # many thin layers, so the slope reads as a smooth concave cone
            f = k / n
            w = 280 * (1 - f) ** 1.6 + 14
            y = 4 + k * 3.2
            snow = k >= n - 9
            col = (0.95, 0.95, 1.0) if snow else (0.32 - 0.1 * f, 0.33 - 0.08 * f, 0.48 - 0.05 * f)
            out.append(box(x, y, z, w, 3.4, w * 0.35, col, 0.5 if snow else 0.15, 0.0, 0.0))
        out.append(box(-80, 72, -300, 30, 30, 2, (1.0, 0.82, 0.7), 1.5, 0.0, 0.0, 0.0, 1.0))  # low evening sun
        out.append(box(-80, 72, -301, 44, 44, 1, (0.7, 0.42, 0.5), 0.8, 0.0, 0.0, 0.0, 1.0))

    def _scenery(self):
        rnd = random.Random(3)
        out = []
        for hx, hz, yaw in HOUSES:
            self.house(out, hx, hz, yaw)
        self.pagoda(out, -40.0, -215.0, 1.25)
        self.torii(out, 35.0, -185.0, 0.15, 1.2)
        self.torii(out, PONDS[0][0] + 6, PONDS[0][1] + PONDS[0][2] + 8, 0.4, 0.9)
        for px, pz, pr in PONDS:
            self.pond(out, rnd, px, pz, pr)
        self.bridge(out, PONDS[0][0], PONDS[0][1], 0.35, PONDS[0][2] * 2 + 3, 3.4)
        for px, pz, pr in PONDS:  # stone lanterns watching each pond
            for a in (0.8, 2.6, 4.4):
                self.stone_lantern(out, px + math.cos(a) * (pr + 4), pz - math.sin(a) * (pr + 4), 1.1)
        self.zen(out, 108.0, -150.0, -0.5)
        self.fuji(out)
        # signature cherries framing the clearing, then a blossoming woodland further out
        for x, z, s in [(-86, 12, 1.5), (88, -8, 1.45), (-84, -150, 1.4), (86, -168, 1.5), (-48, 44, 1.15), (52, 46, 1.2)]:
            if self._free(x, z, 2):
                self.cherry(out, rnd, x, z, s)
        for i in range(55):
            p = self._spot(rnd, 45, 220, 5)
            if p:
                self.cherry(out, rnd, p[0], p[1], rnd.uniform(0.9, 1.35))
        for i in range(7):
            p = self._spot(rnd, 60, 200, 5)
            if p:
                self.bamboo(out, rnd, *p)
        for i in range(40):  # trimmed round azalea bushes, some in flower
            p = self._spot(rnd, 30, 150, 1.5)
            if not p:
                continue
            x, z = p
            g = (0.18, 0.4, 0.15)
            for k in range(3):
                out.append(box(x + (k - 1) * 0.6, 0.7, z, 1.8, 1.4, 1.8, g, 0.12, k * 0.5, EDGE))
            if i % 2 == 0:
                for k in range(8):
                    a = rnd.uniform(0, math.tau)
                    out.append(box(x + math.cos(a) * 1.0, rnd.uniform(0.9, 1.5), z - math.sin(a) * 1.0, 0.3, 0.2, 0.3, (1.0, 0.45, 0.65), 0.8, a, 0.0))
        for i in range(30):  # mossy rocks
            p = self._spot(rnd, 30, 170, 1.0)
            if p:
                x, z = p
                s = rnd.uniform(0.8, 2.0)
                out.append(box(x, 0.45 * s, z, 1.8 * s, 0.9 * s, 1.4 * s, STONE, 0.08, rnd.uniform(0, 2), EDGE))
                out.append(box(x, 0.92 * s, z, 1.4 * s, 0.2 * s, 1.1 * s, (0.3, 0.45, 0.22), 0.1, rnd.uniform(0, 2), EDGE))
        for i in range(260):  # grass tufts
            p = self._spot(rnd, 24, 180, 0.0, 4)
            if p:
                x, z = p
                for k in range(3):
                    a = k * 2.1 + rnd.uniform(0, 1)
                    h = rnd.uniform(0.6, 1.2)
                    out.append(box(x + math.cos(a) * 0.1, h / 2, z - math.sin(a) * 0.1, 0.07, h, 0.03, (0.3, 0.52, 0.18), 0.08, a, 0.0, 0, 0, 0.0, 0.25))
        # stepping-stone paths from the clearing out to each house
        for hx, hz, _ in HOUSES:
            d = math.hypot(hx, hz)
            for k in range(int(d / 3.2)):
                f = k * 3.2 / d
                sx, sz = hx * f, hz * f
                if self._free(sx, sz, -1.0) or not (CLEAR[0] < sx < CLEAR[1] and CLEAR[2] < sz < CLEAR[3]):
                    if any(math.hypot(sx - bx, sz - bz) < br - 2 for bx, bz, br in self.blocked):
                        continue
                    out.append(box(sx + rnd.uniform(-0.4, 0.4), 0.06, sz + rnd.uniform(-0.4, 0.4), 1.8, 0.12, 1.4, (0.55, 0.54, 0.5), 0.1, rnd.uniform(0, 1), EDGE))
        # lantern lines on poles along the sides of the clearing
        for side in (-1, 1):
            for k in range(7):
                z = 10 - k * 26
                x = side * 80
                out.append(box(x, 3.5, z, 0.3, 7.0, 0.3, DARKWOOD, 0.1, 0.0, EDGE))
                if k < 6:
                    out.append(box(x, 6.6, z - 13, 0.05, 0.05, 26, BLACK, 0.0, 0.0, 0.0))
                    for q in range(3):
                        self.lanterns.append((x, 6.1, z - 6.5 * (q + 1), (1.0, 0.95, 0.85) if (k + q) % 2 else (1.0, 0.3, 0.2), k * 1.3 + q))
        return out

    def _mesh_scenery(self):
        """The garden from Blender models. Returns (MeshSet, a few plain boxes: lantern poles and strings, the sun)."""
        rnd = random.Random(3)
        M, out = models.MeshSet(), []
        for hx, hz, yaw in HOUSES:
            M.put("jhouse", hx, 0, hz, 1.0, yaw)
            L = Local(out, hx, hz, yaw)
            for sx in (-1, 1):  # paper lanterns under the front eave
                wx, wz = L.p(sx * 3.2, 5.0 + 1.6)
                self.lanterns.append((wx, 4.4, wz, (1.0, 0.25, 0.15), wx * 0.3))
            self.blocked.append((hx, hz, 10.0))
        M.put("pagoda", -40.0, 0, -215.0, 1.25)
        self.blocked.append((-40.0, -215.0, 9 * 1.25))
        M.put("torii", 35.0, 0, -185.0, 1.2, 0.15)
        M.put("torii", PONDS[0][0] + 6, 0, PONDS[0][1] + PONDS[0][2] + 8, 0.9, 0.4)
        for px, pz, pr in PONDS:
            M.put("water_deep", px, 0.03, pz, (pr + 0.3, 1, pr + 0.3), 0.0, edge=0.0, tint=(0.75, 0.85, 0.9))
            M.put("water_light", px, 0.05, pz, (pr * 0.82, 1, pr * 0.82), 0.4, edge=0.0, tint=(0.75, 0.85, 0.9))
            for k in range(30):
                a = k / 30 * math.tau + rnd.uniform(-0.05, 0.05)
                M.put("rock_a" if k % 3 == 0 else rnd.choice(("stone_a", "stone_b")), px + math.cos(a) * (pr + 0.6), 0, pz - math.sin(a) * (pr + 0.6),
                      rnd.uniform(0.55, 0.9), a)
            for k in range(10):
                a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, pr * 0.85)
                lx, lz = px + math.cos(a) * rr, pz - math.sin(a) * rr
                if k % 2:
                    M.put("lilypad", lx, 0, lz, rnd.uniform(1.1, 1.6), a)
                else:
                    out.append(box(lx, 0.09, lz, 0.5, 0.03, 0.35, rnd.choice(PINKS), 0.5, a, 0.0))  # a petal afloat
            for k in range(12):
                a = rnd.uniform(0, math.tau)
                rr = pr + rnd.uniform(1.4, 2.6)
                M.put("iris", px + math.cos(a) * rr, 0, pz - math.sin(a) * rr, rnd.uniform(0.9, 1.15), rnd.uniform(0, math.tau))
            for a in (0.8, 2.6, 4.4):
                lx, lz = px + math.cos(a) * (pr + 4), pz - math.sin(a) * (pr + 4)
                M.put("toro", lx, 0, lz, 1.1, a)
                self.blocked.append((lx, lz, 1.3))
        M.put("taiko_bridge", PONDS[0][0], 0, PONDS[0][1], 1.0, 0.35)
        M.put("zen_garden", 108.0, 0, -150.0, 1.0, -0.5)
        self.blocked.append((108.0, -150.0, 12.0))
        M.put("fuji", 60.0, 4.0, -330.0, (1.0, 1.0, 0.35))
        out.append(box(-80, 72, -300, 30, 30, 2, (1.0, 0.82, 0.7), 1.5, 0.0, 0.0, 0.0, 1.0))  # low evening sun
        out.append(box(-80, 72, -301, 44, 44, 1, (0.7, 0.42, 0.5), 0.8, 0.0, 0.0, 0.0, 1.0))
        cherries = ("cherry_a", "cherry_b", "cherry_c", "cherry_d")
        for x, z, s in [(-86, 12, 1.5), (88, -8, 1.45), (-84, -150, 1.4), (86, -168, 1.5), (-48, 44, 1.15), (52, 46, 1.2)]:
            if self._free(x, z, 2):
                M.put(rnd.choice(cherries), x, 0, z, s, rnd.uniform(0, math.tau))
                self.blocked.append((x, z, 1.6 * s))
        for i in range(55):
            p = self._spot(rnd, 45, 220, 5)
            if p:
                s = rnd.uniform(0.9, 1.35)
                M.put(rnd.choice(cherries), p[0], 0, p[1], s, rnd.uniform(0, math.tau))
                self.blocked.append((p[0], p[1], 1.6 * s))
        for i in range(7):
            p = self._spot(rnd, 60, 200, 5)
            if p:
                M.put(rnd.choice(("bamboo_a", "bamboo_b")), p[0], 0, p[1], 1.0, rnd.uniform(0, math.tau))
                self.blocked.append((p[0], p[1], 4.0))
        for i in range(40):
            p = self._spot(rnd, 30, 150, 1.5)
            if p:
                M.put("azalea_flower" if i % 2 == 0 else "azalea", p[0], 0, p[1], rnd.uniform(0.85, 1.2), rnd.uniform(0, math.tau))
        for i in range(30):
            p = self._spot(rnd, 30, 170, 1.0)
            if p:
                M.put(rnd.choice(("rock_a", "rock_b", "rock_c")), p[0], 0, p[1], rnd.uniform(0.8, 2.0), rnd.uniform(0, math.tau))
        for i in range(260):
            p = self._spot(rnd, 24, 180, 0.0, 4)
            if p:
                M.put(rnd.choice(("grass_a", "grass_b")), p[0], 0, p[1], rnd.uniform(0.7, 1.0), rnd.uniform(0, math.tau))
        for hx, hz, _ in HOUSES:  # stepping stones out to each house
            d = math.hypot(hx, hz)
            for k in range(int(d / 3.2)):
                f = k * 3.2 / d
                sx, sz = hx * f, hz * f
                inside = CLEAR[0] < sx < CLEAR[1] and CLEAR[2] < sz < CLEAR[3]
                if inside or any(math.hypot(sx - bx, sz - bz) < br - 2 for bx, bz, br in self.blocked):
                    continue
                M.put(rnd.choice(("step_a", "step_b")), sx + rnd.uniform(-0.4, 0.4), 0, sz + rnd.uniform(-0.4, 0.4), rnd.uniform(0.85, 1.1), rnd.uniform(0, 3))
        for side in (-1, 1):  # lantern lines on poles along the sides of the clearing
            for k in range(7):
                z = 10 - k * 26
                x = side * 80
                out.append(box(x, 3.5, z, 0.3, 7.0, 0.3, DARKWOOD, 0.1, 0.0, EDGE))
                out.append(box(x, 7.05, z, 0.42, 0.12, 0.42, DARKWOOD, 0.1, 0.0, EDGE))
                if k < 6:
                    out.append(box(x, 6.6, z - 13, 0.05, 0.05, 26, BLACK, 0.0, 0.0, 0.0))
                    for q in range(3):
                        self.lanterns.append((x, 6.1, z - 6.5 * (q + 1), (1.0, 0.95, 0.85) if (k + q) % 2 else (1.0, 0.3, 0.2), k * 1.3 + q))
        return M.freeze(), out

    # ---------- every frame ----------
    def step(self, t, world):
        self.platforms = world.get("platforms", [])

    def boxes(self, t, cam, r=None):
        if r is not None:
            r.add_boxes(self.static)
            if self.meshes is not None:
                self.meshes.draw(r)
        out = []
        if self.meshes is not None and r is not None:  # paper lanterns (models) swaying in the breeze
            rows = {"lantern_red": [], "lantern_white": []}
            for x, y, z, col, ph in self.lanterns:
                sw = 0.12 * math.sin(t * 1.3 + ph)
                rows["lantern_red" if col[1] < 0.5 else "lantern_white"].append(box(x + math.sin(sw) * 0.5, y, z, 1.8, 1.8, 1.8, (1, 1, 1), 0.6, 0.0, EDGE, 0.0, 0.0, sw))
            for k, v in rows.items():
                r.add_mesh(k, np.array(v, dtype=np.float32).reshape(-1, 16))
        for x, y, z, col, ph in ([] if self.meshes is not None else self.lanterns):  # paper lanterns swaying in the breeze
            sw = 0.12 * math.sin(t * 1.3 + ph)
            lx = x + math.sin(sw) * 0.5
            out.append(box(lx, y, z, 1.0, 1.25, 1.0, col, 1.5, sw, 0.0, 0.0, 0.0, sw))
            out.append(box(lx, y + 0.7, z, 0.75, 0.16, 0.75, BLACK, 0.1, sw, 0.0))
            out.append(box(lx, y - 0.7, z, 0.75, 0.16, 0.75, BLACK, 0.1, sw, 0.0))
            for k in (-0.3, 0.0, 0.3):  # ribs
                out.append(box(lx, y + k, z, 1.04, 0.04, 1.04, (0.5, 0.15, 0.1) if col[1] < 0.5 else (0.8, 0.7, 0.55), 0.6, sw, 0.0))
        for f in self.koi:  # koi gliding in loops just under the surface, tails swishing
            px, pz, pr = PONDS[f["pond"]]
            a = f["a"] + t * f["w"]
            rr = f["r"] * (1 + 0.15 * math.sin(t * 0.3 + f["wob"] * 10))
            x, z = px + math.cos(a) * rr, pz - math.sin(a) * rr * (0.8 + 0.2 * f["wob"])
            head = a + (math.pi / 2 if f["w"] > 0 else -math.pi / 2)
            base, spot = f["pal"]
            sz = f["size"]
            sw = math.sin(t * 6 + f["wob"] * 20)
            fx, fz = math.cos(head), -math.sin(head)  # forward
            sx_, sz_ = math.sin(head), math.cos(head)  # sideways (local +z)
            for k, (off, w_, col) in enumerate([(0.55, 0.42, base), (0.0, 0.5, spot), (-0.55, 0.36, base), (-1.0, 0.2, base)]):
                lat = sw * 0.07 * k * k * sz  # the body bends more toward the tail
                bx, bz = x + fx * off * sz + sx_ * lat, z + fz * off * sz + sz_ * lat
                out.append(box(bx, 0.12, bz, 0.6 * sz, 0.14 * sz, w_ * sz, col, 0.35, head + sw * 0.15 * k, 0.0))
            tail = head + sw * 0.6
            tx, tz = x - fx * 1.35 * sz + sx_ * sw * 0.7 * sz, z - fz * 1.35 * sz + sz_ * sw * 0.7 * sz
            out.append(box(tx, 0.12, tz, 0.5 * sz, 0.04, 0.55 * sz, spot, 0.5, tail, 0.0))
            for sd in (-1, 1):  # pectoral fins
                out.append(box(x + math.cos(head) * 0.3 * sz + math.sin(head) * sd * 0.3 * sz, 0.11, z - math.sin(head) * 0.3 * sz + math.cos(head) * sd * 0.3 * sz,
                               0.3 * sz, 0.03, 0.22 * sz, base, 0.3, head + sd * (0.5 + 0.2 * sw), 0.0))
        h = lambda i, k: (math.sin(i * 12.9898 + k * 78.233) * 43758.5453) % 1.0  # noqa: E731
        for i in range(140):  # cherry petals drifting down on the breeze
            fall = 0.8 + h(i, 1) * 0.8
            period = 16.0 / fall
            u = ((t + h(i, 2) * period) % period) / period
            y = 16 * (1 - u)
            ang = t * (0.8 + h(i, 3)) + i
            x = cam[0] + (h(i, 4) - 0.5) * 130 + math.sin(ang * 0.6) * 3 + u * 6  # a steady breeze carries them sideways
            z = cam[2] + (h(i, 5) - 0.5) * 130 + math.cos(ang * 0.5) * 3
            if math.dist((x, y, z), cam) < 8:
                continue
            out.append(box(x, y + 0.05, z, 0.32, 0.03, 0.24, PINKS[i % len(PINKS)], 0.6, ang, 0.0, 0.0, 0.0, math.sin(ang * 1.9), math.cos(ang * 1.4)))
        return out
