"""Jurassic Park theme: a herd of articulated voxel dinosaurs you can poke, feed and follow.

Each dinosaur is a small rig built from boxes: legs plant their feet on the ground and bend at the knee to reach them (two-bone IK), tails and
necks are chains of tapering segments that sway, jaws hinge, wings flap in three parts. Boxes rotate in their own frame
(`rollz` about the side axis, `rollx` about the forward axis), so a limb can swing about its hip.
"""
import math
import random

from . import mathx, models
from .scene import box

SCALE = 1.25
EDGE = 0.4  # softer neon outline than the world's boxes, so they read as solid animals
WHITE, DARK = (0.95, 0.93, 0.85), (0.04, 0.03, 0.03)


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class Pose:
    """A list of local-frame parts: (x, y, z, sx, sy, sz, colour, glow, rollz, rollx, local_yaw)."""

    def __init__(self):
        self.parts = []

    def add(self, x, y, z, sx, sy, sz, col, glow=0.25, rz=0.0, rx=0.0, yl=0.0):
        self.parts.append((x, y, z, sx, sy, sz, col, glow, rz, rx, yl))

    def seg(self, x, y, z, length, ang, thick, wid, col, glow=0.25, psi=0.0, rx=0.0):
        """A bone starting at (x,y,z) pointing `ang` radians up from forward and `psi` sideways. Returns its end point."""
        ca, sa, cp, sp = math.cos(ang), math.sin(ang), math.cos(psi), math.sin(psi)
        dx, dy, dz = ca * cp, sa, -ca * sp
        self.parts.append((x + dx * length / 2, y + dy * length / 2, z + dz * length / 2, length, thick, wid, col, glow, ang, rx, psi))
        return x + dx * length, y + dy * length, z + dz * length

    def eye(self, x, y, z, size=0.32):
        for sz in (-1, 1):
            self.add(x, y, z + sz * size * 1.6, size, size, size * 0.5, WHITE, 0.6)
            self.add(x + size * 0.18, y, z + sz * size * 1.95, size * 0.5, size * 0.55, size * 0.3, DARK, 0.0)

    def teeth(self, x0, y, count, spacing, zs, size=0.16):
        for i in range(count):
            for z in zs:
                self.add(x0 + i * spacing, y, z, size, size * 1.5, size, WHITE, 0.5)


STRIDE = 0.6 * math.tau / (1.24 * SCALE)  # stride (local units) that keeps a planted foot still while the body walks over it
STANCE = 0.6  # share of the gait cycle a foot spends on the ground


def gait(ph, mv, hip_h, lift):
    """Where the foot is along the body (offset from the hip) and how high it is lifted, at gait phase `ph`. On the
    ground the foot slides back exactly as fast as the body moves forward, so it stays planted; then it swings forward."""
    stride = min(STRIDE, hip_h) * mv
    u = (ph / math.tau) % 1.0
    if u < STANCE:
        return stride * (0.5 - u / STANCE), 0.0, 0.0
    v = (u - STANCE) / (1 - STANCE)
    up = math.sin(math.pi * v)
    return stride * (-0.5 + smooth(v)), lift * hip_h * mv * up, up * mv


def ik(hx, hy, ax, ay, l1, l2, knee):
    """Two-bone leg in the side plane: angles of the upper and lower bone that put the joint end on (ax, ay).
    knee=+1 bends the joint forward (bird / hind leg), -1 backward (elbow)."""
    dx, dy = ax - hx, ay - hy
    d = min(max(math.hypot(dx, dy), abs(l1 - l2) + 1e-3), l1 + l2 - 1e-3)
    base = math.atan2(dy, dx)
    a = math.acos(min(1.0, max(-1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
    a1 = base + knee * a
    kx, ky = hx + l1 * math.cos(a1), hy + l1 * math.sin(a1)
    return a1, math.atan2(ay - ky, ax - kx)


def leg(P, ph, mv, hx, hy, hz, tw, col, dark=None, biped=True, knee=1, claws=True, sickle=False, lift=0.22):
    """A leg whose foot really stands on the ground (y=0).
    Biped (theropod / hadrosaur): thigh -> shin -> raised ankle bone -> three toes flat on the ground, claws at the tips.
    Quadruped: a near-straight column onto a round pad with blunt nails."""
    dark = dark or col
    off, up, swing = gait(ph, mv, hy, lift)
    if biped:
        meta, toe = 0.3 * hy, 0.26 * hy
        l1, l2 = 0.44 * hy, 0.4 * hy
        bx, by = hx + off - 0.05 * hy, up  # where the toes start
        lean = 0.42 + 0.5 * swing  # the ankle bone leans back, more while the foot is carried
        ax, ay = bx - meta * math.sin(lean), by + meta * math.cos(lean)
        a1, a2 = ik(hx, hy, ax, ay, l1, l2, knee)
        kx, ky, kz = P.seg(hx, hy, hz, l1, a1, tw, tw, col)
        P.seg(kx, ky, kz, l2, a2, tw * 0.72, tw * 0.75, dark)
        P.seg(ax, ay, hz, meta, -math.pi / 2 + lean, tw * 0.45, tw * 0.5, dark)
        P.add(bx, by + tw * 0.12, hz, tw * 0.5, tw * 0.42, tw * 0.6, dark)  # the ball of the foot
        tth = tw * 0.24
        droop = -0.5 * swing  # toes curl down a little in the air
        for k, psi in enumerate((-0.38, 0.0, 0.38)):
            ln = toe * (1.0 if k == 1 else 0.78)
            ex, ey, ez = P.seg(bx, by + tth / 2, hz, ln, droop, tth, tth * 1.1, dark, 0.25, psi)
            if claws:
                P.seg(ex - 0.03, ey, ez, tw * 0.32, droop - 0.6, tth * 0.7, tth * 0.6, WHITE, 0.5, psi)
        if sickle:  # the raptor's killing claw, held up off the ground on the second toe
            P.seg(bx + 0.05, by + tth, hz, tw * 0.75, 1.0, tth * 0.8, tth * 0.6, WHITE, 0.8)
    else:
        pad = tw * 0.32
        l1 = l2 = (hy - pad) * 0.53
        ax, ay = hx + off, up + pad
        a1, a2 = ik(hx, hy, ax, ay, l1, l2, knee)
        kx, ky, kz = P.seg(hx, hy, hz, l1, a1, tw, tw, col)
        P.seg(kx, ky, kz, l2, a2, tw * 0.82, tw * 0.85, dark)
        P.add(ax, up + pad / 2, hz, tw * 1.05, pad, tw * 1.05, dark)
        P.add(ax, up + pad / 2, hz, tw * 0.75, pad * 1.01, tw * 1.25, dark, 0.25, 0.0, 0.0, math.pi / 4)  # rounder pad
        if claws:
            for dz in (-0.32, 0.0, 0.32):
                P.add(ax + tw * 0.5, up + pad * 0.4, hz + dz * tw, tw * 0.18, pad * 0.7, tw * 0.2, WHITE, 0.5)


def tail(P, t, x, y, n, length, thick0, thick1, col, belly=None, sway=0.25, droop=0.06, lag=0.0, wave=2.2, wid_k=1.0):
    ang, px, py, pz = 0.0 - droop, x, y, 0.0
    for i in range(n):
        f = i / max(n - 1, 1)
        th = thick0 + (thick1 - thick0) * f
        psi = sway * math.sin(t * wave - i * 0.7) * (i + 1) / n + lag * (i + 1) / n
        ang = -math.pi - droop * 0.5 + (0.12 * math.sin(t * 1.3 - i * 0.5)) * f - 0.04 * i * (1 - f)
        px, py, pz = P.seg(px, py, pz, length, ang, th, th * wid_k, col if i % 2 == 0 or not belly else belly, 0.2, psi)


def neck(P, t, x, y, n, length, ang0, ang1, th0, th1, col, look=0.0, lift=0.0, wid_k=1.0):
    px, py, pz = x, y, 0.0
    ang = ang0
    for i in range(n):
        f = i / max(n - 1, 1)
        ang = ang0 + (ang1 - ang0) * f + lift * (1 - f * 0.4) + 0.05 * math.sin(t * 1.2 - i * 0.6)
        th = th0 + (th1 - th0) * f
        px, py, pz = P.seg(px, py, pz, length, ang, th, th * wid_k, col, 0.25, look * (i + 1) / n)
    return px, py, pz, ang


# ---------------------------------------------------------------- species rigs
def rig_trex(P, st, pal):
    back, belly, acc = pal
    t, ph, mv, r, look, graze = st["t"], st["ph"], st["mv"], st["roar"], st["look"], st["graze"]
    bob = 0.16 * abs(math.sin(ph)) * mv + 0.05 * math.sin(t * 1.6)
    hy = 5.0 + bob + 0.35 * r
    P.add(-0.6, hy + 0.6, 0, 3.0, 2.8, 2.5, back, 0.25, -0.05)
    P.add(1.8, hy + 0.9, 0, 2.8, 2.7, 2.3, back, 0.25, 0.1)
    P.add(0.4, hy - 0.4, 0, 5.2, 0.9, 2.0, belly, 0.3, 0.0)
    nx, ny, nz, nang = neck(P, t, 3.0, hy + 1.7, 3, 1.15, 0.65, 0.05, 1.8, 1.5, back, look, r * 0.5 - graze * 0.9)
    hx = nx
    P.add(hx + 0.9, ny + 0.1, nz, 2.7, 1.8, 2.0, back, 0.3, nang * 0.4, 0.0, look)
    P.add(hx + 2.3, ny - 0.1, nz, 1.7, 1.1, 1.4, back, 0.3, nang * 0.3, 0.0, look)
    jaw = -(0.08 + 0.75 * r + 0.1 * math.sin(t * 6) * mv)
    P.seg(hx + 0.1, ny - 0.75, nz, 3.2, jaw, 0.8, 1.5, belly, 0.3, look)
    P.teeth(hx + 1.6, ny - 0.55, 6, 0.38, (-0.55, 0.55))
    P.teeth(hx + 0.9 + 0.1, ny - 0.95 + jaw * 0.5, 5, 0.38, (-0.5, 0.5))
    P.eye(hx + 1.3, ny + 0.55, nz, 0.34)
    for sz in (-1, 1):  # tiny arms
        P.seg(2.9, hy + 0.2, sz * 1.15, 0.9, -0.9 - 0.3 * math.sin(t * 2), 0.38, 0.38, back)
        P.seg(3.4, hy - 0.5, sz * 1.15, 0.7, -1.5, 0.3, 0.3, belly)
    tail(P, t, -2.0, hy + 0.8, 9, 1.35, 2.0, 0.35, back, belly, 0.28, 0.03, st["turn"])
    for k, sz in enumerate((-1, 1)):
        leg(P, ph + k * math.pi, mv, 0.1, hy - 0.25, sz * 1.15, 1.25, back, belly)


def rig_trike(P, st, pal):
    back, belly, acc = pal
    t, ph, mv, r, look, graze = st["t"], st["ph"], st["mv"], st["roar"], st["look"], st["graze"]
    hy = 3.4 + 0.1 * abs(math.sin(ph)) * mv
    P.add(0, hy + 0.9, 0, 5.6, 3.1, 3.4, back, 0.25)
    P.add(0, hy - 0.4, 0, 5.0, 0.9, 3.0, belly, 0.3)
    P.add(-2.3, hy + 0.9, 0, 1.5, 2.6, 2.8, back, 0.25)
    hx = 3.4 + 0.15 * r
    hyd = hy + 0.2 - 0.6 * graze + 0.2 * r
    P.add(hx, hyd + 0.2, 0, 2.5, 2.0, 2.2, back, 0.3, -0.1, 0.0, look)
    P.add(hx + 1.5, hyd - 0.3, 0, 1.2, 1.1, 1.3, belly, 0.3, -0.1, 0.0, look)  # beak
    P.add(hx - 1.1, hyd + 2.0, 0, 0.55, 4.0, 4.4, acc, 0.4, 0.5, 0.0, look)  # frill
    for k in range(7):
        a = -1.0 + k * 0.33
        P.add(hx - 1.4, hyd + 2.3 + 1.6 * math.cos(a * 1.5), 2.3 * math.sin(a * 1.2) * 1.0 + 0.0, 0.5, 0.5, 0.5, WHITE, 0.6)
    for sz in (-1, 1):
        P.seg(hx + 0.2, hyd + 0.9, sz * 0.75, 2.3, 0.55, 0.38, 0.38, WHITE, 0.6, sz * 0.12)  # brow horns
    P.seg(hx + 1.6, hyd + 0.3, 0, 0.9, 0.9, 0.5, 0.5, WHITE, 0.6)
    P.eye(hx + 0.6, hyd + 0.5, 0, 0.3)
    tail(P, t, -3.0, hy + 1.0, 4, 1.2, 1.6, 0.5, back, belly, 0.18)
    for (lx, sz, off) in ((1.9, -1, 0.0), (1.9, 1, math.pi), (-1.9, -1, math.pi), (-1.9, 1, 0.0)):
        leg(P, ph + off, mv, lx, hy - 0.2, sz * 1.25, 1.15, back, belly, biped=False, knee=-1 if lx > 0 else 1)


def rig_brachio(P, st, pal):
    back, belly, acc = pal
    t, ph, mv, r, look, graze = st["t"], st["ph"], st["mv"], st["roar"], st["look"], st["graze"]
    hy = 6.6 + 0.08 * abs(math.sin(ph)) * mv + 0.05 * math.sin(t * 1.2)
    P.add(0, hy + 0.9, 0, 6.2, 3.6, 3.4, back, 0.22)
    P.add(0, hy - 0.5, 0, 5.6, 0.9, 3.0, belly, 0.3)
    nx, ny, nz, nang = neck(P, t, 3.1, hy + 1.8, 8, 1.75, 1.15, 0.2, 2.0, 0.9, back, look * 1.4, r * 0.25 - graze * 1.35)
    P.add(nx + 0.7, ny + 0.1, nz, 1.9, 1.15, 1.2, back, 0.3, nang * 0.2, 0.0, look)
    P.add(nx + 1.6, ny - 0.15, nz, 0.9, 0.7, 0.9, belly, 0.3, -0.2, 0.0, look)
    P.eye(nx + 0.9, ny + 0.4, nz, 0.26)
    tail(P, t, -3.1, hy + 1.2, 9, 1.6, 2.0, 0.4, back, belly, 0.3, 0.1, st["turn"], 1.6)
    for (lx, sz, off) in ((2.2, -1, 0.0), (2.2, 1, math.pi), (-2.2, -1, math.pi), (-2.2, 1, 0.0)):
        leg(P, ph + off, mv, lx, hy - 0.3, sz * 1.3, 1.5, back, belly, biped=False, knee=-1 if lx > 0 else 1, lift=0.1)


def rig_stego(P, st, pal):
    back, belly, acc = pal
    t, ph, mv, r, look, graze = st["t"], st["ph"], st["mv"], st["roar"], st["look"], st["graze"]
    hy = 3.0 + 0.1 * abs(math.sin(ph)) * mv
    for i, x in enumerate((-2.4, -0.8, 0.8, 2.4)):  # an arched back
        top = hy + 1.2 + 1.1 * math.cos((x + 0.4) * 0.55) * (1 - 0.0)
        P.add(x, top - 0.3, 0, 1.9, 2.3, 2.6, back, 0.25, -0.2 * math.sin(x * 0.5))
    P.add(0, hy, 0, 5.6, 0.9, 2.3, belly, 0.3)
    for i in range(9):  # two staggered rows of plates
        x = -2.9 + i * 0.72
        top = hy + 2.6 + 1.1 * math.cos((x + 0.4) * 0.55) - 0.3
        size = 1.3 + 0.9 * math.sin(math.pi * (i + 0.5) / 9)
        P.add(x, top + size * 0.35, 0.45 * (1 if i % 2 else -1), size, size, 0.26, acc, 0.9, math.pi / 4, 0.0, 0.0)
    hd = hy + 0.2 - 0.5 * graze
    P.seg(3.0, hy + 1.5, 0, 1.5, -0.35 - graze * 0.5, 1.1, 1.2, back, 0.25, look * 0.5)
    P.add(4.4, hd, 0, 1.7, 0.95, 1.1, back, 0.3, -0.2, 0.0, look)
    P.eye(4.2, hd + 0.3, 0, 0.22)
    tx, ty, tz = -3.2, hy + 1.0, 0.0
    for i in range(4):
        th = 1.5 - i * 0.28
        psi = 0.22 * math.sin(t * 2 - i * 0.8) * (i + 1) / 4 + st["turn"] * (i + 1) / 4
        tx, ty, tz = P.seg(tx, ty, tz, 1.3, -math.pi - 0.05 + 0.1 * i, th, th, back, 0.2, psi)
    for k in range(4):  # the thagomizer
        sz = -1 if k % 2 == 0 else 1
        P.seg(tx - 0.2 - 0.25 * (k // 2), ty, tz + sz * 0.3, 1.7, 0.5 + 0.25 * (k // 2) if sz > 0 else 0.5, 0.28, 0.28, WHITE, 0.7, sz * (0.35 + 0.1 * (k // 2)))
    for (lx, sz, off, drop) in ((1.9, -1, 0.0, 0.5), (1.9, 1, math.pi, 0.5), (-1.9, -1, math.pi, 0.0), (-1.9, 1, 0.0, 0.0)):
        leg(P, ph + off, mv, lx, hy - 0.15 - drop, sz * 1.25, 0.95, back, belly, biped=False, knee=-1 if lx > 0 else 1)  # short front legs


def rig_raptor(P, st, pal):
    back, belly, acc = pal
    t, ph, mv, r, look, graze = st["t"], st["ph"], st["mv"], st["roar"], st["look"], st["graze"]
    hy = 2.5 + 0.2 * abs(math.sin(ph)) * mv
    P.add(0, hy + 0.4, 0, 2.7, 1.2, 1.0, back, 0.3, 0.08)
    P.add(0.1, hy - 0.2, 0, 2.4, 0.5, 0.8, belly, 0.35)
    for k in range(4):  # stripes
        P.add(-0.9 + k * 0.7, hy + 0.7, 0, 0.25, 1.25, 1.05, acc, 0.4, 0.08)
    nx, ny, nz, nang = neck(P, t, 1.3, hy + 0.6, 2, 0.8, 0.9, 0.3, 0.6, 0.5, back, look, r * 0.4 - graze * 0.6)
    P.add(nx + 0.5, ny, nz, 1.3, 0.75, 0.8, back, 0.35, nang * 0.3, 0.0, look)
    P.add(nx + 1.2, ny - 0.1, nz, 0.9, 0.45, 0.55, back, 0.35, -0.2, 0.0, look)
    jaw = -(0.05 + 0.45 * r + 0.25 * max(0, math.sin(t * 9)) * mv)
    P.seg(nx + 0.1, ny - 0.4, nz, 1.5, jaw, 0.3, 0.55, belly, 0.35, look)
    P.teeth(nx + 0.6, ny - 0.3, 4, 0.25, (-0.2, 0.2), 0.1)
    P.eye(nx + 0.6, ny + 0.2, nz, 0.17)
    for k in range(3):  # head crest of feathers
        P.seg(nx - 0.3, ny + 0.4, nz, 0.7, 0.8 + 0.3 * k, 0.12, 0.16, acc, 0.6, (k - 1) * 0.2)
    tail(P, t, -1.3, hy + 0.4, 8, 0.85, 0.6, 0.12, back, acc, 0.12, 0.0, st["turn"], 3.0)
    for k, sz in enumerate((-1, 1)):
        leg(P, ph + k * math.pi, mv, 0.1, hy - 0.1, sz * 0.5, 0.5, back, belly, sickle=True, lift=0.3)


def rig_anky(P, st, pal):
    back, belly, acc = pal
    t, ph, mv, r, look, graze = st["t"], st["ph"], st["mv"], st["roar"], st["look"], st["graze"]
    hy = 1.9 + 0.05 * abs(math.sin(ph)) * mv
    P.add(0, hy + 0.5, 0, 5.0, 1.8, 4.0, back, 0.25)
    P.add(0, hy - 0.3, 0, 4.6, 0.7, 3.5, belly, 0.3)
    for i in range(4):  # rows of armour bumps
        for j in range(5):
            P.add(-1.8 + i * 1.2, hy + 1.55 + 0.1 * (i % 2), -1.6 + j * 0.8, 0.8, 0.6, 0.7, acc, 0.45, 0.0, 0.0, 0.0)
    for sz in (-1, 1):
        for i in range(4):
            P.seg(-1.7 + i * 1.1, hy + 0.3, sz * 1.95, 0.9, 0.2, 0.3, 0.3, WHITE, 0.6, sz * 1.1)
    hd = hy + 0.1 - 0.4 * graze
    P.add(3.1, hd, 0, 2.2, 1.2, 2.5, back, 0.3, 0.0, 0.0, look)
    P.eye(3.7, hd + 0.4, 0, 0.26)
    for sz in (-1, 1):
        P.add(2.7, hd + 0.8, sz * 1.3, 0.7, 0.7, 0.5, WHITE, 0.6)
    tx, ty, tz = -2.6, hy + 0.4, 0.0
    for i in range(3):
        psi = 0.35 * math.sin(t * 1.8 - i * 0.8) * (i + 1) / 3 + st["turn"] * (i + 1) / 3
        tx, ty, tz = P.seg(tx, ty, tz, 1.5, -math.pi - 0.02, 1.2 - i * 0.2, 1.8 - i * 0.4, back, 0.25, psi)
    P.add(tx - 0.9, ty, tz + 0.35 * math.sin(t * 1.8 - 2.4), 1.6, 1.4, 2.0, acc, 0.6)  # the club
    for (lx, sz, off) in ((1.8, -1, 0.0), (1.8, 1, math.pi), (-1.8, -1, math.pi), (-1.8, 1, 0.0)):
        leg(P, ph + off, mv, lx, hy - 0.3, sz * 1.5, 1.0, back, belly, biped=False, knee=-1 if lx > 0 else 1, lift=0.18)


def rig_para(P, st, pal):
    back, belly, acc = pal
    t, ph, mv, r, look, graze = st["t"], st["ph"], st["mv"], st["roar"], st["look"], st["graze"]
    hy = 3.9 + 0.14 * abs(math.sin(ph)) * mv
    P.add(0, hy + 0.5, 0, 4.2, 2.3, 2.0, back, 0.25, 0.06)
    P.add(0, hy - 0.4, 0, 3.8, 0.7, 1.7, belly, 0.3)
    nx, ny, nz, nang = neck(P, t, 2.0, hy + 1.3, 3, 1.0, 0.95, 0.35, 1.2, 0.9, back, look, r * 0.5 - graze * 1.2)
    P.add(nx + 0.7, ny, nz, 1.9, 1.0, 1.2, back, 0.3, nang * 0.2, 0.0, look)
    P.add(nx + 1.7, ny - 0.15, nz, 1.2, 0.55, 1.5, belly, 0.3, -0.1, 0.0, look)  # duck bill
    P.eye(nx + 0.8, ny + 0.3, nz, 0.26)
    cx, cy, cz = nx - 0.2, ny + 0.4, 0.0
    for i, a in enumerate((0.9, 0.35, -0.3, -0.9)):  # the hollow crest sweeps back
        cx, cy, cz = P.seg(cx, cy, cz, 1.1, a + math.pi * 0.0 - 0.0 + 3.14159 * 0, 0.34, 0.34, acc, 0.7, look * 0.5)
    for sz in (-1, 1):
        P.seg(2.0, hy + 0.5, sz * 1.05, 1.1, -0.9, 0.4, 0.4, back)
    tail(P, t, -2.1, hy + 0.7, 7, 1.25, 1.3, 0.3, back, belly, 0.2, 0.05, st["turn"], 2.0)
    for k, sz in enumerate((-1, 1)):
        leg(P, ph + k * math.pi, mv, 0.0, hy - 0.2, sz * 0.9, 1.0, back, belly, claws=False)  # hadrosaur: blunt hoof-like toes


def rig_ptero(P, st, pal):
    back, belly, acc = pal
    t = st["t"]
    beat = math.sin(t * st["flap"])
    glide = 0.35 + 0.65 * smooth(0.5 + 0.5 * math.sin(t * 0.7 + st.get("seed", 0.0)))  # flaps in bursts, glides in between
    flap = beat * 0.5 * glide - 0.05
    bob = 0.25 * beat * glide
    P.add(0, bob, 0, 2.2, 0.8, 0.9, back, 0.3)
    P.add(0, bob - 0.15, 0, 1.8, 0.4, 0.8, belly, 0.3)
    P.add(1.5, bob + 0.2, 0, 1.0, 0.7, 0.7, back, 0.3, 0.2)
    P.seg(1.9, bob + 0.2, 0, 2.6, -0.05, 0.28, 0.32, acc, 0.5)  # long beak
    P.seg(0.7, bob + 0.5, 0, 1.8, 0.4, 0.22, 0.25, acc, 0.6)  # crest
    P.eye(1.65, bob + 0.4, 0, 0.2)
    P.add(-1.7, bob, 0, 1.3, 0.25, 0.25, back, 0.3)
    for sz in (-1, 1):  # three wing segments: each one tilts a little more than the one before, so the wing bends as it flaps
        x, y, z = 0.2, bob + 0.2, sz * 0.4
        for k, (ln, wd) in enumerate(((1.9, 2.0), (2.5, 1.6), (2.6, 1.1))):
            phi = flap * (1.0 + 0.3 * k) + 0.06 * k  # elevation: up is positive, both wings flap together
            dy, dz = math.sin(phi), sz * math.cos(phi)
            P.parts.append((x - 0.15 * k, y + dy * ln / 2, z + dz * ln / 2, wd, 0.12, ln, acc if k == 2 else back, 0.35, 0.0, -sz * phi, 0.0))
            y, z = y + dy * ln, z + dz * ln


RIGS = {"trex": rig_trex, "trike": rig_trike, "brachio": rig_brachio, "stego": rig_stego, "raptor": rig_raptor, "anky": rig_anky, "para": rig_para, "ptero": rig_ptero}

# key -> (name, diet, length, era, fact, speed, avoid radius, pick centre height, pick radius, footprint (len, wid), base palette)
SPECIES = {
    "trex": ("Tyrannosaurus rex", "carnivore", "12 m", "Late Cretaceous", "Its bite was the strongest of any land animal ever.", 4.2, 6.5, 6.0, 7.0, (13, 5), ((0.58, 0.22, 0.12), (0.88, 0.58, 0.26), (0.95, 0.7, 0.3))),
    "trike": ("Triceratops", "herbivore", "9 m", "Late Cretaceous", "The frill and three horns defended against T. rex.", 3.0, 5.5, 3.8, 5.5, (11, 5), ((0.42, 0.52, 0.22), (0.78, 0.7, 0.4), (0.72, 0.38, 0.30))),
    "brachio": ("Brachiosaurus", "herbivore", "22 m", "Late Jurassic", "Its raised neck reached the tops of tall conifers.", 2.2, 8.0, 8.5, 10.0, (16, 6), ((0.38, 0.52, 0.66), (0.72, 0.8, 0.86), (0.6, 0.7, 0.8))),
    "stego": ("Stegosaurus", "herbivore", "9 m", "Late Jurassic", "The four tail spikes are called the thagomizer.", 2.6, 5.5, 3.8, 5.5, (11, 5), ((0.42, 0.5, 0.2), (0.8, 0.74, 0.45), (1.0, 0.55, 0.15))),
    "raptor": ("Velociraptor", "carnivore", "2 m", "Late Cretaceous", "Turkey-sized and feathered, it hunted in quick bursts.", 8.5, 2.8, 2.2, 3.0, (5, 2), ((0.9, 0.46, 0.1), (0.95, 0.85, 0.6), (0.18, 0.1, 0.05))),
    "anky": ("Ankylosaurus", "herbivore", "8 m", "Late Cretaceous", "A living tank with a bony tail club.", 2.0, 4.5, 2.4, 4.6, (10, 5), ((0.6, 0.48, 0.3), (0.85, 0.74, 0.5), (0.72, 0.58, 0.36))),
    "para": ("Parasaurolophus", "herbivore", "10 m", "Late Cretaceous", "Its hollow crest worked like a trumpet.", 3.5, 4.5, 4.5, 5.5, (11, 3), ((0.2, 0.58, 0.58), (0.78, 0.85, 0.7), (0.98, 0.78, 0.22))),
    "ptero": ("Pteranodon", "piscivore", "6 m wingspan", "Late Cretaceous", "A toothless flyer that skimmed the seas for fish.", 0.0, 0.0, 0.0, 4.5, (5, 8), ((0.5, 0.26, 0.34), (0.8, 0.6, 0.6), (0.9, 0.7, 0.3))),
}
HERD = ["trex", "trike", "brachio", "stego", "raptor", "raptor", "raptor", "anky", "para", "ptero", "ptero", "ptero"]
FUR = {"carnivore": "meat", "piscivore": "meat", "herbivore": "leaf"}


class Dino:
    def __init__(self, kind, i, rnd):
        self.kind, self.i = kind, i
        sp = SPECIES[kind]
        self.name, self.diet, self.length, self.era, self.fact = sp[0], sp[1], sp[2], sp[3], sp[4]
        self.speed, self.radius, self.pick_h, self.pick_r = sp[5], sp[6], sp[7], sp[8]
        self.foot = sp[9]
        j = rnd.uniform(-0.07, 0.07)  # each animal is tinted a little differently
        self.pal = tuple(tuple(min(1.0, max(0.0, c + j * (k + 1) * 0.5)) for c in col) for k, col in enumerate(sp[10]))
        self.flyer = kind == "ptero"
        self.x = self.z = 0.0
        self.heading, self.phase, self.mv, self.graze, self.turn = rnd.uniform(0, 6.28), rnd.uniform(0, 6), 0.0, 0.0, 0.0
        self.target, self.idle, self.moving = None, rnd.uniform(0, 3), False
        self.roar_t0, self.look, self.look_goal, self.look_t = -9.0, 0.0, 0.0, 0.0
        self.eat_until, self.bait, self.flee_until, self.last_step = 0.0, None, 0.0, 0
        self.flap = 6.0
        if self.flyer:
            self.cx, self.cz = rnd.uniform(-25, 25), rnd.uniform(-25, 25)
            self.rad, self.w, self.a = rnd.uniform(28, 62), rnd.choice((-1, 1)) * rnd.uniform(0.22, 0.38), rnd.uniform(0, 6.28)
            self.alt = rnd.uniform(14, 26)
            self.y = self.alt
        else:
            self.x, self.z = rnd.uniform(-70, 70), rnd.uniform(-70, 70)
            self.y = 0.0


class Herd:
    def __init__(self, seed=7):
        self.rnd = random.Random(seed)
        self.dinos = [Dino(k, i, self.rnd) for i, k in enumerate(HERD)]
        self.last = None
        self.baits = []  # {x, z, kind, t0}
        self.dust = []  # [x, y, z, vx, vy, vz, life]
        self.rings = []  # roar shockwaves: [x, z, t0, radius]
        self.shake = 0.0

    # ---------- interaction ----------
    def centre(self, d):
        return (d.x, d.pick_h * SCALE if not d.flyer else d.y, d.z)

    def pick(self, origin, direction):
        """Index of the dinosaur under the mouse ray (nearest first), or None."""
        best, bi = 1e9, None
        for d in self.dinos:
            cx, cy, cz = self.centre(d)
            rx, ry, rz = origin[0] - cx, origin[1] - cy, origin[2] - cz
            b = rx * direction[0] + ry * direction[1] + rz * direction[2]
            c = rx * rx + ry * ry + rz * rz - (d.pick_r * (SCALE if not d.flyer else 1.0)) ** 2
            disc = b * b - c
            if disc >= 0:
                t = -b - math.sqrt(disc)
                if 0 < t < best:
                    best, bi = t, d.i
        return bi

    def poke(self, i, t):
        """Click a dinosaur: it roars (or screeches), turns to look at you and startles the animals around it."""
        d = self.dinos[i]
        d.roar_t0, d.look_goal, d.look_t = t, 0.0, t
        d.idle = max(d.idle, 1.8)
        d.moving = False
        d.flap = 14.0 if d.flyer else d.flap
        big = d.kind in ("trex", "brachio", "trike")
        self.shake = max(self.shake, 0.9 if d.kind == "trex" else 0.5 if big else 0.0)
        self.rings.append([d.x, d.z, t, 0.0])
        for o in self.dinos:
            if o is d or o.flyer:
                continue
            dist = math.hypot(o.x - d.x, o.z - d.z)
            if dist < 38:
                if o.kind == "raptor" or (d.kind == "trex" and o.diet == "herbivore"):
                    o.flee_until = t + 3.5 + (38 - dist) * 0.05  # the small and the prey run away
                    o.target = None
                else:
                    o.look_goal = 0.6
                    o.idle = max(o.idle, 1.2)
        return d

    def feed(self, x, z, t):
        """Drop food on the ground: the nearest animal that eats it walks over. Returns the dinosaur that responds, if any."""
        want = self.rnd.choice(("leaf", "meat"))
        cands = [d for d in self.dinos if not d.flyer and d.bait is None and FUR[d.diet] == want and math.hypot(d.x - x, d.z - z) < 90]
        if not cands:
            want = "meat" if want == "leaf" else "leaf"
            cands = [d for d in self.dinos if not d.flyer and d.bait is None and FUR[d.diet] == want and math.hypot(d.x - x, d.z - z) < 90]
        bait = {"x": x, "z": z, "kind": want, "t0": t}
        self.baits.append(bait)
        if not cands:
            return None
        d = min(cands, key=lambda d: math.hypot(d.x - x, d.z - z))
        d.bait, d.target, d.idle, d.flee_until = bait, (x, z), 0.0, 0.0
        return d

    # ---------- simulation ----------
    def _blocked(self, x, z, world, r):
        for cx, cz, cr in world["circles"]:
            if math.hypot(x - cx, z - cz) < cr + r:
                return True
        for cx, cz, hw, hd in world["rects"]:
            if abs(x - cx) < hw + r and abs(z - cz) < hd + r:
                return True
        return False

    def _pick(self, d, world):
        rmin, rmax = world["bounds"]
        for _ in range(14):
            a, rad = self.rnd.uniform(0, math.tau), self.rnd.uniform(rmin, rmax)
            x, z = math.sin(a) * rad, math.cos(a) * rad
            if not self._blocked(x, z, world, d.radius + 1):
                return (x, z)
        return (math.sin(d.i) * rmax, math.cos(d.i) * rmax)

    def step(self, t, world):
        dt = 0.0 if self.last is None else min(max(t - self.last, 0.0), 0.1)
        self.last = t
        self.shake *= math.exp(-dt * 3.0)
        self.baits = [b for b in self.baits if t - b["t0"] < 40]
        self.rings = [r_ for r_ in self.rings if t - r_[2] < 1.4]
        for r_ in self.rings:
            r_[3] = 3 + (t - r_[2]) * 26
        for p in self.dust:
            p[0] += p[3] * dt; p[1] += p[4] * dt; p[2] += p[5] * dt; p[4] -= 9 * dt; p[6] -= dt
        self.dust = [p for p in self.dust if p[6] > 0]
        for d in self.dinos:
            roar = t - d.roar_t0 < 1.7
            if d.flyer:
                d.flap += (6.0 - d.flap) * min(1.0, dt * 0.8)
                d.a += d.w * dt * (2.2 if roar else 1.0)
                d.x, d.z = d.cx + math.sin(d.a) * d.rad, d.cz + math.cos(d.a) * d.rad
                d.y = d.alt + math.sin(t * 0.9 + d.i) * 1.5
                d.heading = math.atan2(math.sin(d.a) * d.w * d.rad, math.cos(d.a) * d.w * d.rad)
                continue
            d.look += (d.look_goal - d.look) * min(1.0, dt * 4)
            if t - d.look_t > 2.5:
                d.look_goal *= 0.97
            if d.bait and d.bait not in self.baits:
                d.bait = None
            if d.eat_until > t:  # busy eating
                d.moving = False
                d.mv += (0 - d.mv) * min(1.0, dt * 4)
                d.graze += (1.0 - d.graze) * min(1.0, dt * 5)
                continue
            if d.bait and math.hypot(d.x - d.bait["x"], d.z - d.bait["z"]) < 3.5 + d.radius * 0.3:
                d.eat_until = t + 3.2
                d.idle = 0.0
                self.baits = [b for b in self.baits if b is not d.bait]
                d.bait, d.target = None, None
                continue
            if d.idle > 0 and d.flee_until <= t:
                d.idle -= dt
                d.moving = False
                d.mv += (0 - d.mv) * min(1.0, dt * 4)
                d.graze += ((0.0 if roar else 1.0) - d.graze) * min(1.0, dt * 3)
                if self.rnd.random() < dt * 0.15:
                    d.look_goal, d.look_t = self.rnd.uniform(-0.6, 0.6), t  # look around
                continue
            d.graze += (0.0 - d.graze) * min(1.0, dt * 3)
            fleeing = d.flee_until > t
            if d.target is None or (not d.bait and self._blocked(*d.target, world, d.radius)):
                d.target = self._pick(d, world)
            if fleeing:  # run directly away from the nearest threat
                d.target = (d.x + math.cos(d.heading) * 30, d.z - math.sin(d.heading) * 30)
            dx, dz = d.target[0] - d.x, d.target[1] - d.z
            dist = math.hypot(dx, dz)
            if dist < 3.0 and not d.bait:
                d.target, d.idle, d.moving = None, self.rnd.uniform(1.5, 5.0) if self.rnd.random() < 0.6 else 0.0, False
                continue
            want = math.atan2(-dz, dx)
            diff = (want - d.heading + math.pi) % math.tau - math.pi
            d.heading += max(-1.3 * dt, min(1.3 * dt, diff))
            d.turn += (max(-0.5, min(0.5, diff)) - d.turn) * min(1.0, dt * 3)
            spd = d.speed * (1.9 if fleeing else (1.25 if d.bait else 1.0))
            if abs(diff) < 1.2:
                d.x += math.cos(d.heading) * spd * dt
                d.z += -math.sin(d.heading) * spd * dt
                d.phase += spd * dt * 0.62
                d.moving = True
                d.mv += (1 - d.mv) * min(1.0, dt * 4)
                step_id = int(d.phase / math.pi)
                if step_id != d.last_step:  # a foot came down
                    d.last_step = step_id
                    if d.kind in ("trex", "brachio", "trike", "stego", "anky") and self.rnd.random() < 0.9:
                        for k in range(3):
                            self.dust.append([d.x + math.cos(d.heading) * 1.5 + self.rnd.uniform(-1, 1), 0.2, d.z - math.sin(d.heading) * 1.5 + self.rnd.uniform(-1, 1),
                                              self.rnd.uniform(-1.2, 1.2), self.rnd.uniform(1.5, 3.5), self.rnd.uniform(-1.2, 1.2), 0.9])
            else:
                d.mv += (0 - d.mv) * min(1.0, dt * 4)
            for cx, cz, cr in world["circles"]:  # shove out of obstacles so they walk around pedestals, not through them
                ox, oz = d.x - cx, d.z - cz
                dd = math.hypot(ox, oz) or 1e-6
                if dd < cr + d.radius:
                    d.x, d.z = cx + ox / dd * (cr + d.radius), cz + oz / dd * (cr + d.radius)
                    if not d.bait:
                        d.target = None
            for cx, cz, hw, hd in world["rects"]:
                if abs(d.x - cx) < hw + d.radius and abs(d.z - cz) < hd + d.radius:
                    if (hw + d.radius - abs(d.x - cx)) < (hd + d.radius - abs(d.z - cz)):
                        d.x = cx + math.copysign(hw + d.radius, d.x - cx)
                    else:
                        d.z = cz + math.copysign(hd + d.radius, d.z - cz)
                    if not d.bait:
                        d.target = None

    # ---------- drawing ----------
    def boxes(self, t, cam, r=None):
        out = []
        for d in self.dinos:
            if math.hypot(d.x - cam[0], d.z - cam[2]) > 230:
                continue
            if math.dist((d.x, d.y if d.flyer else 3.0, d.z), cam) < (26 if d.flyer else 9):
                continue  # too close to the lens: hide it rather than let it fill the screen
            roar_u = (t - d.roar_t0) / 1.7
            roar = math.sin(math.pi * roar_u) ** 0.6 if 0 <= roar_u <= 1 else 0.0
            graze = d.graze + (0.0 if d.eat_until <= t else 0.15 * math.sin(t * 7))  # chewing
            st = {"t": t, "ph": d.phase * 2, "mv": d.mv, "roar": roar, "look": d.look, "graze": graze, "turn": d.turn, "flap": d.flap, "seed": d.i * 1.7}
            P = Pose()
            RIGS[d.kind](P, st, d.pal)
            c, s = math.cos(d.heading), math.sin(d.heading)
            y0 = d.y if d.flyer else 0.0
            models.creature_parts(r, [box(d.x + (x * c + z * s) * SCALE, y0 + y * SCALE, d.z + (-x * s + z * c) * SCALE, sx * SCALE, sy * SCALE,
                                          sz * SCALE, col, glow, d.heading + yl, EDGE, 0.0, 0.0, rz, rx)
                                      for (x, y, z, sx, sy, sz, col, glow, rz, rx, yl) in P.parts], out)
            if r is not None:  # a soft shadow on the ground
                ln, wd = d.foot
                alt = 1.0 / (1.0 + max(y0 - 2, 0) * 0.12)
                m = (mathx.translate(d.x, 0.03, d.z) @ mathx.rot_y(d.heading) @ mathx.rot_x(math.pi / 2) @ mathx.translate(-ln * SCALE / 2, -wd * SCALE / 2, 0) @ mathx.scale(ln * SCALE, wd * SCALE, 1))
                r.quad3d(r.white, m, (0, 0, 0, 0.32 * alt))
        for b in self.baits:
            wob = math.sin(t * 3 + b["x"])
            if b["kind"] == "leaf":
                for k in range(5):
                    out.append(box(b["x"] + math.cos(k * 1.3) * 0.7, 0.35 + 0.1 * k, b["z"] + math.sin(k * 1.3) * 0.7, 0.9, 0.3, 0.6, (0.25, 0.8, 0.25), 0.9, k, 0.2))
            else:
                out.append(box(b["x"], 0.55 + 0.1 * wob, b["z"], 1.5, 1.0, 1.0, (0.85, 0.15, 0.15), 0.9, t, 0.3))
                out.append(box(b["x"] + 0.9, 0.55, b["z"], 0.9, 0.3, 0.3, WHITE, 0.6, t, 0.3))
        for x, y, z, vx, vy, vz, life in self.dust:
            k = min(1.0, life / 0.9)
            out.append(box(x, y, z, 0.35 + 0.5 * (1 - k), 0.35 + 0.5 * (1 - k), 0.35 + 0.5 * (1 - k), (0.55 * k + 0.2, 0.5 * k + 0.18, 0.38 * k + 0.12), 0.1, 0.0, 0.0))
        for x, z, t0, rad in self.rings:  # roar shockwave
            fade = 1 - (t - t0) / 1.4
            for k in range(20):
                a = k * math.tau / 20
                out.append(box(x + math.cos(a) * rad, 0.15, z + math.sin(a) * rad, 1.4 * fade + 0.2, 0.25, 0.5, (1.0, 0.75, 0.3), 1.2 * fade, -a, 0.2))
        return out
