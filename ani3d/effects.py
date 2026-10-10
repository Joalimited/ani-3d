"""Animated theme effects. Each returns (boxes, flash); quads are drawn straight into the renderer."""
import math

from . import games as _games
from . import mathx
from .dinos import Herd
from .forest import Forest
from .sakura import Garden
from .haunt import Haunt
from .scene import box


def _h(i, k=0):
    """Deterministic pseudo-random in [0, 1)."""
    return (math.sin(i * 12.9898 + k * 78.233) * 43758.5453) % 1.0


def flash(th, t):
    """Lightning level (Halloween only): a double flicker every 8.5 seconds."""
    if th.fx != "halloween":
        return 0.0
    ph = t % 8.5
    if ph < 0.12:
        return 0.7
    if 0.22 < ph < 0.4:
        return 0.5 * (1 - (ph - 0.22) / 0.18)
    return 0.0


_herd = Herd()
_haunt = Haunt()
_forest = None  # built on first use (the scenery takes a moment)
_garden = None


def _get_forest():
    global _forest
    if _forest is None:
        _forest = Forest()
    return _forest


def creatures(th):
    """The theme's interactive animals (dinosaurs / haunted graveyard), or None."""
    return _herd if th.fx == "jurassic" else _haunt if th.fx == "halloween" else _get_forest() if th.fx == "forest" else None


def jurassic(th, r, text, t, cam, world):
    """Fireflies plus a herd of wandering dinosaurs."""
    out, _ = fireflies(th, r, text, t, cam)
    _herd.step(t, world)
    return out + _herd.boxes(t, cam, r), 0.0


def build(th, r, text, t, cam, world=None):
    if th.fx == "jurassic":
        return jurassic(th, r, text, t, cam, world or {"circles": [], "rects": [], "bounds": (30, 90)})
    if th.fx == "halloween":
        return halloween(th, r, text, t, cam, world or {"circles": [], "rects": [], "bounds": (30, 90)})
    if th.fx == "sakura":
        global _garden
        if _garden is None:
            _garden = Garden()
        _garden.step(t, world or {})
        return _garden.boxes(t, cam, r), 0.0
    if th.fx == "forest":
        f = _get_forest()
        f.step(t, world or {"circles": [], "rects": [], "bounds": (30, 90)})
        return f.boxes(t, cam, r), 0.0
    fn = {"matrix": matrix, "retro": retro, "vcr": vcr}.get(th.fx)
    return fn(th, r, text, t, cam) if fn else ([], 0.0)


def _pumpkin_parts(R, t, i):
    """A rolling jack-o'-lantern (axle along z): round from three rotated slabs, ribs and a carved face on each side."""
    orange, rib, lit = (1.0, 0.45, 0.0), (0.7, 0.25, 0.0), (1.0, 0.85, 0.2)
    flick = 1.4 + 0.4 * math.sin(t * 9 + i * 3) * math.sin(t * 5.3 + i)  # candle flicker
    d = 1.7 * R
    P = [(0, 0, 0, 2 * R, 2 * R * 0.56, d, orange, 0.75, a) for a in (0.0, math.pi / 3, 2 * math.pi / 3)]
    P += [(0, 0, 0, 2 * R * 1.01, 0.09 * R, d * 0.92, rib, 0.4, a + math.pi / 6) for a in (0.0, math.pi / 3, 2 * math.pi / 3)]  # grooves
    P += [(0, R * 1.02, 0, 0.26 * R, 0.5 * R, 0.26 * R, (0.25, 0.55, 0.1), 0.3, 0.25)]  # stem
    for sz in (-1, 1):
        f = sz * (d / 2 + 0.02)
        P += [(-0.35 * R, 0.25 * R, f, 0.32 * R, 0.32 * R, 0.04, lit, flick, math.pi / 4),
              (0.35 * R, 0.25 * R, f, 0.32 * R, 0.32 * R, 0.04, lit, flick, math.pi / 4),
              (0, -0.05 * R, f, 0.16 * R, 0.16 * R, 0.04, lit, flick, math.pi / 4),
              (0, -0.4 * R, f, 0.95 * R, 0.16 * R, 0.04, lit, flick, 0.0)]
        P += [(sx * 0.28 * R, -0.3 * R, f, 0.13 * R, 0.14 * R, 0.04, lit, flick, 0.0) for sx in (-1, 1)]  # jagged teeth
    return P


def billboard(r, tex, pos, w, h, yaw, tint, uv):
    m = mathx.translate(*pos) @ mathx.rot_y(yaw) @ mathx.translate(-w / 2, h, 0) @ mathx.scale(w, -h, 1)
    r.quad3d(tex, m, tint, uv)


def matrix(th, r, text, t, cam):
    """Digital rain: a falling bright glyph with a glowing trail, wrapped around the camera."""
    out = []
    for i in range(130):
        x = cam[0] + (_h(i, 1) - 0.5) * 170
        z = cam[2] + (_h(i, 2) - 0.5) * 170
        speed = 7 + _h(i, 3) * 12
        y = 48 - ((t * speed + _h(i, 4) * 60) % 60)
        if math.hypot(x - cam[0], z - cam[2]) < 16:  # keep the rain off the camera lens
            continue
        out.append(box(x, y + 4.0, z, 0.07, 8, 0.07, (0.0, 0.6, 0.15), 0.25))
        yaw = math.atan2(cam[0] - x, cam[2] - z)
        digit = int(t * 9 + i * 7) % 10
        billboard(r, text.digit_tex, (x, y - 0.4, z), 1.5, 2.1, yaw, (0.8, 1.0, 0.85, 1.0), text.digit_uv(digit))
    return out, 0.0


def halloween(th, r, text, t, cam, world):
    out = []
    for i in range(12):  # jack-o'-lanterns rolling along the ground in big loops (rolling without slipping)
        w = (0.05 + _h(i) * 0.06) * (1 if i % 2 else -1)
        rad = 22 + _h(i, 5) * 55
        a = t * w + i * 1.9
        R = 0.95 + 0.25 * _h(i, 6)  # pumpkin radius
        x, z = cam[0] * 0.3 + math.sin(a) * rad, cam[2] * 0.3 + math.cos(a) * rad
        if math.dist((x, R, z), cam) < 14:
            continue
        yaw = a if w > 0 else a + math.pi  # +x of the pumpkin points along its path
        roll = -t * abs(w) * rad / R  # distance rolled / radius (always forward)
        hop = 0.12 * abs(math.sin(roll * 1.5))  # lumpy pumpkins bump a little as they roll
        if r is not None and r.has_mesh("pumpkin"):  # the Blender jack-o'-lantern, rolling about its axle
            s = R / 0.57
            r.add_mesh("pumpkin", [box(x, R + hop, z, s, s, s, (1, 1, 1), 0.5 + 0.3 * math.sin(t * 9 + i * 3) * math.sin(t * 5.3 + i), yaw, 0.3, 0.0, 0.0, roll)])
        else:
            out += _games.roller(x, R + hop, z, yaw, roll, _pumpkin_parts(R, t, i))
    for i in range(14):  # bats
        a = t * (0.35 + _h(i, 7) * 0.3) + i * 2.4
        rad = 12 + _h(i, 8) * 40
        x, z = math.sin(a) * rad, math.cos(a) * rad
        y = 6 + _h(i, 9) * 9 + math.sin(t * 2 + i) * 1.2
        flap = 0.4 + 0.6 * abs(math.sin(t * 14 + i))
        out.append(box(x, y, z, 0.5, 0.3, 0.5, (0.05, 0.0, 0.08), 0.0, yaw=-a))
        out.append(box(x, y + 0.2 * flap, z, 2.2, 0.25, 0.7 * flap + 0.3, (0.10, 0.0, 0.16), 0.0, yaw=-a))
    for i in range(40):  # drifting candle flames and mist wisps near the ground
        a = t * (0.05 + _h(i, 11) * 0.06) + i * 0.7
        rad = 15 + _h(i, 12) * 90
        x, z = cam[0] * 0.5 + math.sin(a) * rad, cam[2] * 0.5 + math.cos(a) * rad
        out.append(box(x, 0.8 + 0.4 * math.sin(t * 2 + i), z, 0.35, 0.6 + 0.2 * math.sin(t * 9 + i), 0.35, (0.8, 1.0, 0.5), 1.8, 0.0, 0.0))
    _haunt.step(t, world)
    return out + _haunt.boxes(t, cam, r), flash(th, t)


def fireflies(th, r, text, t, cam):
    out = []
    for i in range(70):
        x = cam[0] + (_h(i, 1) - 0.5) * 90 + math.sin(t * 0.5 + i) * 2
        z = cam[2] + (_h(i, 2) - 0.5) * 90 + math.cos(t * 0.4 + i * 1.3) * 2
        y = 1 + _h(i, 3) * 9 + math.sin(t * 0.8 + i * 2) * 1.5
        blink = 0.5 + 0.5 * math.sin(t * 2.1 + i * 3)
        out.append(box(x, y, z, 0.22, 0.22, 0.22, (1.0, 0.85, 0.2), 0.6 + 1.6 * blink))
    return out, 0.0


def retro(th, r, text, t, cam):
    """A big striped synthwave sun on the horizon plus blinking pixel stars."""
    out = []
    cx, cz = cam[0], cam[2] - 280
    for k in range(11):
        f = k / 10
        y = 6 + f * 70
        width = 2 * math.sqrt(max(0.0, 46 ** 2 - (y - 6 - 40) ** 2)) if 0 <= y - 6 <= 80 else 0
        if width <= 1 or (k % 2 == 0 and k < 5):
            continue
        out.append(box(cx, y, cz, width, 5.2, 1.5, (1.0, 0.25 + 0.7 * f, 0.55 - 0.45 * f), 1.0))
    for i in range(60):
        a = _h(i, 1) * math.tau
        rad = 120 + _h(i, 2) * 200
        out.append(box(cam[0] + math.sin(a) * rad, 30 + _h(i, 3) * 90, cam[2] - abs(math.cos(a)) * rad - 40, 0.8, 0.8, 0.8,
                       (1, 1, 1), 1.2 if int(t * 2 + i) % 3 else 0.2))
    return out, 0.0


def vcr(th, r, text, t, cam):
    """Floating VHS cassettes (the screen overlay with scanlines and tracking noise is drawn by the HUD)."""
    out = []
    for i in range(16):
        a = t * (0.05 + _h(i, 1) * 0.07) + i * 1.7
        rad = 20 + _h(i, 2) * 70
        x, z = cam[0] * 0.3 + math.sin(a) * rad, cam[2] * 0.3 + math.cos(a) * rad
        y = 3 + _h(i, 3) * 10 + math.sin(t * 0.9 + i) * 0.8
        if math.dist((x, y, z), cam) < 16:
            continue
        yaw, tilt = a * 2 + t * 0.4, 0.3 * math.sin(t * 0.7 + i)
        out.append(box(x, y, z, 3.6, 0.7, 2.2, (0.06, 0.06, 0.08), 0.15, yaw, 0.5, tilt))
        out.append(box(x, y + 0.36, z, 2.6, 0.06, 1.0, (0.9, 0.9, 0.8), 0.6, yaw, 0.3, tilt))  # white label
        out.append(box(x, y + 0.4, z, 2.6, 0.1, 0.25, (1.0, 0.2 + 0.3 * _h(i, 4), 0.2), 0.9, yaw, 0.3, tilt))  # coloured stripe
        for sgn in (-1, 1):  # the two reel hubs
            out.append(box(x + sgn * 0.8 * math.cos(yaw), y + 0.4, z - sgn * 0.8 * math.sin(yaw), 0.6, 0.12, 0.6, (0.75, 0.75, 0.8), 0.5, yaw + t * sgn, 0.3, tilt))
    for i in range(7):  # tracking-error bars drifting across the sky
        y = ((t * (3 + i) + i * 31) % 70) + 2
        out.append(box(cam[0], y, cam[2] - 150, 380, 0.5 + _h(i, 5) * 1.2, 0.4, (0.8, 0.85, 1.0), 0.5 + _h(i, 6), 0.0, 0.0))
    return out, 0.0
