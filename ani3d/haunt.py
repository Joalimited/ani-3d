"""Halloween theme: a haunted graveyard you can poke, feed and follow - the same idea as the Jurassic herd.

Ghosts drift and BOO, skeletons march and fall to pieces when poked, zombies shamble toward the candy you drop, black cats
arch their backs, a witch loops overhead on her broom and spiders drop out of the dark on silk threads. Static dressing
(gravestones, dead trees, a haunted house with flickering windows, a huge moon) is built once and reused every frame.

The public surface mirrors dinos.Herd (dinos / pick / poke / feed / step / boxes / shake) so the app drives both the same way.
"""
import math
import random

from . import mathx, models
from .scene import box

BONE, DARK, GREEN, SHEET = (0.92, 0.9, 0.8), (0.03, 0.02, 0.04), (0.45, 0.62, 0.35), (0.93, 0.95, 1.0)
PURPLE, ORANGE = (0.55, 0.2, 0.85), (1.0, 0.5, 0.05)
EDGE = 0.35
SCALE = 1.35

# kind -> (name, trait, height, haunting since, fact, speed, avoid radius, pick centre height, pick radius, eats, verb)
SPECIES = {
    "ghost": ("Ghost", "Ectoplasm", "1.8 m", "1692", "Passes through walls but never quite through the cat.", 3.4, 3.5, 5.0, 4.6, None, "wails BOOOO"),
    "skeleton": ("Skeleton", "Calcium", "1.7 m", "1349", "Rattles at 120 bones per minute and has no sense of rhythm.", 3.6, 3.0, 3.8, 3.6, "candy", "rattles"),
    "zombie": ("Zombie", "Brains (candy will do)", "1.8 m", "1968", "Groans in a major key; walks toward anything shiny.", 2.2, 3.2, 3.8, 3.6, "candy", "groans"),
    "cat": ("Black Cat", "Mice and spite", "0.3 m", "1590", "Crossed your path on purpose.", 5.5, 1.8, 1.2, 2.2, "candy", "hisses"),
    "witch": ("Witch", "Eye of newt", "1.6 m", "1692", "Her broom does 140 km/h and is not street legal.", 0.0, 0.0, 0.0, 4.5, None, "cackles"),
    "spider": ("Giant Spider", "Flies, mostly", "0.6 m", "-", "Eight legs, zero patience, one very long thread.", 0.0, 0.0, 0.0, 3.0, None, "skitters"),
}
KINDS = ["ghost", "ghost", "ghost", "skeleton", "skeleton", "skeleton", "zombie", "zombie", "cat", "cat", "witch", "spider", "spider", "spider"]


class Creature:
    def __init__(self, kind, i, rnd):
        self.kind, self.i = kind, i
        sp = SPECIES[kind]
        self.name, self.diet, self.length, self.era, self.fact = sp[0], sp[1], sp[2], sp[3], sp[4]
        self.speed, self.radius, self.pick_h, self.pick_r, self.eats, self.verb = sp[5], sp[6], sp[7], sp[8], sp[9], sp[10]
        self.flyer = kind in ("ghost", "witch", "spider")
        self.x, self.z, self.y = rnd.uniform(-70, 70), rnd.uniform(-70, 70), 0.0
        self.heading, self.phase, self.mv, self.turn = rnd.uniform(0, 6.28), rnd.uniform(0, 6), 0.0, 0.0
        self.target, self.idle, self.moving = None, rnd.uniform(0, 3), False
        self.roar_t0, self.look, self.look_goal, self.look_t = -9.0, 0.0, 0.0, 0.0
        self.eat_until, self.bait, self.flee_until = 0.0, None, 0.0
        self.seed = rnd.random() * 100
        self.pal = rnd.choice([(0.9, 0.9, 1.0), (0.8, 1.0, 0.9), (1.0, 0.9, 0.95)]) if kind == "ghost" else None
        if kind == "ghost":
            self.alt = rnd.uniform(3.5, 9)
            self.y = self.alt
        if kind == "witch":
            self.cx, self.cz = rnd.uniform(-20, 20), rnd.uniform(-20, 20)
            self.rad, self.w, self.a = rnd.uniform(40, 70), rnd.choice((-1, 1)) * 0.3, rnd.uniform(0, 6.28)
            self.alt = rnd.uniform(16, 24)
            self.y = self.alt
        if kind == "spider":
            ang, rad = rnd.uniform(0, 6.28), rnd.uniform(25, 85)
            self.x, self.z = math.sin(ang) * rad, math.cos(ang) * rad
            self.alt = rnd.uniform(8, 13)
            self.y = self.alt


def _seg(out, x, y, z, length, ang, th, wid, col, glow=0.2, yl=0.0):
    """A bone from (x,y,z) pointing `ang` up from forward (local frame). Returns the end point."""
    ca, sa = math.cos(ang), math.sin(ang)
    out.append((x + ca * length / 2, y + sa * length / 2, z, length, th, wid, col, glow, ang, 0.0, yl))
    return x + ca * length, y + sa * length, z


# ------------------------------------------------------------ rigs: local frame, +x forward, +z side
def rig_skeleton(d, t, st):
    ph, mv, c = st["ph"], st["mv"], st["collapse"]
    P = []
    hy = 2.6 + 0.08 * abs(math.sin(ph)) * mv
    for k, sz in enumerate((-1, 1)):
        s = math.sin(ph + k * math.pi) * 0.7 * mv
        kx, ky, kz = _seg(P, 0, hy, sz * 0.3, 1.15, -math.pi / 2 + s, 0.26, 0.26, BONE)
        _seg(P, kx, ky, kz, 1.15, -math.pi / 2 - max(0, -s) * 0.9, 0.22, 0.22, BONE)
        P.append((kx + 0.25, 0.1, kz, 0.6, 0.18, 0.28, BONE, 0.2, 0, 0, 0))
        ax, ay, az = _seg(P, 0, hy + 1.65, sz * 0.62, 1.0, -math.pi / 2 - s * 0.9, 0.2, 0.2, BONE)
        _seg(P, ax, ay, az, 0.9, -math.pi / 2 - s * 0.9 + 0.3, 0.17, 0.17, BONE)
    P.append((0, hy + 0.15, 0, 0.5, 0.35, 0.9, BONE, 0.25, 0, 0, 0))  # pelvis
    P.append((0, hy + 0.9, 0, 0.18, 1.5, 0.18, BONE, 0.25, 0, 0, 0))  # spine
    for k in range(3):  # ribs
        P.append((0, hy + 0.9 + k * 0.42, 0, 0.55 - k * 0.06, 0.12, 1.0 - k * 0.1, BONE, 0.3, 0, 0, 0))
    P.append((0.1, hy + 2.25, 0, 0.95, 0.85, 0.85, BONE, 0.4, 0, 0, st["look"]))  # skull
    P.append((0.55, hy + 2.35, -0.22, 0.12, 0.22, 0.22, DARK, 0.0, 0, 0, 0))
    P.append((0.55, hy + 2.35, 0.22, 0.12, 0.22, 0.22, DARK, 0.0, 0, 0, 0))
    jaw = 0.12 + 0.5 * st["roar"] + 0.08 * math.sin(t * 9) * mv
    P.append((0.35, hy + 1.8 - jaw * 0.5, 0, 0.55, 0.2, 0.6, BONE, 0.3, -jaw, 0, 0))
    if c > 0:  # fall apart: every part slides toward a pile on the ground
        out = []
        for n, (x, y, z, sx, sy, sz, col, gl, rz, rx, yl) in enumerate(P):
            r_ = random.Random(int(d.seed * 100) + n)
            out.append((x * (1 - c) + r_.uniform(-1.6, 1.6) * c, max(y * (1 - c) + 0.2 * c, 0.15), z * (1 - c) + r_.uniform(-1.6, 1.6) * c, sx, sy, sz, col, gl, rz + r_.uniform(-2, 2) * c, rx, yl + r_.uniform(-1.5, 1.5) * c))
        return out
    return P


def rig_zombie(d, t, st):
    ph, mv = st["ph"], st["mv"]
    P = []
    hy = 2.5 + 0.06 * abs(math.sin(ph)) * mv
    lean = 0.18
    for k, sz in enumerate((-1, 1)):
        s = math.sin(ph * 0.8 + k * math.pi) * 0.5 * mv
        kx, ky, kz = _seg(P, 0, hy, sz * 0.32, 1.2, -math.pi / 2 + s, 0.4, 0.4, (0.25, 0.28, 0.45))
        _seg(P, kx, ky, kz, 1.15, -math.pi / 2 - max(0, -s) * 0.6, 0.36, 0.36, (0.25, 0.28, 0.45))
        P.append((kx + 0.2, 0.1, kz, 0.7, 0.2, 0.38, (0.1, 0.08, 0.06), 0.1, 0, 0, 0))
        ax, ay, az = _seg(P, 0.15, hy + 1.8, sz * 0.75, 1.0, 0.05 + 0.1 * math.sin(t * 2 + k), 0.3, 0.3, GREEN)  # arms stretched out
        _seg(P, ax, ay, az, 0.9, 0.0 + 0.1 * math.sin(t * 2.4 + k), 0.26, 0.26, GREEN)
    P.append((0, hy + 1.1, 0, 0.8, 1.8, 1.2, (0.55, 0.15, 0.15), 0.2, -lean, 0, 0))  # torn shirt
    P.append((0.1, hy + 2.4, 0, 0.95, 0.9, 0.9, GREEN, 0.3, -lean, 0, st["look"]))
    P.append((0.6, hy + 2.55, -0.25, 0.12, 0.2, 0.2, (1, 1, 0.6), 0.9, 0, 0, 0))
    P.append((0.6, hy + 2.55, 0.25, 0.12, 0.2, 0.2, (1, 1, 0.6), 0.9, 0, 0, 0))
    P.append((0.55, hy + 2.1, 0, 0.12, 0.2, 0.55, DARK, 0.0, 0, 0, 0))
    for k in (-1, 0, 1):
        P.append((-0.1, hy + 2.95, k * 0.3, 0.2, 0.3, 0.2, (0.15, 0.1, 0.05), 0.1, 0.4 * k, 0, 0))
    return P


def rig_ghost(d, t, st):
    P = []
    bob = 0.35 * math.sin(t * 1.7 + d.seed)
    b = st["roar"]
    h = 1.0 + 0.5 * b
    col = d.pal
    for k in range(4):  # the sheet body: wider toward the hem
        w = 1.3 + k * 0.28 + 0.5 * b
        P.append((0, bob + 3.3 - k * 0.8 * h, 0, w, 0.9 * h, w, col, 0.8, 0, 0, 0))
    for k in range(6):  # a wavy hem
        a = k / 6 * math.tau
        P.append((math.cos(a) * 1.0, bob + 0.2 + 0.25 * math.sin(t * 5 + k * 1.3), math.sin(a) * 1.0, 0.7, 0.55, 0.7, col, 0.8, 0, 0, 0))
    P.append((0, bob + 4.0, 0, 1.4, 1.1, 1.4, col, 0.9, 0, 0, st["look"]))
    P.append((0.7, bob + 4.2, -0.35, 0.14, 0.4 + 0.5 * b, 0.28, DARK, 0.0, 0, 0, 0))
    P.append((0.7, bob + 4.2, 0.35, 0.14, 0.4 + 0.5 * b, 0.28, DARK, 0.0, 0, 0, 0))
    P.append((0.72, bob + 3.6, 0, 0.14, 0.25 + 0.8 * b, 0.4 + 0.5 * b, DARK, 0.0, 0, 0, 0))
    for sz in (-1, 1):  # arms: dangling, or up when it booos
        ang = -1.3 + b * 2.3 + 0.15 * math.sin(t * 2 + sz)
        _seg(P, 0, bob + 3.2, sz * (1.0 + 0.4 * b), 1.5, ang, 0.35, 0.35, col, 0.7)
    return P


def rig_cat(d, t, st):
    P = []
    ph, mv, r = st["ph"], st["mv"], st["roar"]
    arch = 0.5 * r
    hy = 0.9 + 0.35 * r
    P.append((0, hy, 0, 1.5 - 0.3 * r, 0.7 + 0.25 * r, 0.65, DARK, 0.25, arch, 0, 0))
    P.append((0.95, hy + 0.2 + 0.2 * r, 0, 0.7, 0.62, 0.65, DARK, 0.25, 0, 0, st["look"]))
    for sz in (-1, 1):
        P.append((1.05, hy + 0.62 + 0.2 * r, sz * 0.22, 0.14, 0.3, 0.18, DARK, 0.35, 0, 0, 0))  # ears
        P.append((1.3, hy + 0.35 + 0.2 * r, sz * 0.18, 0.1, 0.16, 0.16, (1.0, 0.9, 0.2), 1.6, 0, 0, 0))  # glowing eyes
    for k, sx in enumerate((0.55, 0.55, -0.55, -0.55)):
        sz = (-1, 1)[k % 2] * 0.22
        s = math.sin(ph * 1.6 + k * math.pi / 2) * 0.6 * mv
        _seg(P, sx, hy - 0.25, sz, 0.8, -math.pi / 2 + s, 0.2, 0.2, DARK, 0.2)
    x, y = -0.7, hy + 0.1
    ang = 0.4 + 0.9 * r
    for k in range(5):
        sway = 0.25 * math.sin(t * 3 - k * 0.7)
        x, y, _ = _seg(P, x, y, 0, 0.5, math.pi - ang * (1 - k * 0.1) + sway * 0 + 0.1 * k, 0.2 + 0.1 * r, 0.2 + 0.1 * r, DARK, 0.2)
    return P


def rig_witch(d, t, st):
    P = []
    ang = -0.05 + 0.05 * math.sin(t * 2)
    _seg(P, -2.2, 0, 0, 4.4, ang, 0.18, 0.18, (0.45, 0.28, 0.12), 0.3)  # broom handle
    for k in range(7):  # bristles
        P.append((-2.4 - k * 0.12, 0.0 + 0.02 * k, (k - 3) * 0.1, 0.9, 0.08, 0.08, (0.8, 0.6, 0.2), 0.35, 0.0, 0, 0))
    P.append((0.2, 1.0, 0, 1.1, 1.3, 1.0, (0.12, 0.05, 0.18), 0.3, 0, 0, 0))  # robe
    P.append((0.2, 0.7, 0, 1.4, 0.8, 1.2, (0.12, 0.05, 0.18), 0.3, 0, 0, 0))
    P.append((0.25, 1.95, 0, 0.8, 0.8, 0.8, (0.55, 0.85, 0.4), 0.4, 0, 0, 0))  # face
    P.append((0.7, 1.9, 0, 0.3, 0.2, 0.18, (0.45, 0.75, 0.3), 0.4, -0.2, 0, 0))  # nose
    P.append((0.25, 2.4, 0, 1.6, 0.14, 1.6, (0.07, 0.03, 0.1), 0.3, 0, 0, 0))  # hat brim
    P.append((0.2, 2.8, 0, 0.9, 0.8, 0.9, (0.07, 0.03, 0.1), 0.3, 0, 0, 0))
    P.append((0.1, 3.4, 0, 0.5, 0.7, 0.5, (0.07, 0.03, 0.1), 0.3, -0.25, 0, 0))
    P.append((0.35, 2.55, 0, 1.65, 0.1, 1.65, (0.9, 0.5, 0.1), 0.9, 0, 0, 0))  # hat band
    P.append((-0.4, 1.2, 0.8, 0.8, 0.2, 0.2, (0.55, 0.85, 0.4), 0.3, 0.2, 0, 0))  # arm on the broom
    return P


def _limb(p0, p1, th, col, glow=0.15):
    """A box joining two points of the local frame (a leg segment): rotated so its long (y) axis runs p0 -> p1.
    The shader applies rollz, then rollx, so dir = (-sin rz, cos rz cos rx, cos rz sin rx)."""
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    ln = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
    rz = -math.asin(max(-1.0, min(1.0, dx / ln)))
    rx = math.atan2(dz / ln, dy / ln)
    return ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2, th, ln + th * 0.6, th, col, glow, rz, rx, 0.0)


SPIDER_BODY = (0.08, 0.06, 0.10)
SPIDER_SHEEN = (0.20, 0.14, 0.24)
SPIDER_LEG = (0.11, 0.08, 0.12)
SPIDER_JOINT = (0.55, 0.20, 0.06)
SPIDER_EYE = (1.0, 0.12, 0.08)
SPIDER_SPINNERET = (-1.85, 0.45, 0.0)  # where the silk leaves the abdomen (the thread is drawn from here)


def rig_spider(d, t, st):
    """A dangling spider: cephalothorax + round abdomen, eight jointed three-part legs that paddle at the air
    (and flail when it is poked), eight eyes, fangs and palps."""
    P = []
    r = st["roar"]
    for k, spread in enumerate((0.95, 0.38, -0.22, -0.82)):  # front -> back pair, angle from the side axis toward +x
        for sz in (-1, 1):
            ph = t * (4.5 + 6 * r) + k * math.pi / 2 + (math.pi if sz > 0 else 0) + d.seed
            a = spread + (0.16 + 0.25 * r) * math.sin(ph)  # paddle forward / back
            lift = (0.18 + 0.35 * r) * max(0.0, math.sin(ph + 0.6))
            curl = 0.25 * (1 - r) * (0.5 + 0.5 * math.sin(t * 0.7 + k + d.seed))  # idle legs slowly draw in
            hx, hz = math.sin(a), math.cos(a) * sz
            sock = (0.62 - k * 0.27, 0.18, sz * 0.36)
            knee = (sock[0] + hx * 1.05, sock[1] + 0.8 + lift, sock[2] + hz * 1.05)
            ankle = (knee[0] + hx * (1.0 - curl * 0.6), knee[1] - 0.55 - curl * 0.4, knee[2] + hz * (1.0 - curl * 0.6))
            foot = (ankle[0] + hx * (0.45 - curl * 0.4), ankle[1] - 0.95 + curl * 0.3, ankle[2] + hz * (0.45 - curl * 0.4))
            P.append(_limb(sock, knee, 0.15, SPIDER_LEG))
            P.append(_limb(knee, ankle, 0.12, SPIDER_LEG))
            P.append(_limb(ankle, foot, 0.085, SPIDER_SHEEN, 0.25))
            for j, jt in ((knee, 0.19), (ankle, 0.15)):  # knuckles hide the seams and catch a little orange light
                P.append((j[0], j[1], j[2], jt, jt, jt, SPIDER_JOINT, 0.45 + 0.5 * r, 0.0, 0.0, 0.0))
    # cephalothorax and head
    P.append((0.42, 0.18, 0, 1.05, 0.55, 0.9, SPIDER_BODY, 0.25, 0, 0, 0))
    P.append((0.42, 0.48, 0, 0.8, 0.14, 0.66, SPIDER_SHEEN, 0.3, 0, 0, 0))  # carapace plate
    P.append((1.02, 0.24, 0, 0.42, 0.46, 0.62, SPIDER_BODY, 0.25, 0, 0, 0))
    # eyes: two big glowing ones in front, six small around them
    pulse = 1.5 + 0.4 * math.sin(t * 3 + d.seed) + 1.2 * r
    for sz in (-1, 1):
        P.append((1.24, 0.34, sz * 0.13, 0.15, 0.15, 0.15, SPIDER_EYE, pulse, 0, 0, 0))
        P.append((1.2, 0.43, sz * 0.27, 0.08, 0.08, 0.08, SPIDER_EYE, pulse * 0.7, 0, 0, 0))
        P.append((1.12, 0.47, sz * 0.07, 0.07, 0.07, 0.07, SPIDER_EYE, pulse * 0.7, 0, 0, 0))
        P.append((1.08, 0.42, sz * 0.36, 0.06, 0.06, 0.06, SPIDER_EYE, pulse * 0.6, 0, 0, 0))
        # fangs (open wider when poked) and the little palps beside them
        P.append(_limb((1.22, 0.1, sz * 0.12), (1.36, -0.22, sz * (0.1 + 0.1 * r)), 0.1, (0.30, 0.06, 0.06), 0.4))
        P.append(_limb((1.12, 0.12, sz * 0.28), (1.55, 0.02 + 0.08 * math.sin(t * 5 + sz), sz * 0.36), 0.08, SPIDER_LEG))
    # waist and a round abdomen (three overlapping boxes read as a rounded shape)
    P.append((-0.18, 0.24, 0, 0.32, 0.3, 0.34, SPIDER_LEG, 0.2, 0, 0, 0))
    breathe = 1.0 + 0.03 * math.sin(t * 2 + d.seed)
    P.append((-1.0, 0.42, 0, 1.55 * breathe, 1.0 * breathe, 1.2 * breathe, SPIDER_BODY, 0.25, 0, 0, 0))
    P.append((-1.0, 0.42, 0, 1.2, 1.28 * breathe, 0.95, SPIDER_BODY, 0.25, 0, 0, 0))
    P.append((-1.0, 0.42, 0, 1.8 * breathe, 0.72, 0.9, SPIDER_BODY, 0.25, 0, 0, 0))
    P.append((-1.0, 0.95 * breathe, 0, 1.1, 0.16, 0.8, SPIDER_SHEEN, 0.3, 0, 0, 0))  # glossy back
    # red hourglass on the back
    P.append((-0.78, 1.05 * breathe, 0, 0.3, 0.06, 0.32, SPIDER_EYE, 1.1, 0, 0, 0))
    P.append((-1.22, 1.05 * breathe, 0, 0.3, 0.06, 0.32, SPIDER_EYE, 1.1, 0, 0, 0))
    P.append((-1.0, 1.05 * breathe, 0, 0.22, 0.06, 0.12, SPIDER_EYE, 1.1, 0, 0, 0))
    P.append((SPIDER_SPINNERET[0] + 0.05, SPIDER_SPINNERET[1], 0, 0.22, 0.2, 0.22, SPIDER_SHEEN, 0.3, 0, 0, 0))
    return P


RIGS = {"skeleton": rig_skeleton, "zombie": rig_zombie, "ghost": rig_ghost, "cat": rig_cat, "witch": rig_witch, "spider": rig_spider}


class Haunt:
    def __init__(self, seed=13):
        self.rnd = random.Random(seed)
        self.dinos = [Creature(k, i, self.rnd) for i, k in enumerate(KINDS)]
        self.last = None
        self.baits, self.dust, self.rings = [], [], []  # candy, puffs [x,y,z,vx,vy,vz,life], shockwaves [x,z,t0,r]
        self.shake = 0.0
        self.meshes = None
        if models.available():  # Blender-made graveyard (tools/blender_models.py); the box-built one is the fallback
            self.meshes, self.static = self._mesh_scenery()
        else:
            self.static = self._scenery()

    # ---------- static dressing ----------
    def _mesh_scenery(self):
        """Same layout as _scenery (same seed and spots) with the Blender models. Returns (MeshSet, plain boxes)."""
        rnd = random.Random(99)
        M, out = models.MeshSet(), []
        for i in range(46):
            a, rad = rnd.uniform(0, math.tau), rnd.uniform(34, 150)
            x, z = math.sin(a) * rad, math.cos(a) * rad
            hgt = rnd.uniform(1.6, 3.4)
            yaw = rnd.uniform(-0.4, 0.4)
            name = "grave_round" if i % 3 == 0 else "grave_cross" if i % 5 == 0 else "grave_slab"
            M.put(name, x, 0, z, (1.0, hgt / 2.4, 1.0), yaw)
        for i in range(16):
            a, rad = rnd.uniform(0, math.tau), rnd.uniform(60, 190)
            hgt = rnd.uniform(9, 15)
            M.put("dead_tree_a" if i % 2 else "dead_tree_b", math.sin(a) * rad, 0, math.cos(a) * rad, hgt / 12, rnd.uniform(0, math.tau))
        for i in range(12):
            a = i / 12 * math.tau
            M.put("iron_fence", math.sin(a) * 38, 0, math.cos(a) * 38, 1.0, a)
        M.put("moon", 46, 62, -112, (30, 30, 30))
        out.append(box(46, 62, -113, 38, 38, 1, (0.45, 0.35, 0.6), 1.0, 0.0, 0.0, 0.0, 1.0))  # halo
        M.put("haunted_house", -40, 0, -150, 1.0)
        return M.freeze(), out

    def _scenery(self):
        rnd = random.Random(99)
        out = []
        for i in range(46):  # gravestones
            a, rad = rnd.uniform(0, math.tau), rnd.uniform(34, 150)
            x, z = math.sin(a) * rad, math.cos(a) * rad
            h = rnd.uniform(1.6, 3.4)
            yaw = rnd.uniform(-0.4, 0.4)
            stone = (0.38, 0.4, 0.46)
            out.append(box(x, h / 2, z, 1.5, h, 0.45, stone, 0.15, yaw, 0.5))
            if i % 3 == 0:
                out.append(box(x, h + 0.4, z, 1.0, 0.45, 0.4, stone, 0.15, yaw, 0.5))  # rounded top
            elif i % 5 == 0:
                out.append(box(x, h * 0.75, z, 1.9, 0.35, 0.4, stone, 0.15, yaw, 0.5))  # cross arm
            out.append(box(x, 0.12, z + 0.3, 1.8, 0.2, 2.2, (0.14, 0.1, 0.06), 0.05, yaw, 0.0))  # earth mound
        for i in range(16):  # dead trees: a trunk with forked branches
            a, rad = rnd.uniform(0, math.tau), rnd.uniform(60, 190)
            x, z = math.sin(a) * rad, math.cos(a) * rad
            h = rnd.uniform(9, 15)
            dark = (0.1, 0.07, 0.08)
            out.append(box(x, h / 2, z, 1.2, h, 1.2, dark, 0.1, 0.0, 0.3))
            for k in range(5):
                yy = h * (0.45 + 0.1 * k)
                side = 1 if k % 2 else -1
                out.append(box(x + side * 1.6, yy, z, 3.4, 0.35, 0.35, dark, 0.1, 0.0, 0.3, 0.0, 0.0, side * 0.5))
                out.append(box(x + side * 3.0, yy + 1.0, z, 1.8, 0.25, 0.25, dark, 0.1, 0.0, 0.3, 0.0, 0.0, side * 0.9))
        for i in range(12):  # iron fence posts around the yard
            a = i / 12 * math.tau
            x, z = math.sin(a) * 38, math.cos(a) * 38
            for k in range(-2, 3):
                out.append(box(x + math.cos(a) * k * 1.4, 1.4, z - math.sin(a) * k * 1.4, 0.18, 2.8, 0.18, (0.05, 0.05, 0.07), 0.2, a, 0.4))
            out.append(box(x, 2.4, z, 7.4, 0.15, 0.15, (0.05, 0.05, 0.07), 0.2, a, 0.4))
        # a big pale moon with a halo and craters (close enough that the fog does not swallow it)
        out.append(box(46, 62, -112, 30, 30, 2, (1.0, 0.96, 0.78), 1.8, 0.0, 0.0, 0.0, 1.0))
        out.append(box(46, 62, -113, 38, 38, 1, (0.45, 0.35, 0.6), 1.0, 0.0, 0.0, 0.0, 1.0))
        out.append(box(52, 66, -110, 6, 6, 1, (0.82, 0.78, 0.6), 1.0, 0.0, 0.0, 0.0, 1.0))
        out.append(box(40, 56, -110, 4.5, 4.5, 1, (0.82, 0.78, 0.6), 1.0, 0.0, 0.0, 0.0, 1.0))
        return out

    def house(self, t):
        """The haunted house on the hill: a dark silhouette whose windows flicker."""
        out = []
        hx, hz = -40, -150
        if self.meshes is not None:  # the model is the house; only the flickering lights are drawn here
            for i in range(5):
                on = math.sin(t * 6 + i * 2.7) + math.sin(t * 2.3 + i) > -0.7
                col = (1.0, 0.75, 0.2) if on else (0.12, 0.07, 0.05)
                out.append(box(hx - 14 + i * 7, 12 + (i % 2) * 6, hz + 10.25, 2.4, 3.4, 0.3, col, 1.8 if on else 0.1, 0.0, 0.0))
            out.append(box(hx + 16, 28, hz + 6.1, 2.2, 3.0, 0.3, (1.0, 0.8, 0.25), 1.8))
            out.append(box(hx, 2.9, hz + 10.35, 3.4, 5.8, 0.2, (0.04, 0.02, 0.03), 0.1, 0.0, 0.0))
            return out
        dark, roof = (0.08, 0.06, 0.1), (0.05, 0.03, 0.07)
        out.append(box(hx, 11, hz, 38, 22, 20, dark, 0.15, 0.0, 0.2))
        out.append(box(hx, 25, hz, 40, 6, 22, roof, 0.1, 0.0, 0.2, 0.0, 0.0, 0.0))
        out.append(box(hx - 10, 29, hz, 18, 6, 18, roof, 0.1, 0.0, 0.2))
        out.append(box(hx + 16, 18, hz + 2, 8, 34, 8, dark, 0.15, 0.0, 0.2))  # tower
        out.append(box(hx + 16, 38, hz + 2, 10, 6, 10, roof, 0.1, 0.0, 0.2))
        for i in range(5):  # windows (they blink like candles)
            on = math.sin(t * 6 + i * 2.7) + math.sin(t * 2.3 + i) > -0.7
            col = (1.0, 0.75, 0.2) if on else (0.12, 0.07, 0.05)
            out.append(box(hx - 14 + i * 7, 12 + (i % 2) * 6, hz + 10.2, 2.4, 3.4, 0.4, col, 1.8 if on else 0.1, 0.0, 0.0))
        out.append(box(hx + 16, 28, hz + 6.3, 2.2, 3.0, 0.4, (1.0, 0.8, 0.25), 1.8))
        out.append(box(hx, 3, hz + 10.2, 3.6, 6, 0.4, (0.04, 0.02, 0.03), 0.1, 0.0, 0.0))  # door
        return out

    # ---------- interaction ----------
    def centre(self, d):
        return (d.x, d.y if d.flyer else d.pick_h * SCALE, d.z)

    def pick(self, origin, direction):
        best, bi = 1e9, None
        for d in self.dinos:
            cx, cy, cz = self.centre(d)
            if d.kind == "spider":
                cy = d.y
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
        d = self.dinos[i]
        d.roar_t0, d.look_goal, d.look_t = t, 0.0, t
        d.idle = max(d.idle, 2.2)
        d.moving = False
        self.shake = max(self.shake, 0.55 if d.kind in ("ghost", "witch") else 0.25)
        self.rings.append([d.x, d.z, t, 0.0])
        for k in range(10):
            self.dust.append([d.x, d.y + 2, d.z, self.rnd.uniform(-4, 4), self.rnd.uniform(1, 6), self.rnd.uniform(-4, 4), 0.9])
        for o in self.dinos:  # everything nearby gets spooked by the noise
            if o is d or o.flyer:
                continue
            dist = math.hypot(o.x - d.x, o.z - d.z)
            if dist < 30 and o.kind in ("cat", "zombie"):
                o.flee_until = t + 2.5
                o.target = None
        return d

    def feed(self, x, z, t):
        """Drop candy: the nearest skeleton / zombie / cat walks over to eat it."""
        bait = {"x": x, "z": z, "kind": "candy", "t0": t}
        cands = [d for d in self.dinos if d.eats and d.bait is None and math.hypot(d.x - x, d.z - z) < 110]
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
            r_[3] = 3 + (t - r_[2]) * 24
        for p in self.dust:
            p[0] += p[3] * dt
            p[1] += p[4] * dt
            p[2] += p[5] * dt
            p[4] -= 5 * dt
            p[6] -= dt
        self.dust = [p for p in self.dust if p[6] > 0]
        for d in self.dinos:
            roar = t - d.roar_t0 < 1.7
            if d.kind == "witch":
                d.a += d.w * dt * (2.5 if roar else 1.0)
                d.x, d.z = d.cx + math.sin(d.a) * d.rad, d.cz + math.cos(d.a) * d.rad
                d.y = d.alt + math.sin(t * 0.9 + d.i) * 2.0 + (3 * math.sin(math.pi * (t - d.roar_t0) / 1.7) if roar else 0)
                d.heading = math.atan2(math.sin(d.a) * d.w * d.rad, math.cos(d.a) * d.w * d.rad)
                if self.rnd.random() < dt * 8:  # a trail of sparks
                    self.dust.append([d.x - math.cos(d.heading) * 3, d.y, d.z + math.sin(d.heading) * 3, self.rnd.uniform(-1, 1), self.rnd.uniform(0, 2), self.rnd.uniform(-1, 1), 0.8])
                continue
            if d.kind == "spider":  # drop out of the dark, then climb back up the thread
                drop = 4.5 * math.sin(math.pi * (t - d.roar_t0) / 1.7) if roar else 0.0
                d.y = d.alt - (3.2 + 3.0 * math.sin(t * 0.35 + d.seed)) - drop
                d.heading = d.seed + 0.7 * math.sin(t * 0.23 + d.seed) + (2.5 * math.sin(math.pi * (t - d.roar_t0) / 1.7) if roar else 0.0)  # twists on the silk
                continue
            d.look += (d.look_goal - d.look) * min(1.0, dt * 4)
            if t - d.look_t > 2.5:
                d.look_goal *= 0.97
            if d.kind == "ghost":
                d.y = d.alt + 0.6 * math.sin(t * 0.8 + d.seed)
            if d.bait and d.bait not in self.baits:
                d.bait = None
            if d.eat_until > t:
                d.moving = False
                d.mv += (0 - d.mv) * min(1.0, dt * 4)
                continue
            if d.bait and math.hypot(d.x - d.bait["x"], d.z - d.bait["z"]) < 3.0 + d.radius * 0.3:
                d.eat_until = t + 2.6
                d.idle = 0.0
                self.baits = [b for b in self.baits if b is not d.bait]
                d.bait, d.target = None, None
                continue
            if d.idle > 0 and d.flee_until <= t:
                d.idle -= dt
                d.moving = False
                d.mv += (0 - d.mv) * min(1.0, dt * 4)
                if self.rnd.random() < dt * 0.2:
                    d.look_goal, d.look_t = self.rnd.uniform(-0.6, 0.6), t
                continue
            fleeing = d.flee_until > t
            if d.target is None or (not d.bait and self._blocked(*d.target, world, d.radius)):
                d.target = self._pick(d, world)
            if fleeing:
                d.target = (d.x + math.cos(d.heading) * 30, d.z - math.sin(d.heading) * 30)
            dx, dz = d.target[0] - d.x, d.target[1] - d.z
            dist = math.hypot(dx, dz)
            if dist < 3.0 and not d.bait:
                d.target, d.idle, d.moving = None, self.rnd.uniform(1.0, 4.0) if self.rnd.random() < 0.6 else 0.0, False
                continue
            want = math.atan2(-dz, dx)
            diff = (want - d.heading + math.pi) % math.tau - math.pi
            d.heading += max(-1.4 * dt, min(1.4 * dt, diff))
            d.turn += (max(-0.5, min(0.5, diff)) - d.turn) * min(1.0, dt * 3)
            spd = d.speed * (1.8 if fleeing else (1.3 if d.bait else 1.0))
            if abs(diff) < 1.2:
                d.x += math.cos(d.heading) * spd * dt
                d.z += -math.sin(d.heading) * spd * dt
                d.phase += spd * dt * 0.8
                d.moving = True
                d.mv += (1 - d.mv) * min(1.0, dt * 4)
            else:
                d.mv += (0 - d.mv) * min(1.0, dt * 4)
            for cx, cz, cr in world["circles"]:
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
        out = list(self.static) + self.house(t)
        if self.meshes is not None and r is not None:
            self.meshes.draw(r)
        for d in self.dinos:
            if math.hypot(d.x - cam[0], d.z - cam[2]) > 230:
                continue
            if math.dist((d.x, d.y if d.flyer else 3.0, d.z), cam) < (20 if d.flyer else 8):
                continue
            roar_u = (t - d.roar_t0) / 1.7
            roar = math.sin(math.pi * roar_u) ** 0.6 if 0 <= roar_u <= 1 else 0.0
            eating = d.eat_until > t
            collapse = 0.0
            if d.kind == "skeleton":
                if 0 <= roar_u <= 1.3:  # falls apart, then pulls itself back together
                    collapse = min(1.0, roar_u * 3) if roar_u < 0.7 else max(0.0, 1 - (roar_u - 0.7) / 0.6)
            st = {"ph": d.phase * 2, "mv": d.mv, "roar": roar, "look": d.look, "collapse": collapse, "turn": d.turn}
            parts = RIGS[d.kind](d, t, st)
            c, s = math.cos(d.heading), math.sin(d.heading)
            y0 = d.y if d.flyer and d.kind != "spider" else 0.0
            if d.kind == "spider":
                y0 = d.y
                ax = d.x + SPIDER_SPINNERET[0] * c  # the silk leaves the spinnerets at the back of the abdomen
                az = d.z - SPIDER_SPINNERET[0] * s
                y_lo, sway = y0 + SPIDER_SPINNERET[1], 0.25 * math.sin(t * 0.8 + d.seed)  # the top end drifts a little
                ln = d.alt + 25 - y_lo
                out.append(box(ax + sway / 2, y_lo + ln / 2, az, 0.05, ln, 0.05, (0.8, 0.8, 0.88), 0.35, 0.0, 0.0, 0.0, 0.0,
                               -math.asin(sway / math.hypot(sway, ln)), 0.0))  # the silk thread
            sc = SCALE if d.kind not in ("ghost", "witch", "spider") else 1.0
            edge = 0.12 if d.kind == "spider" else EDGE  # thin legs with a full neon outline read as scribbles
            if d.kind == "cat":
                sc = SCALE * 0.9
            models.creature_parts(r, [box(d.x + (x * c + z * s) * sc, y0 + y * sc, d.z + (-x * s + z * c) * sc, sx * sc, sy * sc, sz * sc, col, glow,
                                          d.heading + yl, edge, 0.0, 0.0, rz, rx) for (x, y, z, sx, sy, sz, col, glow, rz, rx, yl) in parts], out)
            if r is not None and d.kind not in ("spider",):
                ln = 3.0 if d.kind in ("cat",) else 5.0
                alt = 1.0 / (1.0 + max(y0 - 2, 0) * 0.12)
                m = (mathx.translate(d.x, 0.03, d.z) @ mathx.rot_y(d.heading) @ mathx.rot_x(math.pi / 2) @ mathx.translate(-ln / 2, -ln / 4, 0) @ mathx.scale(ln, ln / 2, 1))
                r.quad3d(r.white, m, (0, 0, 0, 0.3 * alt))
        for b in self.baits:  # candy
            for k in range(4):
                a = k * 1.6 + b["x"]
                col = [(1, 0.4, 0.1), (0.8, 0.2, 1.0), (0.2, 1.0, 0.4), (1, 0.9, 0.2)][k]
                out.append(box(b["x"] + math.cos(a) * 0.7, 0.35, b["z"] + math.sin(a) * 0.7, 0.55, 0.3, 0.3, col, 1.5, a + t))
        for x, y, z, vx, vy, vz, life in self.dust:  # ectoplasm puffs and witch sparks
            k = min(1.0, life / 0.9)
            out.append(box(x, y, z, 0.3 + 0.4 * (1 - k), 0.3 + 0.4 * (1 - k), 0.3 + 0.4 * (1 - k), (0.5 + 0.3 * k, 1.0 * k, 0.4 + 0.4 * k), 1.2, 0.0, 0.0))
        for x, z, t0, rad in self.rings:
            fade = 1 - (t - t0) / 1.4
            for k in range(20):
                a = k * math.tau / 20
                out.append(box(x + math.cos(a) * rad, 0.15, z + math.sin(a) * rad, 1.4 * fade + 0.2, 0.25, 0.5, (0.65, 0.3, 1.0), 1.4 * fade, -a, 0.2))
        return out
