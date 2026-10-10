"""Enchanted forest theme: frogs, ladybugs, beetles and butterflies you can poke, feed and follow (like the Jurassic herd).

Frogs live around a lily pond and travel in real hops (legs fold, extend, land), puffing their throats while they sit.
Ladybugs and beetles walk on six legs with a tripod gait; a poked ladybug opens its shell and flies, a poked beetle rears
up and clacks its mandibles / horn. Butterflies flutter on hinged wings and spiral up when startled. Dropped berries draw
everyone over. The dressing (oaks, pines, birches, ferns, mushrooms, flowers, grass, mossy rocks, logs, the pond) is built
once into a numpy block; falling leaves and pollen drift every frame.

The public surface mirrors haunt.Haunt / dinos.Herd (dinos / pick / poke / feed / step / boxes / shake).
"""
import math
import random

import numpy as np

from . import models
from .haunt import _limb
from .scene import box

EDGE = 0.14  # soft outlines: this theme should look natural, not neon
POND = (-104.0, -38.0, 15.0)  # x, z, radius
CLEAR = (-72.0, 72.0, -160.0, 22.0)  # x0, x1, z0, z1: where the pedestals live; trees and rocks stay out of it

# kind -> (name, diet, size, habitat, fact, speed, avoid radius, pick centre height, pick radius, eats, verb, scale)
SPECIES = {
    "frog": ("Tree Frog", "Flies, berries in a pinch", "7 cm", "pond edges", "Can jump twenty times its own length - and does, when poked.", 0.0, 3.0, 0.9, 1.9, "berries", "croaks RIBBIT", 2.6),
    "ladybug": ("Ladybug", "Aphids", "8 mm", "leaves and stems", "Counts its spots to tell the time (it does not).", 3.4, 2.4, 0.6, 1.6, "berries", "pops its shell and flies off", 2.4),
    "stag": ("Stag Beetle", "Tree sap", "7 cm", "old logs", "Those huge jaws are for wrestling rivals, not for eating.", 2.6, 3.3, 0.7, 2.0, "berries", "clacks its jaws", 2.4),
    "rhino": ("Rhinoceros Beetle", "Fruit and sap", "6 cm", "the forest floor", "Lifts 850 times its own weight - pound for pound the strongest.", 2.3, 3.3, 0.7, 2.0, "berries", "rears its horn", 2.4),
    "jewel": ("Jewel Beetle", "Nectar and leaves", "4 cm", "sunny branches", "Its shell has no pigment: the colour is light bending in the layers.", 3.1, 2.7, 0.6, 1.7, "berries", "shimmers", 2.4),
    "butterfly": ("Butterfly", "Nectar, fruit juice", "10 cm span", "meadow flowers", "Tastes with its feet before it sips.", 5.5, 0.0, 0.0, 2.2, "berries", "flutters away", 2.3),
}
KINDS = (["frog"] * 6 + ["ladybug"] * 6 + ["stag", "stag", "rhino", "rhino", "jewel", "jewel"] + ["butterfly"] * 10)

BUTTERFLIES = {  # wing base, border, spots, hind-wing accent, glow
    "monarch": ((1.0, 0.5, 0.05), (0.06, 0.04, 0.03), (1.0, 1.0, 0.95), (1.0, 0.5, 0.05), 0.55),
    "morpho": ((0.15, 0.5, 1.0), (0.04, 0.05, 0.1), (0.85, 0.95, 1.0), (0.1, 0.35, 0.9), 1.1),
    "lemon": ((1.0, 0.9, 0.25), (0.75, 0.55, 0.05), (1.0, 0.5, 0.1), (0.95, 0.85, 0.2), 0.6),
    "cabbage": ((0.96, 0.96, 0.9), (0.15, 0.15, 0.15), (0.12, 0.12, 0.12), (0.92, 0.92, 0.85), 0.55),
    "swallowtail": ((1.0, 0.85, 0.3), (0.05, 0.05, 0.05), (0.3, 0.55, 1.0), (1.0, 0.3, 0.15), 0.6),
}

BLACK, WHITE = (0.04, 0.04, 0.05), (0.95, 0.95, 0.92)
FROG_G, FROG_D, FROG_B = (0.32, 0.66, 0.16), (0.16, 0.38, 0.08), (0.88, 0.9, 0.6)


class Creature:
    def __init__(self, kind, i, rnd):
        self.kind, self.i = kind, i
        sp = SPECIES[kind]
        self.name, self.diet, self.length, self.era, self.fact = sp[0], sp[1], sp[2], sp[3], sp[4]
        self.speed, self.radius, self.pick_h, self.pick_r, self.eats, self.verb, self.sc = sp[5:12]
        self.flyer = kind == "butterfly"
        self.heading, self.phase, self.mv, self.turn = rnd.uniform(0, 6.28), rnd.uniform(0, 6), 0.0, 0.0
        self.target, self.idle, self.moving = None, rnd.uniform(0, 3), False
        self.roar_t0, self.look, self.look_goal, self.look_t = -9.0, 0.0, 0.0, 0.0
        self.eat_until, self.bait, self.flee_until = 0.0, None, 0.0
        self.seed = rnd.random() * 100
        self.y, self.fly_until, self.hop = 0.0, -1.0, None
        a, rad = rnd.uniform(0, math.tau), rnd.uniform(50, 110)
        self.x, self.z = math.sin(a) * rad, math.cos(a) * rad
        if kind == "frog":
            a, rad = rnd.uniform(0, math.tau), POND[2] + rnd.uniform(2, 14)
            self.x, self.z = POND[0] + math.sin(a) * rad, POND[1] + math.cos(a) * rad
        if kind == "butterfly":
            self.pal = rnd.choice(list(BUTTERFLIES))
            self.y = rnd.uniform(3, 8)
            self.vx = self.vy = self.vz = 0.0
            self.flap_w = rnd.uniform(15, 20)
        if kind == "jewel":
            self.pal = rnd.random()


# ------------------------------------------------------------ helpers
def _rot_parts(P, ang, px, py):
    """Pitch a whole rig about a pivot (x, y) in the side plane (used when a beetle rears up)."""
    c, s = math.cos(ang), math.sin(ang)
    out = []
    for x, y, z, sx, sy, sz, col, gl, rz, rx, yl in P:
        dx, dy = x - px, y - py
        out.append((px + dx * c - dy * s, py + dx * s + dy * c, z, sx, sy, sz, col, gl, rz + ang, rx, yl))
    return out


def _six_legs(P, d, t, socks, reach, lift_h, thick, col, mv, knee_h=0.45, three=False):
    """Six legs with a tripod gait: legs 0, 3, 4 step while 1, 2, 5 push (and the other way round)."""
    ph = d.phase * 6.0
    for k, (sx, sy, sz) in enumerate(socks):
        side = 1 if sz > 0 else -1
        grp = (0 if k in (0, 3, 4) else math.pi)
        stride = math.sin(ph + grp) * 0.32 * mv
        lift = max(0.0, math.cos(ph + grp)) * lift_h * mv
        splay = (0.35, 0.0, -0.4)[k // 2]  # front legs reach forward, back legs back
        foot = (sx + splay + stride, 0.03 + lift, sz + side * reach)
        knee = (sx + splay * 0.5 + stride * 0.5, sy + knee_h + lift * 0.5, sz + side * reach * 0.55)
        if three:
            hip = (sx, sy + 0.05, sz + side * 0.12)
            P.append(_limb((sx, sy, sz), hip, thick * 1.2, col))
            P.append(_limb(hip, knee, thick, col))
        else:
            P.append(_limb((sx, sy, sz), knee, thick, col))
        P.append(_limb(knee, foot, thick * 0.8, col))
        P.append((foot[0], foot[1], foot[2], thick * 1.1, thick * 0.6, thick * 1.1, col, 0.1, 0, 0, 0))


# ------------------------------------------------------------ rigs: local frame, +x forward, +z side, y up from the ground
def rig_frog(d, t, st):
    P = []
    air, throat, r = st["air"], st["throat"], st["roar"]
    tilt = 0.28 * (1 - air)  # sits nose-up, stretches flat in the air
    P.append((0, 0.78, 0, 1.8, 0.95, 1.35, FROG_G, 0.3, tilt, 0, 0))  # body
    P.append((-0.15, 1.08, 0, 1.4, 0.5, 1.1, FROG_D, 0.25, tilt, 0, 0))  # darker back
    for sx, sz in ((-0.4, 0.25), (0.15, -0.3), (-0.65, -0.2), (0.05, 0.35)):  # spots
        P.append((sx, 1.3 + sx * 0.25, sz, 0.26, 0.08, 0.26, (0.1, 0.25, 0.05), 0.2, tilt, 0, 0))
    P.append((0.1, 0.42, 0, 1.5, 0.36, 1.12, FROG_B, 0.3, tilt, 0, 0))  # belly
    hy = 1.0 + 0.15 * r
    P.append((0.85, hy, 0, 0.92, 0.72, 1.18, FROG_G, 0.3, tilt * 0.6, 0, st["look"]))  # head
    P.append((1.13, hy - 0.2, 0, 0.5, 0.05, 1.12, (0.12, 0.2, 0.05), 0.1, tilt * 0.6, 0, st["look"]))  # mouth line
    puff = throat + 0.8 * r
    P.append((0.98, 0.58, 0, 0.5, 0.3 + 0.38 * puff, 0.66 + 0.4 * puff, FROG_B, 0.35 + 0.4 * puff, 0, 0, 0))  # throat sac
    blink = 0.15 if (t + d.seed) % 4.3 < 0.12 else 1.0
    for sz in (-1, 1):
        P.append((0.82, hy + 0.42, sz * 0.4, 0.44, 0.44 * blink, 0.44, (0.95, 0.8, 0.15), 0.7, 0, 0, 0))  # bulging eyes
        P.append((1.04, hy + 0.44, sz * 0.42, 0.06, 0.2 * blink, 0.28, BLACK, 0.0, 0, 0, 0))  # horizontal pupils
        P.append((0.78, hy + 0.66, sz * 0.4, 0.38, 0.08, 0.38, FROG_G, 0.3, 0, 0, 0))  # lid ridge
        # front legs: planted while sitting, swept back in the air
        sock = (0.6, 0.55, sz * 0.58)
        hand = (1.05 - 0.75 * air, 0.05 + 0.3 * air, sz * (0.72 + 0.1 * air))
        elbow = ((sock[0] + hand[0]) / 2 + 0.1, 0.35 + 0.1 * air, sz * 0.82)
        P.append(_limb(sock, elbow, 0.2, FROG_G))
        P.append(_limb(elbow, hand, 0.17, FROG_G))
        for f in (-1, 0, 1):  # toes with sticky pads
            P.append((hand[0] + 0.15, hand[1], hand[2] + f * 0.12, 0.2, 0.06, 0.07, FROG_D, 0.2, 0, 0, 0))
            P.append((hand[0] + 0.26, hand[1], hand[2] + f * 0.14, 0.09, 0.08, 0.09, FROG_B, 0.3, 0, 0, 0))
        # back legs: folded Z under the body while sitting, fully extended behind during a hop
        hip = (-0.72, 0.62, sz * 0.6)
        knee = (-0.1 - 1.2 * air, 0.5, sz * (1.05 - 0.2 * air))
        ankle = (-0.95 - 1.15 * air, 0.18 + 0.15 * air, sz * (0.95 - 0.15 * air))
        foot = (-0.3 - 2.15 * air, 0.06 + 0.2 * air, sz * (1.0 - 0.2 * air))
        P.append(_limb(hip, knee, 0.42, FROG_G))
        P.append(_limb(knee, ankle, 0.32, FROG_G))
        P.append(_limb(ankle, foot, 0.2, FROG_D))
        P.append((foot[0] + (0.2 if air < 0.5 else -0.2), foot[1], foot[2], 0.5, 0.05, 0.42, FROG_D, 0.2, 0, 0, 0))  # webbed foot
    return P


def rig_ladybug(d, t, st):
    P = []
    op = st["open"]
    red, glossy = (0.92, 0.08, 0.05), 0.4
    _six_legs(P, d, t, [(0.35, 0.22, -0.3), (0.35, 0.22, 0.3), (0.0, 0.22, -0.34), (0.0, 0.22, 0.34), (-0.35, 0.22, -0.3), (-0.35, 0.22, 0.3)],
              0.42, 0.12, 0.06, BLACK, st["mv"] if op < 0.5 else 0.0, 0.16)
    P.append((0, 0.3, 0, 1.25, 0.24, 0.95, BLACK, 0.1, 0, 0, 0))  # underside
    P.append((0.56, 0.5, 0, 0.36, 0.3, 0.85, BLACK, 0.15, 0, 0, 0))  # pronotum
    P.append((0.56, 0.66, 0, 0.3, 0.06, 0.6, BLACK, 0.15, 0, 0, 0))
    for sz in (-1, 1):
        P.append((0.6, 0.53, sz * 0.34, 0.24, 0.2, 0.16, WHITE, 0.3, 0, 0, 0))
    P.append((0.8, 0.38, 0, 0.34, 0.3, 0.52, BLACK, 0.15, 0, 0, 0))  # head
    for sz in (-1, 1):
        P.append((0.95, 0.55, sz * 0.17, 0.12, 0.1, 0.12, WHITE, 0.4, 0, 0, 0))
        P.append(_limb((0.95, 0.58, sz * 0.12), (1.3, 0.86 + 0.04 * math.sin(t * 4 + sz), sz * 0.32), 0.04, BLACK))  # antennae
        P.append((1.3, 0.86 + 0.04 * math.sin(t * 4 + sz), sz * 0.32, 0.09, 0.09, 0.09, BLACK, 0.1, 0, 0, 0))
    # elytra: each red half hinges at the seam and swings up and out to fly
    piv_y = 0.86
    spots = [(0.25, 0.84, 0.3), (-0.2, 0.9, 0.22), (-0.45, 0.76, 0.42), (0.02, 0.66, 0.53)]
    for sz in (-1, 1):
        a = -sz * op * 1.25
        ca, sa = math.cos(a), math.sin(a)

        def hinge(x, y, z):
            dy, dz = y - piv_y, z
            return x, piv_y + dy * ca - dz * sa, dy * sa + dz * ca
        for (x, y, z, sx, sy, sz_, col, gl) in [(-0.05, 0.52, sz * 0.27, 1.4, 0.36, 0.58, red, glossy),  # a dome from stacked, tapering layers
                                                (-0.05, 0.7, sz * 0.25, 1.28, 0.16, 0.52, red, glossy),
                                                (-0.05, 0.8, sz * 0.21, 1.08, 0.12, 0.42, red, glossy + 0.05),
                                                (-0.08, 0.88, sz * 0.15, 0.8, 0.08, 0.3, red, glossy + 0.1),
                                                (0.22, 0.9, sz * 0.14, 0.26, 0.04, 0.12, (1.0, 0.6, 0.55), 0.7)]:  # gloss highlight
            hx, hy, hz = hinge(x, y, z)
            P.append((hx, hy, hz, sx, sy, sz_, col, gl, 0, a, 0))
        for x, y, z in spots:
            hx, hy, hz = hinge(x, y, sz * z)
            P.append((hx, hy + 0.01, hz, 0.22, 0.07, 0.22, BLACK, 0.05, 0, a, 0))
        if op > 0.05:  # hind wings unfold and buzz (two phases drawn so the beat reads as a blur)
            for k in range(2):
                fl = sz * (0.35 + 0.45 * math.sin(t * 42 + k * 1.6))
                P.append((-0.25, 0.9 + 0.15 * op, sz * 0.95 * op, 1.25 * op, 0.03, 1.2 * op, (0.85, 0.85, 0.8), 0.6, -0.15, fl, 0))
    P.append((0.5, 0.82, 0, 0.14, 0.08, 0.22, BLACK, 0.05, 0, 0, 0))  # the spot on the seam
    return P


def rig_beetle(d, t, st):
    P = []
    r, mv = st["roar"], st["mv"]
    kind = d.kind
    if kind == "jewel":  # structural colour: shifts with the light
        k = 0.5 + 0.5 * math.sin(t * 0.8 + d.pal * 6)
        g2 = 0.5 + 0.5 * math.sin(t * 0.5 + d.pal * 4 + 2)
        shell = tuple((1 - k) * a + k * (b * (1 - g2) + c * g2) for a, b, c in zip((0.1, 0.72, 0.35), (0.1, 0.45, 0.85), (0.85, 0.7, 0.15)))
        dark, sheen, glow = (0.05, 0.2, 0.12), tuple(min(1.0, v * 1.4 + 0.15) for v in shell), 0.75
    elif kind == "stag":
        shell, dark, sheen, glow = (0.32, 0.15, 0.07), (0.14, 0.07, 0.04), (0.75, 0.45, 0.3), 0.3
    else:
        shell, dark, sheen, glow = (0.17, 0.1, 0.06), (0.07, 0.05, 0.04), (0.6, 0.45, 0.35), 0.3
    _six_legs(P, d, t, [(0.45, 0.32, -0.36), (0.45, 0.32, 0.36), (0.0, 0.32, -0.42), (0.0, 0.32, 0.42), (-0.45, 0.32, -0.38), (-0.45, 0.32, 0.38)],
              1.0, 0.2, 0.09, dark, mv, 0.42, three=True)
    P.append((-0.4, 0.5, 0, 1.6, 0.46, 1.1, shell, glow, 0, 0, 0))  # elytra, rounded by stacked tapering layers
    P.append((-0.4, 0.74, 0, 1.5, 0.12, 0.98, shell, glow, 0, 0, 0))
    P.append((-0.42, 0.83, 0, 1.3, 0.1, 0.8, shell, glow + 0.05, 0, 0, 0))
    P.append((-0.45, 0.9, 0, 1.0, 0.06, 0.55, shell, glow + 0.1, 0, 0, 0))
    P.append((-1.18, 0.55, 0, 0.2, 0.4, 0.8, shell, glow, 0, 0, 0))  # rounded rear
    P.append((-0.42, 0.94, 0, 1.3, 0.03, 0.04, dark, 0.05, 0, 0, 0))  # seam
    for sz in (-1, 1):
        P.append((-0.2, 0.92, sz * 0.18, 0.7, 0.02, 0.05, sheen, 0.55, 0, 0, 0))  # a soft highlight
        for k in range(2):  # grooves along the wing cases
            P.append((-0.4, 0.8 - k * 0.14, sz * (0.42 + k * 0.08), 1.35, 0.025, 0.025, dark, 0.05, 0, 0, 0))
    P.append((0.52, 0.52, 0, 0.62, 0.44, 0.98, shell, glow, 0, 0, 0))  # thorax
    P.append((0.52, 0.72, 0, 0.5, 0.08, 0.8, shell, glow, 0, 0, 0))
    P.append((0.98, 0.46, 0, 0.42, 0.34, 0.72 if kind != "stag" else 0.95, dark, 0.2, 0, 0, st["look"]))  # head
    for sz in (-1, 1):
        P.append((1.12, 0.6, sz * 0.3, 0.12, 0.12, 0.12, (0.05, 0.05, 0.05), 0.6, 0, 0, 0))  # eyes
        base = (1.15, 0.55, sz * 0.18)
        P.append(_limb(base, (1.5, 0.8, sz * 0.42), 0.04, dark))  # elbowed antennae with a club
        P.append(_limb((1.5, 0.8, sz * 0.42), (1.75, 0.85, sz * 0.5), 0.04, dark))
        P.append((1.78, 0.86, sz * 0.52, 0.14, 0.1, 0.1, dark, 0.2, 0, 0, 0))
    if kind == "stag":  # antler jaws that open and clack when poked
        clack = r * (0.5 + 0.5 * math.sin(t * 22))
        for sz in (-1, 1):
            jaw = (0.5, 0.2, 0.09)
            a0 = (1.15, 0.5, sz * 0.32)
            a1 = (1.6, 0.66 + 0.2 * r, sz * (0.55 + 0.12 * clack))
            a2 = (2.05, 0.78 + 0.3 * r, sz * (0.48 + 0.1 * clack))
            a3 = (2.35, 0.8 + 0.35 * r, sz * (0.2 + 0.25 * clack))  # the tips curve in toward each other
            P.append(_limb(a0, a1, 0.13, jaw))
            P.append(_limb(a1, a2, 0.1, jaw))
            P.append(_limb(a2, a3, 0.08, jaw))
            P.append(_limb((1.85, 0.72 + 0.25 * r, sz * (0.52 + 0.1 * clack)), (1.88, 0.92 + 0.25 * r, sz * (0.44 + 0.1 * clack)), 0.06, jaw))  # tooth
    elif kind == "rhino":  # a curved head horn and a short one on the thorax
        lift = 0.35 * r
        P.append(_limb((1.15, 0.65, 0), (1.55, 1.15 + lift, 0), 0.2, dark))
        P.append(_limb((1.55, 1.15 + lift, 0), (1.62, 1.6 + lift, 0), 0.14, dark))
        P.append(_limb((1.62, 1.6 + lift, 0), (1.45, 1.85 + lift, 0), 0.1, dark))
        P.append(_limb((0.6, 0.82, 0), (1.05, 1.15 + lift * 0.5, 0), 0.16, dark))
    if r > 0:  # rear up on the back legs
        P = _rot_parts(P, 0.45 * r, -1.0, 0.3)
    return P


def rig_butterfly(d, t, st):
    P = []
    base, border, spot, hind, glow = BUTTERFLIES[d.pal]
    rate = d.flap_w * (0.45 if st["eat"] else 1.0) * (1.6 if st["roar"] else 1.0)
    f = 0.2 + 1.05 * (0.5 + 0.5 * math.sin(t * rate + d.seed))  # wing angle above level
    if st["eat"]:
        f = 0.9 + 0.5 * (0.5 + 0.5 * math.sin(t * rate + d.seed))  # slow open-and-close while sipping
    body = (0.12, 0.09, 0.07)
    P.append((0.15, 0, 0, 0.42, 0.26, 0.26, body, 0.2, 0, 0, 0))  # thorax
    P.append((-0.4, -0.04, 0, 0.75, 0.17, 0.17, body, 0.2, 0.08, 0, 0))  # abdomen
    P.append((0.45, 0.02, 0, 0.2, 0.2, 0.2, body, 0.2, 0, 0, 0))  # head
    for sz in (-1, 1):
        P.append(_limb((0.5, 0.08, sz * 0.05), (1.0, 0.45, sz * 0.25), 0.03, body))  # antennae
        P.append((1.0, 0.45, sz * 0.25, 0.08, 0.08, 0.08, body, 0.2, 0, 0, 0))
        a = -sz * f
        ca, sa = math.cos(a), math.sin(a)

        def w(x, z, sx, sz_, col, gl, rz=0.0, y=0.0):
            zz = sz * z
            P.append((x, y * ca - zz * sa, y * sa + zz * ca, sx, 0.035, sz_, col, gl, rz, a, 0))
        lag = math.sin(t * rate + d.seed - 0.5)  # the hind wing trails a little
        # forewing: strips from the root outward, longer and swept forward toward the tip -> a triangular wing
        fore = [(0.18, 0.62, 0.0), (0.3, 0.86, 0.06), (0.52, 1.0, 0.14), (0.78, 1.0, 0.24), (1.02, 0.86, 0.3), (1.22, 0.56, 0.34)]
        for k, (zc, ln, fwd) in enumerate(fore):
            last = k >= len(fore) - 2
            w(0.12 + fwd, zc, ln, 0.26, border if last else base, 0.1 if last else glow)
            w(0.12 + fwd + ln / 2 - 0.06, zc, 0.12, 0.26, border, 0.1)  # dark leading edge
        for k in range(4):  # white dots in the dark tip
            w(0.25 + k * 0.17, 1.18 + 0.05 * (k % 2), 0.07, 0.07, spot, 0.7, 0, 0.02)
        w(0.35, 0.62, 0.8, 0.03, border, 0.1, 0, 0.02)  # veins
        w(0.45, 0.95, 0.6, 0.03, border, 0.1, 0, 0.02)
        # hindwing: rounder, trailing behind the forewing
        hy = 0.04 * lag
        hind_s = [(0.18, 0.7), (0.36, 0.86), (0.56, 0.86), (0.76, 0.72), (0.94, 0.48)]
        for k, (zc, ln) in enumerate(hind_s):
            last = k == len(hind_s) - 1
            w(-0.3, zc, ln, 0.22, border if last else hind, 0.1 if last else glow, 0, hy)
            w(-0.3 - ln / 2 + 0.05, zc, 0.1, 0.22, border, 0.1, 0, hy)  # dark trailing edge
        if d.pal in ("swallowtail", "morpho", "monarch"):
            w(-0.48, 0.7, 0.16, 0.16, spot if d.pal != "swallowtail" else (1.0, 0.3, 0.1), 0.9, 0, hy + 0.02)
        if d.pal == "swallowtail":
            w(-0.95, 0.82, 0.5, 0.1, border, 0.1, 0, hy)  # the tail
    return P


RIGS = {"frog": rig_frog, "ladybug": rig_ladybug, "stag": rig_beetle, "rhino": rig_beetle, "jewel": rig_beetle, "butterfly": rig_butterfly}


class Forest:
    def __init__(self, seed=21):
        self.rnd = random.Random(seed)
        self.dinos = [Creature(k, i, self.rnd) for i, k in enumerate(KINDS)]
        self.last = None
        self.baits, self.dust, self.rings = [], [], []
        self.shake = 0.0
        self.trees = []  # (x, z, r): trunks the walkers steer around
        self.meshes = None
        if models.available():  # Blender-made scenery (tools/blender_models.py); the box-built version is the fallback
            self.meshes = self._mesh_scenery()
            self.static = np.array(self._sun(), dtype=np.float32)
            self.inner, self.inner_xz = np.zeros((0, 16), np.float32), np.zeros((0, 2), np.float32)
            self.platforms, self._plat_key, self._inner_vis = [], None, self.inner
            return
        self.static = np.array(self._scenery(), dtype=np.float32)
        inner, anchors = self._clearing_cover()
        self.inner, self.inner_xz = np.array(inner, dtype=np.float32).reshape(-1, 16), np.array(anchors, dtype=np.float32).reshape(-1, 2)
        self.platforms, self._plat_key, self._inner_vis = [], None, self.inner

    # ---------- static dressing ----------
    def _free(self, x, z, margin=0.0):
        x0, x1, z0, z1 = CLEAR
        if x0 - margin < x < x1 + margin and z0 - margin < z < z1 + margin:
            return False
        if math.hypot(x - POND[0], z - POND[1]) < POND[2] + 3 + margin:
            return False
        return all(math.hypot(x - tx, z - tz) > tr + margin for tx, tz, tr in self.trees)

    def _spot(self, rnd, rmin, rmax, margin=0.0, tries=30):
        for _ in range(tries):
            a, rad = rnd.uniform(0, math.tau), rnd.uniform(rmin, rmax)
            x, z = math.sin(a) * rad, math.cos(a) * rad
            if self._free(x, z, margin):
                return x, z
        return None

    @staticmethod
    def _sun():
        return [box(-60, 70, -230, 34, 34, 2, (1.0, 0.92, 0.65), 1.7, 0.0, 0.0, 0.0, 1.0),
                box(-60, 70, -231, 50, 50, 1, (0.65, 0.6, 0.35), 0.9, 0.0, 0.0, 0.0, 1.0)]

    def _mesh_scenery(self):
        """The forest from Blender models, laid out exactly like the box version (same seeds, spots and sizes)."""
        rnd = random.Random(7)
        M = models.MeshSet()
        for i in range(115):  # trees
            p = self._spot(rnd, 40, 210, 4)
            if p:
                kind, s = rnd.random(), rnd.uniform(0.85, 1.35)
                name = (rnd.choice(("oak_a", "oak_b", "oak_c")) if kind < 0.42 else rnd.choice(("pine_a", "pine_b")) if kind < 0.8
                        else rnd.choice(("birch_a", "birch_b")))
                M.put(name, p[0], 0, p[1], s, rnd.uniform(0, math.tau))
                self.trees.append((p[0], p[1], (1.4 if name[0] == "o" else 1.0 if name[0] == "p" else 0.9) * s))
        for i in range(34):
            p = self._spot(rnd, 32, 160, 1.5)
            if p:
                M.put("bush_berry" if i % 3 == 0 else rnd.choice(("bush_a", "bush_b")), p[0], 0, p[1], rnd.uniform(0.85, 1.2), rnd.uniform(0, math.tau))
        for i in range(60):
            p = self._spot(rnd, 28, 170, 0.5)
            if p:
                M.put(rnd.choice(("fern_a", "fern_b")), p[0], 0, p[1], rnd.uniform(0.8, 1.4), rnd.uniform(0, math.tau))
        for i in range(55):
            p = self._spot(rnd, 26, 150, 0.3)
            if p:
                k = rnd.random()
                name = "toadstool" if k < 0.45 else "shrooms" if k < 0.85 else "glowshrooms"
                M.put(name, p[0], 0, p[1], rnd.uniform(0.8, 1.4), rnd.uniform(0, math.tau))
        names = [f"flower_{c}" for c in ("white", "blue", "pink", "yellow", "red")]
        for i in range(170):
            p = self._spot(rnd, 24, 140, 0.0, 6)
            if p:
                M.put(rnd.choice(names), p[0], 0, p[1], rnd.uniform(0.75, 1.3), rnd.uniform(0, math.tau))
        for i in range(320):
            p = self._spot(rnd, 22, 170, 0.0, 4)
            if p:
                M.put(rnd.choice(("grass_a", "grass_b", "grass_c")), p[0], 0, p[1], rnd.uniform(0.8, 1.2), rnd.uniform(0, math.tau))
        for i in range(26):
            p = self._spot(rnd, 30, 160, 1.0)
            if p:
                M.put(rnd.choice(("rock_a", "rock_b", "rock_c")), p[0], 0, p[1], rnd.uniform(1.0, 2.6), rnd.uniform(0, math.tau))
        for i in range(7):
            p = self._spot(rnd, 40, 150, 4.0)
            if p:
                M.put("log", p[0], 0, p[1], rnd.uniform(0.8, 1.15), rnd.uniform(0, math.pi))
                self.trees.append((p[0], p[1], 2.0))
        px, pz, pr = POND
        M.put("water_deep", px, 0.03, pz, (pr + 0.4, 1, pr + 0.4), 0.0, edge=0.0)
        M.put("water_light", px, 0.05, pz, (pr * 0.8, 1, pr * 0.8), 0.4, edge=0.0)
        for k in range(26):
            a = k / 26 * math.tau
            M.put(rnd.choice(("stone_a", "stone_b")), px + math.cos(a) * (pr + 0.6), 0, pz - math.sin(a) * (pr + 0.6), rnd.uniform(0.55, 0.85), a)
        for k in range(14):
            a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, pr * 0.8)
            lx, lz = px + math.cos(a) * rr, pz - math.sin(a) * rr
            s = rnd.uniform(1.1, 1.9)
            M.put("lilypad", lx, 0, lz, s, rnd.uniform(0, math.tau))
            if k % 4 == 0:
                M.put("waterlily", lx, 0, lz, 1.0, rnd.uniform(0, math.tau))
        for k in range(11):
            a = rnd.uniform(0, math.tau)
            rr = pr + rnd.uniform(-0.5, 1.6)
            M.put(rnd.choice(("cattail_a", "cattail_b")), px + math.cos(a) * rr, 0, pz - math.sin(a) * rr, rnd.uniform(0.9, 1.2), rnd.uniform(0, math.tau))
        self.trees.append((px, pz, pr))
        # ground cover in the clearing: hidden wherever a section platform stands (see boxes)
        x0, x1, z0, z1 = CLEAR
        crnd = random.Random(11)
        for i in range(520):
            x, z = crnd.uniform(x0 - 6, x1 + 6), crnd.uniform(z0 - 6, z1 + 10)
            k = crnd.random()
            name = (crnd.choice(("grass_a", "grass_b", "grass_c")) if k < 0.5 else crnd.choice(names) if k < 0.85
                    else crnd.choice(("fern_a", "fern_b")) if k < 0.95 else "toadstool")
            M.put(name, x, 0, z, crnd.uniform(0.6, 0.95) if name.startswith(("fern", "toad")) else crnd.uniform(0.75, 1.1), crnd.uniform(0, math.tau), anchor=(x, z))
        return M.freeze()

    def _scenery(self):
        rnd = random.Random(7)
        out = []
        leafs = [(0.18, 0.42, 0.12), (0.22, 0.5, 0.14), (0.15, 0.36, 0.1), (0.28, 0.52, 0.16), (0.32, 0.5, 0.12)]
        bark = (0.3, 0.2, 0.12)

        def oak(x, z, s):
            h = 7.5 * s
            out.append(box(x, h / 2, z, 1.5 * s, h, 1.5 * s, bark, 0.08, rnd.uniform(0, 1), EDGE))
            for k in range(4):  # root flare
                a = k * math.pi / 2 + 0.4
                out.append(box(x + math.cos(a) * 0.9 * s, 0.35 * s, z - math.sin(a) * 0.9 * s, 1.6 * s, 0.6 * s, 0.5 * s, bark, 0.05, a, EDGE, 0, 0, -0.35))
            for k in range(4):  # branches
                a = k * math.pi / 2 + rnd.uniform(0, 1)
                out.append(box(x + math.cos(a) * 1.6 * s, h * 0.82, z - math.sin(a) * 1.6 * s, 3.4 * s, 0.5 * s, 0.5 * s, bark, 0.05, a, EDGE, 0, 0, 0.55))
            for k in range(9):  # lumpy canopy: overlapping leaf clusters at different heights
                a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, 3.2) * s
                cs = rnd.uniform(3.2, 5.0) * s
                out.append(box(x + math.cos(a) * rr, h + rnd.uniform(0.3, 3.4) * s, z - math.sin(a) * rr, cs, cs * 0.75, cs,
                               rnd.choice(leafs), 0.12, rnd.uniform(0, 1.5), EDGE))
            self.trees.append((x, z, 1.4 * s))

        def pine(x, z, s):
            h = 11 * s
            out.append(box(x, h / 2, z, 0.9 * s, h, 0.9 * s, (0.26, 0.17, 0.1), 0.06, 0.0, EDGE))
            needles = (0.07, 0.25, 0.12)
            for k in range(6):  # stacked tiers, each two crossed square layers
                y = 2.2 * s + k * 1.6 * s
                w = (5.6 - k * 0.8) * s
                for yaw in (0.0, math.pi / 4):
                    out.append(box(x, y, z, w, 1.1 * s, w, tuple(c * (0.9 + 0.05 * k) for c in needles), 0.1, yaw + k * 0.3, EDGE))
            out.append(box(x, h + 0.6 * s, z, 0.8 * s, 1.6 * s, 0.8 * s, needles, 0.1, 0.0, EDGE))
            self.trees.append((x, z, 1.0 * s))

        def birch(x, z, s):
            h = 9 * s
            out.append(box(x, h / 2, z, 0.8 * s, h, 0.8 * s, (0.9, 0.9, 0.85), 0.15, 0.0, EDGE))
            for k in range(7):  # black bark marks
                y = rnd.uniform(0.6, h - 0.5)
                side = rnd.choice((-1, 1))
                out.append(box(x + side * 0.41 * s, y, z, 0.04, 0.12 * s, 0.4 * s, (0.08, 0.08, 0.08), 0.0, rnd.choice((0, math.pi / 2)), 0.0))
            for k in range(6):
                a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, 2.0) * s
                cs = rnd.uniform(2.2, 3.4) * s
                out.append(box(x + math.cos(a) * rr, h * 0.8 + rnd.uniform(0, 3) * s, z - math.sin(a) * rr, cs, cs * 0.9, cs,
                               (0.45, 0.62, 0.2), 0.15, rnd.uniform(0, 1.5), EDGE))
            self.trees.append((x, z, 0.9 * s))

        for i in range(115):  # trees: a ring of woodland round the clearing, thicker further out
            p = self._spot(rnd, 40, 210, 4)
            if p:
                kind = rnd.random()
                (oak if kind < 0.42 else pine if kind < 0.8 else birch)(p[0], p[1], rnd.uniform(0.85, 1.35))
        for i in range(34):  # bushes, some with berries
            p = self._spot(rnd, 32, 160, 1.5)
            if not p:
                continue
            x, z = p
            for k in range(5):
                a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, 1.1)
                cs = rnd.uniform(1.3, 2.2)
                out.append(box(x + math.cos(a) * rr, cs * 0.4, z - math.sin(a) * rr, cs, cs * 0.8, cs, rnd.choice(leafs), 0.1, rnd.uniform(0, 1.5), EDGE))
            if i % 3 == 0:
                for k in range(6):
                    a = rnd.uniform(0, math.tau)
                    out.append(box(x + math.cos(a) * 1.0, rnd.uniform(0.5, 1.4), z - math.sin(a) * 1.0, 0.22, 0.22, 0.22, (0.85, 0.08, 0.15), 0.9, 0.0, 0.0))
        for i in range(60):  # ferns: fronds fanning out from a crown
            p = self._spot(rnd, 28, 170, 0.5)
            if not p:
                continue
            x, z = p
            s = rnd.uniform(0.8, 1.4)
            for k in range(8):
                a = k / 8 * math.tau + rnd.uniform(-0.2, 0.2)
                ln = rnd.uniform(1.8, 2.6) * s
                out.append(box(x + math.cos(a) * ln * 0.45, 0.55 * s, z - math.sin(a) * ln * 0.45, ln, 0.05, 0.42 * s,
                               (0.2, 0.52, 0.16) if k % 2 else (0.25, 0.58, 0.2), 0.12, a, EDGE, 0, 0, 0.45))
        for i in range(55):  # mushrooms: red toadstools with white spots, brown clusters, a few glowing ones
            p = self._spot(rnd, 26, 150, 0.3)
            if not p:
                continue
            x, z = p
            kind = rnd.random()
            if kind < 0.45:
                s = rnd.uniform(0.8, 1.4)
                out.append(box(x, 0.55 * s, z, 0.32 * s, 1.1 * s, 0.32 * s, (0.95, 0.93, 0.85), 0.2, 0.0, EDGE))
                out.append(box(x, 1.15 * s, z, 1.3 * s, 0.42 * s, 1.3 * s, (0.9, 0.12, 0.08), 0.35, 0.3, EDGE))
                out.append(box(x, 1.4 * s, z, 0.9 * s, 0.2 * s, 0.9 * s, (0.9, 0.12, 0.08), 0.35, 0.3, EDGE))
                for k in range(5):
                    a = k * 1.3 + rnd.random()
                    out.append(box(x + math.cos(a) * 0.4 * s, 1.43 * s + 0.08 * (k % 2), z - math.sin(a) * 0.4 * s, 0.14 * s, 0.06, 0.14 * s, WHITE, 0.4, 0.0, 0.0))
            elif kind < 0.85:
                for k in range(rnd.randint(3, 5)):
                    a, s = rnd.uniform(0, math.tau), rnd.uniform(0.4, 0.8)
                    mx, mz = x + math.cos(a) * 0.5, z - math.sin(a) * 0.5
                    out.append(box(mx, 0.4 * s, mz, 0.16 * s, 0.8 * s, 0.16 * s, (0.85, 0.78, 0.62), 0.1, 0.0, EDGE))
                    out.append(box(mx, 0.85 * s, mz, 0.75 * s, 0.25 * s, 0.75 * s, (0.5, 0.32, 0.16), 0.15, a, EDGE))
            else:
                for k in range(4):
                    a = rnd.uniform(0, math.tau)
                    mx, mz = x + math.cos(a) * 0.6, z - math.sin(a) * 0.6
                    out.append(box(mx, 0.25, mz, 0.1, 0.5, 0.1, (0.6, 0.85, 1.0), 0.6, 0.0, 0.0))
                    out.append(box(mx, 0.52, mz, 0.42, 0.14, 0.42, (0.3, 0.8, 1.0), 1.6, a, 0.0))
        flowers = [((0.97, 0.97, 0.92), (1.0, 0.8, 0.1)), ((0.55, 0.45, 1.0), (1.0, 0.95, 0.4)), ((1.0, 0.5, 0.7), (1.0, 0.9, 0.3)),
                   ((1.0, 0.85, 0.15), (0.6, 0.3, 0.05)), ((0.95, 0.25, 0.2), (0.1, 0.05, 0.05))]
        for i in range(170):  # flowers: stem, petals around a centre
            p = self._spot(rnd, 24, 140, 0.0, 6)
            if not p:
                continue
            x, z = p
            petal, middle = rnd.choice(flowers)
            h = rnd.uniform(0.7, 1.4)
            out.append(box(x, h / 2, z, 0.07, h, 0.07, (0.2, 0.5, 0.15), 0.1, 0.0, 0.0))
            out.append(box(x + 0.2, h * 0.4, z, 0.4, 0.04, 0.16, (0.25, 0.55, 0.18), 0.1, rnd.uniform(0, 3), 0.0))
            yaw = rnd.uniform(0, 1)
            out.append(box(x, h, z, 0.62, 0.06, 0.24, petal, 0.45, yaw, 0.0))
            out.append(box(x, h, z, 0.24, 0.06, 0.62, petal, 0.45, yaw, 0.0))
            out.append(box(x, h, z, 0.5, 0.06, 0.5, petal, 0.45, yaw + math.pi / 4, 0.0))
            out.append(box(x, h + 0.04, z, 0.2, 0.08, 0.2, middle, 0.7, yaw, 0.0))
        for i in range(320):  # grass tufts: three blades leaning outward
            p = self._spot(rnd, 22, 170, 0.0, 4)
            if not p:
                continue
            x, z = p
            g = rnd.choice([(0.25, 0.5, 0.14), (0.3, 0.58, 0.16), (0.36, 0.55, 0.18), (0.45, 0.55, 0.2)])
            for k in range(3):
                a = k * 2.1 + rnd.uniform(0, 1)
                h = rnd.uniform(0.7, 1.5)
                out.append(box(x + math.cos(a) * 0.12, h / 2, z - math.sin(a) * 0.12, 0.08, h, 0.03, g, 0.08, a, 0.0, 0, 0, 0.0, 0.25))
        for i in range(26):  # mossy rocks
            p = self._spot(rnd, 30, 160, 1.0)
            if not p:
                continue
            x, z = p
            s = rnd.uniform(1.0, 2.6)
            yaw = rnd.uniform(0, 1.5)
            out.append(box(x, 0.45 * s, z, 1.8 * s, 0.9 * s, 1.4 * s, (0.42, 0.43, 0.4), 0.08, yaw, EDGE))
            out.append(box(x + 0.2 * s, 0.85 * s, z, 1.2 * s, 0.5 * s, 1.0 * s, (0.45, 0.46, 0.43), 0.08, yaw + 0.4, EDGE))
            out.append(box(x, 0.95 * s, z, 1.5 * s, 0.25 * s, 1.15 * s, (0.25, 0.48, 0.15), 0.12, yaw, EDGE))  # moss cap
        for i in range(7):  # fallen logs with moss, a cut end and a few shelf mushrooms
            p = self._spot(rnd, 40, 150, 4.0)
            if not p:
                continue
            x, z = p
            yaw, ln, rr = rnd.uniform(0, math.pi), rnd.uniform(7, 11), rnd.uniform(0.7, 1.0)
            for a in (0.0, math.pi / 4):
                out.append(box(x, rr, z, ln, rr * 2, rr * 2, (0.33, 0.22, 0.13), 0.06, yaw, EDGE, 0, 0, 0.0, a))
            out.append(box(x, rr * 1.9, z, ln * 0.7, 0.3, rr * 1.3, (0.25, 0.5, 0.15), 0.12, yaw, EDGE))
            ex, ez = x + math.cos(yaw) * ln / 2, z - math.sin(yaw) * ln / 2
            out.append(box(ex, rr, ez, 0.06, rr * 1.7, rr * 1.7, (0.75, 0.6, 0.4), 0.2, yaw, 0.0))  # rings on the cut end
            out.append(box(ex, rr, ez, 0.08, rr * 1.0, rr * 1.0, (0.55, 0.4, 0.25), 0.2, yaw, 0.0))
            for k in range(3):
                f = (k - 1) * 0.25 * ln
                out.append(box(x + math.cos(yaw) * f + math.sin(yaw) * rr, rr * 1.2, z - math.sin(yaw) * f + math.cos(yaw) * rr, 0.7, 0.12, 0.5,
                               (0.85, 0.6, 0.3), 0.3, yaw, EDGE))
            self.trees.append((x, z, 2.0))
        # the pond: layered water, a ring of stones, lily pads with a flower, reeds and cattails
        px, pz, pr = POND
        for k in range(3):
            out.append(box(px, 0.03, pz, pr * 2, 0.06, pr * 2 * 0.42, (0.1, 0.32, 0.4), 0.35, k * math.pi / 3, 0.0))
            out.append(box(px, 0.05, pz, pr * 1.6, 0.06, pr * 1.6 * 0.42, (0.12, 0.4, 0.5), 0.45, k * math.pi / 3 + 0.5, 0.0))
        for k in range(26):
            a = k / 26 * math.tau + rnd.uniform(-0.05, 0.05)
            s = rnd.uniform(0.7, 1.4)
            out.append(box(px + math.cos(a) * (pr + 0.6), 0.3 * s, pz - math.sin(a) * (pr + 0.6), 1.3 * s, 0.6 * s, 1.0 * s, (0.48, 0.47, 0.44), 0.08, a, EDGE))
        for k in range(14):
            a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, pr * 0.8)
            s = rnd.uniform(0.9, 1.6)
            lx, lz = px + math.cos(a) * rr, pz - math.sin(a) * rr
            yaw = rnd.uniform(0, math.tau)
            for q in range(3):  # round pad from three crossed slabs, the gap left open
                out.append(box(lx, 0.1, lz, 1.4 * s, 0.05, 0.6 * s, (0.2, 0.55, 0.18), 0.2, yaw + q * math.pi / 3, 0.0))
            if k % 4 == 0:  # a water lily on it
                for q in range(3):
                    out.append(box(lx, 0.32, lz, 0.6, 0.18, 0.2, (1.0, 0.7, 0.85), 0.8, yaw + q * math.pi / 3, 0.0))
                out.append(box(lx, 0.42, lz, 0.18, 0.14, 0.18, (1.0, 0.9, 0.3), 1.0, 0.0, 0.0))
        for k in range(22):  # cattails and reeds on the bank
            a = rnd.uniform(0, math.tau)
            rr = pr + rnd.uniform(-0.8, 1.5)
            cx, cz = px + math.cos(a) * rr, pz - math.sin(a) * rr
            h = rnd.uniform(2.2, 3.6)
            lean = rnd.uniform(-0.12, 0.12)
            out.append(box(cx, h / 2, cz, 0.08, h, 0.08, (0.35, 0.55, 0.2), 0.1, a, 0.0, 0, 0, lean))
            if k % 2 == 0:
                out.append(box(cx - math.sin(lean) * h * 0.4, h * 0.85, cz, 0.24, 0.7, 0.24, (0.4, 0.22, 0.1), 0.15, a, EDGE, 0, 0, lean))
            out.append(box(cx + 0.2, h * 0.35, cz, 0.06, h * 0.7, 0.2, (0.3, 0.5, 0.18), 0.1, a + 1, 0.0, 0, 0, 0.3))
        self.trees.append((px, pz, pr))  # walkers go round the water (frogs stay on the bank)
        # a low warm sun behind the trees, with a soft halo
        out.append(box(-60, 70, -230, 34, 34, 2, (1.0, 0.92, 0.65), 1.7, 0.0, 0.0, 0.0, 1.0))
        out.append(box(-60, 70, -231, 50, 50, 1, (0.65, 0.6, 0.35), 0.9, 0.0, 0.0, 0.0, 1.0))
        return out

    def _clearing_cover(self):
        """Flowers, grass, ferns and mushrooms scattered through the clearing where the pedestals stand. Each box remembers
        the plant it belongs to so whole plants can be hidden under the section platforms (see boxes)."""
        rnd = random.Random(11)
        out, anchors = [], []
        x0, x1, z0, z1 = CLEAR
        flowers = [((0.97, 0.97, 0.92), (1.0, 0.8, 0.1)), ((0.55, 0.45, 1.0), (1.0, 0.95, 0.4)), ((1.0, 0.5, 0.7), (1.0, 0.9, 0.3)),
                   ((1.0, 0.85, 0.15), (0.6, 0.3, 0.05))]

        def add(items, x, z):
            out.extend(items)
            anchors.extend([(x, z)] * len(items))
        for i in range(520):
            x, z = rnd.uniform(x0 - 6, x1 + 6), rnd.uniform(z0 - 6, z1 + 10)
            kind = rnd.random()
            if kind < 0.5:  # grass
                g = rnd.choice([(0.25, 0.5, 0.14), (0.3, 0.58, 0.16), (0.36, 0.55, 0.18)])
                add([box(x + math.cos(k * 2.1) * 0.12, h / 2, z - math.sin(k * 2.1) * 0.12, 0.08, h, 0.03, g, 0.08, k * 2.1 + i, 0.0, 0, 0, 0.0, 0.25)
                     for k, h in enumerate((rnd.uniform(0.6, 1.3), rnd.uniform(0.6, 1.3), rnd.uniform(0.6, 1.3)))], x, z)
            elif kind < 0.85:  # flower
                petal, middle = rnd.choice(flowers)
                h, yaw = rnd.uniform(0.6, 1.2), rnd.uniform(0, 1)
                add([box(x, h / 2, z, 0.07, h, 0.07, (0.2, 0.5, 0.15), 0.1, 0.0, 0.0),
                     box(x, h, z, 0.6, 0.06, 0.22, petal, 0.45, yaw, 0.0), box(x, h, z, 0.22, 0.06, 0.6, petal, 0.45, yaw, 0.0),
                     box(x, h + 0.04, z, 0.2, 0.08, 0.2, middle, 0.7, yaw, 0.0)], x, z)
            elif kind < 0.95:  # small fern
                add([box(x + math.cos(a) * 0.7, 0.4, z - math.sin(a) * 0.7, 1.6, 0.05, 0.34, (0.22, 0.55, 0.18), 0.12, a, EDGE, 0, 0, 0.45)
                     for a in (k / 6 * math.tau for k in range(6))], x, z)
            else:  # a toadstool
                s = rnd.uniform(0.6, 1.0)
                add([box(x, 0.5 * s, z, 0.28 * s, 1.0 * s, 0.28 * s, (0.95, 0.93, 0.85), 0.2, 0.0, EDGE),
                     box(x, 1.05 * s, z, 1.1 * s, 0.38 * s, 1.1 * s, (0.9, 0.12, 0.08), 0.35, 0.3, EDGE),
                     box(x, 1.26 * s, z, 0.3 * s, 0.06, 0.3 * s, WHITE, 0.4, 0.0, 0.0)], x, z)
        return out, anchors

    def _visible_cover(self):
        """The clearing plants that are not under a platform (recomputed only when the layout changes)."""
        key = tuple(tuple(round(v, 1) for v in p_) for p_ in self.platforms)
        if key != self._plat_key:
            self._plat_key = key
            keep = np.ones(len(self.inner_xz), dtype=bool)
            for cx, cz, hw, hd in self.platforms:
                keep &= ~((np.abs(self.inner_xz[:, 0] - cx) < hw) & (np.abs(self.inner_xz[:, 1] - cz) < hd))
            self._inner_vis = self.inner[keep]
        return self._inner_vis

    # ---------- interaction ----------
    def centre(self, d):
        if d.flyer:
            return d.x, d.y, d.z
        return d.x, d.y + d.pick_h * d.sc, d.z

    def pick(self, origin, direction):
        best, bi = 1e9, None
        for d in self.dinos:
            cx, cy, cz = self.centre(d)
            rx, ry, rz = origin[0] - cx, origin[1] - cy, origin[2] - cz
            b = rx * direction[0] + ry * direction[1] + rz * direction[2]
            c = rx * rx + ry * ry + rz * rz - (d.pick_r * d.sc) ** 2
            disc = b * b - c
            if disc >= 0:
                t = -b - math.sqrt(disc)
                if 0 < t < best:
                    best, bi = t, d.i
        return bi

    def poke(self, i, t):
        d = self.dinos[i]
        d.roar_t0, d.look_goal, d.look_t = t, 0.0, t
        self.rings.append([d.x, d.z, t, 0.0])
        if d.kind == "frog":  # a big startled leap away
            a = d.heading + math.pi + self.rnd.uniform(-0.6, 0.6)
            self._start_hop(d, t, d.x + math.cos(a) * 13, d.z - math.sin(a) * 13, 5.5, 0.9)
        elif d.kind == "ladybug":
            d.fly_until = t + 3.4
            d.idle = 0.0
        elif d.kind == "butterfly":
            d.flee_until = t + 2.5
            d.target = (d.x + self.rnd.uniform(-8, 8), d.y + 9, d.z + self.rnd.uniform(-8, 8))
        else:  # beetles rear up and stand their ground
            d.idle = max(d.idle, 1.8)
            d.moving = False
        for k in range(8):  # a puff of leaves / pollen
            self.dust.append([d.x, d.y + 1, d.z, self.rnd.uniform(-3, 3), self.rnd.uniform(1, 4), self.rnd.uniform(-3, 3), 0.9])
        for o in self.dinos:  # neighbours scatter
            if o is not d and o.kind in ("ladybug", "butterfly") and math.hypot(o.x - d.x, o.z - d.z) < 14:
                o.flee_until = t + 1.5
                if o.kind == "butterfly":
                    o.target = (o.x + self.rnd.uniform(-10, 10), o.y + 5, o.z + self.rnd.uniform(-10, 10))
        return d

    def feed(self, x, z, t):
        """Drop berries: the nearest bug, frog or butterfly comes over to eat them."""
        bait = {"x": x, "z": z, "kind": "berries", "t0": t}
        cands = [d for d in self.dinos if d.eats and d.bait is None and math.hypot(d.x - x, d.z - z) < 120]
        self.baits.append(bait)
        if not cands:
            return None
        d = min(cands, key=lambda d: math.hypot(d.x - x, d.z - z))
        d.bait, d.target, d.idle, d.flee_until = bait, (x, z) if not d.flyer else (x, 1.4, z), 0.0, 0.0
        return d

    # ---------- simulation ----------
    def _blocked(self, x, z, world, r):
        for cx, cz, cr in world["circles"]:
            if math.hypot(x - cx, z - cz) < cr + r:
                return True
        for cx, cz, hw, hd in world["rects"]:
            if abs(x - cx) < hw + r and abs(z - cz) < hd + r:
                return True
        return any(math.hypot(x - tx, z - tz) < tr + r for tx, tz, tr in self.trees)

    def _pick(self, d, world):
        rmin, rmax = world["bounds"]
        for _ in range(16):
            if d.kind == "frog":  # frogs stay near the pond
                a, rad = self.rnd.uniform(0, math.tau), POND[2] + self.rnd.uniform(3, 20)
                x, z = POND[0] + math.sin(a) * rad, POND[1] + math.cos(a) * rad
            else:
                a, rad = self.rnd.uniform(0, math.tau), self.rnd.uniform(rmin, rmax)
                x, z = math.sin(a) * rad, math.cos(a) * rad
            if not self._blocked(x, z, world, d.radius + 1):
                return (x, z)
        return (d.x, d.z)

    def _start_hop(self, d, t, tx, tz, h=1.6, dur=0.55):
        d.heading = math.atan2(-(tz - d.z), tx - d.x)
        d.hop = {"t0": t, "x0": d.x, "z0": d.z, "x1": tx, "z1": tz, "h": h, "dur": dur}

    def _step_frog(self, d, t, dt, world):
        if d.hop:
            hp = d.hop
            u = (t - hp["t0"]) / hp["dur"]
            if u >= 1:
                d.x, d.z, d.y, d.hop = hp["x1"], hp["z1"], 0.0, None
                d.idle = self.rnd.uniform(0.4, 2.6)
                d.air = 0.0
                return
            d.x = hp["x0"] + (hp["x1"] - hp["x0"]) * u
            d.z = hp["z0"] + (hp["z1"] - hp["z0"]) * u
            d.y = 4 * hp["h"] * u * (1 - u)
            d.air = min(1.0, u / 0.15) if u < 0.75 else max(0.0, 1 - (u - 0.75) / 0.25)  # legs extend at take-off, tuck to land
            return
        d.air = 0.0
        if d.bait and d.bait not in self.baits:
            d.bait = None
        if d.eat_until > t:
            return
        if d.bait and math.hypot(d.x - d.bait["x"], d.z - d.bait["z"]) < 2.5:
            d.eat_until = t + 2.4
            self.baits = [b for b in self.baits if b is not d.bait]
            d.bait, d.target = None, None
            return
        if d.idle > 0:
            d.idle -= dt
            return
        if d.target is None or (not d.bait and self._blocked(*d.target, world, d.radius)):
            d.target = self._pick(d, world)
        dx, dz = d.target[0] - d.x, d.target[1] - d.z
        dist = math.hypot(dx, dz)
        if dist < 1.5:
            d.target, d.idle = None, self.rnd.uniform(0.5, 3.0)
            return
        step = min(dist, self.rnd.uniform(5.0, 7.5))
        tx, tz = d.x + dx / dist * step, d.z + dz / dist * step
        if self._blocked(tx, tz, world, d.radius) and not d.bait:
            d.target = None
            return
        self._start_hop(d, t, tx, tz, self.rnd.uniform(1.8, 2.6), self.rnd.uniform(0.5, 0.65))

    def _step_walker(self, d, t, dt, world):
        if d.kind == "ladybug" and t < d.fly_until:  # a short flight in a loop, then land
            u = 1 - (d.fly_until - t) / 3.4
            d.y = 3.5 * math.sin(math.pi * min(u, 1.0)) ** 0.7
            d.heading += dt * 1.6
            d.x += math.cos(d.heading) * 4.5 * dt
            d.z -= math.sin(d.heading) * 4.5 * dt
            d.open = min(1.0, u / 0.12, (1 - u) / 0.12)
            d.mv *= 0.9
            return
        d.y, d.open = 0.0, 0.0
        d.look += (d.look_goal - d.look) * min(1.0, dt * 4)
        if d.bait and d.bait not in self.baits:
            d.bait = None
        if d.eat_until > t:
            d.mv += (0 - d.mv) * min(1.0, dt * 4)
            return
        if d.bait and math.hypot(d.x - d.bait["x"], d.z - d.bait["z"]) < 2.0 + d.radius * 0.3:
            d.eat_until = t + 3.0
            self.baits = [b for b in self.baits if b is not d.bait]
            d.bait, d.target = None, None
            return
        if d.idle > 0 and d.flee_until <= t:
            d.idle -= dt
            d.mv += (0 - d.mv) * min(1.0, dt * 4)
            if self.rnd.random() < dt * 0.3:
                d.look_goal, d.look_t = self.rnd.uniform(-0.5, 0.5), t
            return
        fleeing = d.flee_until > t
        if d.target is None or (not d.bait and self._blocked(*d.target, world, d.radius)):
            d.target = self._pick(d, world)
        if fleeing:
            d.target = (d.x + math.cos(d.heading) * 20, d.z - math.sin(d.heading) * 20)
        dx, dz = d.target[0] - d.x, d.target[1] - d.z
        dist = math.hypot(dx, dz)
        if dist < 2.0 and not d.bait:
            d.target, d.idle = None, (self.rnd.uniform(1.0, 4.0) if self.rnd.random() < 0.6 else 0.0)
            return
        want = math.atan2(-dz, dx)
        diff = (want - d.heading + math.pi) % math.tau - math.pi
        d.heading += max(-1.6 * dt, min(1.6 * dt, diff))
        spd = d.speed * (1.8 if fleeing else (1.3 if d.bait else 1.0))
        if abs(diff) < 1.3:
            d.x += math.cos(d.heading) * spd * dt
            d.z -= math.sin(d.heading) * spd * dt
            d.phase += spd * dt * 0.55
            d.mv += (1 - d.mv) * min(1.0, dt * 5)
        else:  # turning on the spot: the legs still shuffle
            d.phase += dt * 0.6
            d.mv += (0.6 - d.mv) * min(1.0, dt * 5)
        for cx, cz, cr in list(world["circles"]) + self.trees:
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

    def _step_butterfly(self, d, t, dt, world):
        if d.bait and d.bait not in self.baits:
            d.bait = None
        eating = d.eat_until > t
        if eating:  # sipping on the berries: hover low, drifting a little
            d.vx *= 0.9
            d.vz *= 0.9
            d.y += (1.3 + 0.15 * math.sin(t * 2) - d.y) * min(1.0, dt * 3)
            return
        if d.bait:
            tx, ty, tz = d.bait["x"], 1.4, d.bait["z"]
            if math.dist((d.x, d.y, d.z), (tx, ty, tz)) < 2.4:
                d.eat_until = t + 4.0
                self.baits = [b for b in self.baits if b is not d.bait]
                d.bait, d.target = None, None
                return
            d.target = (tx, ty, tz)
        elif d.target is None or math.dist((d.x, d.y, d.z), d.target) < 2.5 or self.rnd.random() < dt * 0.08:
            rmin, rmax = world["bounds"]
            a, rad = self.rnd.uniform(0, math.tau), self.rnd.uniform(max(18.0, rmin - 20), rmax)
            d.target = (math.sin(a) * rad, self.rnd.uniform(2.5, 8.5), math.cos(a) * rad)
        tx, ty, tz = d.target
        dx, dy, dz = tx - d.x, ty - d.y, tz - d.z
        dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
        spd = d.speed * (2.2 if d.flee_until > t else 1.0)
        k = min(1.0, dt * 1.4)
        d.vx += (dx / dist * spd - d.vx) * k
        d.vy += (dy / dist * spd * 0.6 - d.vy) * k
        d.vz += (dz / dist * spd - d.vz) * k
        d.x += d.vx * dt
        d.z += d.vz * dt
        d.y = max(1.0, d.y + d.vy * dt + 0.9 * math.sin(t * 3.1 + d.seed) * dt * 2)  # the bobbing, erratic butterfly flight
        if abs(d.vx) + abs(d.vz) > 0.2:
            want = math.atan2(-d.vz, d.vx)
            diff = (want - d.heading + math.pi) % math.tau - math.pi
            d.heading += diff * min(1.0, dt * 5)

    def step(self, t, world):
        self.platforms = world.get("platforms", [(0.0, -70.0, 80.0, 95.0)])  # library / games: keep the clearing bare
        dt = 0.0 if self.last is None else min(max(t - self.last, 0.0), 0.1)
        self.last = t
        self.shake *= math.exp(-dt * 3.0)
        self.baits = [b for b in self.baits if t - b["t0"] < 40]
        self.rings = [r_ for r_ in self.rings if t - r_[2] < 1.2]
        for r_ in self.rings:
            r_[3] = 2 + (t - r_[2]) * 14
        for p in self.dust:
            p[0] += p[3] * dt
            p[1] = max(0.1, p[1] + p[4] * dt)
            p[2] += p[5] * dt
            p[4] -= 4 * dt
            p[6] -= dt
        self.dust = [p for p in self.dust if p[6] > 0]
        for d in self.dinos:
            if d.kind == "frog":
                self._step_frog(d, t, dt, world)
            elif d.kind == "butterfly":
                self._step_butterfly(d, t, dt, world)
            else:
                self._step_walker(d, t, dt, world)

    # ---------- drawing ----------
    def ambient(self, t, cam):
        """Falling leaves tumbling down and pollen drifting in the light, recycled around the camera."""
        out = []
        h = lambda i, k: (math.sin(i * 12.9898 + k * 78.233) * 43758.5453) % 1.0  # noqa: E731
        cols = [(0.85, 0.55, 0.12), (0.7, 0.35, 0.08), (0.55, 0.65, 0.15), (0.9, 0.75, 0.2)]
        for i in range(36):
            fall = 1.2 + h(i, 1) * 1.0
            period = 14.0 / fall
            u = ((t + h(i, 2) * period) % period) / period
            y = 14 * (1 - u)
            ang = t * (0.6 + h(i, 3)) + i
            x = cam[0] + (h(i, 4) - 0.5) * 120 + math.sin(ang) * 2.5
            z = cam[2] + (h(i, 5) - 0.5) * 120 + math.cos(ang * 0.7) * 2.5
            if math.dist((x, y, z), cam) < 10:
                continue
            out.append(box(x, y + 0.1, z, 0.55, 0.04, 0.38, cols[i % 4], 0.3, ang, 0.0, 0.0, 0.0, math.sin(ang * 1.7) * 0.9, math.cos(ang * 1.3) * 0.9))
        for i in range(60):  # pollen motes catching the sun
            x = cam[0] + (h(i, 6) - 0.5) * 80 + math.sin(t * 0.3 + i) * 3
            z = cam[2] + (h(i, 7) - 0.5) * 80 + math.cos(t * 0.25 + i * 1.3) * 3
            y = 1 + h(i, 8) * 7 + math.sin(t * 0.5 + i * 2) * 0.8
            tw = 0.5 + 0.5 * math.sin(t * 1.7 + i * 3)
            out.append(box(x, y, z, 0.12, 0.12, 0.12, (1.0, 0.95, 0.6), 0.4 + 1.2 * tw, 0.0, 0.0))
        return out

    def boxes(self, t, cam, r=None):
        if r is not None:
            r.add_boxes(self.static)  # the forest itself: one pre-built block
            if self.meshes is not None:
                self.meshes.draw(r, self.platforms)
            else:
                r.add_boxes(self._visible_cover())
        out = self.ambient(t, cam)
        for d in self.dinos:
            if math.hypot(d.x - cam[0], d.z - cam[2]) > 230:
                continue
            roar_u = (t - d.roar_t0) / 1.6
            roar = math.sin(math.pi * roar_u) ** 0.6 if 0 <= roar_u <= 1 else 0.0
            throat = 0.5 + 0.5 * math.sin(t * 5 + d.seed) if (d.kind == "frog" and d.hop is None and int(t * 0.4 + d.seed) % 3 == 0) else 0.0
            st = {"ph": d.phase, "mv": d.mv, "roar": roar, "look": d.look, "air": getattr(d, "air", 0.0), "throat": throat,
                  "open": getattr(d, "open", 0.0), "eat": d.eat_until > t}
            parts = RIGS[d.kind](d, t, st)
            c, s = math.cos(d.heading), math.sin(d.heading)
            sc = d.sc
            y0 = d.y
            models.creature_parts(r, [box(d.x + (x * c + z * s) * sc, y0 + y * sc, d.z + (-x * s + z * c) * sc, sx * sc, sy * sc, sz * sc, col, glow,
                                          d.heading + yl, EDGE, 0.0, 0.0, rz, rx) for (x, y, z, sx, sy, sz, col, glow, rz, rx, yl) in parts], out)
            if r is not None and not d.flyer:  # soft contact shadow (smaller and fainter while airborne)
                k = 1.0 / (1.0 + d.y * 0.6)
                ln = 2.6 * sc * (1.2 if d.kind == "frog" else 1.0)
                m = (_mx.translate(d.x, 0.03, d.z) @ _mx.rot_y(d.heading) @ _mx.rot_x(math.pi / 2) @ _mx.translate(-ln / 2, -ln / 3, 0) @ _mx.scale(ln, ln / 1.5, 1))
                r.quad3d(r.white, m, (0, 0, 0, 0.32 * k))
        for b in self.baits:  # berries: a little heap of red and blue
            for k in range(7):
                a = k * 0.9 + b["x"]
                rr = 0.35 if k else 0.0
                col = (0.85, 0.1, 0.15) if k % 2 else (0.25, 0.2, 0.75)
                out.append(box(b["x"] + math.cos(a) * rr, 0.25 + (0.25 if k == 0 else 0), b["z"] + math.sin(a) * rr, 0.38, 0.38, 0.38, col, 0.9, a))
            out.append(box(b["x"] + 0.2, 0.6, b["z"], 0.5, 0.05, 0.25, (0.25, 0.55, 0.15), 0.2, 0.4))
        for x, y, z, vx, vy, vz, life in self.dust:
            out.append(box(x, y, z, 0.3, 0.05, 0.22, (0.75, 0.6, 0.2), 0.6, life * 9, 0.0, 0.0, 0.0, life * 7, life * 5))
        for x, z, t0, rad in self.rings:  # ripples on the ground where something was poked
            fade = 1 - (t - t0) / 1.2
            for k in range(18):
                a = k * math.tau / 18
                out.append(box(x + math.cos(a) * rad, 0.1, z + math.sin(a) * rad, 1.0 * fade + 0.2, 0.08, 0.35, (0.8, 1.0, 0.5), 1.0 * fade, -a, 0.0))
        return out


from . import mathx as _mx  # noqa: E402
