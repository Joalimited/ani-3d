"""WGSL shaders. Boxes get a solid lit face plus glowing neon edges (the FSN look); the floor is a procedural grid."""

GLOBALS = """
struct Globals {
  viewproj: mat4x4<f32>,
  cam: vec4<f32>,    // xyz camera position
  fog: vec4<f32>,    // rgb fog colour, a = density
  time: vec4<f32>,   // x = seconds, y = posterize levels, z = lightning flash, w = floor style (1 = forest)
  fbase: vec4<f32>,
  fsmall: vec4<f32>,
  fbig: vec4<f32>,
  fglow: vec4<f32>,
};
@group(0) @binding(0) var<uniform> g: Globals;

fn fog_only(col: vec3<f32>, world: vec3<f32>) -> vec3<f32> {
  let d = length(world - g.cam.xyz) * g.fog.a;
  var c = mix(col, g.fog.rgb, clamp(1.0 - exp(-d * d), 0.0, 1.0));
  c += vec3<f32>(0.55, 0.45, 0.75) * g.time.z;      // lightning
  return c;
}

fn apply_fog(col: vec3<f32>, world: vec3<f32>) -> vec3<f32> {
  var c = fog_only(col, world);
  if (g.time.y > 0.5) { c = floor(c * g.time.y + 0.5) / g.time.y; }   // retro posterize
  return c;
}
"""

BOX = GLOBALS + """
struct VIn {
  @location(0) pos: vec3<f32>,
  @location(1) nrm: vec3<f32>,
  @location(2) ipos: vec3<f32>,
  @location(3) glow: f32,
  @location(4) iscale: vec3<f32>,
  @location(5) yaw: f32,
  @location(6) color: vec4<f32>,
  @location(7) pitch: f32,
  @location(8) flat_: f32,
  @location(9) rollz: f32,
  @location(10) rollx: f32,
};
struct VOut {
  @builtin(position) clip: vec4<f32>,
  @location(0) lp: vec3<f32>,
  @location(1) nrm: vec3<f32>,
  @location(2) world: vec3<f32>,
  @location(3) color: vec4<f32>,
  @location(4) glow: f32,
  @location(5) sc: vec3<f32>,
  @location(6) flat_: f32,
};

fn yaw_rot(v: vec3<f32>, a: f32) -> vec3<f32> {
  let c = cos(a); let s = sin(a);
  return vec3<f32>(v.x * c + v.z * s, v.y, -v.x * s + v.z * c);
}

fn pitch_rot(v: vec3<f32>, a: f32) -> vec3<f32> {
  let c = cos(a); let s = sin(a);
  return vec3<f32>(v.x, v.y * c - v.z * s, v.y * s + v.z * c);
}

fn rotz(v: vec3<f32>, a: f32) -> vec3<f32> {
  let c = cos(a); let s = sin(a);
  return vec3<f32>(v.x * c - v.y * s, v.x * s + v.y * c, v.z);
}

fn rotx(v: vec3<f32>, a: f32) -> vec3<f32> {
  let c = cos(a); let s = sin(a);
  return vec3<f32>(v.x, v.y * c - v.z * s, v.y * s + v.z * c);
}

@vertex
fn vs(i: VIn) -> VOut {
  var o: VOut;
  // local rolls first (limbs swing about the side axis, wings flap about the forward axis), then heading, then the book tilt
  let local = rotx(rotz(i.pos * i.iscale, i.rollz), i.rollx);
  let world = i.ipos + pitch_rot(yaw_rot(local, i.yaw), i.pitch);
  o.clip = g.viewproj * vec4<f32>(world, 1.0);
  o.lp = i.pos;
  o.nrm = pitch_rot(yaw_rot(rotx(rotz(i.nrm, i.rollz), i.rollx), i.yaw), i.pitch);
  o.world = world;
  o.color = i.color;
  o.glow = i.glow;
  o.sc = i.iscale;
  o.flat_ = i.flat_;
  return o;
}

@fragment
fn fs(i: VOut) -> @location(0) vec4<f32> {
  let n = normalize(i.nrm);
  // the face we are on is the local axis where |lp| is largest; edges are measured along the other two axes
  let al = abs(i.lp);
  let mx = max(al.x, max(al.y, al.z));
  let m = vec3<f32>(1.0) - step(vec3<f32>(mx - 0.0001), al);
  let dw = (vec3<f32>(0.5) - abs(i.lp)) * i.sc;
  let e = min(select(1000.0, dw.x, m.x > 0.5), min(select(1000.0, dw.y, m.y > 0.5), select(1000.0, dw.z, m.z > 0.5)));
  let edge = (1.0 - smoothstep(0.0, 0.05, e)) * i.color.a;

  let L = normalize(vec3<f32>(0.35, 0.85, 0.30));
  let lit = 0.30 + 0.70 * max(dot(n, L), 0.0);
  var col = i.color.rgb * lit * 0.65;
  let edge_col = mix(i.color.rgb, vec3<f32>(1.0), 0.45) * (1.1 + i.glow * 1.6);
  col = mix(col, edge_col, edge);
  col += i.color.rgb * i.glow * 0.55;
  // flat boxes (the book) skip posterizing so paper keeps its smooth cream shading in every theme
  if (i.flat_ > 0.5) { return vec4<f32>(fog_only(col, i.world), 1.0); }
  return vec4<f32>(apply_fog(col, i.world), 1.0);
}
"""

MESH = GLOBALS + """
// Blender-made models: same instancing, lighting and neon edges as the boxes. Each vertex carries its colour and its
// distance (in model units) to the three edges of its triangle - edges that are not real corners of the model are
// pushed far away, so only feature edges glow, at the same world width as a box edge.
struct VIn {
  @location(0) pos: vec3<f32>,
  @location(1) nrm: vec3<f32>,
  @location(11) vcol: vec4<f32>,
  @location(12) edist: vec3<f32>,
  @location(2) ipos: vec3<f32>,
  @location(3) glow: f32,
  @location(4) iscale: vec3<f32>,
  @location(5) yaw: f32,
  @location(6) color: vec4<f32>,
  @location(7) pitch: f32,
  @location(8) flat_: f32,
  @location(9) rollz: f32,
  @location(10) rollx: f32,
};
struct VOut {
  @builtin(position) clip: vec4<f32>,
  @location(0) edist: vec3<f32>,
  @location(1) nrm: vec3<f32>,
  @location(2) world: vec3<f32>,
  @location(3) color: vec4<f32>,
  @location(4) glow: f32,
  @location(5) vcol: vec4<f32>,
  @location(6) flat_: f32,
};

fn yaw_rot(v: vec3<f32>, a: f32) -> vec3<f32> {
  let c = cos(a); let s = sin(a);
  return vec3<f32>(v.x * c + v.z * s, v.y, -v.x * s + v.z * c);
}
fn pitch_rot(v: vec3<f32>, a: f32) -> vec3<f32> {
  let c = cos(a); let s = sin(a);
  return vec3<f32>(v.x, v.y * c - v.z * s, v.y * s + v.z * c);
}
fn rotz(v: vec3<f32>, a: f32) -> vec3<f32> {
  let c = cos(a); let s = sin(a);
  return vec3<f32>(v.x * c - v.y * s, v.x * s + v.y * c, v.z);
}
fn rotx(v: vec3<f32>, a: f32) -> vec3<f32> {
  let c = cos(a); let s = sin(a);
  return vec3<f32>(v.x, v.y * c - v.z * s, v.y * s + v.z * c);
}

@vertex
fn vs(i: VIn) -> VOut {
  var o: VOut;
  let local = rotx(rotz(i.pos * i.iscale, i.rollz), i.rollx);
  let world = i.ipos + pitch_rot(yaw_rot(local, i.yaw), i.pitch);
  o.clip = g.viewproj * vec4<f32>(world, 1.0);
  let inv = vec3<f32>(1.0) / max(abs(i.iscale), vec3<f32>(0.0001));
  o.nrm = pitch_rot(yaw_rot(rotx(rotz(normalize(i.nrm * inv), i.rollz), i.rollx), i.yaw), i.pitch);
  o.world = world;
  o.edist = i.edist * min(abs(i.iscale.x), min(abs(i.iscale.y), abs(i.iscale.z)));  // to world units (thin sides stay thin)
  o.color = i.color;
  o.glow = i.glow;
  o.vcol = i.vcol;
  o.flat_ = i.flat_;
  return o;
}

@fragment
fn fs(i: VOut) -> @location(0) vec4<f32> {
  let n = normalize(i.nrm);
  let e = min(i.edist.x, min(i.edist.y, i.edist.z));
  let edge = (1.0 - smoothstep(0.0, 0.05, e)) * i.color.a;
  let base = i.color.rgb * i.vcol.rgb;
  let L = normalize(vec3<f32>(0.35, 0.85, 0.30));
  let lit = 0.30 + 0.70 * max(dot(n, L), 0.0);
  var col = base * lit * 0.65;
  let edge_col = mix(base, vec3<f32>(1.0), 0.45) * (1.1 + i.glow * 1.6);
  col = mix(col, edge_col, edge);
  col += base * (i.glow + i.vcol.a) * 0.55;  // vertex alpha = self-lit parts (lantern paper, windows, eyes)
  if (i.flat_ > 0.5) { return vec4<f32>(fog_only(col, i.world), 1.0); }
  return vec4<f32>(apply_fog(col, i.world), 1.0);
}
"""

FLOOR = GLOBALS + """
struct FOut { @builtin(position) clip: vec4<f32>, @location(0) world: vec3<f32> };

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> FOut {
  var c = array<vec2<f32>, 6>(vec2(-1.0, -1.0), vec2(1.0, -1.0), vec2(-1.0, 1.0), vec2(-1.0, 1.0), vec2(1.0, -1.0), vec2(1.0, 1.0));
  let p = c[vi] * 600.0;
  var o: FOut;
  let w = vec3<f32>(p.x + g.cam.x, -0.02, p.y + g.cam.z);   // follows the camera so the floor is endless
  o.clip = g.viewproj * vec4<f32>(w, 1.0);
  o.world = w;
  return o;
}

fn grid(p: vec2<f32>, cell: f32) -> f32 {
  let q = p / cell;
  let w = fwidth(q) * 1.2;
  let a = abs(fract(q - 0.5) - 0.5) / max(w, vec2<f32>(0.0001));
  return 1.0 - min(min(a.x, a.y), 1.0);
}

fn hash2(p: vec2<f32>) -> f32 {
  return fract(sin(dot(p, vec2<f32>(127.1, 311.7))) * 43758.5453);
}

fn vnoise(p: vec2<f32>) -> f32 {
  let i = floor(p);
  let f = fract(p);
  let u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash2(i), hash2(i + vec2<f32>(1.0, 0.0)), u.x), mix(hash2(i + vec2<f32>(0.0, 1.0)), hash2(i + vec2<f32>(1.0, 1.0)), u.x), u.y);
}

fn fbm(p: vec2<f32>) -> f32 {
  return 0.55 * vnoise(p) + 0.3 * vnoise(p * 2.03 + 17.0) + 0.15 * vnoise(p * 4.1 + 41.0);
}

// forest floor: moss in two shades, bare-earth patches, leaf litter up close and slow dappled sunlight through the canopy
fn forest_floor(p: vec2<f32>) -> vec3<f32> {
  let detail = 1.0 - smoothstep(0.25, 1.4, length(fwidth(p)));
  let moss = fbm(p * 0.06);
  var col = mix(g.fbase.rgb, g.fsmall.rgb, smoothstep(0.32, 0.72, moss));
  let earth = smoothstep(0.58, 0.78, fbm(p * 0.018 + 5.0));
  col = mix(col, g.fbig.rgb, earth * 0.85);
  let litter = vnoise(p * 1.4);
  let tint = mix(vec3<f32>(0.42, 0.26, 0.08), vec3<f32>(0.55, 0.45, 0.12), vnoise(p * 0.7 + 3.0));
  col = mix(col, tint, smoothstep(0.7, 0.8, litter) * select(0.55, 0.12, g.time.w > 1.5) * detail);  // sakura: little leaf litter
  col *= 0.88 + 0.24 * vnoise(p * 0.45) * detail + 0.0;
  let sun = fbm(p * 0.07 + vec2<f32>(g.time.x * 0.04, g.time.x * 0.025));
  col *= 0.72 + 0.6 * smoothstep(0.42, 0.7, sun);
  return col;
}

@fragment
fn fs(i: FOut) -> @location(0) vec4<f32> {
  let p = i.world.xz;
  if (g.time.w > 0.5) {
    var fc = forest_floor(p);
    if (g.time.w > 1.5) {  // sakura: fallen petals, drifted into soft pink patches
      let detail = 1.0 - smoothstep(0.25, 1.4, length(fwidth(p)));
      let drift = smoothstep(0.45, 0.8, fbm(p * 0.035 + 9.0));
      let petal = smoothstep(0.86, 0.92, vnoise(p * 3.1)) * detail;
      let pink = vec3<f32>(0.95, 0.62, 0.74);
      fc = mix(fc, pink * 0.8, clamp(petal * (0.25 + 0.75 * drift) + drift * 0.22, 0.0, 0.85));
    }
    fc += g.fglow.rgb * exp(-length(p) / 70.0);
    return vec4<f32>(apply_fog(fc, i.world), 1.0);
  }
  let small = grid(p, 4.0);
  let big = grid(p, 20.0);
  let r = length(p);
  var col = g.fbase.rgb;
  col += g.fglow.rgb * exp(-r / 70.0);
  col += g.fsmall.rgb * small;
  col += g.fbig.rgb * big;
  return vec4<f32>(apply_fog(col, i.world), 1.0);
}
"""

QUAD = """
struct QU {
  mvp: mat4x4<f32>,
  tint: vec4<f32>,
  uv: vec4<f32>,
  params: vec4<f32>,
};
@group(0) @binding(0) var<uniform> q: QU;
@group(0) @binding(1) var tex: texture_2d<f32>;
@group(0) @binding(2) var samp: sampler;

struct QOut { @builtin(position) clip: vec4<f32>, @location(0) uv: vec2<f32> };

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> QOut {
  var c = array<vec2<f32>, 6>(vec2(0.0, 0.0), vec2(1.0, 0.0), vec2(0.0, 1.0), vec2(0.0, 1.0), vec2(1.0, 0.0), vec2(1.0, 1.0));
  var o: QOut;
  o.clip = q.mvp * vec4<f32>(c[vi], 0.0, 1.0);
  o.uv = mix(q.uv.xy, q.uv.zw, c[vi]);
  return o;
}

@fragment
fn fs(i: QOut) -> @location(0) vec4<f32> {
  let t = textureSample(tex, samp, i.uv);
  return t * q.tint;
}
"""
