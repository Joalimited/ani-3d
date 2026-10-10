"""Blender-made models (built by tools/blender_models.py into models/models.npz) placed as instances.

A MeshSet collects instances by model name in the same row format as scene.box, freezes them into numpy blocks once, and
hands them to the renderer every frame. Instances can carry an anchor (x, z) so ground cover can be hidden wherever a
section platform currently stands.
"""
import os

import numpy as np

from . import paths
from .scene import box

_AVAILABLE = None


def available():
    """True when the model file ships with the app (otherwise the themes fall back to their box-built scenery)."""
    global _AVAILABLE
    if _AVAILABLE is None:
        _AVAILABLE = os.path.exists(paths.resource("models", "models.npz"))
    return _AVAILABLE


class MeshSet:
    def __init__(self):
        self.rows, self.anchors = {}, {}
        self.blocks, self.xz = {}, {}
        self._key, self._vis = None, {}

    def put(self, name, x, y, z, s=1.0, yaw=0.0, glow=0.0, edge=0.14, tint=(1.0, 1.0, 1.0), rz=0.0, rx=0.0, anchor=None):
        sx, sy, sz = s if isinstance(s, tuple) else (s, s, s)
        self.rows.setdefault(name, []).append(box(x, y, z, sx, sy, sz, tint, glow, yaw, edge, 0.0, 0.0, rz, rx))
        self.anchors.setdefault(name, []).append(anchor if anchor is not None else (1e9, 1e9))

    def freeze(self):
        self.blocks = {k: np.array(v, dtype=np.float32) for k, v in self.rows.items()}
        self.xz = {k: np.array(self.anchors[k], dtype=np.float32) for k in self.rows}
        self._vis = dict(self.blocks)
        return self

    def draw(self, r, platforms=None):
        """Send every instance to the renderer; anchored ones under a platform rectangle are left out."""
        if platforms is not None:
            key = tuple(tuple(round(v, 1) for v in p) for p in platforms)
            if key != self._key:
                self._key = key
                self._vis = {}
                for k, blk in self.blocks.items():
                    keep = np.ones(len(blk), dtype=bool)
                    xz = self.xz[k]
                    for cx, cz, hw, hd in platforms:
                        keep &= ~((np.abs(xz[:, 0] - cx) < hw) & (np.abs(xz[:, 1] - cz) < hd))
                    self._vis[k] = blk[keep]
        for k, blk in (self._vis if platforms is not None else self.blocks).items():
            r.add_mesh(k, blk)


def creature_parts(r, rows, out):
    """Animated creature parts: drawn with the chamfered Blender block ("cbox") so bodies, heads and limbs get softened
    edges and tapered ends, while every rig keeps animating exactly as before. Falls back to plain boxes."""
    if r is not None and rows and r.has_mesh("cbox"):
        r.add_mesh("cbox", rows)
    else:
        out.extend(rows)
