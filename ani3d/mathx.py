"""Tiny 4x4 matrix helpers. Matrices are column-vector style (v' = M @ v); `gpu()` uploads them column-major."""
import math

import numpy as np


def perspective(fovy, aspect, near, far):
    f = 1.0 / math.tan(fovy / 2)
    return np.array([
        [f / aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, far / (near - far), near * far / (near - far)],  # depth range 0..1 (wgpu)
        [0, 0, -1, 0],
    ], dtype=np.float64)


def look_at(eye, target, up=(0, 1, 0)):
    eye, target, up = (np.asarray(v, dtype=np.float64) for v in (eye, target, up))
    z = eye - target
    z /= np.linalg.norm(z)
    x = np.cross(up, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = x, y, z
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def translate(x, y, z):
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def scale(x, y, z):
    return np.diag([x, y, z, 1.0])


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    return m


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    return m


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    return m


def ortho_px(w, h):
    """Pixel coordinates, origin top-left, y down."""
    return np.array([[2 / w, 0, 0, -1], [0, -2 / h, 0, 1], [0, 0, 0, 0], [0, 0, 0, 1]], dtype=np.float64)


def gpu(m):
    return np.ascontiguousarray(m.T, dtype=np.float32)


def unproject(inv_viewproj, ndc_x, ndc_y, ndc_z):
    p = inv_viewproj @ np.array([ndc_x, ndc_y, ndc_z, 1.0])
    return p[:3] / p[3]
