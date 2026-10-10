"""DATA MAZE: an FSN-styled neon maze. A clue names an important item from an anime (from your own list when it can); find it
among the decoys before the clock runs out. Every level the maze grows."""
import math
import random

from . import mathx
from .games import DIRS, Game, flat_label, voxel_person
from .scene import box

# keyword in the anime title -> (anime, item, colour)
ITEMS = [
    ("dragon ball", "Dragon Ball", "the 4-Star Dragon Ball", (1.0, 0.6, 0.1)),
    ("one piece", "One Piece", "the Gomu Gomu no Mi", (0.9, 0.2, 0.7)),
    ("death note", "Death Note", "the Death Note", (0.25, 0.25, 0.3)),
    ("naruto", "Naruto", "the Leaf Village headband", (0.1, 0.4, 1.0)),
    ("fullmetal", "Fullmetal Alchemist", "the Philosopher's Stone", (1.0, 0.1, 0.2)),
    ("steins", "Steins;Gate", "the Phone Microwave", (0.8, 0.9, 1.0)),
    ("demon slayer", "Demon Slayer", "the Nichirin Blade", (0.2, 0.9, 0.8)),
    ("kimetsu", "Demon Slayer", "the Nichirin Blade", (0.2, 0.9, 0.8)),
    ("jujutsu", "Jujutsu Kaisen", "Sukuna's Finger", (0.8, 0.1, 0.3)),
    ("bleach", "Bleach", "Zangetsu", (0.7, 0.8, 1.0)),
    ("attack on titan", "Attack on Titan", "the Basement Key", (0.9, 0.8, 0.3)),
    ("shingeki", "Attack on Titan", "the Basement Key", (0.9, 0.8, 0.3)),
    ("hunter x hunter", "Hunter x Hunter", "the Hunter License", (0.2, 0.9, 0.3)),
    ("fairy tail", "Fairy Tail", "the Fairy Tail guild mark", (1.0, 0.4, 0.2)),
    ("sword art", "Sword Art Online", "the Elucidator", (0.3, 0.3, 0.3)),
    ("pokemon", "Pokemon", "the Poke Ball", (1.0, 0.1, 0.1)),
    ("my hero", "My Hero Academia", "One For All", (0.2, 0.9, 0.2)),
    ("boku no hero", "My Hero Academia", "One For All", (0.2, 0.9, 0.2)),
    ("frieren", "Frieren", "the Flower-Field Magic grimoire", (0.8, 0.6, 1.0)),
    ("sousou", "Frieren", "the Flower-Field Magic grimoire", (0.8, 0.6, 1.0)),
    ("spirited away", "Spirited Away", "Haku's golden seal", (1.0, 0.85, 0.2)),
    ("cowboy bebop", "Cowboy Bebop", "the Swordfish II key", (0.9, 0.5, 0.1)),
    ("evangelion", "Neon Genesis Evangelion", "the Lance of Longinus", (0.9, 0.2, 0.9)),
    ("code geass", "Code Geass", "Lelouch's Geass contract", (0.8, 0.1, 0.8)),
    ("chainsaw", "Chainsaw Man", "Pochita's pull cord", (1.0, 0.3, 0.1)),
    ("spy x family", "Spy x Family", "Anya's peanut", (0.95, 0.75, 0.5)),
    ("haikyu", "Haikyu!!", "the match volleyball", (1.0, 0.9, 0.2)),
    ("tokyo ghoul", "Tokyo Ghoul", "Kaneki's mask", (0.9, 0.9, 0.9)),
    ("sailor moon", "Sailor Moon", "the Silver Crystal", (1.0, 0.8, 0.9)),
    ("one punch", "One Punch Man", "Saitama's hero cape", (1.0, 0.9, 0.1)),
    ("mob psycho", "Mob Psycho 100", "Mob's 100% meter", (0.9, 0.3, 0.9)),
    ("gintama", "Gintama", "the wooden sword Toyako", (0.7, 0.5, 0.2)),
    ("re:zero", "Re:Zero", "the Witch's Cult sigil", (0.6, 0.2, 0.9)),
    ("konosuba", "KonoSuba", "Megumin's staff", (0.7, 0.1, 0.1)),
    ("black clover", "Black Clover", "Asta's five-leaf grimoire", (0.2, 0.2, 0.2)),
]
GENERIC = [("Anime", "the Magic Mirror", (0.6, 0.9, 1.0)), ("Anime", "the Golden Key", (1.0, 0.85, 0.2)), ("Anime", "the Cursed Ring", (0.8, 0.2, 0.9))]


def item_for(title):
    t = title.lower()
    for kw, anime, item, col in ITEMS:
        if kw in t:
            return anime, item, col
    return None


class Maze(Game):
    name, help = "DATA MAZE", "arrows / WASD move   find the item named in the clue   R restart   Esc exit"
    CELL = 2.6
    cam = ((0, 0, 0), 0.0, math.radians(68), 30)

    def reset(self):
        self.level = getattr(self, "level", 0) if getattr(self, "next_level", False) else 0
        self.next_level = False
        if self.level == 0:
            self.score = 0
        self.lives_msg = ""
        self.build_level()

    # ----- level generation -----
    def pick_targets(self):
        pool = []
        for src in list(getattr(self.app.scene, "peds", [])) + list(getattr(self.app, "lib", None).books if getattr(self.app, "lib", None) else []):
            hit = item_for(src["title"])
            if hit and hit not in pool:
                pool.append(hit)
        known = list(pool)
        rest = [(a, i, c) for _, a, i, c in ITEMS if (a, i, c) not in pool]
        random.shuffle(rest)
        seen, mixed = set(), []
        for x in known + rest:
            if x[0] not in seen:
                seen.add(x[0])
                mixed.append(x)
        target = random.choice(known) if known else mixed[0]
        decoys = [x for x in mixed if x[0] != target[0]]
        random.shuffle(decoys)
        return target, decoys[:3 + min(self.level, 3)]

    def build_level(self):
        L = self.level
        self.cw, self.ch = 9 + 2 * min(L, 4), 7 + 2 * min(L, 3)
        cw, ch = self.cw, self.ch
        # recursive backtracker; walls[(x, y, 'E'|'S')] = True when the wall between cells exists
        wall_e = {(x, y): True for x in range(cw) for y in range(ch)}
        wall_s = {(x, y): True for x in range(cw) for y in range(ch)}
        seen = {(0, ch - 1)}
        stack = [(0, ch - 1)]
        while stack:
            x, y = stack[-1]
            nbrs = [(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if 0 <= x + dx < cw and 0 <= y + dy < ch and (x + dx, y + dy) not in seen]
            if not nbrs:
                stack.pop()
                continue
            nx, ny = random.choice(nbrs)
            if nx > x:
                wall_e[(x, y)] = False
            elif nx < x:
                wall_e[(nx, ny)] = False
            elif ny > y:
                wall_s[(x, y)] = False
            else:
                wall_s[(nx, ny)] = False
            seen.add((nx, ny))
            stack.append((nx, ny))
        for _ in range(cw * ch // 12):  # a few extra openings so it is not a pure tree
            x, y = random.randrange(cw - 1), random.randrange(ch - 1)
            if random.random() < 0.5:
                wall_e[(x, y)] = False
            else:
                wall_s[(x, y)] = False
        self.wall_e, self.wall_s = wall_e, wall_s
        # distances from the start: the target goes far away, decoys at middling distances
        start = (0, ch - 1)
        dist, queue = {start: 0}, [start]
        for cx, cy in queue:
            for dx, dy, blocked in ((1, 0, wall_e[(cx, cy)]), (-1, 0, wall_e.get((cx - 1, cy), True)), (0, 1, wall_s[(cx, cy)]), (0, -1, wall_s.get((cx, cy - 1), True))):
                n = (cx + dx, cy + dy)
                if not blocked and n not in dist and 0 <= n[0] < cw and 0 <= n[1] < ch:
                    dist[n] = dist[(cx, cy)] + 1
                    queue.append(n)
        cells = sorted(dist, key=lambda c: -dist[c])
        target, decoys = self.pick_targets()
        self.target = {"cell": cells[0], "anime": target[0], "name": target[1], "col": target[2], "got": False}
        far = [c for c in cells[1:len(cells) // 2 + 1]]
        random.shuffle(far)
        self.decoys = [{"cell": c, "anime": d[0], "name": d[1], "col": d[2], "got": False} for c, d in zip(far, decoys)]
        self.px, self.pz = self.center(*start)
        self.face, self.run = 1, 0.0
        self.time_left = 55 + 6 * len(cells) ** 0.5 * 2 + 12
        self.time_left = min(150.0, 40 + dist[cells[0]] * 1.6 + 8 * L)
        self.over, self.won, self.flash = False, False, ("", 0.0)
        self.clue_t = 3.0
        self.cam = ((0, 0, 0.6), 0.0, math.radians(68), max(cw * self.CELL * 0.72, ch * self.CELL * 1.35) + 6)
        if self.app.game is self:
            self.app.scene.cam.goto(*self.cam)

    def center(self, cx, cy):
        return (cx - self.cw / 2 + 0.5) * self.CELL, (cy - self.ch / 2 + 0.5) * self.CELL

    # ----- walls as rectangles near the player -----
    def wall_rects(self, near_x, near_z):
        C, T = self.CELL, 0.34
        out = []
        gx, gy = int((near_x / C) + self.cw / 2), int((near_z / C) + self.ch / 2)
        for x in range(max(gx - 2, 0), min(gx + 3, self.cw)):
            for y in range(max(gy - 2, 0), min(gy + 3, self.ch)):
                x0, z0 = (x - self.cw / 2) * C, (y - self.ch / 2) * C
                if self.wall_e[(x, y)]:
                    out.append((x0 + C - T / 2, z0, x0 + C + T / 2, z0 + C))
                if self.wall_s[(x, y)]:
                    out.append((x0, z0 + C - T / 2, x0 + C, z0 + C + T / 2))
                if x == 0:
                    out.append((x0 - T / 2, z0, x0 + T / 2, z0 + C))
                if y == 0:
                    out.append((x0, z0 - T / 2, x0 + C, z0 + T / 2))
        return out

    def move(self, dx, dz):
        r = 0.42
        for axis in (0, 1):
            nx, nz = (self.px + dx, self.pz) if axis == 0 else (self.px, self.pz + dz)
            blocked = False
            for x0, z0, x1, z1 in self.wall_rects(nx, nz):
                if x0 - r < nx < x1 + r and z0 - r < nz < z1 + r:
                    blocked = True
                    break
            if not blocked:
                self.px, self.pz = nx, nz

    def achievements(self):
        return (["maze1"] if self.over and self.won else []) + (["maze3"] if self.over and self.won and self.level >= 2 else [])

    # ----- game flow -----
    def key(self, k):
        if k == "r":
            self.next_level = False
            self.level = 0
            self.reset()
        elif k == "Enter" and self.over and self.won:
            self.level += 1
            self.next_level = True
            self.reset()

    def update(self, dt, keys):
        self.clue_t = max(0.0, self.clue_t - dt)
        self.flash = (self.flash[0], max(0.0, self.flash[1] - dt))
        if self.over:
            return
        self.time_left -= dt
        if self.time_left <= 0:
            self.over, self.won = True, False
            return
        mx = ((keys & {"ArrowRight", "d"}) and 1 or 0) - ((keys & {"ArrowLeft", "a"}) and 1 or 0)
        mz = ((keys & {"ArrowDown", "s"}) and 1 or 0) - ((keys & {"ArrowUp", "w"}) and 1 or 0)
        if mx or mz:
            n = math.hypot(mx, mz)
            self.move(mx / n * 6.2 * dt, mz / n * 6.2 * dt)
            self.run += dt * 12
            if mx:
                self.face = mx
        for it in [self.target] + self.decoys:
            if it["got"]:
                continue
            ix, iz = self.center(*it["cell"])
            if math.hypot(ix - self.px, iz - self.pz) < 0.95:
                it["got"] = True
                if it is self.target:
                    self.over, self.won = True, True
                    self.score += 500 + 25 * int(self.time_left) + 100 * self.level
                else:
                    self.time_left = max(0.0, self.time_left - 8)
                    self.flash = (f"That's {it['name']} from {it['anime']} - wrong item!  -8s", 2.5)

    # ----- drawing -----
    def build(self, r, text, th, t):
        C = self.CELL
        W, Hh = self.cw * C, self.ch * C
        out = [box(0, -0.25, 0, W + 2.2, 0.5, Hh + 2.2, th.slab, 0.08)]
        for gx in range(self.cw + 1):  # the FSN floor grid
            out.append(box((gx - self.cw / 2) * C, 0.02, 0, 0.05, 0.05, Hh, th.wire, 0.35, 0.0, 0.0))
        for gz in range(self.ch + 1):
            out.append(box(0, 0.02, (gz - self.ch / 2) * C, W, 0.05, 0.05, th.wire, 0.35, 0.0, 0.0))
        T, WH = 0.34, 1.9
        for x in range(self.cw):
            for y in range(self.ch):
                x0, z0 = (x - self.cw / 2) * C, (y - self.ch / 2) * C
                if self.wall_e[(x, y)]:
                    out.append(box(x0 + C, WH / 2, z0 + C / 2, T, WH, C + T, th.ped, 0.45, 0.0, 1.0))
                if self.wall_s[(x, y)]:
                    out.append(box(x0 + C / 2, WH / 2, z0 + C, C + T, WH, T, th.ped, 0.45, 0.0, 1.0))
                if x == 0:
                    out.append(box(x0, WH / 2, z0 + C / 2, T, WH, C + T, th.ped, 0.45, 0.0, 1.0))
                if y == 0:
                    out.append(box(x0 + C / 2, WH / 2, z0, C + T, WH, T, th.ped, 0.45, 0.0, 1.0))
        # start pad and items
        sx, sz = self.center(0, self.ch - 1)
        out.append(box(sx, 0.05, sz, C * 0.8, 0.1, C * 0.8, th.ep_seen, 0.7))
        for it in [self.target] + self.decoys:
            if it["got"]:
                continue
            ix, iz = self.center(*it["cell"])
            bob = 0.25 * math.sin(t * 3 + ix)
            out.append(box(ix, 0.9 + bob, iz, 0.9, 0.9, 0.9, it["col"], 1.7, t * 1.7))
            out.append(box(ix, 0.9 + bob, iz, 0.55, 0.55, 0.55, (1, 1, 1), 1.9, -t * 2.3))
            out.append(box(ix, 0.12, iz, C * 0.5, 0.08, C * 0.5, it["col"], 0.9))
            flat_label(r, text, it["name"].replace("the ", "").upper()[:22], ix, 0.15, iz + C * 0.42, 0.55, (1, 1, 1))
        out += voxel_person(th, self.px, 0.0, self.pz, self.face, math.sin(self.run) * 0.35, False, 0.95)
        return out

    def hud(self, app, W, H):
        th = app.theme
        t = self.target
        app.txt(f"CLUE: find {t['name']}  from  {t['anime']}", W / 2, 92, 20, th.accent, center=True)
        frac = max(0.0, min(1.0, self.time_left / 150.0))
        app.r.rect(W / 2 - 160, 124, 320, 12, (0, 0, 0, 0.6))
        app.r.rect(W / 2 - 158, 126, 316 * frac, 8, th.good + (1,) if self.time_left > 15 else (1.0, 0.3, 0.2, 1.0))
        app.txt(f"LEVEL {self.level + 1}    TIME {int(self.time_left)}s    SCORE {self.score}    decoys: {len(self.decoys)}", W / 2, 142, 13, th.dim, center=True)
        if self.flash[1] > 0:
            app.txt(self.flash[0], W / 2, H * 0.28, 22, (1, 0.5, 0.3), center=True)
        if self.over:
            if self.won:
                app.txt(f"FOUND IT!  {t['name']}", W / 2, H * 0.3, 34, th.good, center=True)
                app.txt(f"+{500 + 25 * int(self.time_left) + 100 * self.level} points   -   Enter: next level (bigger maze)   R: restart", W / 2, H * 0.3 + 46, 16, th.text, center=True)
            else:
                app.txt("TIME'S UP", W / 2, H * 0.3, 34, (1, 0.3, 0.3), center=True)
                app.txt(f"It was {t['name']} from {t['anime']}   -   R to try again", W / 2, H * 0.3 + 46, 16, th.text, center=True)
