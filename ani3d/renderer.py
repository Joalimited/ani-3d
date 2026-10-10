"""wgpu renderer (Vulkan on Linux, Direct3D 12 or Vulkan on Windows): floor grid, instanced neon boxes, textured quads (3D billboards + HUD)."""
import sys

import numpy as np
import wgpu

from . import mathx, shaders

MSAA = 4
DEPTH = "depth24plus"
BOX_STRIDE = 16  # floats per instance: pos(3) glow(1) scale(3) yaw(1) color(4) pitch(1) flat(1) rollz(1) rollx(1)
MAX_BOXES = 32768  # the forest theme alone is ~6k
SLOT = 256  # uniform slot size (min dynamic offset alignment)
MAX_QUADS = 6000
MAX_MESH_INST = 32768
MESH_STRIDE = 13  # floats per mesh vertex: pos(3) normal(3) colour(4: rgb + self-lit) edge distances(3)


def pick_adapter():
    """Prefer the discrete GPU on the Vulkan backend, never the CPU rasteriser."""
    ok_backends = ("Vulkan", "D3D12", "Metal") if sys.platform != "linux" else ("Vulkan",)  # Windows: Direct3D 12 or Vulkan
    try:  # fast path: ask for the high-performance adapter directly (enumerating every adapter costs ~270 ms)
        ad = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        if ad.info.get("backend_type") in ok_backends and ad.info.get("adapter_type") in ("DiscreteGPU", "IntegratedGPU"):
            return ad
    except Exception:  # noqa: BLE001
        pass
    adapters = [a for a in wgpu.gpu.enumerate_adapters_sync() if a.info.get("backend_type") in ok_backends]
    for kind in ("DiscreteGPU", "IntegratedGPU"):
        for a in adapters:
            if a.info.get("adapter_type") == kind:
                return a
    if adapters:
        return adapters[0]
    raise RuntimeError("No usable GPU adapter found (needs a Vulkan or Direct3D 12 capable graphics driver)")


def cube_vertices():
    faces = [  # normal, then four corners (counter-clockwise seen from outside)
        ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
        ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
        ((1, 0, 0), [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)]),
        ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
        ((0, 1, 0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
        ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
    ]
    out = []
    for n, c in faces:
        for i in (0, 1, 2, 0, 2, 3):
            out.append([c[i][0] * 0.5, c[i][1] * 0.5, c[i][2] * 0.5, *n])
    return np.array(out, dtype=np.float32)


class Tex:
    def __init__(self, bind_group, w, h):
        self.bind_group, self.w, self.h = bind_group, w, h


class Renderer:
    def __init__(self, fmt="bgra8unorm"):
        self.adapter = pick_adapter()
        self.device = self.adapter.request_device_sync(required_features=[])
        self.fmt = fmt
        d = self.device
        self.size = (0, 0)
        self.msaa_view = self.depth_view = None

        # uniforms
        self.globals_buf = d.create_buffer(size=256, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        g_layout = d.create_bind_group_layout(entries=[{
            "binding": 0, "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
            "buffer": {"type": "uniform"}}])
        self.globals_bg = d.create_bind_group(layout=g_layout, entries=[
            {"binding": 0, "resource": {"buffer": self.globals_buf, "offset": 0, "size": 256}}])
        self.quad_ubo = d.create_buffer(size=SLOT * MAX_QUADS, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self.q_layout = d.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
             "buffer": {"type": "uniform", "has_dynamic_offset": True}},
            {"binding": 1, "visibility": wgpu.ShaderStage.FRAGMENT, "texture": {"sample_type": "float", "view_dimension": "2d"}},
            {"binding": 2, "visibility": wgpu.ShaderStage.FRAGMENT, "sampler": {"type": "filtering"}},
        ])
        self.sampler = d.create_sampler(mag_filter="linear", min_filter="linear", mipmap_filter="linear", max_anisotropy=8,
                                        address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge")

        # geometry
        verts = cube_vertices()
        self.cube_buf = d.create_buffer_with_data(data=verts, usage=wgpu.BufferUsage.VERTEX)
        self.cube_count = len(verts)
        self.box_buf = d.create_buffer(size=MAX_BOXES * BOX_STRIDE * 4, usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        self.mesh_inst_buf = d.create_buffer(size=MAX_MESH_INST * BOX_STRIDE * 4, usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
        self.meshes = {}  # name -> (vertex buffer, vertex count, bounds)
        self._load_models()

        self._make_pipelines(g_layout)
        self.white = self.make_texture(np.full((2, 2, 4), 255, dtype=np.uint8))
        self.reset()

    # ---------- pipelines ----------
    def _make_pipelines(self, g_layout):
        d, fmt = self.device, self.fmt
        ms = {"count": MSAA}
        blend = {"color": {"src_factor": "src-alpha", "dst_factor": "one-minus-src-alpha", "operation": "add"},
                 "alpha": {"src_factor": "one", "dst_factor": "one-minus-src-alpha", "operation": "add"}}
        depth_on = {"format": DEPTH, "depth_write_enabled": True, "depth_compare": "less"}
        depth_read = {"format": DEPTH, "depth_write_enabled": False, "depth_compare": "less-equal"}
        depth_off = {"format": DEPTH, "depth_write_enabled": False, "depth_compare": "always"}

        g_pl = d.create_pipeline_layout(bind_group_layouts=[g_layout])
        box = d.create_shader_module(code=shaders.BOX)
        box_job = lambda: d.create_render_pipeline(
            layout=g_pl,
            vertex={"module": box, "entry_point": "vs", "buffers": [
                {"array_stride": 24, "step_mode": "vertex", "attributes": [
                    {"format": "float32x3", "offset": 0, "shader_location": 0},
                    {"format": "float32x3", "offset": 12, "shader_location": 1}]},
                {"array_stride": BOX_STRIDE * 4, "step_mode": "instance", "attributes": [
                    {"format": "float32x3", "offset": 0, "shader_location": 2},
                    {"format": "float32", "offset": 12, "shader_location": 3},
                    {"format": "float32x3", "offset": 16, "shader_location": 4},
                    {"format": "float32", "offset": 28, "shader_location": 5},
                    {"format": "float32x4", "offset": 32, "shader_location": 6},
                    {"format": "float32", "offset": 48, "shader_location": 7},
                    {"format": "float32", "offset": 52, "shader_location": 8},
                    {"format": "float32", "offset": 56, "shader_location": 9},
                    {"format": "float32", "offset": 60, "shader_location": 10}]}]},
            primitive={"topology": "triangle-list", "cull_mode": "back", "front_face": "ccw"},
            depth_stencil=depth_on, multisample=ms,
            fragment={"module": box, "entry_point": "fs", "targets": [{"format": fmt}]})

        floor = d.create_shader_module(code=shaders.FLOOR)
        floor_job = lambda: d.create_render_pipeline(
            layout=g_pl, vertex={"module": floor, "entry_point": "vs", "buffers": []},
            primitive={"topology": "triangle-list"}, depth_stencil=depth_on, multisample=ms,
            fragment={"module": floor, "entry_point": "fs", "targets": [{"format": fmt}]})

        q_pl = d.create_pipeline_layout(bind_group_layouts=[self.q_layout])
        quad = d.create_shader_module(code=shaders.QUAD)
        mk = lambda depth: d.create_render_pipeline(
            layout=q_pl, vertex={"module": quad, "entry_point": "vs", "buffers": []},
            primitive={"topology": "triangle-list"}, depth_stencil=depth, multisample=ms,
            fragment={"module": quad, "entry_point": "fs", "targets": [{"format": fmt, "blend": blend}]})
        mesh = d.create_shader_module(code=shaders.MESH)
        inst_attrs = [
            {"format": "float32x3", "offset": 0, "shader_location": 2},
            {"format": "float32", "offset": 12, "shader_location": 3},
            {"format": "float32x3", "offset": 16, "shader_location": 4},
            {"format": "float32", "offset": 28, "shader_location": 5},
            {"format": "float32x4", "offset": 32, "shader_location": 6},
            {"format": "float32", "offset": 48, "shader_location": 7},
            {"format": "float32", "offset": 52, "shader_location": 8},
            {"format": "float32", "offset": 56, "shader_location": 9},
            {"format": "float32", "offset": 60, "shader_location": 10}]
        self.mesh_pipe = d.create_render_pipeline(
            layout=g_pl,
            vertex={"module": mesh, "entry_point": "vs", "buffers": [
                {"array_stride": MESH_STRIDE * 4, "step_mode": "vertex", "attributes": [
                    {"format": "float32x3", "offset": 0, "shader_location": 0},
                    {"format": "float32x3", "offset": 12, "shader_location": 1},
                    {"format": "float32x4", "offset": 24, "shader_location": 11},
                    {"format": "float32x3", "offset": 40, "shader_location": 12}]},
                {"array_stride": BOX_STRIDE * 4, "step_mode": "instance", "attributes": inst_attrs}]},
            primitive={"topology": "triangle-list", "cull_mode": "back", "front_face": "ccw"},
            depth_stencil=depth_on, multisample=ms,
            fragment={"module": mesh, "entry_point": "fs", "targets": [{"format": fmt}]})
        self.box_pipe, self.floor_pipe = box_job(), floor_job()
        self.quad3d_pipe, self.quad2d_pipe = mk(depth_read), mk(depth_off)

    # ---------- resources ----------
    @staticmethod
    def build_levels(rgba, mips=False):
        """CPU side of a texture upload: the image plus its mip chain. Pure Pillow/numpy, so it is safe on a worker thread."""
        from PIL import Image

        rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
        h, w = rgba.shape[:2]
        levels = [rgba]
        if mips:
            img = Image.fromarray(rgba)
            for lvl in range(1, max(1, int(np.floor(np.log2(max(w, h)))) + 1)):
                levels.append(np.ascontiguousarray(np.asarray(img.resize((max(1, w >> lvl), max(1, h >> lvl)), Image.BOX))))
        return levels

    def make_texture_levels(self, levels):
        """GPU side: create the texture and write each prepared mip level (cheap, done on the render thread)."""
        h, w = levels[0].shape[:2]
        tex = self.device.create_texture(size=(w, h, 1), format="rgba8unorm", mip_level_count=len(levels),
                                         usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        for lvl, data in enumerate(levels):
            lh, lw = data.shape[:2]
            self.device.queue.write_texture(
                {"texture": tex, "mip_level": lvl, "origin": (0, 0, 0)}, data,
                {"offset": 0, "bytes_per_row": lw * 4, "rows_per_image": lh}, (lw, lh, 1))
        bg = self.device.create_bind_group(layout=self.q_layout, entries=[
            {"binding": 0, "resource": {"buffer": self.quad_ubo, "offset": 0, "size": 112}},
            {"binding": 1, "resource": tex.create_view()},
            {"binding": 2, "resource": self.sampler}])
        t = Tex(bg, w, h)
        t._tex = tex  # keep alive
        return t

    def make_texture(self, rgba, mips=False):
        """Upload an RGBA8 image. With mips=True a full mip chain is built so small, dense text stays crisp at a distance."""
        return self.make_texture_levels(self.build_levels(rgba, mips))

    def resize(self, w, h):
        if (w, h) == self.size and self.msaa_view:
            return
        self.size = (w, h)
        d = self.device
        self.msaa_view = d.create_texture(size=(w, h, 1), format=self.fmt, sample_count=MSAA,
                                          usage=wgpu.TextureUsage.RENDER_ATTACHMENT).create_view()
        self.depth_view = d.create_texture(size=(w, h, 1), format=DEPTH, sample_count=MSAA,
                                           usage=wgpu.TextureUsage.RENDER_ATTACHMENT).create_view()

    # ---------- Blender models ----------
    def _load_models(self):
        """ani3d/models/models.npz (written by tools/blender_models.py): one triangle list per model."""
        from . import paths
        try:
            data = np.load(paths.resource("models", "models.npz"))
        except (OSError, ValueError):
            return
        for name in data.files:
            v = np.ascontiguousarray(data[name], dtype=np.float32).reshape(-1, MESH_STRIDE)
            self.meshes[name] = (self.device.create_buffer_with_data(data=v, usage=wgpu.BufferUsage.VERTEX), len(v))

    def has_mesh(self, name):
        return name in self.meshes

    def add_mesh(self, name, arr):
        """Instances (rows in the box format, see scene.box) of a Blender model."""
        if name in self.meshes and len(arr):
            self.mesh_inst.setdefault(name, []).append(np.asarray(arr, dtype=np.float32).reshape(-1, BOX_STRIDE))

    # ---------- per-frame recording ----------
    def reset(self):
        self.mesh_inst = {}
        self.boxes = []
        self.q3d = []  # (tex, ubo bytes)
        self.q2d = []

    def add_boxes(self, arr):
        if len(arr):
            self.boxes.append(np.asarray(arr, dtype=np.float32).reshape(-1, BOX_STRIDE))

    @staticmethod
    def _quad_bytes(mvp, tint, uv):
        buf = np.zeros(28, dtype=np.float32)
        buf[:16] = mathx.gpu(mvp).ravel()
        buf[16:20], buf[20:24] = tint, uv
        return buf

    def quad3d(self, tex, model, tint=(1, 1, 1, 1), uv=(0, 0, 1, 1)):
        self.q3d.append((tex, self._quad_bytes(self.viewproj @ model, tint, uv)))

    def quad2d(self, tex, x, y, w, h, tint=(1, 1, 1, 1), uv=(0, 0, 1, 1)):
        m = self.ortho @ mathx.translate(x, y, 0) @ mathx.scale(w, h, 1)
        self.q2d.append((tex, self._quad_bytes(m, tint, uv)))

    def rect(self, x, y, w, h, color):
        self.quad2d(self.white, x, y, w, h, color)

    def set_camera(self, view, proj, cam_pos, t, logical_size, theme, flash=0.0):
        self.viewproj = proj @ view
        self.inv_viewproj = np.linalg.inv(self.viewproj)
        self.ortho = mathx.ortho_px(*logical_size)
        self.clear = (*theme.fog, 1.0)
        buf = np.zeros(44, dtype=np.float32)
        buf[:16] = mathx.gpu(self.viewproj).ravel()
        buf[16:19], buf[20:23], buf[23] = cam_pos, theme.fog, theme.density
        buf[24], buf[25], buf[26], buf[27] = t, theme.levels, flash, getattr(theme, "floor_style", 0.0)
        buf[28:31], buf[32:35], buf[36:39], buf[40:43] = theme.floor_base, theme.floor_small, theme.floor_big, theme.glow
        self.device.queue.write_buffer(self.globals_buf, 0, buf)

    def render(self, target_view):
        d = self.device
        clear = self.clear
        n_boxes = 0
        if self.boxes:
            data = np.concatenate(self.boxes)[:MAX_BOXES]
            n_boxes = len(data)
            d.queue.write_buffer(self.box_buf, 0, data)
        mesh_draws, at = [], 0
        for name, parts in self.mesh_inst.items():
            inst = np.concatenate(parts)[:max(0, MAX_MESH_INST - at)]
            if not len(inst):
                continue
            d.queue.write_buffer(self.mesh_inst_buf, at * BOX_STRIDE * 4, inst)
            mesh_draws.append((name, at, len(inst)))
            at += len(inst)
        quads = (self.q3d + self.q2d)[:MAX_QUADS]
        if quads:
            blob = np.zeros((len(quads), SLOT // 4), dtype=np.float32)
            for i, (_, b) in enumerate(quads):
                blob[i, :28] = b
            d.queue.write_buffer(self.quad_ubo, 0, blob)

        enc = d.create_command_encoder()
        rp = enc.begin_render_pass(
            color_attachments=[{"view": self.msaa_view, "resolve_target": target_view, "clear_value": clear,
                                "load_op": "clear", "store_op": "discard"}],
            depth_stencil_attachment={"view": self.depth_view, "depth_clear_value": 1.0,
                                      "depth_load_op": "clear", "depth_store_op": "discard"})
        rp.set_pipeline(self.floor_pipe)
        rp.set_bind_group(0, self.globals_bg)
        rp.draw(6)
        if n_boxes:
            rp.set_pipeline(self.box_pipe)
            rp.set_bind_group(0, self.globals_bg)
            rp.set_vertex_buffer(0, self.cube_buf)
            rp.set_vertex_buffer(1, self.box_buf)
            rp.draw(self.cube_count, n_boxes)
        if mesh_draws:
            rp.set_pipeline(self.mesh_pipe)
            rp.set_bind_group(0, self.globals_bg)
            for name, first, n in mesh_draws:
                buf, count = self.meshes[name]
                rp.set_vertex_buffer(0, buf)
                rp.set_vertex_buffer(1, self.mesh_inst_buf, first * BOX_STRIDE * 4)
                rp.draw(count, n)
        n3 = len(self.q3d)
        for pipe, lo, hi in ((self.quad3d_pipe, 0, min(n3, len(quads))), (self.quad2d_pipe, n3, len(quads))):
            if hi <= lo:
                continue
            rp.set_pipeline(pipe)
            for i in range(lo, hi):
                rp.set_bind_group(0, quads[i][0].bind_group, [i * SLOT])
                rp.draw(6)
        rp.end()
        d.queue.submit([enc.finish()])
        self.reset_frame_lists()

    def reset_frame_lists(self):
        self.reset()

    def read_pixels(self, tex, w, h):
        data = self.device.queue.read_texture(
            {"texture": tex, "mip_level": 0, "origin": (0, 0, 0)}, {"offset": 0, "bytes_per_row": w * 4, "rows_per_image": h}, (w, h, 1))
        return np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
