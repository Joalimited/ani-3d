"""DINO GALAGA: a Galaga-style shooter where you fly a dinosaur-ship and every wave ends with an anime-character boss."""
import math
import random

from . import dinos
from .games import Game, flat_label
from .scene import box

X, Z = 11.0, 9.5  # half extents of the playfield


# ---------------------------------------------------------------- the player's dinosaur ships
SHIPS = [
    {"kind": "trex", "name": "REX", "blurb": "twin cannons, strong hull", "speed": 13.0, "rate": 0.20, "hp": 4, "shot": "twin", "scale": 0.34},
    {"kind": "raptor", "name": "RAPTOR", "blurb": "fastest, rapid fire", "speed": 19.0, "rate": 0.11, "hp": 3, "shot": "single", "scale": 0.55},
    {"kind": "trike", "name": "TRICERATOPS", "blurb": "triple horn spread, tanky", "speed": 10.0, "rate": 0.26, "hp": 6, "shot": "spread", "scale": 0.38},
    {"kind": "ptero", "name": "PTERANODON", "blurb": "piercing shots", "speed": 15.0, "rate": 0.24, "hp": 3, "shot": "pierce", "scale": 0.42},
]


def dino_boxes(kind, x, y, z, t, scale, heading=math.pi / 2, mv=1.0, roar=0.0, tint=None):
    """The herd's rigs reused as a ship: the dinosaur nose points up the screen (-z)."""
    sp = dinos.SPECIES[kind]
    pal = sp[10] if tint is None else tint
    st = {"t": t, "ph": t * 9, "mv": mv, "roar": roar, "look": 0.0, "graze": 0.0, "turn": 0.0, "flap": 14.0}
    P = dinos.Pose()
    dinos.RIGS[kind](P, st, pal)
    c, s = math.cos(heading), math.sin(heading)
    out = []
    for (px, py, pz, sx, sy, sz, col, glow, rz, rx, yl) in P.parts:
        out.append(box(x + (px * c + pz * s) * scale, y + py * scale, z + (-px * s + pz * c) * scale, sx * scale, sy * scale, sz * scale,
                       col, glow + 0.2, heading + yl, 0.5, 0.0, 0.0, rz, rx))
    return out


# ---------------------------------------------------------------- anime-character bosses
# name, anime, skin, hair, outfit, accent, attack
BOSSES = [
    ("GOKU", "Dragon Ball", (0.96, 0.8, 0.65), (0.05, 0.05, 0.08), (1.0, 0.5, 0.05), (0.1, 0.3, 0.9), "beam", "spiky"),
    ("LUFFY", "One Piece", (0.96, 0.8, 0.65), (0.05, 0.05, 0.08), (0.85, 0.1, 0.1), (0.95, 0.8, 0.3), "pistol", "hat"),
    ("NARUTO", "Naruto", (0.96, 0.8, 0.65), (1.0, 0.85, 0.2), (1.0, 0.55, 0.1), (0.1, 0.2, 0.7), "clones", "spiky"),
    ("SAITAMA", "One Punch Man", (0.96, 0.8, 0.65), (0.96, 0.8, 0.65), (1.0, 0.9, 0.1), (1.0, 1.0, 1.0), "punch", "bald"),
    ("RYUK", "Death Note", (0.9, 0.9, 0.95), (0.05, 0.05, 0.1), (0.1, 0.1, 0.14), (0.9, 0.1, 0.1), "apples", "wild"),
    ("LELOUCH", "Code Geass", (0.96, 0.85, 0.75), (0.05, 0.03, 0.1), (0.35, 0.1, 0.5), (0.95, 0.15, 0.55), "geass", "side"),
]
ENEMY_COLORS = [(0.2, 0.9, 0.5), (0.9, 0.3, 0.7), (0.3, 0.6, 1.0), (1.0, 0.7, 0.2)]


def figure(x, z, s, skin, hair, outfit, accent, style, t, glow=0.3):
    """A blocky character standing on the field facing the player (+z)."""
    bob = 0.12 * math.sin(t * 3)
    y = bob
    out = [box(x - 0.45 * s, y + 0.8 * s, z, 0.6 * s, 1.6 * s, 0.7 * s, accent, glow), box(x + 0.45 * s, y + 0.8 * s, z, 0.6 * s, 1.6 * s, 0.7 * s, accent, glow),
           box(x, y + 2.3 * s, z, 1.7 * s, 1.5 * s, 0.9 * s, outfit, glow + 0.2),
           box(x - 1.15 * s, y + 2.4 * s, z, 0.5 * s, 1.4 * s, 0.5 * s, skin, glow), box(x + 1.15 * s, y + 2.4 * s, z, 0.5 * s, 1.4 * s, 0.5 * s, skin, glow),
           box(x, y + 3.65 * s, z, 1.2 * s, 1.1 * s, 1.0 * s, skin, glow + 0.1),
           box(x - 0.28 * s, y + 3.7 * s, z + 0.52 * s, 0.22 * s, 0.22 * s, 0.1 * s, (0.05, 0.05, 0.05), 0.0), box(x + 0.28 * s, y + 3.7 * s, z + 0.52 * s, 0.22 * s, 0.22 * s, 0.1 * s, (0.05, 0.05, 0.05), 0.0)]
    if style == "spiky":
        for k in (-1, 0, 1):
            out.append(box(x + k * 0.4 * s, y + 4.5 * s + (0.3 * s if k == 0 else 0), z, 0.4 * s, 0.9 * s, 0.5 * s, hair, glow + 0.3, 0.0, 1.0, 0.0, 0.0, k * 0.4))
    elif style == "hat":
        out += [box(x, y + 4.35 * s, z, 2.0 * s, 0.18 * s, 2.0 * s, (0.95, 0.85, 0.4), glow + 0.2), box(x, y + 4.65 * s, z, 1.2 * s, 0.6 * s, 1.2 * s, (0.95, 0.85, 0.4), glow + 0.2),
                box(x, y + 4.5 * s, z + 0.1 * s, 1.25 * s, 0.14 * s, 1.25 * s, (0.85, 0.1, 0.1), glow)]
    elif style == "wild":
        for k in (-2, -1, 0, 1, 2):
            out.append(box(x + k * 0.3 * s, y + 4.4 * s, z, 0.3 * s, 0.7 * s, 0.4 * s, hair, glow, 0.0, 1.0, 0.0, 0.0, k * 0.35))
    elif style == "side":
        out += [box(x, y + 4.35 * s, z, 1.3 * s, 0.4 * s, 1.1 * s, hair, glow), box(x - 0.7 * s, y + 3.9 * s, z, 0.25 * s, 0.9 * s, 0.9 * s, hair, glow)]
    elif style == "bald":
        out.append(box(x, y + 4.0 * s, z + 0.3 * s, 0.3 * s, 0.25 * s, 0.1 * s, (1, 1, 1), 0.6))  # a shine on the head
        out.append(box(x, y + 3.2 * s, z - 0.65 * s, 2.0 * s, 2.4 * s, 0.2 * s, (1, 1, 1), glow))  # the cape
    return out


class Galaga(Game):
    name, help = "DINO GALAGA", "A/D or arrows move   Space fire   B roar bomb   R restart   Esc exit"
    cam = ((0, 0, 0.5), 0.0, math.radians(64), 33)

    def reset(self):
        self.stage = "select"  # select | play | over
        self.sel = 0
        self.score, self.wave, self.over = 0, 0, False
        self.bullets, self.ebullets, self.enemies, self.drops, self.sparks, self.beams = [], [], [], [], [], []
        self.boss = None
        self.bosses_down = 0
        self.msg = ("", 0.0)

    def achievements(self):
        return (["galaga_boss"] if self.bosses_down else []) + (["galaga_w3"] if self.wave >= 3 and self.stage == "play" else [])

    # ----- setup -----
    def start(self, i):
        self.ship = SHIPS[i]
        self.px, self.hp, self.max_hp = 0.0, self.ship["hp"], self.ship["hp"]
        self.cool, self.rapid, self.shield, self.bombs, self.invuln, self.reverse = 0.0, 0.0, 0.0, 1, 1.5, 0.0
        self.stage, self.wave = "play", 0
        self.next_wave()

    def next_wave(self):
        self.wave += 1
        self.bullets, self.ebullets, self.beams = [], [], []
        self.bombs = min(self.bombs + 1, 3)
        cols, rows = 8, 3 + min(self.wave // 2, 2)
        self.enemies = []
        for r_ in range(rows):
            for c in range(cols):
                self.enemies.append({"fx": (c - (cols - 1) / 2) * 2.2, "fz": -Z + 1.6 + r_ * 1.7, "x": random.uniform(-X, X), "z": -Z - 3 - r_ * 2 - c * 0.5,
                                     "mode": "enter", "u": 0.0, "kind": r_ % 4, "hp": 1 + (r_ == 0 and self.wave > 3), "dive_t": random.uniform(2, 9), "sx": 0, "shoot": random.uniform(1, 4)})
        self.boss = None
        self.msg = (f"WAVE {self.wave}", 2.0)

    def spawn_boss(self):
        b = BOSSES[(self.wave // 1 - 1) % len(BOSSES)]
        lap = (self.wave - 1) // len(BOSSES)
        hp = 34 + 10 * self.wave + 12 * lap
        self.boss = {"def": b, "x": 0.0, "z": -Z - 5.0, "hp": hp, "max": hp, "dir": 1, "t": 0.0, "atk": 2.5, "charge": 0.0, "enter": True, "clones": []}
        self.msg = (f"BOSS: {b[0]}  ({b[1]})", 2.8)

    # ----- input -----
    def key(self, k):
        if k == "r":
            self.reset()
            return
        if self.stage == "select":
            if k in ("1", "2", "3", "4"):
                self.start(int(k) - 1)
            elif k in ("ArrowLeft", "a"):
                self.sel = (self.sel - 1) % len(SHIPS)
            elif k in ("ArrowRight", "d"):
                self.sel = (self.sel + 1) % len(SHIPS)
            elif k in ("Enter", " "):
                self.start(self.sel)
        elif self.stage == "play" and k in ("b", "Shift") and self.bombs > 0:
            self.bombs -= 1
            self.ebullets.clear()
            for e in self.enemies:
                e["hp"] -= 2
            if self.boss:
                self.boss["hp"] -= 12
            self.msg = ("ROOOAR!", 1.0)
            for i in range(24):
                self.sparks.append({"x": self.px, "z": Z - 2, "vx": math.cos(i * math.tau / 24) * 14, "vz": math.sin(i * math.tau / 24) * 14, "life": 0.7, "col": (1, 0.8, 0.2)})

    # ----- simulation -----
    def fire(self):
        s = self.ship["shot"]
        z = Z - 1.5
        pierce = s == "pierce"
        shots = {"single": [0.0], "twin": [-0.5, 0.5], "spread": [-0.18, 0.0, 0.18], "pierce": [0.0]}[s]
        if self.rapid > 0:
            shots = shots + ([-0.9, 0.9] if len(shots) < 3 else [])
        for k in shots:
            vx = k * 22 if s == "spread" else 0.0
            ox = k if s in ("twin",) or abs(k) > 0.8 else 0.0
            self.bullets.append({"x": self.px + ox, "z": z, "vx": vx, "vz": -26.0, "pierce": pierce, "hit": set()})

    def hurt(self):
        if self.invuln > 0:
            return
        if self.shield > 0:
            self.shield = 0.0
            self.invuln = 0.8
            return
        self.hp -= 1
        self.invuln = 1.6
        for i in range(14):
            self.sparks.append({"x": self.px, "z": Z - 1, "vx": random.uniform(-8, 8), "vz": random.uniform(-9, 3), "life": 0.7, "col": (1, 0.3, 0.2)})
        if self.hp <= 0:
            self.stage, self.over = "over", True

    def kill_enemy(self, e):
        self.score += 100 + 20 * e["kind"]
        for i in range(8):
            a = i * math.tau / 8
            self.sparks.append({"x": e["x"], "z": e["z"], "vx": math.cos(a) * 6, "vz": math.sin(a) * 6, "life": 0.5, "col": ENEMY_COLORS[e["kind"]]})
        if random.random() < 0.12:
            self.drops.append({"x": e["x"], "z": e["z"], "kind": random.choice(("rapid", "shield", "heal"))})

    def eshot(self, x, z, vx, vz, big=False, tag=""):
        self.ebullets.append({"x": x, "z": z, "vx": vx, "vz": vz, "big": big, "tag": tag})

    def update(self, dt, keys):
        t = self.app.t
        self.msg = (self.msg[0], max(0.0, self.msg[1] - dt))
        for sp in self.sparks:
            sp["life"] -= dt
            sp["x"] += sp["vx"] * dt
            sp["z"] += sp["vz"] * dt
        self.sparks = [sp for sp in self.sparks if sp["life"] > 0]
        if self.stage != "play":
            return
        self.cool = max(0.0, self.cool - dt)
        self.rapid, self.shield, self.invuln, self.reverse = (max(0.0, v - dt) for v in (self.rapid, self.shield, self.invuln, self.reverse))
        move = ((keys & {"ArrowRight", "d"}) and 1 or 0) - ((keys & {"ArrowLeft", "a"}) and 1 or 0)
        if self.reverse > 0:
            move = -move
        self.px = max(-X + 0.8, min(X - 0.8, self.px + move * self.ship["speed"] * dt))
        if " " in keys and self.cool <= 0:
            self.cool = self.ship["rate"] * (0.5 if self.rapid > 0 else 1.0)
            self.fire()
        # player bullets
        for b in self.bullets:
            b["x"] += b["vx"] * dt
            b["z"] += b["vz"] * dt
        self.bullets = [b for b in self.bullets if b["z"] > -Z - 4 and abs(b["x"]) < X + 3]
        # enemies
        for e in self.enemies:
            sway = math.sin(t * 0.8) * 2.6
            if e["mode"] == "enter":
                tx, tz = e["fx"] + sway, e["fz"]
                dx, dz = tx - e["x"], tz - e["z"]
                d = math.hypot(dx, dz) or 1.0
                step = min(d, 14 * dt)
                e["x"] += dx / d * step
                e["z"] += dz / d * step
                if d < 0.3:
                    e["mode"] = "form"
            elif e["mode"] == "form":
                e["x"], e["z"] = e["fx"] + sway, e["fz"]
                e["dive_t"] -= dt
                if e["dive_t"] <= 0 and not self.boss:
                    e["mode"], e["u"], e["sx"] = "dive", 0.0, e["x"]
            else:  # dive: a looping swoop toward the player's side of the field, then back in from the top
                e["u"] += dt * 0.55
                u = e["u"]
                e["x"] = e["sx"] + math.sin(u * math.pi * 2) * 5 * (1 if e["fx"] > 0 else -1) + (self.px - e["sx"]) * 0.4 * min(u * 2, 1)
                e["z"] = e["fz"] + (Z + 3 - e["fz"]) * min(u * 1.25, 1.0)
                if u >= 1.0:
                    e["mode"], e["x"], e["z"], e["dive_t"] = "enter", random.uniform(-X, X), -Z - 3, random.uniform(5, 12)
            e["shoot"] -= dt
            if e["shoot"] <= 0 and e["mode"] != "enter":
                e["shoot"] = random.uniform(2.0, 5.0) / (1 + 0.1 * self.wave) + (1.5 if e["mode"] == "form" else 0)
                if abs(e["x"]) < X:
                    self.eshot(e["x"], e["z"] + 0.6, (self.px - e["x"]) * 0.12 if e["mode"] == "dive" else 0.0, 8.5 + 0.4 * self.wave)
            for b in self.bullets:
                if abs(b["x"] - e["x"]) < 0.9 and abs(b["z"] - e["z"]) < 0.9 and id(e) not in b["hit"]:
                    e["hp"] -= 1
                    b["hit"].add(id(e))
                    if not b["pierce"]:
                        b["z"] = -Z - 99
            if abs(e["x"] - self.px) < 1.0 and abs(e["z"] - (Z - 1)) < 1.0:
                e["hp"] = 0
                self.hurt()
        for e in [e for e in self.enemies if e["hp"] <= 0]:
            self.kill_enemy(e)
        self.enemies = [e for e in self.enemies if e["hp"] > 0]
        if not self.enemies and not self.boss and self.stage == "play":
            self.spawn_boss()
        if self.boss:
            self.update_boss(dt)
        # enemy bullets, drops
        for eb in self.ebullets:
            eb["x"] += eb["vx"] * dt
            eb["z"] += eb["vz"] * dt
            if abs(eb["x"] - self.px) < (0.9 if eb["big"] else 0.6) and abs(eb["z"] - (Z - 1)) < (1.0 if eb["big"] else 0.7):
                eb["z"] = Z + 99
                self.hurt()
                if eb["tag"] == "geass":
                    self.reverse = 3.0
        self.ebullets = [b for b in self.ebullets if -Z - 6 < b["z"] < Z + 4 and abs(b["x"]) < X + 6]
        for d in self.drops:
            d["z"] += 5 * dt
            if abs(d["x"] - self.px) < 1.3 and abs(d["z"] - (Z - 1)) < 1.3:
                d["z"] = Z + 99
                if d["kind"] == "rapid":
                    self.rapid = 9.0
                elif d["kind"] == "shield":
                    self.shield = 12.0
                else:
                    self.hp = min(self.max_hp, self.hp + 1)
                self.score += 50
        self.drops = [d for d in self.drops if d["z"] < Z + 3]

    def update_boss(self, dt):
        b = self.boss
        kind = b["def"][6]
        b["t"] += dt
        if b["enter"]:
            b["z"] += 5 * dt
            if b["z"] >= -Z + 3.2:
                b["enter"] = False
            return
        b["x"] += b["dir"] * (3.0 + 0.2 * self.wave) * dt
        if abs(b["x"]) > X - 3:
            b["dir"] *= -1
        for sh in self.bullets:
            if abs(sh["x"] - b["x"]) < 2.6 and abs(sh["z"] - (b["z"] - 0.5)) < 3.4 and id(b) not in sh["hit"]:
                b["hp"] -= 1
                self.score += 10
                sh["hit"].add(id(b))
                if not sh["pierce"]:
                    sh["z"] = -Z - 99
        for c in b["clones"]:
            c["x"] += c["dir"] * 5 * dt
            if abs(c["x"]) > X - 1:
                c["dir"] *= -1
            c["shoot"] -= dt
            if c["shoot"] <= 0:
                c["shoot"] = 1.4
                self.eshot(c["x"], c["z"] + 1, (self.px - c["x"]) * 0.2, 9)
            for sh in self.bullets:
                if abs(sh["x"] - c["x"]) < 1.2 and abs(sh["z"] - c["z"]) < 1.4:
                    c["hp"] -= 1
                    sh["z"] = -Z - 99
        b["clones"] = [c for c in b["clones"] if c["hp"] > 0]
        b["atk"] -= dt
        for bm in self.beams:
            bm["life"] -= dt
            if bm["t_on"] <= 0 and abs(self.px - bm["x"]) < bm["w"] / 2:
                self.hurt()
            bm["t_on"] -= dt
        self.beams = [bm for bm in self.beams if bm["life"] > 0]
        if b["atk"] <= 0:
            lap = 0.92 ** min(self.wave, 8)
            if kind == "beam":
                b["atk"] = 3.6 * lap
                self.beams.append({"x": self.px, "w": 2.4, "t_on": 1.0, "life": 1.7})
                self.msg = ("KA-ME-HA-ME-HA!", 1.0)
            elif kind == "pistol":
                b["atk"] = 2.2 * lap
                for k in (-1, 0, 1):
                    self.eshot(b["x"], b["z"] + 1.5, (self.px - b["x"]) * 0.25 + k * 2.5, 13)
                self.msg = ("GUM-GUM PISTOL!", 0.8)
            elif kind == "clones":
                b["atk"] = 5.5 * lap
                if len(b["clones"]) < 3:
                    for k in (-1, 1):
                        b["clones"].append({"x": b["x"] + k * 3, "z": b["z"] + 1.5, "dir": k, "hp": 4, "shoot": 0.6})
                    self.msg = ("SHADOW CLONE JUTSU!", 1.0)
                for k in (-0.3, 0, 0.3):
                    self.eshot(b["x"], b["z"] + 1.5, k * 8, 10)
            elif kind == "punch":
                b["atk"] = 3.2 * lap
                self.eshot(b["x"], b["z"] + 1.5, (self.px - b["x"]) * 0.18, 7.5, big=True)
                for k in (-4, 4):
                    self.eshot(b["x"] + k * 0.4, b["z"] + 1.5, k * 0.4, 9)
                self.msg = ("SERIOUS PUNCH!", 0.8)
            elif kind == "apples":
                b["atk"] = 0.55 * lap
                self.eshot(random.uniform(-X + 1, X - 1), -Z - 1, 0.0, random.uniform(7, 11), tag="apple")
            else:  # geass
                b["atk"] = 2.6 * lap
                self.eshot(b["x"], b["z"] + 1.5, (self.px - b["x"]) * 0.2, 9, big=True, tag="geass")
                self.eshot(b["x"] + 1, b["z"] + 1.5, 1.5, 9)
                self.eshot(b["x"] - 1, b["z"] + 1.5, -1.5, 9)
        if b["hp"] <= 0:
            self.score += 1500 + 250 * self.wave
            for i in range(30):
                a = i * math.tau / 30
                self.sparks.append({"x": b["x"], "z": b["z"], "vx": math.cos(a) * 9, "vz": math.sin(a) * 9, "life": 0.9, "col": b["def"][4]})
            self.msg = (f"{b['def'][0]} DEFEATED!  +{1500 + 250 * self.wave}", 2.2)
            self.boss = None
            self.bosses_down += 1
            self.hp = min(self.max_hp, self.hp + 1)
            self.next_wave()

    # ----- drawing -----
    def build(self, r, text, th, t):
        out = [box(0, -0.2, 0, 2 * X + 2, 0.4, 2 * Z + 4, th.slab, 0.1)]
        for x in (-X - 0.4, X + 0.4):
            out.append(box(x, 0.3, 0, 0.3, 0.6, 2 * Z + 4, th.wire, 0.7))
        for i in range(36):  # scrolling star field
            sx = ((i * 7919) % 100) / 100 * 2 * X - X
            sz = ((i * 104729) % 100 / 100 * 2 * Z + t * (2 + i % 4)) % (2 * Z) - Z
            out.append(box(sx, 0.05, sz, 0.12, 0.05, 0.12, (0.8, 0.9, 1.0), 0.9, 0.0, 0.0))
        if self.stage == "select":
            for i, sh in enumerate(SHIPS):
                x = (i - 1.5) * 6.4
                on = i == self.sel
                out.append(box(x, 0.05, 1.0, 5.4, 0.2, 5.4, th.ped_sel if on else th.ped, 0.9 if on else 0.2))
                out += dino_boxes(sh["kind"], x, 0.4, 1.6, t, sh["scale"] * 1.9, math.pi / 2 + (0.4 * math.sin(t) if on else 0), 0.6, 0.0)
                flat_label(r, text, f"{i + 1}  {sh['name']}", x, 0.3, 4.9, 0.7, (1, 1, 1) if on else th.t_ped)
            return out
        for e in self.enemies:
            c = ENEMY_COLORS[e["kind"]]
            wob = math.sin(t * 5 + e["fx"])
            out += [box(e["x"], 0.6, e["z"], 1.3, 0.9, 1.0, c, 0.7), box(e["x"] - 0.25, 0.65, e["z"] + 0.52, 0.22, 0.22, 0.1, (1, 1, 1), 0.8),
                    box(e["x"] + 0.25, 0.65, e["z"] + 0.52, 0.22, 0.22, 0.1, (1, 1, 1), 0.8),
                    box(e["x"] - 0.7 - 0.1 * wob, 0.4, e["z"], 0.3, 0.3, 0.8, c, 0.4), box(e["x"] + 0.7 + 0.1 * wob, 0.4, e["z"], 0.3, 0.3, 0.8, c, 0.4)]
            if e["kind"] % 2 == 0:  # ears / horns
                out += [box(e["x"] - 0.4, 1.25, e["z"], 0.3, 0.5, 0.3, c, 0.9), box(e["x"] + 0.4, 1.25, e["z"], 0.3, 0.5, 0.3, c, 0.9)]
        if self.boss:
            b = self.boss
            nm, anime, skin, hair, outfit, accent, atk, style = b["def"]
            out += figure(b["x"], b["z"], 1.5, skin, hair, outfit, accent, style, t)
            if atk == "beam" and b["atk"] < 1.0:  # charging orb
                out.append(box(b["x"], 3.0, b["z"] + 1.2, 1.2 + (1 - b["atk"]) * 1.4, 1.2 + (1 - b["atk"]) * 1.4, 1.2, (0.4, 0.7, 1.0), 2.0, t * 3))
            for c in b["clones"]:
                out += figure(c["x"], c["z"], 0.8, skin, hair, outfit, accent, style, t, 0.5)
            flat_label(r, text, f"{nm}  ({anime})", b["x"], 0.2, b["z"] + 3.0, 0.8, (1, 0.9, 0.5))
        for bm in self.beams:
            on = bm["t_on"] <= 0
            out.append(box(bm["x"], 0.5, 0.0, bm["w"] if on else 0.25, 0.7 if on else 0.2, 2 * Z + 4, (0.4, 0.8, 1.0) if on else (1, 0.3, 0.3), 2.0 if on else 1.0, 0.0, 0.0))
        for sh in self.bullets:
            out.append(box(sh["x"], 0.5, sh["z"], 0.3, 0.3, 0.9, (0.5, 1.0, 0.7) if sh["pierce"] else (1.0, 0.9, 0.3), 1.8))
        for eb in self.ebullets:
            s = 1.1 if eb["big"] else 0.5
            col = (1, 0.15, 0.2) if eb["tag"] != "apple" else (0.9, 0.05, 0.05)
            out.append(box(eb["x"], 0.5, eb["z"], s, s, s, col, 1.7, t * 4))
        for d in self.drops:
            col = {"rapid": (1, 0.8, 0.1), "shield": (0.3, 0.7, 1), "heal": (0.3, 1, 0.4)}[d["kind"]]
            out.append(box(d["x"], 0.6, d["z"], 0.9, 0.9, 0.9, col, 1.8, t * 3))
        for sp in self.sparks:
            out.append(box(sp["x"], 0.6, sp["z"], 0.28, 0.28, 0.28, sp["col"], 1.8))
        if self.stage == "play" and not (self.invuln > 0 and int(t * 14) % 2):
            out += dino_boxes(self.ship["kind"], self.px, 0.35, Z - 2.1, t, self.ship["scale"], math.pi / 2, 1.0)
            out.append(box(self.px, 0.1, Z - 1.9, 1.5, 0.2, 2.4, th.ped_sel, 0.9))  # the ship's hull plate
            for sx in (-1, 1):  # wings and an engine glow, so the dinosaur reads as a ship from above
                out.append(box(self.px + sx * 1.3, 0.12, Z - 1.4, 1.7, 0.14, 1.0, th.ped_sel, 0.8, sx * 0.0))
                out.append(box(self.px + sx * 0.45, 0.2, Z - 0.4 + 0.15 * math.sin(t * 30), 0.4, 0.3, 0.7, (1.0, 0.6, 0.15), 1.9))
            if self.shield > 0:
                out.append(box(self.px, 0.9, Z - 1.6, 3.0, 1.2, 3.0, (0.3, 0.7, 1.0), 1.0, t * 2, 1.0))
        return out

    def hud(self, app, W, H):
        th = app.theme
        if self.stage == "select":
            app.txt("CHOOSE YOUR DINOSAUR", W / 2, 92, 24, th.accent, center=True)
            sh = SHIPS[self.sel]
            app.txt(f"{sh['name']}: {sh['blurb']}   (lives {sh['hp']})", W / 2, 124, 15, th.text, center=True)
            app.txt("1-4 or arrows + Enter   -   every wave ends with an anime-character boss", W / 2, 148, 12, th.dim, center=True)
            return
        app.txt(f"SCORE {self.score}    WAVE {self.wave}    {self.ship['name']}  HP {'#' * max(self.hp, 0)}{'.' * max(self.max_hp - self.hp, 0)}    ROAR BOMBS {self.bombs} (B)", W / 2, 92, 15, th.accent, center=True)
        extras = []
        if self.rapid > 0:
            extras.append(f"RAPID FIRE {self.rapid:0.0f}s")
        if self.shield > 0:
            extras.append(f"SHIELD {self.shield:0.0f}s")
        if self.reverse > 0:
            extras.append("CONTROLS REVERSED!")
        if extras:
            app.txt("   ".join(extras), W / 2, 114, 13, th.good, center=True)
        if self.boss:
            b = self.boss
            app.r.rect(W / 2 - 200, 138, 400, 14, (0, 0, 0, 0.6))
            app.r.rect(W / 2 - 198, 140, 396 * max(b["hp"], 0) / b["max"], 10, (1.0, 0.25, 0.25, 1.0))
            app.txt(f"{b['def'][0]}  -  {b['def'][1]}", W / 2, 156, 13, th.text, center=True)
        if self.msg[1] > 0:
            app.txt(self.msg[0], W / 2, H * 0.34, 30, th.logo, center=True)
        if self.over:
            app.txt("SHIP DOWN  -  press R", W / 2, H * 0.32, 34, (1, 0.3, 0.3), center=True)
            app.txt(f"Score {self.score}  -  reached wave {self.wave}", W / 2, H * 0.32 + 46, 16, th.text, center=True)
