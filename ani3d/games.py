"""Mini-games played inside the 3D world. Each game owns its state, draws boxes/quads and its own HUD bits."""
import html
import math
import random

from . import mathx
from .scene import box

DIRS = {"ArrowUp": (0, -1), "w": (0, -1), "ArrowDown": (0, 1), "s": (0, 1), "ArrowLeft": (-1, 0), "a": (-1, 0), "ArrowRight": (1, 0), "d": (1, 0)}


def flat_label(r, text, s, x, y, z, height, color, center=True):
    tex, w, h = text.get(s, 44, tuple(int(c * 255) for c in color))
    ww = height * w / h
    r.quad3d(tex, mathx.translate(x - (ww / 2 if center else 0), y, z - height / 2) @ mathx.rot_x(math.pi / 2) @ mathx.scale(ww, height, 1))


# ------------------------------------------------------------ shared motion helpers
def roller(cx, cy, cz, yaw, roll, parts):
    """Boxes of something that rolls: `parts` are (ox, oy, oz, sx, sy, sz, color, glow, rz) in the object's frame
    (axle along z, +x = travel direction); `roll` turns them about the axle, then `yaw` points the axle in the world."""
    c, s = math.cos(roll), math.sin(roll)
    cy_, sy_ = math.cos(yaw), math.sin(yaw)
    out = []
    for ox, oy, oz, sx, sy, sz, col, glow, rz in parts:
        x, y = ox * c - oy * s, ox * s + oy * c
        out.append(box(cx + x * cy_ + oz * sy_, cy + y, cz - x * sy_ + oz * cy_, sx, sy, sz, col, glow, yaw, 0.6, 0.0, 0.0, roll + rz, 0.0))
    return out


def barrel_parts(theme_fx, t=0.0):
    """A barrel (or, in the Halloween theme, a jack-o'-lantern) seen end-on, radius ~0.55: round from three rotated
    slabs, with markings that make the roll visible."""
    if theme_fx == "halloween":
        orange, rib, glow = (1.0, 0.45, 0.05), (0.75, 0.28, 0.02), 1.3 + 0.3 * math.sin(t * 6)
        P = [(0, 0, 0, 1.1, 0.62, 0.95, orange, 0.7, a) for a in (0.0, math.pi / 3, 2 * math.pi / 3)]
        P += [(0, 0, sz * 0.48, 1.08, 0.07, 0.04, rib, 0.3, a) for sz in (-1, 1) for a in (math.pi / 2, math.pi / 6, -math.pi / 6)]
        P += [(0, 0.6, 0, 0.14, 0.26, 0.14, (0.25, 0.6, 0.1), 0.3, 0.2)]  # stem
        for sz in (-1, 1):  # carved face on both ends, glowing from inside
            P += [(-0.18, 0.12, sz * 0.49, 0.14, 0.14, 0.03, (1.0, 0.9, 0.3), glow, math.pi / 4),
                  (0.18, 0.12, sz * 0.49, 0.14, 0.14, 0.03, (1.0, 0.9, 0.3), glow, math.pi / 4),
                  (0, -0.17, sz * 0.49, 0.42, 0.09, 0.03, (1.0, 0.9, 0.3), glow, 0.0)]
        return P
    wood, band = (0.62, 0.36, 0.14), (0.25, 0.16, 0.08)
    P = [(0, 0, 0, 1.1, 0.5, 0.95, wood, 0.45, a) for a in (0.0, math.pi / 3, 2 * math.pi / 3)]
    P += [(0, 0, sz * 0.48, 0.98, 0.1, 0.04, band, 0.2, a) for sz in (-1, 1) for a in (0.0, math.pi / 2)]  # cross on the lid
    P += [(0, 0, sz * 0.36, 1.13, 0.52, 0.06, band, 0.2, a) for sz in (-1, 1) for a in (0.0, math.pi / 3, 2 * math.pi / 3)]  # hoops
    return P


def tip_book(bk, push_z=1.0, push_x=0.0, spin=1.0):
    """Start a standing book (dict with x, y0 (its base), z, w, h, d, color) tipping over its front bottom edge."""
    bk.update({"phase": "tip", "tilt": 0.0, "wt": 2.0 + 2.5 * push_z, "vx": push_x, "vy": 0.0, "vz": 0.0, "wz": 0.0,
               "spin": spin, "age": 0.0})
    return bk


def step_book(bk, dt, floor):
    """Advance a tipping / falling book. Returns False once it has landed and faded out."""
    bk["age"] += dt
    if bk["phase"] == "tip":  # rotating about the front bottom edge, gravity pulling harder as it leans
        bk["wt"] += (14 * math.sin(max(bk["tilt"], 0.15))) * dt
        bk["tilt"] += bk["wt"] * dt
        if bk["tilt"] > 1.05:  # over the edge: fly free, keeping the rotation it had
            hh, dd = bk["h"] / 2, bk["d"] / 2
            c, s = math.cos(bk["tilt"]), math.sin(bk["tilt"])
            bk["px"], bk["py"], bk["pz"] = bk["x"], bk["y0"] + hh * c + dd * s, bk["z"] + dd + hh * s - dd * c
            bk["vy"], bk["vz"] = 1.0, 2.2 + bk["wt"] * 0.4
            bk["wz"] = random.uniform(-3, 3) * bk["spin"]
            bk["phase"] = "fall"
        return True
    if bk["phase"] == "fall":
        bk["vy"] -= 26 * dt
        bk["px"] += bk["vx"] * dt
        bk["py"] += bk["vy"] * dt
        bk["pz"] += bk["vz"] * dt
        bk["tilt"] += bk["wt"] * dt
        bk["roll"] = bk.get("roll", 0.0) + bk["wz"] * dt
        if bk["py"] - 0.3 <= floor:
            if abs(bk["vy"]) > 4:  # one bounce, losing most of the spin
                bk["py"], bk["vy"] = floor + 0.3, -bk["vy"] * 0.28
                bk["wt"] *= 0.35
                bk["wz"] *= 0.35
                bk["vx"] *= 0.5
                bk["vz"] *= 0.4
            else:  # settle flat on its back and fade
                bk["py"], bk["phase"], bk["rest"] = floor + bk["d"] / 2, "rest", 0.0
                bk["tilt"] = math.pi / 2
        return True
    bk["rest"] += dt
    return bk["rest"] < 1.6


def book_boxes(bk, glow=0.15):
    """Boxes for a book while it tips / falls / rests (fades out at the end)."""
    col = bk["color"]
    if bk["phase"] == "rest" and bk["rest"] > 0.8:
        k = max(0.0, 1 - (bk["rest"] - 0.8) / 0.8)
        col = tuple(c * k for c in col)
    if bk["phase"] == "tip":
        hh, dd = bk["h"] / 2, bk["d"] / 2
        c, s = math.cos(bk["tilt"]), math.sin(bk["tilt"])
        cx, cy, cz = bk["x"], bk["y0"] + hh * c + dd * s, bk["z"] + dd + hh * s - dd * c
        roll = 0.0
    else:
        cx, cy, cz, roll = bk["px"], bk["py"], bk["pz"], bk.get("roll", 0.0)
    return [box(cx, cy, cz, bk["w"], bk["h"], bk["d"], col, glow, 0.0, 0.6, 0.0, 0.0, roll, bk["tilt"])]


class Game:
    name = ""
    help = ""
    cam = ((0, 0, 0), 0.0, math.radians(60), 28)

    def __init__(self, app):
        self.app = app
        self.score = 0
        self.over = False
        self.note = ""
        self.reset()

    def reset(self):
        pass

    def update(self, dt, keys):
        pass

    def key(self, k):
        pass

    def build(self, r, text, th, t):
        return []

    def hud(self, app, W, H):
        pass

    def achievements(self):
        """Keys (see advance.GAME_ADV) of the advancements this run has earned so far."""
        return []


class Snake(Game):
    name, help = "SNAKE", "arrows / WASD steer   R restart   Esc exit"
    GW, GH = 22, 14
    cam = ((0, 0, 1.0), 0.0, math.radians(62), 31)

    def reset(self):
        self.body = [(5, 7), (4, 7), (3, 7)]
        self.dir, self.queue = (1, 0), []
        self.score, self.over, self.acc, self.speed = 0, False, 0.0, 0.13
        self.food = self.spawn()

    def spawn(self):
        free = [(x, y) for x in range(self.GW) for y in range(self.GH) if (x, y) not in self.body]
        return random.choice(free)

    def key(self, k):
        if k == "r":
            self.reset()
        elif k in DIRS and len(self.queue) < 2:
            self.queue.append(DIRS[k])

    def update(self, dt, keys):
        if self.over:
            return
        self.acc += dt
        while self.acc >= self.speed and not self.over:
            self.acc -= self.speed
            while self.queue:
                d = self.queue.pop(0)
                if (d[0] + self.dir[0], d[1] + self.dir[1]) != (0, 0):
                    self.dir = d
                    break
            head = (self.body[0][0] + self.dir[0], self.body[0][1] + self.dir[1])
            if not (0 <= head[0] < self.GW and 0 <= head[1] < self.GH) or head in self.body[:-1]:
                self.over = True
                return
            self.body.insert(0, head)
            if head == self.food:
                self.score += 10
                self.speed = max(0.05, self.speed * 0.97)
                self.food = self.spawn()
            else:
                self.body.pop()

    def cell(self, i, j):
        return i - self.GW / 2 + 0.5, j - self.GH / 2 + 0.5

    def build(self, r, text, th, t):
        out = [box(0, -0.2, 0, self.GW + 0.8, 0.4, self.GH + 0.8, th.slab, 0.1)]
        for x in (-self.GW / 2 - 0.25, self.GW / 2 + 0.25):
            out.append(box(x, 0.3, 0, 0.3, 0.6, self.GH + 0.8, th.wire, 0.7))
        for z in (-self.GH / 2 - 0.25, self.GH / 2 + 0.25):
            out.append(box(0, 0.3, z, self.GW + 0.8, 0.6, 0.3, th.wire, 0.7))
        for n, (i, j) in enumerate(self.body):
            x, z = self.cell(i, j)
            head = n == 0
            out.append(box(x, 0.45, z, 0.88, 0.7, 0.88, th.ep_play if (head and not self.over) else th.ep_seen, 0.6 if head else 0.15))
        fx, fz = self.cell(*self.food)
        out.append(box(fx, 0.55 + 0.12 * math.sin(t * 6), fz, 0.6, 0.6, 0.6, th.tower, 1.3, yaw=t * 2))
        flat_label(r, text, f"SCORE {self.score}", 0, 0.03, -self.GH / 2 - 1.5, 0.9, th.t_field)
        if self.over:
            flat_label(r, text, "GAME OVER  -  press R", 0, 0.5, 0, 1.6, (1, 0.3, 0.3))
        return out


class Breakout(Game):
    name, help = "BREAKOUT", "left/right (A/D) move paddle   Space launch   R restart   Esc exit"
    cam = ((0, 0, 1.5), 0.0, math.radians(62), 36)
    X, Z = 11.0, 9.0
    PZ, PW = 8.2, 3.6

    def reset(self):
        self.px, self.lives, self.score, self.over = 0.0, 3, 0, False
        self.bricks = [[-self.X + 1.1 + c * 2.2, -self.Z + 2.0 + rw * 1.0, True, rw] for rw in range(5) for c in range(10)]
        self.stick()
        self.won = False

    def stick(self):
        self.ball, self.vel, self.stuck = [self.px, self.PZ - 0.7], [0.0, 0.0], True

    def key(self, k):
        if k == "r":
            self.reset()
        elif k == " " and self.stuck and not self.over:
            self.stuck = False
            self.vel = [random.choice((-4.0, 4.0)), -11.0]

    def update(self, dt, keys):
        if self.over:
            return
        move = ((keys & {"ArrowRight", "d"}) and 1 or 0) - ((keys & {"ArrowLeft", "a"}) and 1 or 0)
        self.px = max(-self.X + self.PW / 2, min(self.X - self.PW / 2, self.px + move * 17 * dt))
        if self.stuck:
            self.ball[0] = self.px
            return
        speed = math.hypot(*self.vel) + dt * 0.2
        for _ in range(3):  # sub-steps keep the ball from tunnelling
            h = dt / 3
            self.ball[0] += self.vel[0] * h
            self.ball[1] += self.vel[1] * h
            bx, bz = self.ball
            if bx < -self.X + 0.3 or bx > self.X - 0.3:
                self.vel[0] *= -1
                self.ball[0] = max(-self.X + 0.3, min(self.X - 0.3, bx))
            if bz < -self.Z + 0.3:
                self.vel[1] = abs(self.vel[1])
            if self.vel[1] > 0 and self.PZ - 0.45 <= bz <= self.PZ + 0.3 and abs(bx - self.px) <= self.PW / 2 + 0.3:
                off = (bx - self.px) / (self.PW / 2)
                self.vel = [off * 9.0, -math.sqrt(max(speed ** 2 - (off * 9.0) ** 2, 36))]
            if bz > self.Z + 1.5:
                self.lives -= 1
                if self.lives <= 0:
                    self.over = True
                self.stick()
                return
            for b in self.bricks:
                if b[2] and abs(bx - b[0]) < 1.1 + 0.3 and abs(bz - b[1]) < 0.5 + 0.3:
                    b[2] = False
                    self.score += 10
                    if (1.4 - abs(bx - b[0])) < (0.8 - abs(bz - b[1])):
                        self.vel[0] *= -1
                    else:
                        self.vel[1] *= -1
                    break
        if not any(b[2] for b in self.bricks):
            self.over, self.won = True, True

    def build(self, r, text, th, t):
        cols = [th.ep_play, th.link, th.tower, th.ep_seen, th.ep]
        out = [box(0, -0.2, 0, self.X * 2 + 1, 0.4, self.Z * 2 + 3, th.slab, 0.1)]
        for x in (-self.X - 0.25, self.X + 0.25):
            out.append(box(x, 0.4, 0.75, 0.3, 0.8, self.Z * 2 + 1.5, th.wire, 0.7))
        out.append(box(0, 0.4, -self.Z - 0.25, self.X * 2 + 0.8, 0.8, 0.3, th.wire, 0.7))
        for x, z, alive, rw in self.bricks:
            if alive:
                out.append(box(x, 0.45, z, 2.0, 0.8, 0.86, cols[rw % len(cols)], 0.25))
        out.append(box(self.px, 0.4, self.PZ, self.PW, 0.6, 0.6, th.core, 0.9))
        out.append(box(self.ball[0], 0.45, self.ball[1], 0.6, 0.6, 0.6, (1, 1, 1), 1.5))
        flat_label(r, text, f"SCORE {self.score}    LIVES {max(self.lives, 0)}", 0, 0.03, -self.Z - 1.7, 0.9, th.t_field)
        if self.over:
            flat_label(r, text, "YOU WIN!  press R" if self.won else "GAME OVER  -  press R", 0, 0.5, 1, 1.6, (1, 0.9, 0.3))
        elif self.stuck:
            flat_label(r, text, "press SPACE to launch", 0, 0.3, 3, 1.0, th.t_ped)
        return out


class Quiz(Game):
    name, help = "POSTER QUIZ", "press 1-4 or click an answer   R restart   Esc exit"
    cam = ((0, 3.4, 3.0), 0.0, math.radians(17), 25)
    ROUNDS = 8

    def reset(self):
        self.pool = [p for p in self.app.scene.peds if p.get("poster")]
        self.round, self.score, self.over, self.t0, self.reveal = 0, 0, False, self.app.t, None
        self.cur = None
        if len(self.pool) >= 4:
            self.next_round()

    def next_round(self):
        if self.round >= min(self.ROUNDS, len(self.pool)):
            self.over = True
            return
        answer = random.choice(self.pool)
        others = random.sample([p for p in self.pool if p is not answer], 3)
        choices = others + [answer]
        random.shuffle(choices)
        self.cur = {"answer": answer, "choices": choices, "cu": random.uniform(0.3, 0.7), "cv": random.uniform(0.3, 0.7)}
        self.round += 1
        self.t0, self.reveal = self.app.t, None

    def pick(self, i):
        if self.over or not self.cur or self.reveal:
            return
        correct = self.cur["choices"][i] is self.cur["answer"]
        if correct:
            self.score += max(10, int(100 - 7 * (self.app.t - self.t0)))
        self.reveal = (i, correct, self.app.t)

    def key(self, k):
        if k == "r":
            self.reset()
        elif k in "1234" and len(k) == 1:
            self.pick(int(k) - 1)

    def achievements(self):
        return ["quiz"] if self.over and self.score >= 600 else []

    def update(self, dt, keys):
        if self.reveal and self.app.t - self.reveal[2] > 1.7:
            self.next_round()

    def build(self, r, text, th, t):
        out = [box(0, -0.2, 3, 26, 0.4, 14, th.slab, 0.1), box(0, 5.2, -0.4, 6.8, 9.8, 0.3, th.wood, 0.3)]
        if len(self.pool) < 4 or not self.cur:
            flat_label(r, text, "Open HISTORY or search first (needs 4+ posters)" if len(self.pool) < 4 else "FINAL SCORE %d" % self.score, 0, 0.3, 4, 1.2, th.t_field)
            return out
        cur = self.cur
        prog = 1.0 if self.reveal else min(1.0, (t - self.t0) / 14)
        s = 0.2 + 0.8 * prog
        u0 = min(max(cur["cu"] - s / 2, 0), 1 - s)
        v0 = min(max(cur["cv"] - s / 2, 0), 1 - s)
        m = mathx.translate(-3.0, 10.1, -0.2) @ mathx.scale(6.0, -9.0, 1)
        r.quad3d(cur["answer"]["poster"], m, (1, 1, 1, 1), (u0, v0, u0 + s, v0 + s))
        for i in range(4):
            x = -7.5 + i * 5.0
            glow, col = 0.1, th.ped
            if self.reveal:
                if cur["choices"][i] is cur["answer"]:
                    glow, col = 1.0, th.ep_seen
                elif self.reveal[0] == i:
                    glow, col = 1.0, (1.0, 0.2, 0.2)
            out.append(box(x, 0.3, 6.5, 4.2, 0.6, 2.4, col, glow))
            flat_label(r, text, str(i + 1), x, 0.62, 6.5, 1.5, (1, 1, 1))
        return out

    def hud(self, app, W, H):
        if self.over or not self.cur or len(self.pool) < 4:
            return
        app.txt(f"ROUND {self.round}/{min(self.ROUNDS, len(self.pool))}    SCORE {self.score}", W / 2, 92, 18, app.theme.accent, center=True)
        if self.reveal:
            app.txt("CORRECT!" if self.reveal[1] else f"It was: {self.cur['answer']['title'][:40]}", W / 2, 120, 16, app.theme.good if self.reveal[1] else (1, 0.4, 0.4), center=True)
        bw = min(330, (W - 80) / 4)
        for i, p in enumerate(self.cur["choices"]):
            x = W / 2 - 2 * bw - 12 + i * (bw + 8)
            app.button(f"{i + 1}  {p['title'][:26]}", x, H - 190, bw, 38, lambda i=i: self.pick(i))





def voxel_person(th, x, y, z, face=1, swing=0.0, arms_up=False, sc=0.75):
    """The tiny person from the library, as a list of boxes (also the hero of the barrel climb)."""
    skin = (0.96, 0.80, 0.66)
    out = [box(x - 0.4 * sc, y + 0.45 * sc, z + swing * 0.5, 0.56 * sc, 0.9 * sc, 0.6 * sc, (0.15, 0.15, 0.3), 0.0),
           box(x + 0.4 * sc, y + 0.45 * sc, z - swing * 0.5, 0.56 * sc, 0.9 * sc, 0.6 * sc, (0.15, 0.15, 0.3), 0.0),
           box(x, y + 1.3 * sc, z, 0.95 * sc, 0.95 * sc, 0.55 * sc, th.ped_sel, 0.2), box(x, y + 2.1 * sc, z, 0.75 * sc, 0.7 * sc, 0.7 * sc, skin, 0.1),
           box(x, y + 2.5 * sc, z, 0.85 * sc, 0.25 * sc, 0.8 * sc, th.core, 0.3), box(x + face * 0.42 * sc, y + 2.05 * sc, z + 0.3 * sc, 0.12, 0.12, 0.15, skin, 0.0)]
    for sx in (-1, 1):
        out.append(box(x + sx * 0.62 * sc, y + (1.95 if arms_up else 1.3) * sc, z, 0.24 * sc, 0.8 * sc, 0.24 * sc, skin, 0.05))
    return out


class KongClimb(Game):
    """Donkey Kong on the bookshelf: the shelves are the girders, the books are scenery. Climb to the top, jump the barrels,
    grab a hammer to smash them. Five different stages (more shelves, more barrels, fireballs), then the loop starts again
    faster."""
    name, help = "BARREL CLIMB", "A/D move   W/S climb ladders   Space jump   grab the hammer to smash barrels   R restart   Esc exit"
    HW, GAP = 14.0, 4.4
    LAYOUTS = [  # gap g connects level g and g+1; hammers are (level, x)
        {"name": "THE SHELVES", "N": 5, "ladders": {0: [9.0], 1: [-9.0, -1.0], 2: [9.0, 1.5], 3: [-9.0]}, "hammers": [(1, -4.5), (3, 3.0)], "spawn": 2.6, "speed": 5.5, "fire": 0},
        {"name": "STACKS AND STAIRS", "N": 5, "ladders": {0: [-9.0, 5.0], 1: [9.0, -3.0], 2: [-8.0, 2.0], 3: [10.0]}, "hammers": [(1, 1.0), (3, -4.0)], "spawn": 2.1, "speed": 6.2, "fire": 0},
        {"name": "FIREBALL ALLEY", "N": 6, "ladders": {0: [9.0], 1: [-9.0, 2.0], 2: [9.0, -2.0], 3: [-9.0, 4.0], 4: [8.0]}, "hammers": [(2, -5.0), (4, 5.0)], "spawn": 2.0, "speed": 6.4, "fire": 1},
        {"name": "THE LONG CLIMB", "N": 6, "ladders": {0: [-10.0], 1: [10.0], 2: [-10.0, 0.0], 3: [10.0], 4: [-9.0]}, "hammers": [(1, -6.0), (3, 6.0), (4, 0.0)], "spawn": 1.5, "speed": 7.2, "fire": 2},
        {"name": "KONG'S PENTHOUSE", "N": 7, "ladders": {0: [9.0], 1: [-9.0, 3.0], 2: [9.0, -4.0], 3: [-9.0, 1.0], 4: [9.0, -2.0], 5: [-8.0]}, "hammers": [(2, -6.0), (4, 5.0), (5, 0.0)], "spawn": 1.3, "speed": 7.6, "fire": 3},
    ]
    HAMMER_TIME = 9.0

    @property
    def cam(self):
        n = getattr(self, "N", 5)
        top = 0.3 + self.GAP * (n - 1)
        return ((0, top / 2 + 1.4, 0), 0.0, math.radians(5), 34 + (n - 5) * 5.5)

    def reset(self):
        if not getattr(self, "keep_stage", False):
            self.stage, self.cycle, self.smashes = 1, 0, 0
        self.keep_stage = False
        self.lives, self.over, self.won = 3, False, False
        if self.stage == 1:
            self.score = 0
        self.load_stage()

    def load_stage(self):
        lay = self.LAYOUTS[(self.stage - 1) % len(self.LAYOUTS)]
        self.lay, self.N, self.LADDERS = lay, lay["N"], lay["ladders"]
        self.ly = [0.3 + self.GAP * i for i in range(self.N)]
        self.cycle = (self.stage - 1) // len(self.LAYOUTS)
        self.barrels, self.fires, self.sparks = [], [], []
        self.hammers = [{"level": lv, "x": x, "taken": False} for lv, x in lay["hammers"]]
        self.shelf, self.falling = [], []  # the books standing behind each girder, and the ones knocked off it
        for lv, y in enumerate(self.ly):
            for i in range(26):
                hh = 2.2 + ((i * 37 + int(y * 10)) % 9) * 0.14
                self.shelf.append({"level": lv, "x": -self.HW + 0.6 + i * 1.08, "y0": y + 0.02, "z": -0.95, "w": 0.9, "h": hh, "d": 1.2,
                                   "ci": i + int(y), "gone": False})
        self.chop = 0.0
        self.spawn_t, self.throw = 1.5, 0.0
        self.banner = 2.6  # seconds the stage title is shown (the barrels wait)
        self.bonus = 4000 + 500 * self.cycle
        self.fire_t = 4.0
        self.respawn()
        if self.app.game is self:
            self.app.scene.cam.goto(*self.cam)

    def respawn(self):
        self.p = {"x": -12.0, "y": self.ly[0], "vy": 0.0, "mode": "ground", "level": 0, "lad": None, "face": 1, "run": 0.0, "hammer": 0.0}
        self.barrels = [b for b in self.barrels if b["level"] >= 2]
        self.fires = []

    def key(self, k):
        if k == "r":
            self.stage, self.cycle, self.keep_stage = 1, 0, False
            self.reset()
        elif k == " " and self.p["mode"] == "ground" and not self.over and self.p["hammer"] <= 0 and self.banner <= 0:
            self.p["mode"], self.p["vy"] = "air", 9.5

    def ladder_at(self, gap, x, tol=0.7):
        for lx in self.LADDERS.get(gap, []):
            if abs(lx - x) < tol:
                return lx
        return None

    def speed(self):
        return self.lay["speed"] + 0.9 * self.cycle

    def achievements(self):
        return (["kong3"] if self.stage >= 3 else []) + (["kong_hammer"] if self.smashes >= 5 else [])

    def knock(self, level, x, rad, push=1.0):
        """Books on that shelf near x topple forward off the girder."""
        cols = self.app.theme.books
        for bk in self.shelf:
            if not bk["gone"] and bk["level"] == level and abs(bk["x"] - x) < rad:
                bk["gone"] = True
                fb = dict(bk, color=cols[bk["ci"] % len(cols)])
                self.falling.append(tip_book(fb, push * random.uniform(0.7, 1.3), (bk["x"] - x) * random.uniform(0.5, 1.5)))

    def smash(self, x, y, pts):
        self.score += pts
        self.smashes += 1
        lv = min(range(self.N), key=lambda i: abs(self.ly[i] - y))
        self.knock(lv, x, 1.6, 1.6)
        for i in range(10):
            a = i * math.tau / 10
            self.sparks.append({"x": x, "y": y, "vx": math.cos(a) * 5, "vy": 3 + math.sin(a) * 4, "life": 0.6})

    def lose_life(self):
        self.lives -= 1
        if self.lives <= 0:
            self.over = True
        else:
            self.respawn()
            self.banner = 1.2

    def update(self, dt, keys):
        for sp in self.sparks:
            sp["life"] -= dt
            sp["x"] += sp["vx"] * dt
            sp["vy"] -= 14 * dt
            sp["y"] += sp["vy"] * dt
        self.sparks = [sp for sp in self.sparks if sp["life"] > 0]
        self.falling = [bk for bk in self.falling if step_book(bk, dt, 0.0)]
        for b in self.barrels:  # the little landing hop (visual only)
            b["hv"] -= 30 * dt
            b["hop"] = max(0.0, b["hop"] + b["hv"] * dt)
        if self.over:
            return
        if self.banner > 0:
            self.banner -= dt
            return
        self.bonus = max(0, self.bonus - 40 * dt)
        p = self.p
        move = ((keys & {"ArrowRight", "d"}) and 1 or 0) - ((keys & {"ArrowLeft", "a"}) and 1 or 0)
        up, down = bool(keys & {"ArrowUp", "w"}), bool(keys & {"ArrowDown", "s"})
        p["hammer"] = max(0.0, p["hammer"] - dt)
        armed = p["hammer"] > 0
        if armed:  # the chop: raise, slam down in front, recoil; the slam knocks books off the shelf
            before = self.chop % 1.0
            self.chop += dt * 2.3
            if before < 0.68 <= self.chop % 1.0 or (before > self.chop % 1.0 and before < 0.68):
                hx = p["x"] + p["face"] * 1.4
                self.knock(p["level"], hx, 0.75, 1.2)
                for i in range(5):
                    a = math.pi * (0.15 + 0.7 * i / 4)
                    self.sparks.append({"x": hx, "y": p["y"] - 0.3, "vx": math.cos(a) * 3, "vy": 2 + math.sin(a) * 2, "life": 0.3})
        else:
            self.chop = 0.0
        if p["mode"] == "ground":
            p["x"] = max(-self.HW, min(self.HW, p["x"] + move * (5.2 if armed else 7) * dt))
            if move:
                p["face"], p["run"] = move, p["run"] + dt * 12
            if not armed:  # a hammer needs both hands: no ladders while swinging it
                if up and (lx := self.ladder_at(p["level"], p["x"])) is not None:
                    p["mode"], p["lad"], p["x"] = "climb", p["level"], lx
                elif down and p["level"] > 0 and (lx := self.ladder_at(p["level"] - 1, p["x"])) is not None:
                    p["mode"], p["lad"], p["x"] = "climb", p["level"] - 1, lx
        elif p["mode"] == "climb":
            g = p["lad"]
            p["y"] += ((up and 1) - (down and 1)) * 5.0 * dt
            p["run"] += abs((up and 1) - (down and 1)) * dt * 10
            if p["y"] >= self.ly[g + 1]:
                p["y"], p["level"], p["mode"] = self.ly[g + 1], g + 1, "ground"
            elif p["y"] <= self.ly[g]:
                p["y"], p["level"], p["mode"] = self.ly[g], g, "ground"
        else:  # airborne
            p["x"] = max(-self.HW, min(self.HW, p["x"] + move * 5 * dt))
            p["vy"] -= 28 * dt
            p["y"] += p["vy"] * dt
            if p["y"] <= self.ly[p["level"]] and p["vy"] < 0:
                p["y"], p["vy"], p["mode"] = self.ly[p["level"]], 0.0, "ground"
        # hammer pickups
        for h in self.hammers:
            if not h["taken"] and h["level"] == p["level"] and abs(h["x"] - p["x"]) < 1.0 and p["mode"] == "ground":
                h["taken"] = True
                p["hammer"] = self.HAMMER_TIME
                self.score += 100
        # Kong throws barrels
        self.spawn_t -= dt
        self.throw = max(0.0, self.throw - dt)
        if self.spawn_t <= 0:
            self.spawn_t = max(0.9, self.lay["spawn"] * (0.85 ** self.cycle)) + random.uniform(0, 0.8)
            self.throw = 0.5
            self.barrels.append({"x": -9.0, "y": self.ly[-1] + 0.5, "level": self.N - 1, "dir": 1, "mode": "roll", "vy": 0.0, "spin": 0.0, "scored": False, "ladder_checked": set(),
                                 "roll": 0.0, "hop": 0.0, "hv": 0.0})
        speed = self.speed()
        for b in self.barrels:
            if b["mode"] == "roll":
                b["x"] += b["dir"] * speed * dt
                b["roll"] -= b["dir"] * speed * dt / 0.5  # rolls without slipping (radius 0.5)
                for g in range(b["level"] - 1, b["level"]):
                    lx = self.ladder_at(g, b["x"], 0.25) if g >= 0 else None
                    if lx is not None and (g, lx) not in b["ladder_checked"]:
                        b["ladder_checked"].add((g, lx))
                        if random.random() < 0.3:
                            b["mode"], b["x"], b["vy"] = "drop", lx, 0.0
                if abs(b["x"]) > self.HW + 0.6:
                    b["mode"], b["vy"] = "fall", 0.0
            else:
                b["vy"] -= 30 * dt
                b["y"] += b["vy"] * dt
                b["roll"] -= b["dir"] * (3.0 if b["mode"] == "drop" else 7.0) * dt  # keeps tumbling in the air
                if b["mode"] == "fall":
                    b["x"] += b["dir"] * speed * 0.35 * dt  # off the end of a shelf: carries on outward as it drops
                if b["level"] > 0 and b["y"] <= self.ly[b["level"] - 1] + 0.5:
                    b["level"] -= 1
                    b["hv"] = min(6.0, -b["vy"] * 0.3)
                    b["y"], b["vy"] = self.ly[b["level"]] + 0.5, 0.0
                    self.knock(b["level"], b["x"], 0.9, 0.9)
                    if b["mode"] == "fall":
                        b["dir"] *= -1
                        b["x"] = max(-self.HW + 0.2, min(self.HW - 0.2, b["x"]))
                    else:
                        b["dir"] = random.choice((-1, 1))
                    b["mode"] = "roll"
        self.barrels = [b for b in self.barrels if not (b["level"] == 0 and abs(b["x"]) > self.HW + 1.5)]
        # fireballs: wander the girders and climb toward the player
        self.fire_t -= dt
        if self.lay["fire"] and self.fire_t <= 0 and len(self.fires) < self.lay["fire"] + self.cycle:
            self.fire_t = 7.0
            self.fires.append({"x": 12.5, "y": self.ly[0], "level": 0, "dir": -1, "mode": "walk", "lad": None, "think": 1.0, "spin": 0.0})
        for f in self.fires:
            f["spin"] += dt * 5
            f["think"] -= dt
            if f["mode"] == "walk":
                f["x"] += f["dir"] * (2.6 + 0.5 * self.cycle) * dt
                if abs(f["x"]) > self.HW:
                    f["x"] = max(-self.HW, min(self.HW, f["x"]))
                    f["dir"] *= -1
                if f["think"] <= 0:
                    f["think"] = 1.2
                    want = p["level"]
                    if want > f["level"] and (lx := self.ladder_at(f["level"], f["x"], 0.5)) is not None:
                        f["mode"], f["lad"], f["x"] = "climb", (f["level"], 1), lx
                    elif want < f["level"] and f["level"] > 0 and (lx := self.ladder_at(f["level"] - 1, f["x"], 0.5)) is not None:
                        f["mode"], f["lad"], f["x"] = "climb", (f["level"] - 1, -1), lx
                    elif random.random() < 0.3:
                        f["dir"] *= -1
                    else:
                        f["dir"] = 1 if p["x"] > f["x"] else -1
            else:
                g, d = f["lad"]
                f["y"] += d * 2.6 * dt
                if d > 0 and f["y"] >= self.ly[g + 1]:
                    f["y"], f["level"], f["mode"] = self.ly[g + 1], g + 1, "walk"
                elif d < 0 and f["y"] <= self.ly[g]:
                    f["y"], f["level"], f["mode"] = self.ly[g], g, "walk"
        # collisions: the hammer smashes whatever is in front of you, anything else hurts
        armed = p["hammer"] > 0
        reach = 2.1
        for b in list(self.barrels):
            dx = b["x"] - p["x"]
            if armed and abs(b["y"] - (p["y"] + 0.5)) < 1.5 and ((dx * p["face"] > -0.4 and abs(dx) < reach) or abs(dx) < 0.8):
                self.barrels.remove(b)
                self.smash(b["x"], b["y"], 300)
                continue
            if abs(dx) < 0.9 and abs(b["y"] - (p["y"] + 0.95)) < 1.1 and p["mode"] != "climb":
                self.lose_life()
                return
            if abs(dx) < 0.8 and p["mode"] == "air" and p["y"] > b["y"] + 0.2 and b["level"] == p["level"] and not b["scored"]:
                b["scored"] = True
                self.score += 100
        for f in list(self.fires):
            dx = f["x"] - p["x"]
            if armed and abs(f["y"] - p["y"]) < 1.6 and abs(dx) < reach:
                self.fires.remove(f)
                self.smash(f["x"], f["y"] + 0.6, 500)
                continue
            if abs(dx) < 0.8 and abs(f["y"] + 0.5 - (p["y"] + 0.9)) < 1.2 and p["mode"] != "climb":
                self.lose_life()
                return
        if p["level"] == self.N - 1 and p["x"] > 10.5 and p["mode"] == "ground":
            self.score += 1000 + int(self.bonus)
            self.stage += 1
            self.keep_stage = True
            self.load_stage()
            self.banner = 3.0

    def build(self, r, text, th, t):
        out = []
        top = self.ly[-1] + 4.2
        out.append(box(0, top / 2, -1.5, 2 * self.HW + 3.6, top, 0.3, tuple(c * 0.55 for c in th.wood), 0.05))
        for sx in (-self.HW - 1.4, self.HW + 1.4):
            out.append(box(sx, top / 2, 0, 0.5, top, 2.6, th.wood, 0.15))
        for y in self.ly:
            out.append(box(0, y - 0.15, 0, 2 * self.HW + 2.4, 0.3, 2.4, th.wood, 0.25))
        for bk in self.shelf:  # books standing behind the girders
            if not bk["gone"]:
                out.append(box(bk["x"], bk["y0"] + bk["h"] / 2, bk["z"], bk["w"], bk["h"], bk["d"], th.books[bk["ci"] % len(th.books)], 0.1, 0.0, 0.5))
        for bk in self.falling:
            out += book_boxes(bk)
        for g, xs in self.LADDERS.items():
            for lx in xs:
                h = self.GAP
                out.append(box(lx - 0.45, self.ly[g] + h / 2, 0.45, 0.12, h, 0.12, (0.9, 0.7, 0.2), 0.6))
                out.append(box(lx + 0.45, self.ly[g] + h / 2, 0.45, 0.12, h, 0.12, (0.9, 0.7, 0.2), 0.6))
                for k in range(1, int(h / 0.6)):
                    out.append(box(lx, self.ly[g] + k * 0.6, 0.45, 0.9, 0.08, 0.1, (0.9, 0.7, 0.2), 0.5))
        # Kong (top left) and the goal
        ty = self.ly[-1]
        arm = 0.4 + 1.3 * math.sin(math.pi * (1 - self.throw / 0.5)) if self.throw > 0 else 0.4  # wind up and throw, not a snap
        out += [box(-12, ty + 1.6, 0, 3.0, 3.0, 2.2, (0.45, 0.28, 0.16), 0.3), box(-12, ty + 3.6, 0.2, 1.8, 1.5, 1.6, (0.55, 0.35, 0.2), 0.3),
                box(-12, ty + 3.4, 1.05, 1.0, 0.8, 0.3, (0.9, 0.75, 0.55), 0.3), box(-10.2, ty + 1.8 + arm, 0.2, 0.9, 1.8, 0.9, (0.45, 0.28, 0.16), 0.3),
                box(-13.8, ty + 1.8, 0.2, 0.9, 1.8, 0.9, (0.45, 0.28, 0.16), 0.3)]
        out += [box(12.2, ty + 0.9, 0, 0.9, 1.6, 0.7, (1.0, 0.4, 0.7), 0.6), box(12.2, ty + 1.95, 0, 0.7, 0.6, 0.6, (0.96, 0.8, 0.66), 0.3), box(12.2, ty + 2.4 + 0.1 * math.sin(t * 5), 0, 0.6, 0.25, 0.7, GOLD_, 1.2)]
        for h in self.hammers:  # hammer pickups: standing on their handle, rocking gently, with a glow ring under them
            if not h["taken"]:
                ly = self.ly[h["level"]]
                rock = 0.18 * math.sin(t * 2.5 + h["x"])
                lift = 0.25 + 0.12 * math.sin(t * 4 + h["x"])
                out += self.hammer_boxes(h["x"], ly + lift, rock, 1.0, 0.9 + 0.5 * (0.5 + 0.5 * math.sin(t * 5)))
                out.append(box(h["x"], ly + 0.03, 0.6, 1.4, 0.05, 1.4, GOLD_, 0.8 + 0.6 * (0.5 + 0.5 * math.sin(t * 5)), t * 0.8))
        parts = barrel_parts(th.fx, t)
        for b in self.barrels:
            mname = "pumpkin" if th.fx == "halloween" else "barrel"
            if r.has_mesh(mname):  # Blender model, rolling about its axle
                s = 0.92 if mname == "pumpkin" else 0.95
                r.add_mesh(mname, [box(b["x"], b["y"] + b["hop"], 0.3, s, s, s, (1, 1, 1), 0.4, 0.0, 0.5, 0.0, 0.0, b["roll"])])
            else:
                out += roller(b["x"], b["y"] + b["hop"], 0.3, 0.0, b["roll"], parts)
        for f in self.fires:  # living flames
            fl = 0.8 + 0.4 * math.sin(t * 14 + f["x"])
            out += [box(f["x"], f["y"] + 0.55, 0.3, 0.9, 1.0 * fl, 0.9, (1.0, 0.45, 0.05), 1.6), box(f["x"], f["y"] + 1.1, 0.3, 0.5, 0.8 * fl, 0.5, (1.0, 0.9, 0.2), 1.9, f["spin"])]
        p = self.p
        if p["hammer"] > 0:  # the chop pivots about the hands: raise over the head, slam down in front, small recoil
            u = self.chop % 1.0
            up_a, down_a = math.radians(-15), math.radians(125)
            if u < 0.55:
                k = 1 - (1 - u / 0.55) ** 2
                phi = down_a + (up_a - down_a) * k
            elif u < 0.68:
                k = ((u - 0.55) / 0.13) ** 2
                phi = up_a + (down_a - up_a) * k
            else:
                phi = down_a - math.radians(10) * math.sin(math.pi * (u - 0.68) / 0.32)
            blink = p["hammer"] < 2.0 and int(t * 8) % 2 == 0
            out += voxel_person(th, p["x"], p["y"], 0.5, p["face"], math.sin(p["run"]) * 0.35, phi < math.radians(60))
            hx, hy = p["x"] + p["face"] * 0.35, p["y"] + 1.45
            out += self.hammer_boxes(hx, hy, -p["face"] * phi, 1.0, 1.9 if blink else 1.2)
        else:
            out += voxel_person(th, p["x"], p["y"], 0.5, p["face"], math.sin(p["run"]) * 0.35, p["mode"] in ("climb", "air"))
        for sp in self.sparks:
            out.append(box(sp["x"], sp["y"] + 0.5, 0.8, 0.28, 0.28, 0.28, (1.0, 0.85, 0.2), 1.8))
        return out

    @staticmethod
    def hammer_boxes(x, y, a, sc=1.0, glow=1.2):
        """A mallet whose handle starts at (x, y) and points along angle `a` (0 = straight up, rotating like rollz)."""
        dx, dy = -math.sin(a), math.cos(a)
        L = 1.3 * sc
        wood, steel = (0.55, 0.36, 0.16), (0.82, 0.84, 0.92)
        return [box(x + dx * L / 2, y + dy * L / 2, 0.6, 0.16 * sc, L, 0.16 * sc, wood, 0.3, 0.0, 0.6, 0.0, 0.0, a, 0.0),
                box(x + dx * (L + 0.22 * sc), y + dy * (L + 0.22 * sc), 0.6, 1.0 * sc, 0.55 * sc, 0.6 * sc, steel, glow, 0.0, 0.6, 0.0, 0.0, a, 0.0),
                box(x + dx * (L + 0.22 * sc), y + dy * (L + 0.22 * sc), 0.6, 1.06 * sc, 0.14 * sc, 0.66 * sc, (0.35, 0.35, 0.4), 0.4, 0.0, 0.6, 0.0, 0.0, a, 0.0)]

    def hud(self, app, W, H):
        th = app.theme
        app.txt(f"SCORE {self.score}    LIVES {max(self.lives, 0)}    STAGE {self.stage}: {self.lay['name']}    BONUS {int(self.bonus)}", W / 2, 92, 16, th.accent, center=True)
        if self.p["hammer"] > 0:
            frac = self.p["hammer"] / self.HAMMER_TIME
            app.r.rect(W / 2 - 110, 120, 220, 12, (0, 0, 0, 0.6))
            app.r.rect(W / 2 - 108, 122, 216 * frac, 8, (1.0, 0.85, 0.2, 1.0))
            app.txt("HAMMER!  swing into barrels and fireballs", W / 2, 136, 12, th.dim, center=True)
        if self.banner > 0 and not self.over:
            app.txt(f"STAGE {self.stage}", W / 2, H * 0.30, 40, th.logo, center=True)
            app.txt(self.lay["name"] + ("" if not self.cycle else f"   (lap {self.cycle + 1}: faster)"), W / 2, H * 0.30 + 52, 22, th.accent, center=True)
            hint = "grab the hammer to smash barrels" if self.stage == 1 else ("watch out for fireballs" if self.lay["fire"] else "the barrels are faster now")
            app.txt(hint, W / 2, H * 0.30 + 84, 14, th.dim, center=True)
        if self.over:
            app.txt("GAME OVER  -  press R", W / 2, H * 0.32, 34, (1, 0.3, 0.3), center=True)
            app.txt(f"You reached stage {self.stage} with {self.score} points", W / 2, H * 0.32 + 46, 16, th.text, center=True)


GOLD_ = (1.0, 0.82, 0.2)

BANK = [
    ("Who is the main protagonist of Naruto?", "Naruto Uzumaki", ["Sasuke Uchiha", "Kakashi Hatake", "Rock Lee"]),
    ("What is Goku's birth name as a Saiyan?", "Kakarot", ["Vegeta", "Raditz", "Bardock"]),
    ("Which studio made Spirited Away?", "Studio Ghibli", ["Madhouse", "Kyoto Animation", "Bones"]),
    ("What is Luffy's pirate crew called?", "Straw Hat Pirates", ["Red Hair Pirates", "Heart Pirates", "Whitebeard Pirates"]),
    ("What is the name of Light Yagami's Shinigami in Death Note?", "Ryuk", ["Rem", "L", "Gelus"]),
    ("Who wrote the manga Fullmetal Alchemist?", "Hiromu Arakawa", ["Eiichiro Oda", "Masashi Kishimoto", "Tite Kubo"]),
    ("What is the Survey Corps fighting in Attack on Titan?", "Titans", ["Demons", "Hollows", "Curses"]),
    ("In Cowboy Bebop, what is the name of the dog?", "Ein", ["Pochi", "Max", "Cosmo"]),
    ("What Devil Fruit did Luffy eat?", "Gomu Gomu no Mi", ["Mera Mera no Mi", "Hito Hito no Mi", "Yami Yami no Mi"]),
    ("What is Tanjiro's sister called in Demon Slayer?", "Nezuko", ["Kanao", "Shinobu", "Mitsuri"]),
    ("Which anime has the Hunter Exam?", "Hunter x Hunter", ["Fairy Tail", "Black Clover", "Bleach"]),
    ("Who is the author of One Piece?", "Eiichiro Oda", ["Akira Toriyama", "Hajime Isayama", "Yoshihiro Togashi"]),
    ("What is Izuku Midoriya's hero name in My Hero Academia?", "Deku", ["Dynamight", "Shoto", "Ingenium"]),
    ("Which technique is Naruto famous for?", "Rasengan", ["Chidori", "Kamehameha", "Getsuga Tensho"]),
    ("Who is the vessel of Sukuna in Jujutsu Kaisen?", "Yuji Itadori", ["Megumi Fushiguro", "Satoru Gojo", "Nobara Kugisaki"]),
    ("Who directed My Neighbor Totoro?", "Hayao Miyazaki", ["Makoto Shinkai", "Mamoru Hosoda", "Satoshi Kon"]),
    ("What is the principle at the heart of alchemy in Fullmetal Alchemist?", "Equivalent exchange", ["Conservation of soul", "Elemental balance", "Transmutation of life"]),
    ("Who is the protagonist of Cowboy Bebop?", "Spike Spiegel", ["Jet Black", "Vash the Stampede", "Edward Wong"]),
    ("What does Okabe Rintaro call himself in Steins;Gate?", "Hououin Kyouma", ["Okarin Prime", "Mad Chronicler", "Time Lord Zero"]),
    ("What are Soul Reapers' swords called in Bleach?", "Zanpakuto", ["Shikai", "Bankai", "Nodachi"]),
    ("Which anime is about high school volleyball?", "Haikyu!!", ["Kuroko's Basketball", "Slam Dunk", "Yowamushi Pedal"]),
    ("What race is Frieren?", "Elf", ["Human", "Dwarf", "Demon"]),
    ("Who directed Your Name?", "Makoto Shinkai", ["Hayao Miyazaki", "Isao Takahata", "Mamoru Oshii"]),
    ("What is Kirito's real first name in Sword Art Online?", "Kazuto", ["Kirigaya", "Akihiko", "Eiji"]),
    ("Which is NOT one of the three walls in Attack on Titan?", "Shiganshina", ["Maria", "Rose", "Sina"]),
    ("What breathing style does Zenitsu use?", "Thunder Breathing", ["Water Breathing", "Flame Breathing", "Wind Breathing"]),
    ("Who is the Fourth Hokage?", "Minato Namikaze", ["Hiruzen Sarutobi", "Tobirama Senju", "Jiraiya"]),
    ("Who is the swordsman of the Straw Hat crew?", "Roronoa Zoro", ["Sanji", "Usopp", "Franky"]),
    ("What is the name of Goku's first son?", "Gohan", ["Goten", "Trunks", "Pan"]),
    ("What is Chihiro renamed in Spirited Away?", "Sen", ["Yubaba", "Haku", "Lin"]),
    ("What type is Charmander in Pokemon?", "Fire", ["Water", "Grass", "Dragon"]),
    ("Who is the Flame Alchemist?", "Roy Mustang", ["Edward Elric", "Alex Armstrong", "Scar"]),
    ("What position does Hinata play in Haikyu!!?", "Middle blocker", ["Setter", "Libero", "Wing spiker"]),
    ("What is Gojo's famous technique called?", "Limitless", ["Ten Shadows", "Cursed Speech", "Boogie Woogie"]),
    ("Which year did Astro Boy first air on TV?", "1963", ["1975", "1952", "1989"]),
    ("Which anime features the mecha 'EVA' units?", "Neon Genesis Evangelion", ["Mobile Suit Gundam", "Code Geass", "Gurren Lagann"]),
    ("What does 'senpai' usually mean?", "Upperclassman / senior", ["Teacher", "Younger sibling", "Rival"]),
    ("Who is Saitama's disciple in One Punch Man?", "Genos", ["Mumen Rider", "King", "Tatsumaki"]),
    ("In Death Note, what is L's real first name?", "L Lawliet", ["Light Yagami", "Near", "Mello"]),
    ("Which anime is set on the floating castle-airship world of 'Laputa'?", "Castle in the Sky", ["Howl's Moving Castle", "Princess Mononoke", "Ponyo"]),
]


def _fetch_trivia_api():
    import httpx  # noqa: PLC0415

    r = httpx.get("https://opentdb.com/api.php", params={"amount": 12, "category": 31, "type": "multiple"}, timeout=10)
    out = []
    for q in r.json().get("results", []):
        out.append((html.unescape(q["question"]), html.unescape(q["correct_answer"]), [html.unescape(a) for a in q["incorrect_answers"]]))
    return out


class Trivia(Game):
    name, help = "ANIME TRIVIA", "press 1-4 or click an answer   R restart   Esc exit"
    cam = ((0, 6.5, 0), 0.0, math.radians(10), 25)
    ROUNDS, TIME = 10, 15.0

    def reset(self):
        pool = list(BANK)
        random.shuffle(pool)
        self.queue = pool[: self.ROUNDS + 2]
        self.round, self.score, self.streak, self.best, self.over = 0, 0, 0, 0, False
        self.cur, self.reveal, self.t0 = None, None, self.app.t
        self.source = "bundled questions"
        self.app.be.run(self._api(), self._api_done)  # fresh questions from OpenTDB if reachable
        self.next_round()

    async def _api(self):
        import asyncio  # noqa: PLC0415

        return await asyncio.get_running_loop().run_in_executor(None, _fetch_trivia_api)

    def _api_done(self, qs, err):
        if err or not qs or self.app.game is not self:
            return
        rest = self.queue[1:] + qs
        random.shuffle(rest)
        self.queue = self.queue[:1] + rest  # the question already on screen stays
        self.source = "fresh questions (OpenTDB) + bundled"

    def next_round(self):
        if self.round >= self.ROUNDS or not self.queue:
            self.over = True
            self.cur = None
            return
        q, correct, wrong = self.queue.pop(0)
        opts = wrong[:3] + [correct]
        random.shuffle(opts)
        self.cur = {"q": q, "answer": correct, "opts": opts}
        self.round += 1
        self.t0, self.reveal = self.app.t, None

    def pick(self, i):
        if self.over or not self.cur or self.reveal:
            return
        ok = self.cur["opts"][i] == self.cur["answer"]
        if ok:
            left = max(0.0, self.TIME - (self.app.t - self.t0))
            self.streak += 1
            self.best = max(self.best, self.streak)
            self.score += 50 + int(100 * left / self.TIME) + 10 * min(self.streak - 1, 5)
        else:
            self.streak = 0
        self.reveal = (i, ok, self.app.t)

    def key(self, k):
        if k == "r":
            self.reset()
        elif len(k) == 1 and k in "1234":
            self.pick(int(k) - 1)

    def achievements(self):
        return ["trivia"] if self.over and self.best >= 7 else []

    def update(self, dt, keys):
        if self.cur and not self.reveal and self.app.t - self.t0 > self.TIME:
            self.streak = 0
            self.reveal = (-1, False, self.app.t)  # out of time
        if self.reveal and self.app.t - self.reveal[2] > 1.9:
            self.next_round()

    def build(self, r, text, th, t):
        out = [box(0, -0.2, 2, 30, 0.4, 12, th.slab, 0.1)]
        glow = 0.2
        if self.reveal:
            glow = 1.0
        col = th.ep_seen if (self.reveal and self.reveal[1]) else ((1.0, 0.25, 0.2) if self.reveal else th.wire)
        out.append(box(0, 7.0, 0, 25, 9.5, 0.6, th.slab, 0.15))
        for dx, dy, sx, sy in ((0, 11.9, 25.4, 0.3), (0, 2.1, 25.4, 0.3), (-12.7, 7.0, 0.3, 9.8), (12.7, 7.0, 0.3, 9.8)):
            out.append(box(dx, dy, 0.1, sx, sy, 0.8, col, glow))
        if self.over:
            for i, (msg, h, c) in enumerate([("TRIVIA COMPLETE", 1.6, th.t_field), (f"SCORE {self.score}", 1.3, th.accent), (f"BEST STREAK {self.best}   -   press R to play again", 0.8, th.t_ped)]):
                self.wall_text(r, text, msg, 8.8 - i * 1.9, h, c)
            return out
        if not self.cur:
            return out
        frac = max(0.0, 1 - (t - self.t0) / self.TIME) if not self.reveal else 0.0
        out.append(box(-12.5 + 25 * frac / 2, 12.6, 0.2, max(25 * frac, 0.01), 0.35, 0.4, th.ep_seen if frac > 0.35 else (1.0, 0.3, 0.2), 1.0))
        lines, cur = [], ""
        for w in self.cur["q"].split():
            if len(cur) + len(w) > 36 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        y = 9.4 + (len(lines) - 1) * 0.55
        for ln in lines:
            self.wall_text(r, text, ln, y, 1.05, (1, 1, 1))
            y -= 1.35
        self.wall_text(r, text, f"QUESTION {self.round}/{self.ROUNDS}     SCORE {self.score}     STREAK {self.streak}", 3.0, 0.7, th.t_field)
        if self.reveal:
            msg = "CORRECT!" if self.reveal[1] else ("TIME'S UP!" if self.reveal[0] < 0 else "WRONG!")
            self.wall_text(r, text, f"{msg}   {self.cur['answer']}", 5.0, 1.1, (0.4, 1, 0.5) if self.reveal[1] else (1, 0.45, 0.35))
        return out

    @staticmethod
    def wall_text(r, text, s, y, height, color):
        if not s:
            return
        tex, w, h = text.get(s, 44, tuple(int(c * 255) for c in color))
        ww = min(height * w / h, 23.5)
        hh = ww * h / w
        r.quad3d(tex, mathx.translate(-ww / 2, y + hh / 2, 0.36) @ mathx.scale(ww, -hh, 1))

    def hud(self, app, W, H):
        if self.over or not self.cur:
            return
        app.txt(f"questions: {self.source}", W / 2, 92, 12, app.theme.dim, center=True)
        bw = min(360, (W - 80) / 2)
        for i, o in enumerate(self.cur["opts"]):
            x = W / 2 - bw - 6 + (i % 2) * (bw + 12)
            y = H - 244 + (i // 2) * 46
            state = None
            if self.reveal and o == self.cur["answer"]:
                state = True
            app.button(f"{i + 1}  {o[:34]}", x, y, bw, 40, lambda i=i: self.pick(i), active=bool(state))


GAMES = {"snake": Snake, "breakout": Breakout, "quiz": Quiz, "kong": KongClimb, "trivia": Trivia}

from .galaga import Galaga  # noqa: E402  (these import Game/flat_label from here, so they come last)
from .maze import Maze  # noqa: E402

GAMES.update({"maze": Maze, "galaga": Galaga})
