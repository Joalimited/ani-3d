"""Builds every theme model in Blender and exports them for the engine.

    blender -b --factory-startup -P tools/blender_models.py -- ani3d/models/models.npz [--blend out.blend]

Everything is written in ENGINE coordinates (x right / forward for creatures, y up, z toward the viewer) and converted to
Blender's Z-up space by the helpers below, so positions read the same as the boxes they replace. Each model keeps the
app's look - faceted, chamfered blocks with neon edges - but with proper shapes: tapered trunks, real roofs, lobed
pumpkins, rounded caps. The exporter writes one flat-shaded triangle list per model:
pos(3) normal(3) colour(rgb + self-lit) distance-to-feature-edge(3). Only real corners (> FEATURE_DEG between faces) and
colour boundaries count as feature edges, so round parts don't get a line on every facet.
"""
import math
import random
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

FEATURE_DEG = 40.0
NOEDGE = 1000.0


# ------------------------------------------------------------ engine <-> blender
def to_b(p):
    x, y, z = p
    return Vector((x, -z, y))


def mat(pos=(0, 0, 0), scale=(1, 1, 1), yaw=0.0, rz=0.0, rx=0.0):
    """Engine transform (scale, then roll about z, roll about x, then yaw - same order as the box shader) in Blender space."""
    sx, sy, sz = scale
    S = Matrix.Diagonal((sx, sz, sy, 1.0))
    return Matrix.Translation(to_b(pos)) @ Matrix.Rotation(yaw, 4, "Z") @ Matrix.Rotation(rx, 4, "X") @ Matrix.Rotation(-rz, 4, "Y") @ S


class Model:
    """A bmesh being built from primitives; each primitive's faces get a colour (and a self-lit amount)."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.pal = self.bm.faces.layers.int.new("pal")
        self.colors = [(1, 1, 1, 0)]  # palette: index 0 = unassigned

    def _paint(self, col, lit=0.0):
        c = (col[0], col[1], col[2], lit)
        if c not in self.colors:
            self.colors.append(c)
        idx = self.colors.index(c)
        for f in self.bm.faces:
            if f[self.pal] == 0:
                f[self.pal] = idx

    def box(self, pos, size, col, yaw=0.0, rz=0.0, rx=0.0, bevel=0.06, lit=0.0):
        """A chamfered block (bevel is an absolute width, clamped to the block's thinnest side)."""
        bm = self.bm
        r = bmesh.ops.create_cube(bm, size=1.0, matrix=mat(pos, size, yaw, rz, rx))
        b = min(bevel, 0.3 * min(size))
        if b > 0.004:
            edges = list({e for v in r["verts"] for e in v.link_edges})
            bmesh.ops.bevel(bm, geom=list(r["verts"]) + edges, offset=b, segments=1, affect="EDGES", profile=0.5)
        self._paint(col, lit)

    def cyl(self, pos, r1, r2, h, col, seg=10, yaw=0.0, rz=0.0, rx=0.0, lit=0.0, caps=True):
        """A (tapered) prism standing on pos (pos is the base centre)."""
        cx, cy, cz = pos
        M = mat((0, 0, 0), (1, 1, 1), yaw, rz, rx)
        base = to_b(pos)
        m = Matrix.Translation(base) @ M @ Matrix.Translation((0, 0, h / 2))
        bmesh.ops.create_cone(self.bm, cap_ends=caps, cap_tris=False, segments=seg, radius1=r1, radius2=r2, depth=h, matrix=m)
        self._paint(col, lit)

    def limb(self, p0, p1, r0, r1, col, seg=8, lit=0.0):
        """A tapered prism from engine point p0 to p1."""
        a, b = to_b(p0), to_b(p1)
        d = b - a
        ln = d.length or 1e-6
        q = d.normalized().to_track_quat("Z", "Y")
        m = Matrix.Translation((a + b) / 2) @ q.to_matrix().to_4x4()
        bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r0, radius2=r1, depth=ln, matrix=m)
        self._paint(col, lit)

    def ball(self, pos, size, col, subdiv=1, yaw=0.0, rz=0.0, rx=0.0, lit=0.0, jitter=0.0, seed=0):
        """A faceted low-poly ellipsoid (icosphere), optionally with jittered vertices (rocks)."""
        before = set(self.bm.verts)
        bmesh.ops.create_icosphere(self.bm, subdivisions=subdiv, radius=0.5, matrix=mat(pos, size, yaw, rz, rx))
        if jitter:
            rnd = random.Random(seed)
            new = [v for v in self.bm.verts if v not in before]
            c = to_b(pos)
            for v in new:
                v.co = c + (v.co - c) * (1 + rnd.uniform(-jitter, jitter))
        self._paint(col, lit)

    def dome(self, pos, rad, h, col, seg=12, rings=3, lit=0.0):
        """A half-ellipsoid cap (mushroom caps, lantern tops) sitting on pos."""
        bm = self.bm
        c = to_b(pos)
        rows = []
        for k in range(rings + 1):
            a = (k / rings) * math.pi / 2
            rr, zz = rad * math.cos(a), h * math.sin(a)
            if k == rings:
                rows.append([bm.verts.new(c + Vector((0, 0, zz)))])
            else:
                rows.append([bm.verts.new(c + Vector((rr * math.cos(t), rr * math.sin(t), zz))) for t in (j / seg * math.tau for j in range(seg))])
        for k in range(rings):
            lo, hi = rows[k], rows[k + 1]
            for j in range(seg):
                if len(hi) == 1:
                    bm.faces.new((lo[j], lo[(j + 1) % seg], hi[0]))
                else:
                    bm.faces.new((lo[j], lo[(j + 1) % seg], hi[(j + 1) % seg], hi[j]))
        bm.faces.new(list(reversed(rows[0])))
        self._paint(col, lit)

    def poly(self, pts, col, lit=0.0, thick=0.0):
        """A flat polygon from engine points (optionally extruded downward by `thick`)."""
        bm = self.bm
        vs = [bm.verts.new(to_b(p)) for p in pts]
        f = bm.faces.new(vs)
        if thick:
            r = bmesh.ops.extrude_face_region(bm, geom=[f])
            for v in [e for e in r["geom"] if isinstance(e, bmesh.types.BMVert)]:
                v.co.z -= thick
            bmesh.ops.recalc_face_normals(bm, faces=list({ff for v in vs for ff in v.link_faces} | {ff for e in r["geom"] if isinstance(e, bmesh.types.BMVert) for ff in e.link_faces}))
        self._paint(col, lit)

    def surface(self, rows, col, lit=0.0, close=False):
        """A quad-strip surface from rows of engine points (roofs, curved beams)."""
        bm = self.bm
        vr = [[bm.verts.new(to_b(p)) for p in row] for row in rows]
        for a, b in zip(vr, vr[1:]):
            for j in range(len(a) - 1):
                bm.faces.new((a[j], a[j + 1], b[j + 1], b[j]))
            if close:
                bm.faces.new((a[-1], a[0], b[0], b[-1]))
        self._paint(col, lit)
        return vr

    def faces(self, polys, col, lit=0.0):
        """Faces from lists of engine points (duplicate corners are merged on export)."""
        bm = self.bm
        for pts in polys:
            bm.faces.new([bm.verts.new(to_b(q)) for q in pts])
        self._paint(col, lit)

    def recolor_up(self, col, min_z=0.6, lit=0.0):
        """Faces of the LAST-painted colour that face up get `col` (moss on rocks, snow on peaks)."""
        c = (col[0], col[1], col[2], lit)
        if c not in self.colors:
            self.colors.append(c)
        idx = self.colors.index(c)
        last = len(self.colors) - 2
        for f in self.bm.faces:
            f.normal_update()
            if f[self.pal] == last and f.normal.z > min_z:
                f[self.pal] = idx


# ------------------------------------------------------------ export
def export(models, path):
    out = {}
    thr = math.radians(FEATURE_DEG)
    for m in models:
        bm = m.bm
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        feat = bm.edges.layers.int.new("feat")
        for e in bm.edges:
            lf = e.link_faces
            if len(lf) != 2:
                e[feat] = 1
            else:
                a, b = lf
                ang = a.normal.angle(b.normal, 0.0)
                e[feat] = 1 if (ang > thr or a[m.pal] != b[m.pal]) else 0
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        rows = []
        for f in bm.faces:
            vs = [l.vert for l in f.loops]
            if len(vs) != 3:
                continue
            P = [v.co.copy() for v in vs]
            area2 = (P[1] - P[0]).cross(P[2] - P[0]).length
            if area2 < 1e-9:
                continue
            n = f.normal
            col = m.colors[f[m.pal]]
            # edge k is opposite vertex k: (P[k+1], P[k+2])
            dist = [[0.0, 0.0, 0.0] for _ in range(3)]
            for k in range(3):
                a_, b_ = vs[(k + 1) % 3], vs[(k + 2) % 3]
                e = bm.edges.get((a_, b_))
                is_feat = bool(e and e[feat])
                ln = (P[(k + 2) % 3] - P[(k + 1) % 3]).length
                h = area2 / max(ln, 1e-9)  # altitude from vertex k onto edge k
                for j in range(3):
                    dist[j][k] = (h if j == k else 0.0) if is_feat else NOEDGE
            for j in range(3):
                p = P[j]
                rows.append([p.x, p.z, -p.y, n.x, n.z, -n.y, col[0], col[1], col[2], col[3], *dist[j]])
        out[m.name] = np.array(rows, dtype=np.float32)
        print(f"  {m.name:<18} {len(rows) // 3:6d} tris")
    np.savez_compressed(path, **out)
    print("wrote", path, len(out), "models")


# ------------------------------------------------------------ palettes
LEAF = [(0.18, 0.42, 0.12), (0.22, 0.5, 0.14), (0.15, 0.36, 0.1), (0.28, 0.52, 0.16), (0.32, 0.5, 0.12)]
BARK = (0.3, 0.2, 0.12)
WHITE = (0.95, 0.95, 0.92)
STONE = (0.46, 0.46, 0.44)
MOSS = (0.25, 0.48, 0.15)
PINKS = [(1.0, 0.74, 0.84), (1.0, 0.66, 0.8), (0.98, 0.82, 0.9), (0.95, 0.58, 0.74), (1.0, 0.88, 0.93)]


# ------------------------------------------------------------ forest
def oak(name, seed):
    m, rnd = Model(name), random.Random(seed)
    h = 7.5
    m.cyl((0, 0, 0), 0.82, 0.55, h, BARK, 10)
    for k in range(5):  # root flare
        a = k / 5 * math.tau + 0.3
        m.limb((0, 1.0, 0), (math.cos(a) * 1.6, 0.0, -math.sin(a) * 1.6), 0.42, 0.15, BARK, 7)
    tips = []
    for k in range(5):  # branches climbing out of the trunk
        a = k / 5 * math.tau + rnd.uniform(0, 1)
        y0 = h * rnd.uniform(0.62, 0.9)
        tip = (math.cos(a) * 3.2, y0 + rnd.uniform(1.2, 2.2), -math.sin(a) * 3.2)
        m.limb((0, y0, 0), tip, 0.36, 0.16, BARK, 7)
        tips.append(tip)
    for k in range(13):  # lumpy canopy of chamfered leaf blocks
        bx, by, bz = rnd.choice(tips + [(0, h + 1.5, 0)])
        cs = rnd.uniform(2.6, 4.2)
        m.box((bx + rnd.uniform(-1.3, 1.3), by + rnd.uniform(0.2, 1.8), bz + rnd.uniform(-1.3, 1.3)), (cs, cs * 0.75, cs),
              rnd.choice(LEAF), yaw=rnd.uniform(0, 1.5), bevel=0.35)
    return m


def pine(name, seed):
    m, rnd = Model(name), random.Random(seed)
    h = 11.0
    m.cyl((0, 0, 0), 0.5, 0.25, h, (0.26, 0.17, 0.1), 8)
    needles = (0.07, 0.25, 0.12)
    for k in range(6):  # octagonal tiers, each flaring out at its base
        y = 1.6 + k * 1.6
        w = (5.8 - k * 0.82) / 2
        shade = tuple(c * (0.9 + 0.06 * k) for c in needles)
        m.cyl((0, y, 0), w, w * 0.35, 1.9, shade, 8, yaw=k * 0.35)
        m.cyl((0, y - 0.18, 0), w * 1.04, w * 0.98, 0.22, tuple(c * 0.75 for c in shade), 8, yaw=k * 0.35)
    m.cyl((0, h - 0.4, 0), 0.7, 0.0, 1.8, needles, 8)
    return m


def birch(name, seed):
    m, rnd = Model(name), random.Random(seed)
    h = 9.0
    m.cyl((0, 0, 0), 0.42, 0.32, h, (0.9, 0.9, 0.85), 10)
    for k in range(9):  # black bark marks
        y = rnd.uniform(0.6, h - 0.6)
        a = rnd.uniform(0, math.tau)
        m.box((math.cos(a) * 0.38, y, -math.sin(a) * 0.38), (0.1, 0.12, 0.45), (0.08, 0.08, 0.08), yaw=a + math.pi / 2, bevel=0.02)
    tips = []
    for k in range(4):
        a = k / 4 * math.tau + rnd.uniform(0, 1)
        y0 = h * rnd.uniform(0.6, 0.85)
        tip = (math.cos(a) * 1.8, y0 + 1.6, -math.sin(a) * 1.8)
        m.limb((0, y0, 0), tip, 0.18, 0.08, (0.85, 0.85, 0.8), 6)
        tips.append(tip)
    for k in range(8):
        bx, by, bz = rnd.choice(tips + [(0, h + 0.5, 0)])
        cs = rnd.uniform(1.9, 3.0)
        m.box((bx + rnd.uniform(-0.8, 0.8), by + rnd.uniform(0, 1.6), bz + rnd.uniform(-0.8, 0.8)), (cs, cs * 0.9, cs), (0.45, 0.62, 0.2),
              yaw=rnd.uniform(0, 1.5), bevel=0.3)
    return m


def bush(name, seed, berries=False):
    m, rnd = Model(name), random.Random(seed)
    for k in range(6):
        a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, 1.1)
        cs = rnd.uniform(1.3, 2.2)
        m.box((math.cos(a) * rr, cs * 0.42, -math.sin(a) * rr), (cs, cs * 0.8, cs), rnd.choice(LEAF), yaw=rnd.uniform(0, 1.5), bevel=0.22)
    if berries:
        for k in range(9):
            a = rnd.uniform(0, math.tau)
            m.ball((math.cos(a) * 1.05, rnd.uniform(0.5, 1.5), -math.sin(a) * 1.05), (0.24, 0.24, 0.24), (0.85, 0.08, 0.15), 1, lit=0.8)
    return m


def fern(name, seed):
    m, rnd = Model(name), random.Random(seed)
    for k in range(9):  # fronds: a stem arching out with leaflet pairs along it
        a = k / 9 * math.tau + rnd.uniform(-0.2, 0.2)
        ln = rnd.uniform(1.9, 2.6)
        d = (math.cos(a), -math.sin(a))
        pts = [(d[0] * ln * f, 0.15 + 1.1 * math.sin(math.pi * f * 0.75) - 0.2 * f, d[1] * ln * f) for f in (0.0, 0.35, 0.7, 1.0)]
        col = (0.2, 0.52, 0.16) if k % 2 else (0.25, 0.58, 0.2)
        for p0, p1 in zip(pts, pts[1:]):
            m.limb(p0, p1, 0.05, 0.04, col, 4)
        for j in range(1, 7):
            f = j / 7
            i = min(int(f * 3), 2)
            t = f * 3 - i
            p = [pts[i][q] + (pts[i + 1][q] - pts[i][q]) * t for q in range(3)]
            w = 0.42 * (1 - f * 0.7)
            for sd in (-1, 1):
                tip = (p[0] - d[1] * sd * w + d[0] * 0.1, p[1] - 0.05, p[2] + d[0] * sd * w + d[1] * 0.1)
                m.limb(tuple(p), tip, 0.07, 0.02, col, 4)
    return m


def toadstool(name, seed):
    m, rnd = Model(name), random.Random(seed)
    m.cyl((0, 0, 0), 0.2, 0.15, 1.15, (0.95, 0.93, 0.85), 10)
    m.cyl((0, 0.7, 0), 0.24, 0.24, 0.07, (0.9, 0.88, 0.8), 10)  # ring on the stem
    m.dome((0, 1.05, 0), 0.75, 0.55, (0.9, 0.12, 0.08), 12, 3)
    for k in range(9):
        a = rnd.uniform(0, math.tau)
        rr = rnd.uniform(0.15, 0.6)
        y = 1.05 + 0.55 * math.sqrt(max(0.0, 1 - (rr / 0.75) ** 2))
        m.ball((math.cos(a) * rr, y, -math.sin(a) * rr), (0.16, 0.06, 0.16), WHITE, 1, lit=0.2)
    return m


def shrooms(name, seed):
    m, rnd = Model(name), random.Random(seed)
    for k in range(5):
        a, s = rnd.uniform(0, math.tau), rnd.uniform(0.45, 0.85)
        x, z = math.cos(a) * 0.5, -math.sin(a) * 0.5
        m.cyl((x, 0, z), 0.1 * s, 0.08 * s, 0.85 * s, (0.85, 0.78, 0.62), 8)
        m.dome((x, 0.82 * s, z), 0.4 * s, 0.22 * s, (0.5, 0.32, 0.16), 10, 2)
    return m


def glowshrooms(name, seed):
    m, rnd = Model(name), random.Random(seed)
    for k in range(5):
        a, s = rnd.uniform(0, math.tau), rnd.uniform(0.6, 1.0)
        x, z = math.cos(a) * 0.6, -math.sin(a) * 0.6
        m.cyl((x, 0, z), 0.06 * s, 0.05 * s, 0.55 * s, (0.6, 0.85, 1.0), 6, lit=0.6)
        m.dome((x, 0.52 * s, z), 0.24 * s, 0.14 * s, (0.3, 0.8, 1.0), 10, 2, lit=1.6)
    return m


FLOWERS = {"white": ((0.97, 0.97, 0.92), (1.0, 0.8, 0.1)), "blue": ((0.55, 0.45, 1.0), (1.0, 0.95, 0.4)), "pink": ((1.0, 0.5, 0.7), (1.0, 0.9, 0.3)),
           "yellow": ((1.0, 0.85, 0.15), (0.6, 0.3, 0.05)), "red": ((0.95, 0.25, 0.2), (0.1, 0.05, 0.05))}


def flower(name, petal, middle, h=1.05):
    m = Model(name)
    m.cyl((0, 0, 0), 0.04, 0.03, h, (0.2, 0.5, 0.15), 6)
    m.limb((0, h * 0.35, 0), (0.35, h * 0.5, 0.05), 0.09, 0.02, (0.25, 0.55, 0.18), 4)  # leaf
    for k in range(6):
        a = k / 6 * math.tau
        m.box((math.cos(a) * 0.2, h + 0.02, -math.sin(a) * 0.2), (0.34, 0.05, 0.17), petal, yaw=a, rz=0.0, rx=0.0, bevel=0.03, lit=0.25)
    m.dome((0, h + 0.03, 0), 0.12, 0.08, middle, 8, 2, lit=0.4)
    return m


def grass(name, seed, col):
    m, rnd = Model(name), random.Random(seed)
    for k in range(5):
        a = k * 1.3 + rnd.uniform(0, 0.6)
        h = rnd.uniform(0.6, 1.4)
        lean = rnd.uniform(0.12, 0.35)
        m.limb((math.cos(a) * 0.08, 0, -math.sin(a) * 0.08), (math.cos(a) * lean, h, -math.sin(a) * lean), 0.05, 0.005, col, 3)
    return m


def rock(name, seed, moss=True):
    m = Model(name)
    m.ball((0, 0.42, 0), (1.8, 0.95, 1.4), (0.44, 0.45, 0.42), 2, jitter=0.16, seed=seed)
    if moss:
        m.recolor_up(MOSS, 0.75)
    return m


def log(name, seed):
    m, rnd = Model(name), random.Random(seed)
    ln, r = 9.0, 0.85
    m.limb((-ln / 2, r, 0), (ln / 2, r, 0), r, r * 0.92, (0.33, 0.22, 0.13), 10)
    m.recolor_up(MOSS, 0.55)
    m.limb((ln / 2 - 0.01, r, 0), (ln / 2 + 0.03, r, 0), r * 0.82, r * 0.8, (0.75, 0.6, 0.4), 10)  # cut end, rings
    m.limb((ln / 2 + 0.02, r, 0), (ln / 2 + 0.05, r, 0), r * 0.45, r * 0.45, (0.55, 0.4, 0.25), 10)
    for k in range(3):  # shelf fungus
        f = (k - 1) * 0.25 * ln
        m.dome((f, r * 1.1, r * 0.95), 0.45, 0.14, (0.85, 0.6, 0.3), 8, 2, lit=0.15)
    return m


def lilypad(name):
    m = Model(name)
    n, r = 14, 0.75
    pts = [(0, 0.1, 0)] + [(math.cos(a) * r, 0.1, -math.sin(a) * r) for a in (0.35 + j / n * (math.tau - 0.7) for j in range(n + 1))]
    m.poly(pts, (0.22, 0.52, 0.2), thick=0.04)
    return m


def waterlily(name):
    m = Model(name)
    for k in range(8):
        a = k / 8 * math.tau
        m.box((math.cos(a) * 0.2, 0.28 + 0.06 * (k % 2), -math.sin(a) * 0.2), (0.42, 0.08, 0.16), (1.0, 0.7, 0.85), yaw=a, rz=0.35, bevel=0.03, lit=0.5)
    m.dome((0, 0.3, 0), 0.12, 0.1, (1.0, 0.9, 0.3), 8, 2, lit=0.8)
    return m


def cattail(name, seed):
    m, rnd = Model(name), random.Random(seed)
    for k in range(3):
        a = rnd.uniform(0, math.tau)
        x, z = math.cos(a) * 0.3, -math.sin(a) * 0.3
        h = rnd.uniform(2.4, 3.4)
        lean = rnd.uniform(-0.25, 0.25)
        m.limb((x, 0, z), (x + lean, h, z), 0.05, 0.03, (0.35, 0.55, 0.2), 5)
        if k != 1:
            m.limb((x + lean * 0.7, h * 0.68, z), (x + lean * 0.95, h * 0.95, z), 0.13, 0.11, (0.4, 0.22, 0.1), 6)
        m.limb((x, 0, z), (x + 0.3 * math.cos(a + 1), h * 0.7, z - 0.3 * math.sin(a + 1)), 0.09, 0.0, (0.3, 0.5, 0.18), 3)
    return m


def disc(name, col, seg=28, lit=0.0):
    m = Model(name)
    m.poly([(math.cos(a), 0.0, -math.sin(a)) for a in (j / seg * math.tau for j in range(seg))], col, lit)
    return m


def forest_models():
    out = [oak("oak_a", 1), oak("oak_b", 2), oak("oak_c", 3), pine("pine_a", 4), pine("pine_b", 5), birch("birch_a", 6), birch("birch_b", 7),
           bush("bush_a", 8), bush("bush_b", 9), bush("bush_berry", 10, True), fern("fern_a", 11), fern("fern_b", 12),
           toadstool("toadstool", 13), shrooms("shrooms", 14), glowshrooms("glowshrooms", 15),
           rock("rock_a", 16), rock("rock_b", 17), rock("rock_c", 18), rock("stone_a", 19, False), rock("stone_b", 20, False),
           log("log", 21), lilypad("lilypad"), waterlily("waterlily"), cattail("cattail_a", 22), cattail("cattail_b", 23),
           disc("water_deep", (0.1, 0.32, 0.4), lit=0.35), disc("water_light", (0.12, 0.4, 0.5), lit=0.45)]
    out += [flower(f"flower_{k}", p, c) for k, (p, c) in FLOWERS.items()]
    out += [grass("grass_a", 30, (0.25, 0.5, 0.14)), grass("grass_b", 31, (0.3, 0.58, 0.16)), grass("grass_c", 32, (0.4, 0.55, 0.2))]
    return out


# ------------------------------------------------------------ shared builders
def roof(m, cx, y0, cz, W, D, rise, col, ridge=0.55, curl=0.45, thick=0.32, n=8, hip=True):
    """A Japanese hip (or gable) roof as a closed shell: slopes rise from an eave rectangle to a ridge, and the corners of
    the eave turn up (`curl`). The underside is the same surface `thick` lower, joined by a fascia all round."""
    def eave_y(x, z):
        k = max(abs(x) / (W / 2), abs(z) / (D / 2))
        return y0 + curl * k ** 6
    rl = W * ridge / 2
    rings = []
    for off in (0.0, -thick):
        front = [((-W / 2 + W * j / n), (-rl + 2 * rl * j / n)) for j in range(n + 1)]
        F = [[(cx + ex, eave_y(ex, D / 2) + off, cz + D / 2) for ex, _ in front], [(cx + rx, y0 + rise + off, cz) for _, rx in front]]
        B = [[(cx + ex, eave_y(ex, D / 2) + off, cz - D / 2) for ex, _ in front], [(cx + rx, y0 + rise + off, cz) for _, rx in front]]
        side = [(-D / 2 + D * j / n) for j in range(n + 1)]
        Ls = [(cx - W / 2, eave_y(W / 2, z) + off, cz + z) for z in side]
        Rs = [(cx + W / 2, eave_y(W / 2, z) + off, cz + z) for z in side]
        rings.append((F, B, Ls, Rs, (cx - rl, y0 + rise + off, cz), (cx + rl, y0 + rise + off, cz)))
    polys = []
    for idx, (F, B, Ls, Rs, pl, pr) in enumerate(rings):
        up = idx == 0
        for j in range(n):
            q = [F[0][j], F[0][j + 1], F[1][j + 1], F[1][j]]
            polys.append(q if up else q[::-1])
            q = [B[0][j + 1], B[0][j], B[1][j], B[1][j + 1]]
            polys.append(q if up else q[::-1])
            q = [Ls[j], Ls[j + 1], pl]
            polys.append(q[::-1] if up else q)
            q = [Rs[j + 1], Rs[j], pr]
            polys.append(q[::-1] if up else q)
    (F0, B0, L0, R0, _, _), (F1, B1, L1, R1, _, _) = rings
    for top, bot in ((F0[0], F1[0]), (B0[0][::-1], B1[0][::-1]), (L0[::-1], L1[::-1]), (R0, R1)):
        for j in range(len(top) - 1):
            polys.append([top[j + 1], top[j], bot[j], bot[j + 1]])
    m.faces(polys, col)


def beam(m, pts, h, d, col, lit=0.0):
    """A beam following a 2D curve (x, y) in the z=0 plane: one chamfered block per segment."""
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        ang = math.atan2(y1 - y0, x1 - x0)
        m.box(((x0 + x1) / 2, (y0 + y1) / 2, 0), (math.hypot(x1 - x0, y1 - y0) + 0.06, h, d), col, rz=ang, bevel=0.05, lit=lit)


def lathe(m, profile, col, seg=16, lit=0.0, axis="y", center=(0, 0, 0), lobes=0, lobe_amt=0.0):
    """A surface of revolution from (radius, height) pairs; `lobes` ribs the surface (pumpkins)."""
    cx, cy, cz = center
    rows = []
    for rr, hh in profile:
        row = []
        for j in range(seg):
            a = j / seg * math.tau
            k = 1 + lobe_amt * math.cos(lobes * a) if lobes else 1.0
            u, v = math.cos(a) * rr * k, math.sin(a) * rr * k
            if axis == "y":
                row.append((cx + u, cy + hh, cz + v))
            else:  # axis along z (rolling things seen end-on)
                row.append((cx + u, cy + v, cz + hh))
        rows.append(row)
    polys = []
    for a, b in zip(rows, rows[1:]):
        for j in range(seg):
            q = [a[j], a[(j + 1) % seg], b[(j + 1) % seg], b[j]]
            polys.append(q if axis == "y" else q[::-1])
    polys.append(rows[0][::-1] if axis == "y" else rows[0])
    polys.append(rows[-1] if axis == "y" else rows[-1][::-1])
    m.faces(polys, col, lit)


# ------------------------------------------------------------ sakura
BARK_S, RED, BLACK = (0.24, 0.13, 0.11), (0.82, 0.16, 0.1), (0.06, 0.05, 0.06)
WOOD, DARKWOOD, PAPER, TILE = (0.46, 0.3, 0.18), (0.22, 0.13, 0.09), (1.0, 0.93, 0.78), (0.2, 0.21, 0.25)


def cherry(name, seed):
    m, rnd = Model(name), random.Random(seed)
    lean = rnd.uniform(0, math.tau)
    p0 = (0, 0, 0)
    p1 = (math.cos(lean) * 0.8, 3.2, -math.sin(lean) * 0.8)
    p2 = (p1[0] - math.cos(lean) * 0.6, 5.6, p1[2] + math.sin(lean) * 0.6)
    m.limb(p0, p1, 0.62, 0.46, BARK_S, 9)
    m.limb(p1, p2, 0.48, 0.36, BARK_S, 9)
    for k in range(4):
        a = k * math.pi / 2 + 0.3
        m.limb((0, 0.7, 0), (math.cos(a) * 1.4, 0.0, -math.sin(a) * 1.4), 0.3, 0.1, BARK_S, 6)
    tips = []
    for k in range(6):
        a = k / 6 * math.tau + rnd.uniform(-0.3, 0.3)
        ln = rnd.uniform(3.0, 4.8)
        mid = (p2[0] + math.cos(a) * ln * 0.5, p2[1] + rnd.uniform(0.8, 1.6), p2[2] - math.sin(a) * ln * 0.5)
        tip = (p2[0] + math.cos(a) * ln, p2[1] + rnd.uniform(1.0, 2.6), p2[2] - math.sin(a) * ln)
        m.limb(p2, mid, 0.26, 0.17, BARK_S, 7)
        m.limb(mid, tip, 0.17, 0.08, BARK_S, 6)
        tips += [mid, tip]
    for k in range(34):
        bx, by, bz = rnd.choice(tips)
        cs = rnd.uniform(1.4, 2.6)
        m.box((bx + rnd.uniform(-1.4, 1.4), by + rnd.uniform(-0.3, 1.2), bz + rnd.uniform(-1.4, 1.4)), (cs, cs * 0.62, cs),
              rnd.choice(PINKS), yaw=rnd.uniform(0, 1.5), bevel=0.3, lit=0.3)
    for k in range(6):  # fallen petals under the tree
        a, rr = rnd.uniform(0, math.tau), rnd.uniform(1.5, 6.5)
        ps = rnd.uniform(1.2, 2.8)
        m.box((math.cos(a) * rr, 0.02, -math.sin(a) * rr), (ps, 0.04, ps * 0.7), rnd.choice(PINKS), yaw=rnd.uniform(0, 3), bevel=0.0, lit=0.2)
    return m


def house(name):
    m = Model(name)
    W, D = 14.0, 10.0
    for lx in (-W / 2 + 0.5, 0.0, W / 2 - 0.5):
        for lz in (-D / 2 + 0.5, D / 2 - 0.5):
            m.box((lx, 0.35, lz), (0.9, 0.7, 0.9), STONE, bevel=0.12)
    m.box((0, 0.85, 0), (W, 0.3, D), WOOD, bevel=0.06)
    m.box((0, 0.9, D / 2 + 1.0), (W + 1.0, 0.16, 2.0), (0.55, 0.38, 0.22), bevel=0.04)
    for k in range(9):  # veranda boards
        m.box((-W / 2 - 0.4 + (W + 0.8) * (k + 0.5) / 9, 0.99, D / 2 + 1.0), (0.04, 0.02, 1.9), (0.42, 0.28, 0.16), bevel=0.0)
    m.box((0, 0.45, D / 2 + 2.3), (2.2, 0.3, 1.0), STONE, bevel=0.1)
    post_x = [-W / 2, -W / 2 + 3.5, -1.0, 1.0, W / 2 - 3.5, W / 2]
    for lx in post_x:
        for lz in (-D / 2, D / 2):
            m.box((lx, 2.95, lz), (0.32, 4.0, 0.32), DARKWOOD, bevel=0.04)
    for lz in (-D / 2 + 3.3, D / 2 - 3.3):
        for lx in (-W / 2, W / 2):
            m.box((lx, 2.95, lz), (0.32, 4.0, 0.32), DARKWOOD, bevel=0.04)
    for k in range(len(post_x) - 1):  # shoji: glowing paper in a dark lattice
        a, b = post_x[k], post_x[k + 1]
        if b - a < 2.5:
            continue
        cx, pw = (a + b) / 2, b - a - 0.32
        m.box((cx, 2.95, D / 2), (pw, 3.9, 0.1), PAPER, bevel=0.0, lit=0.9)
        for gy in (1.9, 2.95, 4.0):
            m.box((cx, gy, D / 2 + 0.07), (pw, 0.06, 0.05), DARKWOOD, bevel=0.0)
        for gx in (-pw / 3, 0.0, pw / 3):
            m.box((cx + gx, 2.95, D / 2 + 0.07), (0.06, 3.9, 0.05), DARKWOOD, bevel=0.0)
    m.box((0, 2.4, D / 2 - 0.4), (1.7, 2.9, 0.1), (0.15, 0.08, 0.05), bevel=0.0)
    for k in (-0.45, 0.45):  # noren curtain
        m.box((k, 4.25, D / 2 + 0.06), (0.85, 1.0, 0.04), (0.12, 0.18, 0.4), bevel=0.0, lit=0.15)
    m.box((0, 4.4, D / 2 + 0.09), (0.4, 0.4, 0.03), (0.95, 0.95, 0.9), bevel=0.0, lit=0.3)
    for lx in (-W / 2, W / 2):
        m.box((lx, 2.95, 0), (0.14, 3.9, D), (0.92, 0.9, 0.84), bevel=0.0, lit=0.15)
        m.box((lx, 4.7, 0), (0.22, 0.3, D), DARKWOOD, bevel=0.03)
    m.box((0, 2.95, -D / 2), (W, 3.9, 0.14), (0.4, 0.27, 0.17), bevel=0.0)
    m.box((0, 4.95, 0), (W + 0.4, 0.3, D + 0.4), DARKWOOD, bevel=0.05)
    roof(m, 0, 5.15, 0, W + 3.4, D + 3.4, 2.5, TILE, ridge=0.6, curl=0.55)
    m.box((0, 7.75, 0), (W * 0.62, 0.45, 0.7), (0.12, 0.12, 0.15), bevel=0.08)  # ridge
    for sx in (-1, 1):
        m.box((sx * W * 0.31, 8.05, 0), (0.6, 0.8, 0.8), (0.12, 0.12, 0.15), bevel=0.12)  # onigawara end tiles
    return m


def pagoda(name):
    m = Model(name)
    s = 1.0
    m.box((0, 0.6, 0), (12, 1.2, 12), STONE, bevel=0.15)
    y = 1.2
    for k in range(5):
        bw, bh = 8.0 - k * 1.1, 4.2
        m.box((0, y + bh / 2, 0), (bw, bh, bw), (0.75, 0.2, 0.12), bevel=0.08, lit=0.1)
        for sd in range(4):  # paper windows on each face
            a = sd * math.pi / 2
            m.box((math.sin(a) * bw / 2, y + bh / 2, math.cos(a) * bw / 2), (bw * 0.5, bh * 0.55, 0.06), PAPER, yaw=a, bevel=0.0, lit=0.7)
        m.box((0, y + bh - 0.2, 0), (bw + 0.6, 0.35, bw + 0.6), DARKWOOD, bevel=0.06)  # railing band
        rw = bw + 4.4
        roof(m, 0, y + bh, 0, rw, rw, 1.6, TILE, ridge=0.18, curl=0.7, thick=0.35)
        y += bh + 1.3
    m.cyl((0, y - 0.4, 0), 0.25, 0.18, 8, (0.8, 0.65, 0.25), 8, lit=0.4)
    for k in range(7):
        m.cyl((0, y + 0.8 + k * 0.95, 0), 0.65 - k * 0.04, 0.65 - k * 0.04, 0.22, (0.85, 0.7, 0.3), 12, lit=0.4)
    m.ball((0, y + 8.0, 0), (0.7, 0.9, 0.7), (0.9, 0.75, 0.3), 2, lit=0.6)
    return m


def torii(name):
    m = Model(name)
    for sx in (-1, 1):
        m.cyl((sx * 4.5, 0.8, 0), 0.47, 0.4, 9.4, RED, 14, lit=0.25)
        m.cyl((sx * 4.5, 0, 0), 0.68, 0.62, 0.8, BLACK, 14)
    m.box((0, 7.6, 0), (11.5, 0.6, 0.55), RED, bevel=0.06, lit=0.25)  # nuki
    m.box((0, 9.9, 0), (12.5, 0.6, 0.95), RED, bevel=0.06, lit=0.25)  # shimaki
    curve = [(-7.4 + 14.8 * j / 12, 10.5 + 0.55 * abs((j - 6) / 6) ** 2.5) for j in range(13)]  # kasagi: the top beam sweeps up
    beam(m, curve, 0.55, 1.35, BLACK)
    m.box((0, 8.8, 0.05), (1.3, 1.8, 0.4), BLACK, bevel=0.06)  # gakuzuka with its plaque
    m.box((0, 8.8, 0.27), (0.9, 1.3, 0.05), (0.85, 0.7, 0.3), bevel=0.0, lit=0.5)
    return m


def stone_lantern(name):
    m = Model(name)
    m.cyl((0, 0, 0), 0.85, 0.8, 0.5, STONE, 6)
    m.cyl((0, 0.5, 0), 0.3, 0.26, 1.8, STONE, 6)
    m.cyl((0, 2.3, 0), 0.75, 0.6, 0.35, STONE, 6)
    m.cyl((0, 2.65, 0), 0.55, 0.55, 1.0, STONE, 6)
    for sd in range(3):
        a = sd * math.pi / 3
        m.box((0, 3.15, 0), (1.14, 0.48, 0.42), (1.0, 0.8, 0.4), yaw=a, bevel=0.0, lit=1.8)  # light through the windows
    m.cyl((0, 3.65, 0), 1.15, 0.55, 0.55, STONE, 6)
    m.cyl((0, 4.2, 0), 0.4, 0.2, 0.4, STONE, 6)
    m.ball((0, 4.75, 0), (0.42, 0.55, 0.42), STONE, 2)
    return m


def bridge(name, span=35.0, rise=3.4):
    m = Model(name)
    n = 18
    pts = [(-span / 2 + span * k / n, 0.3 + rise * (1 - (2 * k / n - 1) ** 2)) for k in range(n + 1)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        ang = math.atan2(y1 - y0, x1 - x0)
        ln = math.hypot(x1 - x0, y1 - y0) + 0.04
        m.box(((x0 + x1) / 2, (y0 + y1) / 2, 0), (ln, 0.28, 3.2), (0.55, 0.32, 0.18), rz=ang, bevel=0.04)
        for sz in (-1, 1):
            m.box(((x0 + x1) / 2, (y0 + y1) / 2 - 0.28, sz * 1.65), (ln, 0.4, 0.26), RED, rz=ang, bevel=0.04, lit=0.25)
            m.box(((x0 + x1) / 2, (y0 + y1) / 2 + 1.25, sz * 1.65), (ln, 0.2, 0.22), RED, rz=ang, bevel=0.04, lit=0.25)
    for k in range(0, n + 1, 2):
        px, py = pts[k]
        for sz in (-1, 1):
            tall = k in (0, n)
            m.cyl((px, py - 0.1, sz * 1.65), 0.14, 0.13, 1.5 if not tall else 2.0, RED, 8, lit=0.25)
            if tall:
                m.ball((px, py + 2.05, sz * 1.65), (0.42, 0.55, 0.42), (0.85, 0.7, 0.3), 2, lit=0.5)  # giboshi caps
    return m


def bamboo(name, seed):
    m, rnd = Model(name), random.Random(seed)
    for k in range(rnd.randint(13, 18)):
        a, rr = rnd.uniform(0, math.tau), rnd.uniform(0, 3.0)
        bx, bz = math.cos(a) * rr, -math.sin(a) * rr
        h = rnd.uniform(9, 15)
        lean = rnd.uniform(-0.5, 0.5)
        g = rnd.choice([(0.38, 0.6, 0.2), (0.45, 0.65, 0.22), (0.32, 0.55, 0.18)])
        top = (bx + lean, h, bz)
        m.limb((bx, 0, bz), top, 0.16, 0.12, g, 8)
        for yy in np.arange(1.4, h - 0.5, 1.5):
            f = yy / h
            m.cyl((bx + lean * f, yy, bz), 0.19, 0.19, 0.1, (0.6, 0.72, 0.35), 8)
        for q in range(6):
            la = rnd.uniform(0, math.tau)
            yy = h - rnd.uniform(0, 3.0)
            base = (bx + lean * yy / h, yy, bz)
            m.limb(base, (base[0] + math.cos(la) * 1.7, yy - 0.5, base[2] - math.sin(la) * 1.7), 0.12, 0.01, (0.35, 0.6, 0.2), 3)
    return m


def azalea(name, seed, flowers):
    m, rnd = Model(name), random.Random(seed)
    for k in range(3):
        m.box(((k - 1) * 0.6, 0.7, 0), (1.8, 1.4, 1.8), (0.18, 0.4, 0.15), yaw=k * 0.5, bevel=0.35)
    if flowers:
        for k in range(12):
            a = rnd.uniform(0, math.tau)
            m.ball((math.cos(a) * 1.05, rnd.uniform(0.8, 1.5), -math.sin(a) * 1.0), (0.32, 0.22, 0.32), (1.0, 0.45, 0.65), 1, lit=0.6)
    return m


def paper_lantern(name, col):
    m = Model(name)
    prof = [(0.32, -0.62), (0.46, -0.45), (0.53, -0.2), (0.55, 0.0), (0.53, 0.2), (0.46, 0.45), (0.32, 0.62)]
    lathe(m, prof, col, 12, lit=1.4)
    for _, hh in prof[1:-1]:
        r_ = dict((h, r) for r, h in prof)[hh]
        m.cyl((0, hh - 0.02, 0), r_ + 0.015, r_ + 0.015, 0.04, tuple(c * 0.45 for c in col), 12, lit=0.5)  # ribs
    for yy in (-0.72, 0.62):
        m.cyl((0, yy, 0), 0.36, 0.36, 0.12, BLACK, 12)
    return m


def fuji(name):
    m = Model(name)
    seg = 28
    prof = [(1.0 * (1 - f) ** 1.7 + 0.05, f) for f in (j / 14 for j in range(15))]
    lo = [(r, h) for r, h in prof if h <= 0.62]
    hi = [(r, h) for r, h in prof if h >= 0.58]
    lathe(m, [(r * 140, h * 100) for r, h in lo], (0.3, 0.31, 0.46), seg)
    lathe(m, [(r * 140, h * 100) for r, h in hi], (0.95, 0.95, 1.0), seg, lit=0.4)
    return m


def iris(name):
    m = Model(name)
    m.cyl((0, 0, 0), 0.04, 0.03, 1.8, (0.25, 0.5, 0.2), 6)
    for a in (0.4, 2.5, 4.4):
        m.limb((0, 0, 0), (math.cos(a) * 0.3, 1.5, -math.sin(a) * 0.3), 0.08, 0.0, (0.3, 0.55, 0.22), 3)
    for k in range(3):
        a = k / 3 * math.tau
        m.box((math.cos(a) * 0.2, 1.8, -math.sin(a) * 0.2), (0.45, 0.06, 0.2), (0.5, 0.3, 0.85), yaw=a, rz=-0.5, bevel=0.03, lit=0.4)
        m.box((math.cos(a + 1) * 0.08, 1.95, -math.sin(a + 1) * 0.08), (0.12, 0.3, 0.1), (0.6, 0.4, 0.95), yaw=a, bevel=0.02, lit=0.4)
    return m


def zen(name):
    m = Model(name)
    W, D = 20.0, 13.0
    m.box((0, 0.06, 0), (W, 0.12, D), (0.82, 0.8, 0.74), bevel=0.0, lit=0.1)
    for sx in (-1, 1):
        m.box((sx * W / 2, 0.15, 0), (0.4, 0.3, D + 0.4), DARKWOOD, bevel=0.05)
    for sz in (-1, 1):
        m.box((0, 0.15, sz * D / 2), (W + 0.4, 0.3, 0.4), DARKWOOD, bevel=0.05)
    rocks = [(-5.0, -1.5, 1.6), (3.5, 2.0, 1.1), (6.5, -3.0, 0.8)]
    for k in range(-11, 12):
        lz = k * 0.55
        segs = [(-W / 2 + 0.3, W / 2 - 0.3)]
        for rx, rz_, rs in rocks:  # rake lines stop at the rings around each rock
            if abs(lz - rz_) < rs + 2.0:
                half = math.sqrt(max((rs + 2.0) ** 2 - (lz - rz_) ** 2, 0))
                segs = [s for a, b in segs for s in ((a, min(b, rx - half)), (max(a, rx + half), b)) if s[1] - s[0] > 0.2]
        for a, b in segs:
            m.box(((a + b) / 2, 0.13, lz), (b - a, 0.03, 0.08), (0.68, 0.66, 0.6), bevel=0.0)
    for rx, rz_, rs in rocks:
        for ring in (rs + 0.6, rs + 1.2, rs + 1.8):
            pts = [(rx + math.cos(a) * ring, 0.13, rz_ + math.sin(a) * ring) for a in (j / 32 * math.tau for j in range(33))]
            for p0, p1 in zip(pts, pts[1:]):
                m.limb(p0, p1, 0.04, 0.04, (0.68, 0.66, 0.6), 3)
        m.ball((rx, 0.55 * rs, rz_), (2.0 * rs, 1.3 * rs, 1.6 * rs), (0.38, 0.38, 0.38), 2, jitter=0.15, seed=int(rx * 10))
        m.recolor_up((0.34, 0.45, 0.28), 0.7)
    return m


def step_stone(name, seed):
    m = Model(name)
    m.ball((0, 0.04, 0), (1.8, 0.22, 1.4), (0.55, 0.54, 0.5), 2, jitter=0.12, seed=seed)
    return m


def creature_models():
    m = Model("cbox")  # the part every animated creature is built from: a unit block with chamfered edges
    m.box((0, 0, 0), (1, 1, 1), (1, 1, 1), bevel=0.14)
    return [m]


def sakura_models():
    return ([cherry("cherry_a", 101), cherry("cherry_b", 102), cherry("cherry_c", 103), cherry("cherry_d", 104), house("jhouse"),
             pagoda("pagoda"), torii("torii"), stone_lantern("toro"), bridge("taiko_bridge"), bamboo("bamboo_a", 105), bamboo("bamboo_b", 106),
             azalea("azalea", 107, False), azalea("azalea_flower", 108, True), paper_lantern("lantern_red", (1.0, 0.28, 0.16)),
             paper_lantern("lantern_white", (1.0, 0.95, 0.85)), fuji("fuji"), iris("iris"), zen("zen_garden"),
             step_stone("step_a", 109), step_stone("step_b", 110)])


# ------------------------------------------------------------ halloween
GSTONE, EARTH, DEAD = (0.38, 0.4, 0.46), (0.14, 0.1, 0.06), (0.1, 0.07, 0.08)


def grave(name, kind, seed):
    m, rnd = Model(name), random.Random(seed)
    h = 2.4
    m.box((0, 0.1, 0.3), (1.9, 0.22, 2.3), EARTH, bevel=0.1)  # earth mound
    m.box((0, 0.22, 0.3), (1.6, 0.12, 1.9), EARTH, bevel=0.06)
    if kind == "round":
        m.box((0, h / 2, 0), (1.5, h, 0.42), GSTONE, bevel=0.08)
        lathe(m, [(0.75, -0.21), (0.75, 0.21)], GSTONE, 16, axis="z", center=(0, h, 0))  # rounded top (half sunk into the slab)
        m.box((0, h * 0.62, 0.22), (0.9, 0.08, 0.02), (0.25, 0.27, 0.32), bevel=0.0)  # carved lines
        m.box((0, h * 0.5, 0.22), (0.7, 0.06, 0.02), (0.25, 0.27, 0.32), bevel=0.0)
    elif kind == "cross":
        m.box((0, 1.5, 0), (0.45, 3.0, 0.42), GSTONE, bevel=0.06)
        m.box((0, 2.2, 0), (1.7, 0.42, 0.42), GSTONE, bevel=0.06)
        m.box((0, 0.3, 0), (1.0, 0.6, 0.7), GSTONE, bevel=0.08)
    else:  # an old slab, cracked and leaning
        m.box((0, 1.2, 0), (1.4, 2.4, 0.38), GSTONE, rx=-0.12, rz=0.08, bevel=0.1)
        m.box((0.2, 1.6, 0.25), (0.06, 0.9, 0.02), (0.2, 0.2, 0.25), rx=-0.12, rz=0.4, bevel=0.0)
    m.recolor_up((0.3, 0.38, 0.28), 0.85)  # a little moss on the tops
    return m


def dead_tree(name, seed):
    m, rnd = Model(name), random.Random(seed)
    h = 12.0
    m.cyl((0, 0, 0), 0.75, 0.3, h, DEAD, 8)
    for k in range(4):
        a = k / 4 * math.tau + 0.4
        m.limb((0, 0.8, 0), (math.cos(a) * 1.6, 0.0, -math.sin(a) * 1.6), 0.38, 0.1, DEAD, 6)
    for k in range(6):
        y = h * (0.42 + 0.09 * k)
        a = k * 2.3 + rnd.uniform(-0.3, 0.3)
        p1 = (math.cos(a) * 3.0, y + 1.0, -math.sin(a) * 3.0)
        m.limb((0, y, 0), p1, 0.22, 0.12, DEAD, 6)
        for q in (-1, 1):  # forked twigs
            p2 = (p1[0] + math.cos(a + q * 0.6) * 1.6, p1[1] + 1.2, p1[2] - math.sin(a + q * 0.6) * 1.6)
            m.limb(p1, p2, 0.11, 0.03, DEAD, 5)
    return m


def fence(name):
    m = Model(name)
    iron = (0.05, 0.05, 0.07)
    for k in range(-2, 3):
        x = k * 1.4
        m.cyl((x, 0, 0), 0.08, 0.08, 2.6, iron, 6)
        m.cyl((x, 2.6, 0), 0.16, 0.0, 0.45, iron, 6)  # spear tip
    for y in (0.6, 2.2):
        m.box((0, y, 0), (7.2, 0.12, 0.12), iron, bevel=0.02)
    return m


def haunted_house(name):
    m = Model(name)
    dark, roofc = (0.08, 0.06, 0.1), (0.05, 0.03, 0.07)
    m.box((0, 11, 0), (38, 22, 20), dark, bevel=0.3)
    roof(m, 0, 22, 0, 41, 23, 7, roofc, ridge=0.75, curl=0.2, thick=0.5)
    m.box((-10, 28, 0), (14, 6, 16), dark, bevel=0.25)
    roof(m, -10, 31, 0, 16, 18, 4, roofc, ridge=0.6, curl=0.1, thick=0.4)
    m.box((16, 17, 2), (8, 34, 8), dark, bevel=0.25)  # tower
    roof(m, 16, 34, 2, 10, 10, 9, roofc, ridge=0.0, curl=0.25, thick=0.4)
    m.box((12, 30, -6), (2.4, 10, 2.4), (0.12, 0.08, 0.1), bevel=0.15)  # chimney
    for i in range(5):  # window frames (the lights flicker on top of these every frame)
        m.box((-14 + i * 7, 12 + (i % 2) * 6, 10.05), (3.0, 4.0, 0.3), (0.15, 0.1, 0.12), bevel=0.06)
    m.box((0, 3, 10.1), (4.2, 6.4, 0.4), (0.12, 0.08, 0.1), bevel=0.08)  # door frame
    m.box((0, 0.4, 13), (8, 0.8, 6), dark, bevel=0.1)  # porch
    for sx in (-1, 1):
        m.cyl((sx * 3.6, 0.8, 15.5), 0.25, 0.25, 6.0, dark, 6)
    m.box((0, 7.0, 13.2), (9, 0.5, 6.5), roofc, rx=0.25, bevel=0.06)
    return m


def pumpkin(name):
    """A ribbed jack-o'-lantern rolling about the z axle: lobes around the vertical, a carved glowing face on both sides."""
    m = Model(name)
    prof = [(0.12, -0.5), (0.36, -0.44), (0.52, -0.28), (0.57, 0.0), (0.52, 0.28), (0.36, 0.44), (0.12, 0.5)]
    lathe(m, [(r, h) for r, h in prof], (1.0, 0.45, 0.05), 24, lit=0.35, lobes=8, lobe_amt=0.07)
    m.limb((0, 0.45, 0), (0.06, 0.72, 0.02), 0.08, 0.05, (0.25, 0.55, 0.1), 6)
    lit = (1.0, 0.85, 0.25)
    for sz in (-1, 1):
        f = sz * 0.5
        for sx in (-1, 1):  # triangle eyes
            m.faces([[(sx * 0.18 - 0.08, 0.06, f), (sx * 0.18 + 0.08, 0.06, f), (sx * 0.18, 0.2, f)][::sz]], lit, lit=1.6)
        m.faces([[(-0.06, -0.04, f), (0.06, -0.04, f), (0.0, 0.06, f)][::sz]], lit, lit=1.6)  # nose
        mouth = [(-0.28, -0.14), (-0.14, -0.2), (-0.07, -0.14), (0.0, -0.21), (0.07, -0.14), (0.14, -0.2), (0.28, -0.14), (0.0, -0.3)]
        m.faces([[(x, y, f) for x, y in (mouth if sz > 0 else mouth[::-1])]], lit, lit=1.6)
    return m


def barrel(name):
    """A wooden barrel lying on its side (axle along z) with hoops and a cross on the lid."""
    m = Model(name)
    prof = [(0.44, -0.48), (0.52, -0.3), (0.55, 0.0), (0.52, 0.3), (0.44, 0.48)]
    lathe(m, prof, (0.62, 0.36, 0.14), 16, axis="z", lit=0.15)
    for h in (-0.36, 0.36):
        lathe(m, [(0.535, h - 0.04), (0.545, h + 0.04)], (0.25, 0.16, 0.08), 16, axis="z")
    for sz in (-1, 1):
        for a in (0.0, math.pi / 2):
            m.box((0, 0, sz * 0.485), (0.8, 0.1, 0.03), (0.25, 0.16, 0.08), rz=a, bevel=0.0)
    return m


def moon(name):
    m = Model(name)
    lathe(m, [(0.5, -0.02), (0.5, 0.02)], (1.0, 0.96, 0.78), 32, axis="z", lit=1.8)
    for (x, y, r) in [(0.18, 0.12, 0.1), (-0.15, -0.2, 0.08), (-0.2, 0.18, 0.05), (0.1, -0.1, 0.04)]:
        lathe(m, [(r, 0.02), (r * 0.8, 0.03)], (0.82, 0.78, 0.6), 12, axis="z", center=(x, y, 0), lit=1.0)
    return m


def halloween_models():
    return [grave("grave_round", "round", 201), grave("grave_cross", "cross", 202), grave("grave_slab", "slab", 203),
            dead_tree("dead_tree_a", 204), dead_tree("dead_tree_b", 205), fence("iron_fence"), haunted_house("haunted_house"),
            pumpkin("pumpkin"), barrel("barrel"), moon("moon")]


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    path = argv[0] if argv else "models.npz"
    models = forest_models()
    for extra in ("sakura_models", "halloween_models", "creature_models"):
        fn = globals().get(extra)
        if fn:
            models += fn()
    export(models, path)
    if "--blend" in argv:  # optional: save a .blend to look at / tweak the models by hand
        for m in models:
            me = bpy.data.meshes.new(m.name)
            m.bm.to_mesh(me)
            ob = bpy.data.objects.new(m.name, me)
            bpy.context.scene.collection.objects.link(ob)
        bpy.ops.wm.save_as_mainfile(filepath=argv[argv.index("--blend") + 1])


if __name__ == "__main__":
    main()
