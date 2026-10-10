"""The FSN world: a root pedestal, one pedestal per anime wired to it, and a block field of episodes."""
import math

import numpy as np

from . import mathx

PED_W, PED_D, PED_H = 4.6, 6.4, 0.5
CYAN, BLUE, GREEN, MAGENTA, GOLD = (0.10, 0.75, 1.0), (0.12, 0.22, 0.46), (0.12, 0.95, 0.50), (1.0, 0.18, 0.80), (1.0, 0.75, 0.2)


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def box(x, y, z, sx, sy, sz, color, glow=0.0, yaw=0.0, edge=1.0, pitch=0.0, flat=0.0, rollz=0.0, rollx=0.0):
    """One instance. `edge` scales the neon outline (0 gives a plain smooth surface, used for paper); `pitch` tilts it about X; `flat` exempts it from retro posterizing; `rollz`/`rollx` rotate it in its own frame (limbs, jaws, wings)."""
    return [x, y, z, glow, sx, sy, sz, yaw, color[0], color[1], color[2], edge, pitch, flat, rollz, rollx]


class Camera:
    """Orbit camera that glides to goals (the FSN fly-through)."""

    def __init__(self):
        self.target = np.array([0.0, 0.0, 0.0])
        self.yaw, self.pitch, self.dist = 0.0, math.radians(38), 55.0
        self.g_target, self.g_yaw, self.g_pitch, self.g_dist = self.target.copy(), self.yaw, self.pitch, self.dist

    def goto(self, target, yaw, pitch, dist):
        self.g_target, self.g_yaw, self.g_pitch, self.g_dist = np.array(target, dtype=float), yaw, pitch, dist

    def update(self, dt):
        k = 1 - math.exp(-dt * 3.5)
        self.target += (self.g_target - self.target) * k
        dy = (self.g_yaw - self.yaw + math.pi) % (2 * math.pi) - math.pi
        self.yaw += dy * k
        self.pitch += (self.g_pitch - self.pitch) * k
        self.dist += (self.g_dist - self.dist) * k

    def snap(self):
        self.target, self.yaw, self.pitch, self.dist = self.g_target.copy(), self.g_yaw, self.g_pitch, self.g_dist

    def eye(self):
        c = math.cos(self.pitch)
        return self.target + self.dist * np.array([c * math.sin(self.yaw), math.sin(self.pitch), c * math.cos(self.yaw)])

    def orbit(self, dx, dy):
        self.g_yaw -= dx * 0.006
        self.g_pitch = min(max(self.g_pitch + dy * 0.006, 0.12), 1.5)
        self.yaw, self.pitch = self.g_yaw, self.g_pitch

    def pan(self, dx, dy):
        right = np.array([math.cos(self.yaw), 0, -math.sin(self.yaw)])
        fwd = np.array([-math.sin(self.yaw), 0, -math.cos(self.yaw)])
        s = self.dist * 0.0016
        self.g_target = self.g_target - right * dx * s + fwd * dy * s * -1
        self.target = self.g_target.copy()

    def zoom(self, dy):
        self.g_dist = min(max(self.g_dist * (1.0015 ** dy), 6.0), 400.0)


class Scene:
    def __init__(self):
        self.cam = Camera()
        self.peds = []  # dicts: id,title,poster(Tex|None),x,z,born,eps
        self.field = None
        self.selected = None
        self.heading = "ANI"
        self.pick_boxes = []  # (min, max, ref) rebuilt each frame
        self.t_open = 0.0
        self.sections = []
        self.dist_scale = 1.0
        self.starred = set()  # ids on the watch list (shared with the app)

    # ---------- layout ----------
    @staticmethod
    def ring_positions(n):
        pos, idx, ring = [], 0, 0
        while idx < n:
            radius = 17 + ring * 13
            cap = max(6, int(2 * math.pi * radius / 8.6))
            take = min(cap, n - idx)
            for k in range(take):
                a = 2 * math.pi * (k + 0.5 * (ring % 2)) / take
                pos.append((radius * math.sin(a), radius * math.cos(a)))
            idx += take
            ring += 1
        return pos

    PX, PZ, HEADER = PED_W + 2.0, PED_D + 3.6, 4.4  # cell pitch inside a section, and the heading band at its front edge

    def set_results(self, rows, t, heading="SEARCH", groups=None):
        """Lay the rows out in labelled sections: each is a platform with a heading and a grid of pedestals, wired to the root
        by an orthogonal bus. `groups` is [(label, [rows])]; without it everything goes into one section."""
        self.heading = heading
        self.field, self.selected = None, None
        groups = [(lab, rs) for lab, rs in (groups or [(heading, rows)]) if rs]
        self.peds, self.sections = [], []
        z_front, row_h, cursor_x, row_secs = -13.0, 0.0, 0.0, []
        limit = 118.0
        sized = []
        for lab, rs in groups:
            n = len(rs)
            cols = min(n, 4 if n <= 8 else 5 if n <= 15 else 6)
            sized.append((lab, rs, cols, (n + cols - 1) // cols, max(cols * self.PX + 2.0, (len(lab) + 6) * 0.98 + 3.0)))
        rows_of_secs, cur, cur_w = [], [], 0.0
        for item in sized:  # wrap sections into rows of platforms
            w = item[4]
            if cur and cur_w + w > limit:
                rows_of_secs.append(cur)
                cur, cur_w = [], 0.0
            cur.append(item)
            cur_w += w + 5.0
        if cur:
            rows_of_secs.append(cur)
        i = 0
        for row in rows_of_secs:
            total = sum(it[4] for it in row) + 5.0 * (len(row) - 1)
            x = -total / 2
            depth = max(it[3] * self.PZ + self.HEADER for it in row)
            for lab, rs, cols, nrows, w in row:
                sec = {"label": lab, "x0": x, "w": w, "zf": z_front, "d": nrows * self.PZ + self.HEADER, "cx": x + w / 2, "n": len(rs)}
                self.sections.append(sec)
                for k, r in enumerate(rs):
                    c, rw = k % cols, k // cols
                    px = x + (w - cols * self.PX) / 2 + (c + 0.5) * self.PX
                    pz = z_front - self.HEADER - (rw + 0.5) * self.PZ + self.PZ * 0.0
                    self.peds.append({"id": r["id"], "title": r["title"], "poster_url": r.get("poster", ""), "poster": None,
                                      "x": px, "z": pz, "born": t + 0.05 * i, "eps": r.get("eps"), "sub": r.get("sub", ""), "resume": r.get("resume"), "sec": len(self.sections) - 1, "row": rw, "col": c})
                    i += 1
                x += w + 5.0
            z_front -= depth + 6.0
        self.goto_home()

    def extents(self):
        """(min x, max x, min z, max z) of everything laid out, including the root."""
        xs = [p["x"] for p in self.peds] + [0.0]
        zs = [p["z"] for p in self.peds] + [0.0]
        for s_ in getattr(self, "sections", []):
            xs += [s_["x0"], s_["x0"] + s_["w"]]
            zs += [s_["zf"], s_["zf"] - s_["d"]]
        return min(xs), max(xs), min(zs), max(zs)

    def goto_home(self):
        x0, x1, z0, z1 = self.extents()
        w, d = x1 - x0, z1 - z0
        dist = (max(w * 0.52, d * 0.9, 16) + 14) * self.dist_scale
        self.cam.goto(((x0 + x1) / 2, 0, (z0 + z1) / 2 + 4), 0.0, math.radians(46), dist)

    def open_field(self, idx, episodes, watched, t):
        p = self.peds[idx]
        self.selected = idx
        n = max(len(episodes), 1)
        cols = min(n, max(5, math.ceil(math.sqrt(n * 1.7))))
        rows = math.ceil(n / cols)
        pitch = 1.5
        w, d = cols * pitch, rows * pitch
        # the field sits in front of the root (+z, where the camera looks from) so its rows climb away from the viewer
        fc = (0.0, 15 + d / 2)
        self.field = {"idx": idx, "eps": list(episodes), "watched": set(watched), "cols": cols, "rows": rows, "pitch": pitch,
                      "w": w, "d": d, "cx": fc[0], "cz": fc[1], "born": t}
        self.cam.goto((fc[0], 0, fc[1] - d * 0.1), 0.0, math.radians(44), max(w, d) * 0.8 + 15)

    def close_field(self):
        self.field, self.selected = None, None
        self.goto_home()

    def ep_pos(self, i):
        f = self.field
        c, r = i % f["cols"], i // f["cols"]
        return (f["cx"] - f["w"] / 2 + (c + 0.5) * f["pitch"], f["cz"] + f["d"] / 2 - (r + 0.5) * f["pitch"])

    # ---------- per-frame build ----------
    def build(self, r, text, t, hover, player, cam_pos, th):
        boxes, self.pick_boxes = [], []

        def pickable(x0, y0, z0, x1, y1, z1, ref):
            self.pick_boxes.append(((x0, y0, z0), (x1, y1, z1), ref))

        # root
        bob = 0.15 * math.sin(t * 1.4)
        rg = 0.8 if hover == ("root",) else 0.15
        boxes.append(box(0, 0.3, 0, 8, 0.6, 8, th.root, rg))
        boxes.append(box(0, 1.9 + bob, 0, 1.7, 2.6, 1.7, th.core, 0.5 + 0.2 * math.sin(t * 2), yaw=t * 0.4))
        pickable(-4, 0, -4, 4, 3.5, 4, ("root",))
        self._label(r, text, self.heading, (0, 0.04, 5.3), 1.1, th.t_root, center=True)

        # section platforms, headings and wiring: root -> trunk -> a bus along each section's front edge -> one stub per pedestal
        zmin = min([sec["zf"] - sec["d"] for sec in self.sections] + [-6.0])
        if self.sections:
            boxes.append(box(0, 0.37, (zmin + 4) / 2, 0.22, 0.1, 4 - zmin, th.wire, 0.7))  # the trunk runs behind the root
        for si, sec in enumerate(self.sections):
            boxes.append(box(sec["cx"], 0.14, sec["zf"] - sec["d"] / 2, sec["w"], 0.28, sec["d"], th.slab, 0.12))
            boxes.append(box(sec["cx"], 0.3, sec["zf"] - 0.05, sec["w"], 0.1, 0.18, th.wire, 0.9))
            if sec["cx"] != 0:
                boxes.append(box(sec["cx"] / 2, 0.37, sec["zf"] + 0.6, abs(sec["cx"]), 0.1, 0.2, th.wire, 0.7))
            f = (t * 0.25 + si * 0.21) % 1.0
            boxes.append(box(0, 0.45, 4 + (sec["zf"] + 0.6 - 4) * f, 0.5, 0.3, 0.5, th.pulse, 1.4))
            heading = f"{sec['label']}  ({sec['n']})" if len(self.sections) > 1 else sec["label"]
            self._label(r, text, heading, (sec["x0"] + 0.9, 0.31, sec["zf"] - 2.2), 1.5, th.t_root)
        slot = {(p["sec"], p["row"], p["col"]): p for p in self.peds}
        for i, p in enumerate(self.peds):
            sec = self.sections[p["sec"]]
            up = slot.get((p["sec"], p["row"] - 1, p["col"]))  # wired to the pedestal in front of it, or to the bus
            z_from = (up["z"] - PED_D / 2) if up else sec["zf"]
            stub = z_from - (p["z"] + PED_D / 2)
            if stub > 0.05:
                boxes.append(box(p["x"] - PED_W / 2 + 0.35, 0.3, z_from - stub / 2, 0.14, 0.1, stub, th.wire, 0.6))

        # pedestals
        for i, p in enumerate(self.peds):
            s = ease((t - p["born"]) / 0.7)
            h = PED_H * max(s, 0.001)
            hov = hover == ("ped", i)
            sel = self.selected == i
            glow = 0.15 + (0.7 if hov else 0) + (0.5 if sel else 0)
            boxes.append(box(p["x"], h / 2, p["z"], PED_W, h, PED_D, th.ped if not sel else th.ped_sel, glow))
            if p["id"] in self.starred:  # gold star-gem: this one is on your watch list
                boxes.append(box(p["x"] - PED_W / 2 + 0.6, PED_H + 0.9 * s + 0.2 * math.sin(t * 2 + i), p["z"] - PED_D / 2 + 0.6, 0.7, 0.7, 0.4, (1.0, 0.82, 0.2), 1.5, yaw=t * 1.5))
            pickable(p["x"] - PED_W / 2, 0, p["z"] - PED_D / 2, p["x"] + PED_W / 2, 1.2, p["z"] + PED_D / 2, ("ped", i))
            if p["poster"] and s > 0.5:
                tex = p["poster"]
                m = mathx.translate(p["x"] - (PED_W - 0.5) / 2, h + 0.02, p["z"] - (PED_D - 0.5) / 2 - 0.0) @ mathx.rot_x(math.pi / 2) @ mathx.scale(PED_W - 0.5, PED_D - 0.5, 1)
                r.quad3d(tex, m, (1, 1, 1, 1))
            col = (1.0, 1.0, 1.0) if (hov or sel) else th.t_ped
            for ln_i, ln in enumerate(self._wrap_title(p["title"])):  # at most two short lines, so neighbours never overlap
                self._label(r, text, ln, (p["x"], 0.33, p["z"] + PED_D / 2 + 1.0 + ln_i * 0.95), 0.8, col, center=True)
            if p.get("sub"):  # e.g. "EP 12 - 14:05" on a continue-watching pedestal
                self._label(r, text, p["sub"], (p["x"], 0.33, p["z"] + PED_D / 2 + 1.0 + len(self._wrap_title(p["title"])) * 0.95), 0.8, (1.0, 0.82, 0.2), center=True)

        # episode field
        f = self.field
        if f:
            p = self.peds[f["idx"]]
            L = math.hypot(f["cx"] - p["x"], f["cz"] - p["z"])
            yaw = math.atan2(-(f["cz"] - p["z"]), f["cx"] - p["x"])
            boxes.append(box((p["x"] + f["cx"]) / 2, 0.06, (p["z"] + f["cz"]) / 2, L, 0.12, 0.2, th.link, 0.9, yaw))
            for k in range(3):
                q = (t * 0.3 + k / 3) % 1.0
                boxes.append(box(p["x"] + (f["cx"] - p["x"]) * q, 0.3, p["z"] + (f["cz"] - p["z"]) * q, 0.5, 0.3, 0.5, th.pulse, 1.4, yaw))
            boxes.append(box(f["cx"], 0.2, f["cz"], f["w"] + 2.5, 0.4, f["d"] + 2.5, th.slab, 0.1))
            n = len(f["eps"])
            playing = player.get("episode") if (player.get("anime") or {}).get("id") == p["id"] and player.get("playing") else None
            labels = []
            for i, ep in enumerate(f["eps"]):
                s = ease((t - f["born"] - 0.008 * i) / 0.5)
                if s <= 0:
                    continue
                x, z = self.ep_pos(i)
                h = (0.6 + 3.2 * ((i + 1) / n) ** 0.9) * s
                if ep == playing:
                    col, glow = th.ep_play, 0.9 + 0.5 * math.sin(t * 5)
                elif ep in f["watched"]:
                    col, glow = th.ep_seen, 0.15
                else:
                    col, glow = th.ep, 0.0
                if hover == ("ep", ep):
                    glow += 0.8
                boxes.append(box(x, 0.4 + h / 2, z, 1.05, h, 1.05, col, glow))
                pickable(x - 0.53, 0.4, z - 0.53, x + 0.53, 0.4 + h, z + 0.53, ("ep", ep))
                if math.hypot(x - cam_pos[0], z - cam_pos[2]) < 38 and len(labels) < 650:
                    labels.append((ep, x, 0.4 + h + 0.02, z, ep in f["watched"] or ep == playing))
            for ep, x, y, z, seen in labels:
                self._digits(r, text, ep, x, y, z, (0.9, 1.0, 0.9, 1) if seen else (0.8, 0.9, 1.0, 1))
            self._label(r, text, p["title"][:40] + f"  //  {n} EPISODES", (f["cx"], 0.04, f["cz"] + f["d"] / 2 + 2.6), 0.9, th.t_field, center=True)

        r.add_boxes(np.array(boxes, dtype=np.float32))

    @staticmethod
    def _wrap_title(title, width=15):
        words, lines, cur = title.split(), [], ""
        for w in words:
            if len(cur) + len(w) + 1 > width and cur:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        if len(lines) > 2:
            lines = [lines[0], lines[1][:width - 2] + ".."]
        return [ln[:width + 3] for ln in lines]

    # ---------- text in the world ----------
    def _label(self, r, text, s, pos, height, color, center=False):
        tex, w, h = text.get(s, 44, tuple(int(c * 255) for c in color))
        ww = height * w / h
        x = pos[0] - (ww / 2 if center else 0)
        m = mathx.translate(x, pos[1], pos[2] - height / 2) @ mathx.rot_x(math.pi / 2) @ mathx.scale(ww, height, 1)
        r.quad3d(tex, m)

    def _digits(self, r, text, ep, x, y, z, tint):
        n = len(ep)
        dw = min(0.34, 0.95 / n)
        dh = dw / text.digit_aspect
        x0 = x - n * dw / 2
        for k, ch in enumerate(ep):
            if ch.isdigit():
                m = mathx.translate(x0 + k * dw, y, z - dh / 2) @ mathx.rot_x(math.pi / 2) @ mathx.scale(dw, dh, 1)
                r.quad3d(text.digit_tex, m, tint, text.digit_uv(int(ch)))

    # ---------- picking ----------
    def pick(self, origin, direction):
        if not self.pick_boxes:
            return None
        mn = np.array([b[0] for b in self.pick_boxes])
        mx = np.array([b[1] for b in self.pick_boxes])
        inv = 1.0 / np.where(np.abs(direction) < 1e-9, 1e-9, direction)
        t1, t2 = (mn - origin) * inv, (mx - origin) * inv
        tmin = np.minimum(t1, t2).max(axis=1)
        tmax = np.maximum(t1, t2).min(axis=1)
        hit = (tmax >= np.maximum(tmin, 0))
        if not hit.any():
            return None
        idx = np.where(hit)[0]
        best = idx[np.argmin(tmin[idx])]
        return self.pick_boxes[best][2]
