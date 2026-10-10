"""Visual themes: palette for the 3D world, floor/fog parameters, HUD colours and an optional animated effect."""
import json
import os
from dataclasses import dataclass, field

from . import paths

SETTINGS = os.path.join(paths.config_dir(), "settings.json")


@dataclass
class Theme:
    key: str
    label: str
    fog: tuple
    density: float
    floor_base: tuple
    floor_small: tuple
    floor_big: tuple
    glow: tuple
    levels: int  # posterize steps per channel, 0 = off
    root: tuple
    core: tuple
    ped: tuple
    ped_sel: tuple
    tower: tuple
    tower_off: tuple
    wire: tuple
    pulse: tuple
    slab: tuple
    ep: tuple
    ep_seen: tuple
    ep_play: tuple
    link: tuple
    t_root: tuple
    t_ped: tuple
    t_field: tuple
    panel: tuple
    edge: tuple
    text: tuple
    dim: tuple
    accent: tuple
    good: tuple
    logo: tuple
    wood: tuple  # bookshelf / arcade cabinet frame
    books: list = field(default_factory=list)  # spine colours
    fx: str = ""
    floor_style: float = 0.0  # 0 = neon grid, 1 = organic forest floor (moss, earth, leaf litter, dappled light), 2 = the same with cherry petals


THEMES = {t.key: t for t in [
    Theme("fsn", "CLASSIC FSN", (0.01, 0.02, 0.05), 0.0075, (0.012, 0.022, 0.055), (0.008, 0.114, 0.19), (0.075, 0.465, 0.71), (0, 0.05, 0.11), 0,
          root=(0.10, 0.18, 0.40), core=(1.0, 0.18, 0.80), ped=(0.12, 0.22, 0.46), ped_sel=(0.2, 0.3, 0.65), tower=(0.1, 0.75, 1.0),
          tower_off=(0.3, 0.4, 0.6), wire=(0.1, 0.75, 1.0), pulse=(0.6, 1, 1), slab=(0.08, 0.13, 0.30), ep=(0.10, 0.50, 1.0),
          ep_seen=(0.12, 0.95, 0.50), ep_play=(1.0, 0.18, 0.80), link=(1.0, 0.75, 0.2), t_root=(0.55, 0.95, 1.0), t_ped=(0.65, 0.9, 1.0),
          t_field=(1.0, 0.9, 0.6), panel=(0.01, 0.05, 0.12, 0.82), edge=(0.10, 0.65, 0.95, 0.9), text=(0.55, 0.95, 1.0),
          dim=(0.45, 0.62, 0.78), accent=(1.0, 0.95, 0.7), good=(0.4, 1.0, 0.7), logo=(0.4, 0.9, 1.0), wood=(0.10, 0.16, 0.30),
          books=[(0.1, 0.5, 1.0), (0.1, 0.8, 0.9), (0.5, 0.3, 1.0), (0.9, 0.2, 0.7), (0.2, 0.9, 0.6)]),
    Theme("jurassic", "JURASSIC PARK", (0.02, 0.035, 0.02), 0.009, (0.015, 0.025, 0.015), (0.11, 0.09, 0.01), (0.76, 0.52, 0.04), (0.05, 0.04, 0.0), 0,
          root=(0.07, 0.20, 0.11), core=(0.95, 0.10, 0.08), ped=(0.07, 0.22, 0.12), ped_sel=(0.12, 0.38, 0.20), tower=(1.0, 0.72, 0.05),
          tower_off=(0.35, 0.30, 0.10), wire=(1.0, 0.70, 0.10), pulse=(1.0, 0.95, 0.6), slab=(0.05, 0.12, 0.07), ep=(0.85, 0.55, 0.05),
          ep_seen=(0.25, 0.80, 0.20), ep_play=(1.0, 0.12, 0.10), link=(1.0, 0.2, 0.1), t_root=(1.0, 0.85, 0.35), t_ped=(1.0, 0.85, 0.5),
          t_field=(1.0, 0.95, 0.6), panel=(0.03, 0.05, 0.02, 0.86), edge=(0.95, 0.65, 0.05, 0.9), text=(1.0, 0.85, 0.35),
          dim=(0.62, 0.52, 0.26), accent=(1.0, 0.45, 0.2), good=(0.5, 1.0, 0.4), logo=(1.0, 0.75, 0.1), wood=(0.18, 0.12, 0.05),
          books=[(0.85, 0.55, 0.05), (0.2, 0.6, 0.2), (0.8, 0.15, 0.1), (0.5, 0.4, 0.1), (0.15, 0.4, 0.25)], fx="jurassic"),
    Theme("forest", "ENCHANTED FOREST", (0.19, 0.28, 0.2), 0.0047, (0.07, 0.13, 0.05), (0.17, 0.3, 0.09), (0.26, 0.18, 0.09), (0.12, 0.1, 0.03), 0,
          root=(0.30, 0.20, 0.11), core=(1.0, 0.85, 0.35), ped=(0.26, 0.18, 0.10), ped_sel=(0.40, 0.28, 0.15), tower=(0.55, 0.85, 0.25),
          tower_off=(0.35, 0.40, 0.25), wire=(0.45, 0.80, 0.22), pulse=(1.0, 0.95, 0.6), slab=(0.12, 0.20, 0.08), ep=(0.35, 0.65, 0.20),
          ep_seen=(0.95, 0.75, 0.25), ep_play=(1.0, 0.35, 0.55), link=(1.0, 0.8, 0.3), t_root=(0.95, 0.95, 0.7), t_ped=(0.92, 0.96, 0.78),
          t_field=(1.0, 0.95, 0.7), panel=(0.04, 0.08, 0.04, 0.86), edge=(0.55, 0.85, 0.30, 0.9), text=(0.90, 0.96, 0.78),
          dim=(0.62, 0.74, 0.52), accent=(1.0, 0.82, 0.35), good=(0.55, 1.0, 0.45), logo=(0.70, 0.95, 0.35), wood=(0.32, 0.21, 0.11),
          books=[(0.35, 0.55, 0.2), (0.6, 0.35, 0.15), (0.85, 0.7, 0.3), (0.25, 0.45, 0.3), (0.75, 0.3, 0.25)], fx="forest", floor_style=1.0),
    Theme("sakura", "SAKURA GARDEN", (0.30, 0.22, 0.30), 0.005, (0.09, 0.12, 0.07), (0.18, 0.24, 0.12), (0.4, 0.34, 0.3), (0.12, 0.06, 0.08), 0,
          root=(0.35, 0.12, 0.10), core=(1.0, 0.7, 0.8), ped=(0.30, 0.12, 0.10), ped_sel=(0.50, 0.20, 0.16), tower=(1.0, 0.6, 0.75),
          tower_off=(0.4, 0.3, 0.35), wire=(1.0, 0.55, 0.7), pulse=(1.0, 0.9, 0.95), slab=(0.16, 0.10, 0.12), ep=(0.95, 0.55, 0.7),
          ep_seen=(0.55, 0.85, 0.5), ep_play=(1.0, 0.85, 0.3), link=(1.0, 0.6, 0.75), t_root=(1.0, 0.9, 0.95), t_ped=(1.0, 0.88, 0.92),
          t_field=(1.0, 0.95, 0.85), panel=(0.08, 0.04, 0.07, 0.88), edge=(1.0, 0.6, 0.75, 0.9), text=(1.0, 0.9, 0.94),
          dim=(0.78, 0.62, 0.7), accent=(1.0, 0.8, 0.45), good=(0.6, 1.0, 0.6), logo=(1.0, 0.62, 0.78), wood=(0.40, 0.17, 0.11),
          books=[(0.95, 0.6, 0.7), (0.85, 0.2, 0.15), (0.2, 0.25, 0.4), (0.95, 0.85, 0.6), (0.4, 0.6, 0.35)], fx="sakura", floor_style=2.0),
    Theme("halloween", "HALLOWEEN", (0.06, 0.02, 0.09), 0.0075, (0.03, 0.01, 0.04), (0.14, 0.035, 0.18), (0.80, 0.36, 0.0), (0.12, 0.04, 0.0), 0,
          root=(0.20, 0.08, 0.25), core=(1.0, 0.45, 0.0), ped=(0.22, 0.08, 0.28), ped_sel=(0.40, 0.15, 0.50), tower=(1.0, 0.5, 0.05),
          tower_off=(0.40, 0.25, 0.40), wire=(1.0, 0.5, 0.05), pulse=(0.7, 1.0, 0.4), slab=(0.12, 0.05, 0.15), ep=(0.55, 0.20, 0.85),
          ep_seen=(1.0, 0.5, 0.05), ep_play=(0.5, 1.0, 0.2), link=(0.5, 1.0, 0.3), t_root=(1.0, 0.7, 0.3), t_ped=(1.0, 0.75, 0.45),
          t_field=(0.8, 1.0, 0.5), panel=(0.06, 0.02, 0.08, 0.86), edge=(1.0, 0.5, 0.05, 0.9), text=(1.0, 0.75, 0.4),
          dim=(0.65, 0.45, 0.60), accent=(0.6, 1.0, 0.3), good=(0.6, 1.0, 0.3), logo=(1.0, 0.5, 0.05), wood=(0.20, 0.09, 0.07),
          books=[(1.0, 0.5, 0.05), (0.55, 0.2, 0.85), (0.3, 0.8, 0.2), (0.8, 0.1, 0.1), (0.9, 0.9, 0.85)], fx="halloween"),
    Theme("matrix", "MATRIX // HACKER", (0.0, 0.02, 0.0), 0.008, (0.0, 0.01, 0.0), (0.0, 0.16, 0.035), (0.075, 0.75, 0.225), (0.0, 0.06, 0.01), 0,
          root=(0.0, 0.15, 0.04), core=(0.4, 1.0, 0.5), ped=(0.0, 0.20, 0.06), ped_sel=(0.05, 0.40, 0.12), tower=(0.2, 1.0, 0.4),
          tower_off=(0.1, 0.35, 0.15), wire=(0.1, 1.0, 0.3), pulse=(0.8, 1.0, 0.8), slab=(0.0, 0.10, 0.03), ep=(0.05, 0.55, 0.18),
          ep_seen=(0.6, 1.0, 0.7), ep_play=(1.0, 1.0, 1.0), link=(0.6, 1.0, 0.6), t_root=(0.4, 1.0, 0.5), t_ped=(0.4, 1.0, 0.5),
          t_field=(0.8, 1.0, 0.8), panel=(0.0, 0.04, 0.0, 0.88), edge=(0.1, 0.9, 0.3, 0.9), text=(0.4, 1.0, 0.5),
          dim=(0.2, 0.60, 0.30), accent=(0.8, 1.0, 0.8), good=(0.4, 1.0, 0.5), logo=(0.3, 1.0, 0.4), wood=(0.0, 0.14, 0.04),
          books=[(0.1, 0.8, 0.3), (0.05, 0.5, 0.2), (0.4, 1.0, 0.5), (0.0, 0.35, 0.1), (0.7, 1.0, 0.7)], fx="matrix"),
    Theme("retro", "RETRO ARCADE", (0.05, 0.0, 0.12), 0.0026, (0.03, 0.0, 0.08), (0.40, 0.04, 0.28), (0.09, 0.81, 0.90), (0.15, 0.0, 0.20), 6,
          root=(0.5, 0.1, 0.8), core=(1.0, 0.9, 0.1), ped=(0.2, 0.2, 0.9), ped_sel=(0.4, 0.4, 1.0), tower=(1.0, 0.2, 0.2),
          tower_off=(0.5, 0.5, 0.5), wire=(1.0, 0.3, 0.8), pulse=(1.0, 1.0, 0.2), slab=(0.1, 0.1, 0.4), ep=(0.1, 0.6, 1.0),
          ep_seen=(0.2, 1.0, 0.2), ep_play=(1.0, 1.0, 0.1), link=(1.0, 0.5, 0.1), t_root=(1.0, 1.0, 0.3), t_ped=(0.4, 1.0, 1.0),
          t_field=(1.0, 1.0, 0.3), panel=(0.05, 0.0, 0.12, 0.88), edge=(1.0, 0.2, 0.8, 0.95), text=(0.4, 1.0, 1.0),
          dim=(0.7, 0.5, 0.9), accent=(1.0, 1.0, 0.3), good=(0.3, 1.0, 0.3), logo=(1.0, 0.3, 0.9), wood=(0.35, 0.12, 0.55),
          books=[(1.0, 0.2, 0.2), (0.2, 0.4, 1.0), (1.0, 0.9, 0.1), (0.2, 1.0, 0.3), (1.0, 0.3, 0.9)], fx="retro"),
    Theme("vcr", "OLD VCR (VHS)", (0.05, 0.05, 0.09), 0.0062, (0.04, 0.045, 0.08), (0.20, 0.22, 0.33), (0.55, 0.58, 0.72), (0.06, 0.06, 0.1), 9,
          root=(0.30, 0.32, 0.46), core=(0.95, 0.15, 0.15), ped=(0.22, 0.24, 0.36), ped_sel=(0.40, 0.42, 0.62), tower=(0.9, 0.9, 0.95),
          tower_off=(0.35, 0.36, 0.45), wire=(0.65, 0.68, 0.85), pulse=(1.0, 0.3, 0.3), slab=(0.12, 0.13, 0.22), ep=(0.45, 0.5, 0.72),
          ep_seen=(0.35, 0.8, 0.5), ep_play=(0.95, 0.15, 0.15), link=(0.95, 0.85, 0.3), t_root=(0.92, 0.94, 1.0), t_ped=(0.85, 0.88, 0.98),
          t_field=(1.0, 0.92, 0.45), panel=(0.04, 0.04, 0.09, 0.86), edge=(0.7, 0.72, 0.95, 0.9), text=(0.9, 0.93, 1.0),
          dim=(0.55, 0.58, 0.72), accent=(1.0, 0.88, 0.25), good=(0.45, 0.95, 0.55), logo=(0.95, 0.95, 1.0), wood=(0.18, 0.15, 0.13),
          books=[(0.75, 0.2, 0.2), (0.25, 0.35, 0.7), (0.8, 0.7, 0.25), (0.3, 0.6, 0.4), (0.55, 0.55, 0.6)], fx="vcr"),
]}
ORDER = list(THEMES)


def load_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(**changes):
    try:
        data = load_settings()
        data.update(changes)
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def load_theme():
    return load_settings().get("theme", "fsn")


def save_theme(key):
    save_settings(theme=key)
