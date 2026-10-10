"""ani-3d application: engine glue (background thread), input, HUD and the frame function."""
import time as _time

T0 = _time.perf_counter()  # for the "first frame" timing printed at startup
import asyncio
import math
import os
import queue
import sys
import threading
import time
import webbrowser

import numpy as np
from PIL import Image

from . import advance, effects, games, library, mathx, multisrc, paths, sections, themes
from .scene import PED_D, PED_H, PED_W, Scene
from .text import TextCache
from .textinput import TextInput

from . import core  # noqa: E402
from . import engine as engine_mod  # noqa: E402



def _open_thumb(path, size):
    img = Image.open(path).convert("RGBA")
    if img.height > 1.6 * img.width:  # long-strip (webtoon) page: limit only the width, or it shrinks to a sliver
        img.thumbnail((min(size[0], 900), 1 << 16))
    else:
        img.thumbnail(size)
    return img


async def decode_image(path, size):
    """Decode + shrink an image on a worker thread so the render loop never waits on Pillow."""
    return await asyncio.get_running_loop().run_in_executor(None, _open_thumb, path, size)


class Backend:
    """Runs the ani-tui engine's asyncio loop on a thread and posts results back to the render thread."""

    def __init__(self, post):
        self.post = post
        self.loop = asyncio.new_event_loop()
        self.engine = engine_mod.Engine()
        self.engine.send = lambda obj: post(("event", obj))
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def call(self, cmd, args, cb=None):
        self.run(self.engine.handle(cmd, args), cb)

    def run(self, coro, cb=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if cb:
            def done(f):
                try:
                    self.post(("cb", cb, f.result(), None))
                except Exception as e:  # noqa: BLE001
                    self.post(("cb", cb, None, e))
            fut.add_done_callback(done)


class App:
    def __init__(self, renderer, ratio=1.0):
        self.r = renderer
        self.gpu_label = str(renderer.adapter.info.get("backend_type", "GPU")).upper()
        self.ratio = ratio
        self.text = TextCache(renderer, ratio)
        self.scene = Scene()
        self.q = queue.Queue()
        self.be = Backend(self.q.put)
        cfg = themes.load_settings()
        self.be.call("control", {"action": "autofs", "value": bool(cfg.get("auto_fullscreen", False))})
        self.auto_intro, self.auto_outro = bool(cfg.get("auto_skip_intro", False)), bool(cfg.get("auto_skip_outro", False))
        self.be.call("control", {"action": "autoskip", "value": {"intro": self.auto_intro, "outro": self.auto_outro}})
        self.t = 0.0
        self.q_in, self.lib_in = TextInput(), TextInput(limit=60)  # the search bar and the librarian's question
        self.typing, self.audio = True, "sub"
        self.mods = ()
        self.status = "Type an anime name and press Enter"
        self.player = {}
        self.info = {"manga": [], "related": None}
        self.hover = None
        self.blurbs = {}  # (kind, title) -> {state: loading|ok|none|err, data, t}: what the hover hologram shows
        self.card = None  # the hover hologram: {key, since}
        self.mouse = (0, 0)
        self.hits = []
        self.size = (1500, 900)
        self.seq = 0
        self.poster_tex = {}
        self.swallow = None
        self.down = None
        self.dragged = False
        self.history_mode = False
        self.view, self.home_started = "none", False  # which list the world shows: home | search | history
        self.mode = "world"  # world | game | library
        self.game = self.lib = None
        self.keys, self.pressed = set(), set()
        self.arcade_menu = False
        self.cam_ground = (0.0, 60.0)
        self.dino_hover, self.dino_card, self.follow = None, None, None  # Jurassic theme: hovered dinosaur, info card (idx, t0), follow-cam index
        self.busy = {}  # token -> (message, start time): drives the loading spinner
        self.upload_q = []  # finished poster images waiting for a GPU upload (a couple per frame, so loading never hitches)
        self.hide_ui = False  # U hides every button/label so a book (or anything) can fill the screen
        self.game_back = None  # "library" when a game was started from the shelves
        # manga read right to left by default. (The older "manga_rtl" key was written when left-to-right was the default, so it is ignored.)
        self.manga_rtl = bool(themes.load_settings().get("manga_rtl_v2", True))
        self.manga_jp = bool(themes.load_settings().get("manga_jp", False))  # shelf titles: English (default) or Japanese (romaji)
        self.lib_typing = False  # the librarian's search box is open
        self.auto_fs = bool(themes.load_settings().get("auto_fullscreen", False))  # media player: start episodes fullscreen
        self.lib_busy = False
        self.lib_sel = -1  # highlighted entry in the librarian's recent / suggested list
        self.recent = list(themes.load_settings().get("librarian_recent", []))[:8]
        self.suggest, self.sugg_sel, self.sugg_for, self.sugg_due = [], -1, "", 0.0  # search-bar suggestions
        self.toasts = []  # advancement toasts: (title, desc, group, born)
        self.adv = advance.Tracker()
        self.adv.refresh()  # the first pass records what you had already earned, silently (no toast flood on an old history)
        self.adv_open, self.adv_scroll = False, 0
        self.edits = None  # fan edits for the open anime: None | "loading" | [..]
        self.starred = {w["id"] for w in core.wl_list()}  # the "planning to watch" list
        self.scene.starred = self.starred
        self.lib_t0 = 0.0
        self.theme = themes.THEMES.get(os.environ.get("ANI3D_THEME") or themes.load_theme(), themes.THEMES["fsn"])
        self.scene.dist_scale = 1.35 if self.theme.fx in ("jurassic", "halloween", "forest") else 1.0

    @property
    def query(self):
        return self.q_in.text

    @query.setter
    def query(self, v):
        self.q_in.set(v)

    @property
    def lib_query(self):
        return self.lib_in.text

    @lib_query.setter
    def lib_query(self, v):
        self.lib_in.set(v)

    def jurassic(self):
        """True when the theme has interactive animals (dinosaurs / the haunted graveyard) and the world view is showing."""
        return self.theme.fx in ("jurassic", "halloween", "forest") and self.mode == "world"

    def keep_clear(self, fx, n_q3d, eye):
        """Library: drop the theme's moving things (creatures, petals, leaves, rain, their shadows) that are in the space
        between the camera and the bookcase / open book. Everything else in the world stays where it is."""
        lib = self.lib
        x0, x1 = -library.SHELF_W / 2 - 4.0, library.SHELF_W / 2 + 4.0
        z0, z1 = -3.0, float(eye[2]) + 6.0
        top = lib.row_y[-1] + library.BOOK_H + 6.0

        def inside(x, y, z):
            return (x > x0) & (x < x1) & (z > z0) & (z < z1) & (y < top)
        if len(fx):
            fx = fx[~inside(fx[:, 0], fx[:, 1], fx[:, 2])]
        r = self.r
        for name, parts in r.mesh_inst.items():  # Blender models (creatures, scenery) obey the same rule
            r.mesh_inst[name] = [p_[~inside(p_[:, 0], p_[:, 1], p_[:, 2])] for p_ in parts]
        kept = []
        for tex, buf in r.q3d[n_q3d:]:  # billboards and contact shadows: find each quad's world position from its matrix
            clip = buf[:16].reshape(4, 4).T[:, 3]
            p = r.inv_viewproj @ clip
            if abs(p[3]) > 1e-9:
                p = p[:3] / p[3]
                if inside(p[0], p[1], p[2]):
                    continue
            kept.append((tex, buf))
        r.q3d[n_q3d:] = kept
        return fx

    def reading_focus(self):
        """True while a book is open in the library: the world, its creatures and effects step aside so you can read."""
        lib = self.lib
        return bool(self.mode == "library" and lib and lib.pick and lib.pick["u"] >= 0.9 and not lib.pick["closing"])

    def herd(self):
        return effects.creatures(self.theme) or effects._herd

    def floor_point(self):
        """Where the mouse ray meets the ground (y = 0), or None."""
        o, d = self.mouse_ray()
        if d[1] > -1e-4:
            return None
        t = -o[1] / d[1]
        return o[0] + d[0] * t, o[2] + d[2] * t

    def click_dino(self):
        """Jurassic theme: click a dinosaur to make it roar, or click the ground to drop food. True if the click was used."""
        herd = self.herd()
        i = herd.pick(*self.mouse_ray())
        if i is not None:
            d = herd.poke(i, self.t)
            self.dino_card = (i, self.t)
            self.status = f"The {d.name} {getattr(d, 'verb', 'screeches' if d.flyer else 'roars')}!  (V to follow it)"
            return True
        pt = self.floor_point()
        if pt is None or math.hypot(*pt) > 260:
            return False
        d = herd.feed(pt[0], pt[1], self.t)
        what = {"halloween": "candy", "forest": "berries"}.get(self.theme.fx, "food")
        self.status = f"You dropped some {what} - a {d.name} is coming for it" if d else f"Nothing wants that {what} right now"
        return True

    def toggle_follow(self):
        herd = self.herd()
        i = self.dino_hover if self.dino_hover is not None else (self.dino_card[0] if self.dino_card else None)
        if self.follow is not None:
            self.follow = None
            self.scene.goto_home()
            self.status = "Stopped following"
        elif i is not None:
            self.follow = i
            self.status = f"Following the {herd.dinos[i].name} (V or Esc to stop)"
        else:
            self.status = "Hover or click a creature first"

    def tracked(self, msg, cb):
        """Wrap a result callback so a spinner with `msg` shows (after a short delay) until the work finishes."""
        tok = object()
        self.busy[tok] = (msg, self.t)

        def done(*args):
            self.busy.pop(tok, None)
            return cb(*args)
        return done

    # ---------- engine glue ----------
    def pump(self):
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                return
            if item[0] == "event":
                self.on_engine_event(item[1])
            else:
                _, cb, result, err = item
                try:
                    cb(result, err)
                except Exception as e:  # noqa: BLE001
                    self.status = f"UI error: {e}"

    def on_engine_event(self, ev):
        kind = ev.get("event")
        if kind == "player":
            self.player = ev["state"]
            self.audio = self.player.get("mode", self.audio)
        elif kind == "watched" and self.lib and any(b["id"] == ev["anime_id"] for b in self.lib.books):
            for b in self.lib.books:
                if b["id"] == ev["anime_id"]:
                    b["episodes"], b["watched"] = ev["episodes"], len(set(ev["episodes"]))
        elif kind == "watched" and self.scene.field and self.scene.peds[self.scene.field["idx"]]["id"] == ev["anime_id"]:
            self.scene.field["watched"] = set(ev["episodes"])
        elif kind == "error":
            self.status = ev["message"]
        if kind == "watched":
            self.check_adv()

    # ---------- actions ----------
    def search(self, q=None):
        q = (q or self.query).strip()
        if not q:
            return
        self.suggest, self.sugg_sel, self.sugg_for = [], -1, q
        self.history_mode = False
        self.view, self.home_started = "search", True
        self.status = f"Searching '{q}'..."
        self.be.call("search", {"q": q}, self.tracked(f"Searching '{q}'", self._got_results))

    def _got_results(self, rows, err):
        if err:
            self.status = f"Search failed: {err}"
            return
        self.status = f"{len(rows)} results - click a pedestal" if rows else "Nothing found on hianime or miruro - try another spelling"
        self.show_rows(rows[:30], "SEARCH", sections.group_search(rows[:30]))

    # ---------- home: continue watching + recommendations + popular ----------
    def show_home(self):
        """HOME: the shows you are partway through (click to resume where you stopped), what to watch next, and what is popular."""
        self.history_mode = False
        self.view, self.home_started = "home", True
        self.follow = None
        self.status = "Loading your home..."
        self.home_gen = gen = getattr(self, "home_gen", 0) + 1
        self.be.call("home", {}, self.tracked("Loading home", lambda r, e: self._got_home(gen, r, e)))

    def _got_home(self, gen, r, err):
        if gen != getattr(self, "home_gen", 0) or self.view != "home":
            return  # a search / history view replaced it while this was loading
        if err or not r:
            self.status = f"Home failed: {err}"
            return
        rows, groups, seen = [], [], set()

        def add(label, items, make):
            sect = []
            for it in items:
                row = make(it)
                key = multisrc.akey(row["title"])
                if key in seen:
                    continue
                seen.add(key)
                sect.append(row)
            if sect:
                groups.append((label, sect))
                rows.extend(sect)

        def cont(c):
            where = f" - {core.fmt(c['pos'])}" if c["pos"] > 10 else ""
            return {"id": c["id"], "title": c["title"], "poster": c["poster"], "sub": f"EP {c['ep']}{where}", "resume": {"ep": c["ep"], "pos": c["pos"]}}
        add("CONTINUE WATCHING", r["continue"], cont)
        add("RECOMMENDED FOR YOU" if r.get("personal") else "TOP RATED", r["recommended"],
            lambda x: {"id": "q:" + x["title"], "title": x["title"], "poster": x["poster"]})
        add("POPULAR", r["popular"], lambda x: {"id": x["id"], "title": x["title"], "poster": x["poster"]})
        add("TOP AIRING", r["airing"], lambda x: {"id": x["id"], "title": x["title"], "poster": x["poster"]})
        n = len(r["continue"])
        self.status = (f"{n} show{'s' if n != 1 else ''} to continue - click one to pick up where you left off" if n
                       else "Pick something popular, or search with /")
        self.show_rows(rows, "HOME", groups)

    def show_rows(self, rows, heading, groups=None):
        self.seq += 1
        self.scene.set_results(rows, self.t, heading, groups)
        self.info = {"manga": [], "related": None}
        for p in self.scene.peds:
            self.load_poster(p)
            if not p["id"].startswith("q:"):  # recommendations are only titles until opened
                self.be.run(self._count(p["id"]), lambda n, e, p=p: p.__setitem__("eps", n))
            if not p["poster_url"] and p["id"]:
                self.be.run(self._poster_for(p["title"], p["id"]), lambda url, e, p=p: (p.__setitem__("poster_url", url), self.load_poster(p)) if url else None)

    async def _count(self, anime_id):
        return len((await core.backend("episodes", anime_id)).split())

    def load_poster(self, ped):
        if not ped["poster_url"]:
            return

        async def go():
            return await decode_image(await core.fetch_poster(ped["poster_url"]), (400, 600))
        self.be.run(go(), lambda img, e, p=ped: self._poster(p, img, e))

    def _poster(self, ped, img, err):
        if err or img is None:
            return
        self.upload_q.append((ped, img))  # uploaded by drain_uploads(), two per frame

    def drain_uploads(self, budget=2):
        while self.upload_q and budget > 0:
            ped, img = self.upload_q.pop(0)
            ped["poster"] = self.r.make_texture(np.asarray(img))
            budget -= 1

    def show_history(self):
        """HISTORY works from anywhere: it closes the library / game / overlays and shows your watch history in the world."""
        self.arcade_menu, self.adv_open, self.lib_typing, self.typing = False, False, False, False
        if self.mode != "world":
            self.mode, self.game, self.lib, self.game_back = "world", None, None, None
        self.follow = None
        self.history_mode = True
        self.view, self.home_started = "history", True
        self.status = "Loading watch history..."
        self.be.call("history", {}, self.tracked("Loading history", self._got_history))

    def _got_history(self, rows, err):
        if err:
            self.status = f"History failed: {err}"
            return
        rows = [h for h in rows if h["id"]][:36]
        self.status = f"{len(rows)} anime in your watch history" if rows else "No watch history yet - play an episode first"
        rows = [{"id": h["id"], "title": h["title"], "poster": "", "last": h.get("last")} for h in rows]
        self.show_rows(rows, "HISTORY", sections.group_history(rows))
        for p in self.scene.peds:  # history has no posters, find them through the (cached) search
            self.be.run(self._poster_for(p["title"], p["id"]), lambda url, e, p=p: (p.__setitem__("poster_url", url), self.load_poster(p)) if url else None)

    async def _poster_for(self, title, anime_id):
        rows = (await core.backend("search", title.replace(" ", "+"))).splitlines()
        for line in rows:
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0] == anime_id:
                return parts[2]
        for line in rows:  # ids differ between sites: fall back to the same show by title
            parts = line.split("\t")
            if len(parts) >= 3 and multisrc.same_show(parts[1], title):
                return parts[2]
        return None

    def update_suggestions(self):
        """Search-bar suggestions: your own titles right away, then what the sources return (cached, so Enter is instant)."""
        q = self.query.strip()
        if not (self.typing and self.mode == "world") or not q:
            if not q:
                self.suggest, self.sugg_for = [], ""
            return
        if q == self.sugg_for or self.t < self.sugg_due:
            return
        self.sugg_for = q
        low = q.lower()
        mine = [t_ for t_ in dict.fromkeys(core.known_titles() + [p["title"] for p in self.scene.peds]) if low in t_.lower()]
        self.suggest, self.sugg_sel = mine[:7], -1
        if len(q) >= 2:
            async def remote():
                return [ln.split("\t")[1] for ln in (await core.backend("search", q)).splitlines() if "\t" in ln]
            self.be.run(remote(), lambda rows, e, q=q: self._got_suggest(q, rows, e))

    def _got_suggest(self, q, rows, err):
        if err or not rows or q != self.sugg_for or not self.typing:
            return
        self.suggest = list(dict.fromkeys(self.suggest + rows))[:8]

    def pick_suggestion(self, i):
        if 0 <= i < len(self.suggest):
            self.query, self.typing, self.suggest = self.suggest[i], False, []
            self.search()

    def load_edits(self):
        f = self.scene.field
        title = self.scene.peds[f["idx"]]["title"] if f else None
        if not title:
            self.status = "Open an anime first"
            return
        self.edits = "loading"
        self.be.call("edits", {"title": title}, lambda r, e: setattr(self, "edits", r if r else []))

    def check_adv(self, only=None):
        """Evaluate advancements (after an episode / chapter / game event) and queue toasts for new ones."""
        new = [only] if only else self.adv.refresh()
        for title, desc, group in [n for n in new if n]:
            self.toasts.append((title, desc, group, self.t))
        if new and any(new):
            self.status = f"Advancement made: {new[-1][0]}"

    def open_ped(self, idx):
        p = self.scene.peds[idx]
        self.seq += 1
        seq = self.seq
        self.scene.selected = idx
        self.info = {"manga": [], "related": None}
        self.edits = None
        self.status = f"Opening {p['title']}..."
        self.be.call("episodes", {"id": p["id"], "title": p["title"]},
                     self.tracked(f"Opening {p['title'][:28]}", lambda r, e: self._opened(seq, idx, r, e)))
        self.be.call("info", {"title": p["title"]}, lambda r, e: seq == self.seq and r and self.info.__setitem__("manga", r["manga"]))

    def _opened(self, seq, idx, r, err):
        if seq != self.seq:
            return
        if err:
            self.status = f"Failed: {err}"
            return
        ped = self.scene.peds[idx]
        ped["eps"] = len(r["episodes"])
        if r.get("id"):
            ped["id"] = r["id"]  # a recommendation resolved to a real site id
        self.scene.open_field(idx, r["episodes"], r["watched"], self.t)
        self.status = f"{len(r['episodes'])} episodes - click a block to play"
        rs = ped.get("resume")
        if rs:  # CONTINUE WATCHING: start playing right where it was left
            ep = next((e for e in r["episodes"] if e == rs["ep"] or multisrc.canon(e) == multisrc.canon(rs["ep"])), None)
            if ep:
                self.play(ep, rs["pos"] if rs["pos"] > 10 else 0)

    def play(self, ep, start=0):
        f = self.scene.field
        p = self.scene.peds[f["idx"]]
        self.status = f"Starting episode {ep}..." if not start else f"Resuming episode {ep} at {core.fmt(start)}..."
        self.be.call("play", {"id": p["id"], "title": p["title"], "ep": ep, "mode": self.audio, "episodes": f["eps"], "start": start,
                              "poster": p.get("poster_url", "")},
                     lambda r, e: setattr(self, "status", f"Play failed: {e}") if e else
                     setattr(self, "status", f"Playing episode {ep}" + (f" via {r['source']}" if r and r.get("source") else "")))

    def toggle_skip(self, kind):
        """SKIP INTRO / SKIP CREDITS: switches automatic skipping for every episode on or off, and skips right now when turning on."""
        if kind == "intro":
            self.auto_intro = not self.auto_intro
            on = self.auto_intro
        else:
            self.auto_outro = not self.auto_outro
            on = self.auto_outro
        themes.save_settings(auto_skip_intro=self.auto_intro, auto_skip_outro=self.auto_outro)
        self.control("autoskip", {"intro": self.auto_intro, "outro": self.auto_outro})
        if on and self.player.get("playing"):
            self.control("skip_intro" if kind == "intro" else "skip_outro")
        what = "intro" if kind == "intro" else "credits"
        self.status = f"Auto-skip {what}: ON for every episode (click again to turn off)" if on else f"Auto-skip {what}: off"

    def toggle_autofs(self):
        self.auto_fs = not self.auto_fs
        themes.save_settings(auto_fullscreen=self.auto_fs)
        self.control("autofs", self.auto_fs)
        self.status = "Auto fullscreen ON: episodes open fullscreen" if self.auto_fs else "Auto fullscreen off"

    def control(self, action, value=None):
        self.be.call("control", {"action": action, "value": value}, lambda r, e: setattr(self, "status", str(e)) if e else None)

    def toggle_mode(self):
        self.audio = "dub" if self.audio == "sub" else "sub"
        if self.player.get("playing"):
            self.control("mode", self.audio)
        self.status = f"Audio: {self.audio.upper()}"

    def load_related(self):
        f = self.scene.field
        title = self.scene.peds[f["idx"]]["title"] if f else None
        if not title:
            self.status = "Open an anime first"
            return
        self.info["related"] = "loading"
        self.be.call("related", {"title": title}, lambda r, e: self.info.__setitem__("related", r if r else None))

    # ---------- modes: arcade + library ----------
    def exit_mode(self):
        if self.mode == "game" and self.game_back == "library" and self.lib:
            self.mode, self.game, self.game_back = "library", None, None  # back to the shelves
            return
        self.mode, self.game, self.lib, self.arcade_menu, self.game_back = "world", None, None, False, None
        self.scene.goto_home()

    def start_game(self, key, back=None):
        self.arcade_menu, self.typing = False, False
        self.game_back = back if (back == "library" and self.lib) else None
        self.game = games.GAMES[key](self)
        self.mode = "game"
        self.scene.cam.goto(*self.game.cam)
        self.status = f"{self.game.name}: {self.game.help}"

    def open_library(self, kind="anime"):
        self.arcade_menu, self.typing = False, False
        if kind == "manga":
            self.status = "Building your manga library (MangaDex)... this can take a few seconds the first time"
            self.be.run(self._manga_groups(), self.tracked("Building the manga library", lambda r, e: self._library_ready(r, e, "manga")))
            return
        self.status = "Building your library from the watch history..."
        self.be.run(self._library_rows(), self.tracked("Building the library", lambda r, e: self._library_ready(r, e, "anime")))

    async def _manga_groups(self):
        """Sections for the manga shelf: what you're reading, manga of your anime, and what's popular - hosted chapters only."""
        reading = core.mr_list()[:14]
        hist = await self.be.engine.handle("history", {})
        seen, titles = set(), []
        for t_ in [h["title"] for h in hist][:10] + [w["title"] for w in core.wl_list()][:6]:
            key = core.norm(core.base_title(t_))
            if key not in seen:  # seasons / movies of one series map to the same manga: look it up once
                seen.add(key)
                titles.append(t_)
        matches = await asyncio.gather(*(core.md_for_title(t) for t in titles), return_exceptions=True)
        popular = await core.md_popular(18)
        items, order = {}, []

        def add(it, group):
            if it and not isinstance(it, Exception) and it["id"] not in items:
                items[it["id"]] = {"id": it["id"], "title": it["title"], "cover": it.get("cover", ""), "group": group,
                                   "title_en": it.get("title_en") or it["title"], "title_jp": it.get("title_jp") or ""}
                order.append(it["id"])
        for rd in reading:
            add({"id": rd["id"], "title": rd["title"], "cover": rd["cover"], "title_jp": rd.get("title_jp", "")}, "reading")
        for pm in core.mp_list():
            add(pm, "plan")
        for m in matches:
            add(m, "anime")
        probes = await asyncio.gather(*(core.probe_any(i) for i in order), return_exceptions=True)  # one cheap request each
        read = {rd["id"]: rd for rd in reading}
        groups = {"reading": [], "plan": [], "anime": [], "popular": [], "done": []}
        for mid, total in zip(order, probes):
            if isinstance(total, Exception) or not total:
                continue
            it = items[mid]
            done_chs = [c for c in read.get(mid, {}).get("chapters", []) if c]
            # the full chapter list is fetched later, when the book is opened (see ensure_chapters)
            book = {"id": mid, "title": it["title"], "title_en": it["title_en"], "title_jp": it["title_jp"], "episodes": done_chs, "all_eps": [],
                    "chapters": None, "total": total, "last": read.get(mid, {}).get("last"), "poster_url": it["cover"],
                    "src": mid.split(":")[0] if ":" in mid else "md"}
            if done_chs and len(set(done_chs)) >= total:
                groups["done"].append(book)
            elif done_chs:
                groups["reading"].append(book)
            else:
                groups[it["group"]].append(book)
        self._popular_todo = [pm for pm in popular if pm["id"] not in items][:16]  # probed in the background after the shelf shows
        return groups

    async def _library_rows(self):
        hist = [h for h in await self.be.engine.handle("history", {}) if h["id"]][:48]
        wl = core.wl_list()[:30]

        async def fill(h):
            try:
                h["all_eps"] = (await core.backend("episodes", h["id"])).split()
            except Exception:  # noqa: BLE001
                h["all_eps"] = []
            h["total"] = len(h["all_eps"])
        await asyncio.gather(*(fill(h) for h in hist + wl))
        return hist, wl

    def _library_ready(self, result, err, kind="anime"):
        if err:
            self.status = f"Library failed: {err}"
            return
        if kind == "manga":
            self.lib = library.Library(self, [], [], "manga", result)
            self.lib_t0, self.mode = self.t, "library"
            n = {k: v[1] for k, v in self.lib.section_info.items()}
            self.status = f"Reading {n['reading']}  -  Of your anime {n['anime']}  -  Finished {n['done']}  -  loading popular..."
            self._fill_jp_titles()
            todo = getattr(self, "_popular_todo", [])
            if todo:
                self.be.run(self._probe_popular(todo), lambda books, e: self._popular_ready(books) if not e else None)
            return
        rows, wl = result
        self.starred.clear()
        self.starred.update(w["id"] for w in core.wl_list())
        self.lib = library.Library(self, rows, wl)
        self.lib_t0, self.mode = self.t, "library"
        n = {k: v[1] for k, v in self.lib.section_info.items()}
        self.status = f"Watching {n['watching']}  -  Planning {n['planning']}  -  Watched {n['watched']}"

    async def _probe_popular(self, todo):
        probes = await asyncio.gather(*(core.md_probe(it["id"]) for it in todo), return_exceptions=True)
        return [{"id": it["id"], "title": it["title"], "title_en": it.get("title_en") or it["title"], "title_jp": it.get("title_jp") or "", "episodes": [],
                 "all_eps": [], "chapters": None, "total": n, "last": None, "poster_url": it["cover"]}
                for it, n in zip(todo, probes) if not isinstance(n, Exception) and n]

    def _popular_ready(self, books):
        if self.lib and self.lib.kind == "manga" and books:
            self.lib.extend("popular", books)
            self.status = f"Popular manga added ({len(books)})"

    def wl_with_data(self, new_wl, old_wl):
        """Keep the episode data we already fetched when the star list changes."""
        have = {w["id"]: w for w in old_wl}
        for w in new_wl:
            if w["id"] in have:
                w["all_eps"], w["total"] = have[w["id"]].get("all_eps", []), have[w["id"]].get("total", 0)
        return new_wl

    def toggle_star(self, anime_id, title, poster=""):
        if anime_id in self.starred:
            core.wl_remove(anime_id)
            self.starred.discard(anime_id)
            self.status = f"Removed '{title}' from your watch list"
        else:
            core.wl_add(anime_id, title, poster)
            self.starred.add(anime_id)
            self.status = f"* Added '{title}' to your watch list (see Planning on the bookshelf)"

    def star_selected(self):
        """World view: star/unstar the hovered pedestal, else the open anime."""
        idx = self.hover[1] if self.hover and self.hover[0] == "ped" else self.scene.selected
        if idx is None or idx >= len(self.scene.peds):
            self.status = "Hover or open an anime first"
            return
        p = self.scene.peds[idx]
        self.toggle_star(p["id"], p["title"], p.get("poster_url", ""))

    def ensure_chapters(self, book, then=None, quiet=False):
        """Manga shelves only probe chapter counts; the full list is fetched the first time a book is opened."""
        if book.get("chapters") is not None:
            return then() if then else None
        book.setdefault("_after", [])
        if then:
            book["_after"].append(then)
        if book.get("_loading"):
            return
        book["_loading"] = True

        def done(res, err):
            book["_loading"] = False
            if err or res is None:
                if not quiet:
                    self.status = f"Couldn't load the chapter list: {err}"
                book["_after"] = []
                return
            chs, label = res
            book["chapters"], book["all_eps"], book["total"], book["source"] = chs, [c["chapter"] for c in chs], len(chs), label
            if label != "MangaDex" and not quiet:
                self.status = f"MangaDex only hosts part of '{book['title'][:30]}' - reading all {len(chs)} chapters from {label}"
            if self.lib and self.lib.bv and self.lib.bv.b is book:
                self.lib.bv.art.clear()
            for cb in book.pop("_after", []):
                cb()
        self.be.run(core.full_chapters(book), done if quiet else self.tracked("Loading chapter list", done))

    def read_chapter(self, book, chapter):
        """Open a manga chapter inside the open book: fetch its page list, then the images stream in as you turn pages."""
        if book.get("chapters") is None:
            return self.ensure_chapters(book, lambda: self.read_chapter(book, chapter))
        ch = next((c for c in book.get("chapters", []) if c["chapter"] == chapter), None)
        bv = self.lib.bv if self.lib else None
        if not ch or not bv:
            self.status = "That chapter isn't available"
            return
        self.status = f"Loading chapter {chapter} of {book['title']}..."

        def done(urls, err):
            if err or not urls:
                self.status = f"Couldn't load chapter {chapter}: {err or 'no pages'}"
                return
            bv.set_chapter(chapter, urls)
            core.mr_add(book["id"], book.get("title_en") or book["title"], book.get("poster_url", ""), chapter, book.get("title_jp", ""))
            self.check_adv()
            if chapter not in book["episodes"]:
                book["episodes"] = book["episodes"] + [chapter]
                book["watched"] = len(set(book["episodes"]))
            book["last"] = time.strftime("%Y-%m-%d")
            self.status = f"Chapter {chapter}: {len(urls)} pages - scroll down to read (V for the book)" if bv.scrolling() else f"Chapter {chapter}: {len(urls)} pages - " + ("right to left (left arrow = next page)" if bv.rtl else "left to right (right arrow = next page)") + ", wheel to zoom, Z fits a page"
        self.be.run(core.chapter_pages(ch), self.tracked(f"Loading chapter {chapter}", done))

    def fetch_page_image(self, url, bv):
        async def go():
            return await decode_image(await core.fetch_manga_image(url), (1100, 1600))

        def done(img, err):
            if img is not None and not err:
                bv.imgs[url] = img
            elif err:
                self.status = f"Page failed to load: {err}"
        self.be.run(go(), done)

    def play_from_book(self, book, ep):
        self.status = f"Starting episode {ep} of {book['title']}..."
        self.be.call("play", {"id": book["id"], "title": book["title"], "ep": ep, "mode": self.audio, "episodes": book["all_eps"] or [ep]},
                     lambda r, e: setattr(self, "status", f"Play failed: {e}") if e else None)

    def fetch_book_poster(self, book):
        """Fetch the poster shown on the left page when a book is opened."""
        if book.get("poster_img") or book.get("poster_loading"):
            return
        book["poster_loading"] = True

        async def go():
            url = book.get("poster_url") or await self._poster_for(book["title"], book["id"])
            return await decode_image(await core.fetch_poster(url), (400, 600)) if url else None

        def done(img, err):
            if img is not None and not err:
                book["poster_img"] = img
            book["poster_loading"] = False
        self.be.run(go(), done)

    def open_history_book(self, book):
        """The person pulled a book out: show that anime's episodes in the main world."""
        self.exit_mode()
        self.show_rows([{"id": book["id"], "title": book["title"], "poster": ""}], "HISTORY")
        self.history_mode = True
        p = self.scene.peds[0]
        self.be.run(self._poster_for(book["title"], book["id"]), lambda url, e, p=p: (p.__setitem__("poster_url", url), self.load_poster(p)) if url else None)
        self.open_ped(0)

    def _fill_jp_titles(self):
        """Books that came from your reading list only have one title: fetch the other language in one request."""
        need = [b["id"] for b in (self.lib.books if self.lib else []) if not b.get("title_jp") and ":" not in b["id"]]
        if not need:
            return

        def done(res, err):
            if err or not res or not self.lib:
                return
            for b in self.lib.books:
                if b["id"] in res:
                    b["title_en"], b["title_jp"] = res[b["id"]]
            self.lib.apply_titles()
        self.be.run(core.md_alt_titles(need[:100]), done)

    def toggle_titles(self):
        self.manga_jp = not self.manga_jp
        themes.save_settings(manga_jp=self.manga_jp)
        if self.lib and self.lib.kind == "manga":
            self.lib.apply_titles()
        self.status = "Manga titles: Japanese (romaji)" if self.manga_jp else "Manga titles: English"

    def open_mangafire(self, title):
        """MangaFire as the last resort: its search page opens in the browser (no hosted chapters to read in the 3D book)."""
        url = core.mangafire_url(title)
        webbrowser.open(url)
        self.status = f"Opened MangaFire for '{title}'"

    def librarian_search(self, q):
        q = q.strip()
        if not q or not (self.mode == "library" and self.lib and self.lib.kind == "manga"):
            return
        self.status = f"The librarian is searching for '{q}'..."
        self.recent = [q] + [r_ for r_ in self.recent if r_.lower() != q.lower()]
        self.recent = self.recent[:8]
        themes.save_settings(librarian_recent=self.recent)
        self.lib_busy = True

        async def go():
            items = await core.search_all(q)
            return [{"id": it["id"], "title": it["title"], "title_en": it.get("title_en") or it["title"], "title_jp": it.get("title_jp") or "", "episodes": [], "all_eps": [],
                     "chapters": None, "total": it["total"], "last": None, "poster_url": it["cover"], "src": it.get("src", "md")} for it in items]

        def done(books, err):
            self.lib_busy = False
            if err:
                self.status = f"The librarian couldn't search: {err}"
            elif not self.lib or self.lib.kind != "manga":
                return
            elif not books:
                self.lib.mangafire = q
                self.status = f"Nothing hosted for '{q}' - the MANGAFIRE button opens it in your browser"
            else:
                self.lib.set_search(q, books)
                self.status = f"The librarian found {len(books)} for '{q}' - she walked you to the shelf"
        self.be.run(go(), self.tracked(f"Librarian: {q}", done))

    STARTERS = ["One Piece", "Berserk", "Vagabond", "Chainsaw Man", "Frieren", "Dandadan", "Blue Lock", "Vinland Saga"]

    def lib_choices(self):
        """Entries under the librarian's box: recent searches, or matches among your searches and the books on the shelves."""
        q = self.lib_query.strip().lower()
        if not q:
            return (self.recent + [t_ for t_ in self.STARTERS if t_ not in self.recent])[:7]
        pool = self.recent + [b["title"] for b in (self.lib.books if self.lib else [])]
        return [t_ for t_ in dict.fromkeys(pool) if q in t_.lower() and t_.lower() != q][:7]

    def librarian_overlay(self, W, H):
        """The librarian's question box: a modal panel with the input field, recent searches and clear hints."""
        th = self.theme
        r = self.r
        n0 = len(self.hits)
        r.rect(0, 0, W, H, (0, 0, 0, 0.55))
        pw = min(W - 40, 640)
        choices = self.lib_choices()
        ph = 150 + 34 * len(choices) + (24 if choices else 0) + 72
        x, y = W / 2 - pw / 2, max(90, H * 0.18)
        r.rect(x, y, pw, ph, (0.015, 0.02, 0.04, 0.98))
        self.panel(x, y, pw, ph)
        r.rect(x, y, pw, 5, th.accent + (1,))
        self.txt("ASK THE LIBRARIAN", x + 24, y + 18, 24, th.logo)
        self.txt("Search MangaDex for manga with chapters you can read here", x + 24, y + 52, 12, th.dim)
        # input field
        fx, fy, fw, fh = x + 24, y + 80, pw - 48, 46
        r.rect(fx, fy, fw, fh, (0.0, 0.0, 0.0, 0.75))
        for rx, ry, rw, rh in ((fx, fy, fw, 2), (fx, fy + fh - 2, fw, 2), (fx, fy, 2, fh), (fx + fw - 2, fy, 2, fh)):
            r.rect(rx, ry, rw, rh, th.accent + (1,))
        room = max(int((fw - 70) / 11), 8)
        if self.lib_query:
            vis, cp = self.lib_in.window(room)
            caret = "|" if int(self.t * 2) % 2 == 0 else " "
            self.txt(f"{vis[:cp]}{caret}{vis[cp:]}", fx + 46, fy + 11, 20, (1, 1, 1))
        else:
            caret = "|" if int(self.t * 2) % 2 == 0 else " "
            self.txt(f"{caret}e.g. berserk, solo leveling, one piece", fx + 46, fy + 12, 18, th.dim)
        self.txt("?", fx + 16, fy + 8, 26, th.accent)
        if self.lib_busy:
            self.txt("searching...", fx + fw - 120, fy + 14, 14, th.accent)
        # choices
        cy = fy + fh + 14
        if choices:
            self.txt("RECENT AND SUGGESTED" if not self.lib_query.strip() else "MATCHES", x + 24, cy, 11, th.dim)
            cy += 24
        hits = []
        for i, c in enumerate(choices):
            on = i == self.lib_sel or self.hit_test(fx, cy, fw, 30)
            if on:
                r.rect(fx, cy, fw, 30, (*th.edge[:3], 0.35))
            tag = "recent" if c in self.recent else "shelf" if self.lib_query.strip() else "idea"
            self.txt(c[:56], fx + 12, cy + 6, 15, (1, 1, 1) if on else th.text)
            self.txt(tag, fx + fw - 12 - len(tag) * 7, cy + 9, 11, th.dim)
            hits.append((fx, cy, fw, 30, lambda *_, c=c: (self.lib_in.set(c), setattr(self, "lib_typing", False), self.librarian_search(c))))
            cy += 34
        # footer
        by = y + ph - 54
        self.txt("Enter search  -  up/down choose  -  Esc close  -  hold Backspace to erase", x + 24, by - 22, 11, th.dim)
        self.button("SEARCH", x + pw - 24 - 110, by, 110, 36, lambda: (setattr(self, "lib_typing", False), self.librarian_search(self.lib_query)))
        self.button("CANCEL", x + pw - 24 - 230, by, 110, 36, lambda: setattr(self, "lib_typing", False))
        # modal: the panel's own hits first, then a full-screen catch-all so nothing behind it can be clicked
        self.hits[:] = hits + self.hits[n0:] + [(0, 0, W, H, lambda *_: None)]

    def export_chapter(self, book, chapter=None):
        """Write a chapter as a PDF and open it in the system's document reader (the next unread chapter when none is given)."""
        if chapter is None and self.lib and self.lib.bv and self.lib.bv.b is book:
            chapter = self.lib.bv.next_ep() if self.lib.bv.mode == "toc" else self.lib.bv.chapter
        self.status = f"Preparing {'chapter ' + str(chapter) if chapter else 'the next chapter'} of {book['title']} as a PDF..."

        def make_pdf(files, out):
            from PIL import Image  # noqa: PLC0415

            imgs = []
            for f in files:
                im = Image.open(f).convert("RGB")
                if im.width > 1500:
                    im = im.resize((1500, round(im.height * 1500 / im.width)), Image.LANCZOS)
                imgs.append(im)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            imgs[0].save(out, "PDF", save_all=True, append_images=imgs[1:], resolution=110.0)
            return out

        async def go():
            if book.get("chapters") is None:
                book["chapters"], book["source"] = await core.full_chapters(book)
                book["all_eps"] = [c["chapter"] for c in book["chapters"]]
            if not book["chapters"]:
                raise RuntimeError("no hosted chapters")
            done_set = set(book.get("episodes") or [])
            no = chapter if chapter is not None else next((c["chapter"] for c in book["chapters"] if c["chapter"] not in done_set), book["chapters"][0]["chapter"])
            ch = next((c for c in book["chapters"] if c["chapter"] == no), None)
            if not ch:
                raise RuntimeError(f"chapter {no} isn't available")
            urls = await core.chapter_pages(ch)
            files = list(await asyncio.gather(*(core.fetch_manga_image(u) for u in urls)))  # the API gate keeps a few in flight
            safe = "".join(c for c in (book.get("title_en") or book["title"]) if c.isalnum() or c in " -_")[:60].strip() or "manga"
            out = os.path.join(paths.documents_dir(), safe, f"{safe} - chapter {no}.pdf")
            return await asyncio.to_thread(make_pdf, files, out), no

        def done(res, err):
            if err or not res:
                self.status = f"Couldn't make the PDF: {err}"
                return
            out, no = res
            core.mr_add(book["id"], book.get("title_en") or book["title"], book.get("poster_url", ""), no, book.get("title_jp", ""))
            if no not in book["episodes"]:
                book["episodes"] = book["episodes"] + [no]
                book["watched"] = len(set(book["episodes"]))
            paths.open_file(out)
            self.status = f"Opened chapter {no} in your document reader  ({out})"
            self.check_adv()
        self.be.run(go(), self.tracked("Making the chapter PDF", done))

    def toggle_manga_direction(self):
        self.manga_rtl = not self.manga_rtl
        themes.save_settings(manga_rtl_v2=self.manga_rtl)
        if self.lib and self.lib.bv:
            self.lib.bv.set_direction(self.manga_rtl)
        self.status = "Reading direction: right to left (classic manga, left arrow = next page)" if self.manga_rtl else "Reading direction: left to right (right arrow = next page)"

    def cycle_theme(self, step=1):
        i = (themes.ORDER.index(self.theme.key) + step) % len(themes.ORDER)
        self.theme = themes.THEMES[themes.ORDER[i]]
        themes.save_theme(self.theme.key)
        self.scene.dist_scale = 1.35 if self.theme.fx in ("jurassic", "halloween", "forest") else 1.0
        if self.mode == "world" and not self.scene.field and self.scene.peds:
            self.scene.goto_home()
        self.status = f"Theme: {self.theme.label}"

    def home(self):
        self.follow = None
        if self.mode != "world":
            return self.exit_mode()
        if self.scene.field:
            self.scene.close_field()
        elif self.view != "home":
            self.show_home()  # HOME from a search / history view: back to continue-watching + recommendations
        else:
            self.scene.goto_home()
        self.info = {"manga": [], "related": None}

    # ---------- input ----------
    def on_input(self, ev):
        k = ev["event_type"]
        if k == "pointer_move":
            self.mouse = (ev["x"], ev["y"])
            if self.down and ev.get("buttons"):
                dx, dy = ev["x"] - self.down[0], ev["y"] - self.down[1]
                if self.dragged or math.hypot(dx, dy) > 5:
                    self.dragged = True
                    mx, my = self.last_drag
                    if self.mode == "library" and self.lib and self.lib.drag_candidate is not None:
                        self.lib.start_drag(*self.mouse_ray())
                    if self.mode == "library" and self.lib and self.lib.drag:
                        self.lib.drag_move(*self.mouse_ray())
                    elif self.mode == "library" and self.lib and self.lib.pick:
                        self.lib.pan_by(ev["x"] - mx, ev["y"] - my)  # drag pans the zoomed book
                    elif 1 in ev["buttons"]:
                        self.scene.cam.orbit(ev["x"] - mx, ev["y"] - my)
                    else:
                        self.scene.cam.pan(ev["x"] - mx, ev["y"] - my)
                self.last_drag = (ev["x"], ev["y"])
        elif k == "pointer_down":
            self.down = (ev["x"], ev["y"])
            self.last_drag = self.down
            self.dragged = False
            self.mouse = self.down
            if self.mode == "library" and self.lib and not self.lib.pick and not self.arcade_menu and not self.adv_open \
                    and not any(hx <= ev["x"] <= hx + hw and hy <= ev["y"] <= hy + hh for hx, hy, hw, hh, _ in self.hits):
                self.lib.drag_candidate = self.lib.pick_book(*self.mouse_ray())  # a press on a shelved book may become a drag
        elif k == "pointer_up":
            if self.mode == "library" and self.lib and self.lib.drag:
                self.lib.drop()
            elif self.down and not self.dragged and ev.get("button") == 1:
                self.click(ev["x"], ev["y"])
            if self.lib:
                self.lib.drag_candidate = None
            self.down = None
        elif k == "wheel":
            if self.adv_open:
                self.adv_scroll = max(0, self.adv_scroll + (60 if ev.get("dy", 0) > 0 else -60))
            elif self.mode == "library" and self.lib and self.lib.drawer and not self.lib.pick and self.mouse[0] < 340:
                self.lib.drawer_scroll += 1 if ev.get("dy", 0) > 0 else -1
            elif self.mode == "library" and self.lib and self.lib.pick:
                self.lib.zoom_by(ev.get("dy", 0))  # zoom the open book
            else:
                self.scene.cam.zoom(ev.get("dy", 0))
        elif k == "char":
            c = ev.get("data") or ev.get("char_str") or ""
            if self.swallow == c:
                self.swallow = None
            elif self.lib_typing and c.isprintable():
                self.lib_in.insert(c)
            elif self.typing and c.isprintable():
                self.q_in.insert(c)
                self.sugg_due = self.t + 0.25
        elif k == "key_down":
            self.mods = tuple(ev.get("modifiers") or ())
            self.keys.add(ev["key"])
            self.pressed.add(ev["key"])
            self.on_key(ev["key"])
        elif k == "key_up":
            self.keys.discard(ev["key"])

    def on_key(self, key):
        if self.lib_typing:  # the librarian's question
            if self.lib_in.key(key, self.mods):
                self.lib_sel = -1
            elif key == "Enter":
                if self.lib_sel >= 0 and self.lib_sel < len(self.lib_choices()):
                    self.lib_in.set(self.lib_choices()[self.lib_sel])
                self.lib_typing = False
                self.librarian_search(self.lib_query)
            elif key == "ArrowDown":
                self.lib_sel = min(self.lib_sel + 1, len(self.lib_choices()) - 1)
            elif key == "ArrowUp":
                self.lib_sel = max(self.lib_sel - 1, -1)
            elif key == "Escape":
                self.lib_typing = False
            return
        if self.adv_open:
            if key in ("Escape", "t", "T"):
                self.adv_open = False
            elif key in ("ArrowDown", "PageDown"):
                self.adv_scroll += 120
            elif key in ("ArrowUp", "PageUp"):
                self.adv_scroll = max(0, self.adv_scroll - 120)
            return
        if key == "h" and not self.typing:
            self.show_history()  # from anywhere: library, games, an open book...
            return
        if key == "u" and not self.typing and not self.arcade_menu:
            self.hide_ui = not self.hide_ui
            self.status = "UI hidden - press U or click the corner chip to bring it back" if self.hide_ui else "UI shown"
            return
        if self.arcade_menu:
            names = list(games.GAMES)
            if len(key) == 1 and key in "1234567"[:len(names)]:
                self.start_game(names[int(key) - 1], back="library" if self.mode == "library" else None)
            elif key in ("Escape", "g"):
                self.arcade_menu = False
            return
        if self.mode != "world":
            if key == "Escape" and not (self.lib and self.lib.pick):
                self.exit_mode()
            elif key == "t":
                self.cycle_theme()
            else:
                (self.game or self.lib).key(key)
            return
        if self.typing:
            if self.q_in.key(key, self.mods):
                self.sugg_sel, self.sugg_due = -1, self.t + 0.2
            elif key == "ArrowDown" and self.suggest:
                self.sugg_sel = (self.sugg_sel + 1) % len(self.suggest)
            elif key == "ArrowUp" and self.suggest:
                self.sugg_sel = (self.sugg_sel - 1) % len(self.suggest)
            elif key == "Enter":
                if self.sugg_sel >= 0:
                    self.pick_suggestion(self.sugg_sel)
                else:
                    self.typing = False
                    self.suggest = []
                    self.search()
            elif key == "Tab" and self.suggest:  # complete with the highlighted (or first) suggestion without searching yet
                self.query = self.suggest[max(self.sugg_sel, 0)]
                self.sugg_for, self.sugg_sel = self.query.strip(), -1
            elif key in ("Escape", "Tab"):
                self.typing = False
                self.suggest = []
            return
        keys = {
            " ": lambda: self.control("pause"), "ArrowLeft": lambda: self.control("seek", -10), "ArrowRight": lambda: self.control("seek", 10),
            "ArrowUp": lambda: self.control("volume", min(130, self.player.get("volume", 100) + 5)),
            "ArrowDown": lambda: self.control("volume", max(0, self.player.get("volume", 100) - 5)),
            "n": lambda: self.control("next"), "p": lambda: self.control("prev"), "i": lambda: self.toggle_skip("intro"), "o": lambda: self.toggle_skip("outro"),
            "e": self.load_edits,
            "s": lambda: self.control("stop"), "d": self.toggle_mode, "t": self.cycle_theme, "g": lambda: setattr(self, "arcade_menu", True), "l": self.open_library, "m": lambda: self.open_library("manga"), "f": self.star_selected, "v": self.toggle_follow, "r": self.load_related, "h": self.show_history,
            "Escape": self.home, "Backspace": self.home,
        }
        if key in ("/", "Tab"):
            self.typing, self.swallow = True, "/" if key == "/" else None
        elif key in keys:
            keys[key]()

    def click(self, x, y):
        for hx, hy, hw, hh, cb in self.hits:
            if hx <= x <= hx + hw and hy <= y <= hy + hh:
                self.typing = False
                cb(x, y)
                return
        self.typing = False
        if self.mode == "library" and self.lib:
            pk, bv = self.lib.pick, self.lib.bv
            if self.hide_ui and pk and bv and pk["u"] >= 2.85 and (x < self.size[0] * 0.14 or x > self.size[0] * 0.86):
                bv.go(bv.left_delta() if x < self.size[0] / 2 else -bv.left_delta())  # click the screen edges to turn pages
                return
            self.lib.click(*self.mouse_ray())
            return
        if self.mode != "world":
            return
        ref = self.scene.pick(*self.mouse_ray())
        if not ref:
            if self.jurassic():
                self.click_dino()
            return
        if ref[0] == "ped":
            self.open_ped(ref[1])
        elif ref[0] == "ep":
            self.play(ref[1])
        elif ref[0] == "root":
            self.home()

    def mouse_ray(self):
        W, H = self.size
        nx, ny = 2 * self.mouse[0] / W - 1, 1 - 2 * self.mouse[1] / H
        near = mathx.unproject(self.r.inv_viewproj, nx, ny, 0.0)
        far = mathx.unproject(self.r.inv_viewproj, nx, ny, 1.0)
        d = far - near
        return self.scene.cam.eye(), d / np.linalg.norm(d)

    # ---------- frame ----------
    def frame(self, view, phys, ratio, dt):
        self.ratio = ratio
        self.text.ratio = ratio
        W, H = phys[0] / ratio, phys[1] / ratio
        self.size = (W, H)
        self.t += dt
        self.dt_last = dt
        self.pump()
        if not self.home_started and self.mode == "world":  # first frame: the world opens on HOME unless a search ran already
            self.show_home()
        self.drain_uploads()
        r = self.r
        r.resize(*phys)
        cam = self.scene.cam
        if self.typing and self.mode == "world" and self.q_in.update(self.t, self.keys, self.mods):
            self.sugg_sel, self.sugg_due = -1, self.t + 0.2
        if self.lib_typing and self.lib_in.update(self.t, self.keys, self.mods):
            self.lib_sel = -1
        self.update_suggestions()
        if self.mode == "game":
            self.game.update(dt, self.keys)
            for key in self.game.achievements():
                got = self.adv.award(key)
                if got:
                    self.check_adv(got)
        elif self.mode == "library":
            lib = self.lib
            lib.update(dt, self.keys)  # may leave library mode (a picked book opens in the world)
            if self.lib is lib:
                cam.goto(*lib.camera())
        herd = self.herd()
        if self.follow is not None and self.jurassic():  # follow-cam keeps the chosen animal in frame (you can still orbit/zoom)
            d = herd.dinos[self.follow]
            cam.goto((d.x, d.y if d.flyer else 4.0, d.z), cam.g_yaw, max(cam.g_pitch, 0.25), min(max(cam.g_dist, 18), 70))
        cam.update(dt)
        eye = cam.eye()
        self.cam_ground = (float(eye[0]), float(eye[2]))
        view_eye = eye + (np.random.uniform(-1, 1, 3) * herd.shake * 0.7 if self.jurassic() else 0)  # roar shake
        proj = mathx.perspective(math.radians(55), W / H, 0.1, 1200)
        focus = self.reading_focus()
        r.set_camera(mathx.look_at(view_eye, cam.target), proj, view_eye, self.t, (W, H), self.theme, 0.0 if focus else effects.flash(self.theme, self.t))
        if self.mode == "library" and self.lib:
            self.lib.ray = self.mouse_ray()
        if self.mode == "world" and not any(x <= self.mouse[0] <= x + w and y <= self.mouse[1] <= y + h for x, y, w, h, _ in self.hits):
            self.hover = self.scene.pick(*self.mouse_ray())
        else:
            self.hover = None
        self.dino_hover = None
        if self.jurassic() and self.hover is None and not any(x <= self.mouse[0] <= x + w and y <= self.mouse[1] <= y + h for x, y, w, h, _ in self.hits):
            self.dino_hover = herd.pick(*self.mouse_ray())
        if self.mode == "world":
            self.scene.build(r, self.text, self.t, self.hover, self.player, eye, self.theme)
        else:
            r.add_boxes(np.array((self.game or self.lib).build(r, self.text, self.theme, self.t), dtype=np.float32))
        if self.mode != "library":
            self.pressed.clear()
        n_q3d = len(r.q3d)
        fx_boxes, _ = effects.build(self.theme, r, self.text, self.t, eye, self.roam_world())
        fx = np.array(fx_boxes, dtype=np.float32).reshape(-1, 16)
        if self.mode == "library" and self.lib:  # the world stays, but nothing that moves may come between you and the books
            fx = self.keep_clear(fx, n_q3d, eye)
        r.add_boxes(fx)
        self.hits = []
        self.hud(W, H)
        r.render(view)

    # ---------- HUD ----------
    def panel(self, x, y, w, h):
        self.r.rect(x, y, w, h, self.theme.panel)
        for rx, ry, rw, rh in ((x, y, w, 1.5), (x, y + h - 1.5, w, 1.5), (x, y, 1.5, h), (x + w - 1.5, y, 1.5, h)):
            self.r.rect(rx, ry, rw, rh, self.theme.edge)

    def txt(self, s, x, y, px=14, color=None, cb=None, center=False):
        color = color or self.theme.text
        tex, w, h = self.text.get(s, px, tuple(int(c * 255) for c in color))
        if center:
            x -= w / 2
        self.r.quad2d(tex, x, y, w, h)
        if cb:
            self.hits.append((x, y, w, h, cb))
        return w, h

    def button(self, label, x, y, w, h, cb, active=False):
        hot = self.hit_test(x, y, w, h)
        e = self.theme.edge
        self.r.rect(x, y, w, h, (e[0] * 0.6, e[1] * 0.6, e[2] * 0.6, 0.95) if active else ((e[0] * 0.35, e[1] * 0.35, e[2] * 0.35, 0.95) if hot else (e[0] * 0.12, e[1] * 0.12, e[2] * 0.12, 0.92)))
        self.r.rect(x, y + h - 2, w, 2, e)
        self.txt(label, x + w / 2, y + h / 2 - 8, 13, (1, 1, 1) if hot or active else self.theme.text, center=True)
        self.hits.append((x, y, w, h, lambda *_: cb()))

    def hit_test(self, x, y, w, h):
        return x <= self.mouse[0] <= x + w and y <= self.mouse[1] <= y + h

    def hud(self, W, H):
        if self.hide_ui:  # reading mode: nothing but a faint chip to bring the controls back
            self.button("SHOW UI (U)", W - 118, H - 38, 108, 28, lambda: setattr(self, "hide_ui", False))
            return
        self.txt("ANI-3D", 20, 10, 30, self.theme.logo)
        pending = [m for m, t0 in self.busy.values() if self.t - t0 > 0.25]  # spinner for work that takes noticeable time
        if pending:
            cx, cy = 34, 84
            for i in range(8):
                ang = i * math.pi / 4
                a = ((self.t * 9 - i) % 8) / 8
                self.r.rect(cx + math.cos(ang) * 9 - 2.5, cy + math.sin(ang) * 9 - 2.5, 5, 5, (*self.theme.accent, 0.15 + 0.85 * (1 - a)))
            self.txt(pending[-1] + "...", 56, 74, 13, self.theme.accent)
        wide = W >= 1500
        self.txt(f"FILE SYSTEM NAVIGATOR // ANIME  -  {self.gpu_label}  -  {self.theme.label}" if wide else self.theme.label, 22, 46, 11, self.theme.dim)

        # top bar laid out from the right: buttons, then a search bar that fills what is left after the logo
        bx = W - 7 * 85 - 8
        right_edge = bx - 8
        left_limit = 410 if wide else 190
        avail = right_edge - left_limit
        sw = min(460, max(avail, 160))
        sx = left_limit + max(avail - sw, 0) / 2
        self.panel(sx, 14, sw, 38)
        if self.mode == "world":
            room = max(int((sw - 70) / 9.4), 6)
            if self.query or self.typing:
                vis, cp = self.q_in.window(room)
                caret = "|" if self.typing and int(self.t * 2) % 2 == 0 else " "
                self.txt(f"SEARCH> {vis[:cp]}{caret}{vis[cp:]}", sx + 14, 22, 16, self.theme.text)
            else:
                self.txt("SEARCH> press / to search", sx + 14, 22, 16, self.theme.dim)
            self.hits.append((sx, 14, sw, 38, lambda *_: setattr(self, "typing", True)))
        else:
            self.txt(f"{(self.game or self.lib).name}", sx + sw / 2, 22, 16, self.theme.accent, center=True)
        in_manga = self.mode == "library" and self.lib and self.lib.kind == "manga"
        for i, (label, cb, act) in enumerate([("ARCADE", lambda: setattr(self, "arcade_menu", not self.arcade_menu), self.arcade_menu or self.mode == "game"),
                                              ("LIBRARY", self.open_library, self.mode == "library" and not in_manga),
                                              ("MANGA", lambda: self.open_library("manga"), bool(in_manga)), ("THEME", self.cycle_theme, False),
                                              ("HOME", self.home, False), ("HISTORY", self.show_history, self.history_mode and self.mode == "world"),
                                              ("TROPHIES", lambda: self.__setattr__("adv_open", not self.adv_open), self.adv_open)]):
            self.button(label, bx + i * 85, 14, 80, 38, cb, act)

        if self.mode == "world":
            self.info_panel(W, H)
        elif self.game:
            self.txt(self.game.help, W / 2, 66, 14, self.theme.dim, center=True)
            self.game.hud(self, W, H)
        else:
            self.lib.hud(self, W, H)
        if self.arcade_menu:
            self.arcade_overlay(W, H)

        # status + hover hint
        hint = self.status
        if self.hover:
            if self.hover[0] == "ep":
                f = self.scene.field
                hint = f"EPISODE {self.hover[1]}  {'(watched)' if self.hover[1] in f['watched'] else ''}  - click to play"
            elif self.hover[0] == "ped":
                hint = f"{self.scene.peds[self.hover[1]]['title']}  - click to open"
            elif self.hover[0] == "root":
                hint = "click to return to the overview"
        if self.mode == "world":
            self.txt(hint, 22, H - 142, 15, self.theme.accent)
            more = {"jurassic": "   click a dinosaur: roar   click the ground: feed   v follow",
                    "forest": "   click a frog / ladybug / beetle / butterfly: poke it   click the ground: drop berries   v follow"}.get(
                self.theme.fx, "   click a ghost / skeleton / cat...: poke it   click the ground: drop candy   v follow") if self.jurassic() else ""
            help_text = "drag: orbit   right-drag: pan   wheel: zoom   / search   h history   r related   esc back   space pause   arrows seek/volume   n p next/prev   d dub   t theme   g arcade   l library   m manga   u hide UI" + more
            room = max(int((W - 44) / 6.4), 30)
            lines, cur = [], ""
            for chunk in help_text.split("   "):  # wrap between hints so the line never runs off the window
                if len(cur) + len(chunk) + 3 > room and cur:
                    lines.append(cur)
                    cur = chunk
                else:
                    cur = (cur + "   " + chunk) if cur else chunk
            lines.append(cur)
            for i, ln in enumerate(reversed(lines)):
                self.txt(ln, 22, H - 162 - i * 16, 11, self.theme.dim)
        else:
            self.txt(self.status, 22, H - (36 if self.mode == "library" else 142), 13, self.theme.dim)

        if self.jurassic():
            self.dino_hud(W, H)
        self.hover_card(W, H)
        if self.mode != "library":  # the libraries are for reading and browsing: no media player there
            self.player_bar(W, H)
        self.suggestions_dropdown(sx, sw)
        if self.lib_typing:
            self.librarian_overlay(W, H)
        if self.adv_open:
            self.advancement_panel(W, H)
        if self.reading_focus():  # achievements wait until the book is closed
            self.toasts = [(a_, b_, c_, born + self.dt_last) for a_, b_, c_, born in self.toasts]
        else:
            self.toast_hud(W, H)
            if self.theme.fx == "vcr":
                self.vcr_overlay(W, H)

    def suggestions_dropdown(self, sx, sw):
        if not (self.typing and self.mode == "world" and self.suggest):
            return
        rows = self.suggest[:8]
        y0 = 54
        self.panel(sx, y0, sw, 8 + 26 * len(rows))
        room = max(int((sw - 28) / 8.4), 10)
        hits = []
        for i, name in enumerate(rows):
            y = y0 + 5 + i * 26
            on = i == self.sugg_sel or self.hit_test(sx, y, sw, 26)
            if on:
                self.r.rect(sx + 3, y, sw - 6, 26, (*self.theme.edge[:3], 0.35))
            label = name if len(name) <= room else name[:room - 1] + "~"
            self.txt(label, sx + 14, y + 4, 14, (1, 1, 1) if on else self.theme.text)
            hits.append((sx, y, sw, 26, lambda *_, i=i: self.pick_suggestion(i)))
        self.hits[:0] = hits  # on top of everything beneath

    def toast_hud(self, W, H):
        """'Advancement made' toasts slide down from the top centre one after another."""
        self.toasts = [t_ for t_ in self.toasts if self.t - t_[3] < 6.5][-4:]
        for i, (title, desc, group, born) in enumerate(self.toasts):
            age = self.t - born
            slide = min(1.0, age / 0.35) * min(1.0, (6.5 - age) / 0.35)
            w, h = 420, 62
            x, y = W / 2 - w / 2, 8 - (1 - slide) * 90 + 110 + i * 70
            self.r.rect(x, y, w, h, (0.02, 0.03, 0.05, 0.94))
            for rx, ry, rw, rh in ((x, y, w, 2), (x, y + h - 2, w, 2), (x, y, 2, h), (x + w - 2, y, 2, h)):
                self.r.rect(rx, ry, rw, rh, self.theme.accent + (1,))
            self.r.rect(x + 12, y + 14, 34, 34, (*self.theme.accent, 0.9))
            self.txt("*", x + 29, y + 17, 26, (0.05, 0.05, 0.05), center=True)
            self.txt("ADVANCEMENT MADE!", x + 58, y + 6, 12, self.theme.accent)
            self.txt(title[:36], x + 58, y + 22, 16, (1, 1, 1))
            self.txt(desc[:52], x + 58, y + 43, 11, self.theme.dim)

    def advancement_panel(self, W, H):
        th = self.theme
        pw, ph = min(W - 80, 980), H - 230
        x, y = W / 2 - pw / 2, 70
        self.r.rect(x, y, pw, ph, (0.01, 0.015, 0.03, 0.97))  # opaque backdrop: the list is long and busy
        self.panel(x, y, pw, ph)
        done, total = self.adv.counts()
        self.txt(f"ADVANCEMENTS   {done} / {total}", x + 18, y + 12, 22, th.logo)
        self.button("CLOSE (T)", x + pw - 120, y + 10, 104, 30, lambda: setattr(self, "adv_open", False))
        self.txt("generated from what you watch and read - every anime you watch gets its own ladder", x + 18, y + 44, 12, th.dim)
        top, bottom = y + 72, y + ph - 10
        cy = top - self.adv_scroll
        content = 0
        for grp in self.adv.groups():
            head_y = cy
            if top - 24 <= head_y <= bottom - 24:
                n = sum(1 for it in grp["items"] if it["done"])
                self.txt(f"{grp['group'][:60]}   ({n}/{len(grp['items'])})", x + 18, head_y, 16, th.accent)
            cy += 30
            cols = max(1, int((pw - 36) // 232))
            for k, it in enumerate(grp["items"]):
                cx, ry = x + 18 + (k % cols) * 232, cy + (k // cols) * 58
                if top - 4 <= ry <= bottom - 54:
                    col = th.good if it["done"] else th.dim
                    self.r.rect(cx, ry, 224, 52, (*th.edge[:3], 0.22) if it["done"] else (0, 0, 0, 0.35))
                    self.r.rect(cx, ry, 4, 52, col + (1,))
                    self.txt(("* " if it["done"] else "") + it["title"][:26], cx + 12, ry + 4, 13, (1, 1, 1) if it["done"] else th.dim)
                    self.txt(it["desc"][:36], cx + 12, ry + 24, 10, th.dim)
                    if not it["done"]:
                        self.r.rect(cx + 12, ry + 42, 200, 4, (0.2, 0.2, 0.25, 1))
                        self.r.rect(cx + 12, ry + 42, 200 * it["have"] / max(it["need"], 1), 4, th.accent + (1,))
            cy += ((len(grp["items"]) + cols - 1) // cols) * 58 + 12
            content = cy - top + self.adv_scroll
        self.adv_scroll = max(0, min(self.adv_scroll, max(0, int(content - (bottom - top)))))

    def vcr_overlay(self, W, H):
        """Old-VCR look: scanlines, a rolling tracking band, tape noise flecks, a PLAY / timecode OSD and a REC lamp."""
        r, t = self.r, self.t
        for yy in range(0, int(H), 4):
            r.rect(0, yy, W, 1.5, (0, 0, 0, 0.16))
        band = (t * 90) % (H + 120) - 60  # a slow tracking band rolling up the screen
        r.rect(0, band, W, 14, (1, 1, 1, 0.045))
        r.rect(0, band + 14, W, 3, (1, 1, 1, 0.09))
        glitch = (t % 11.0) < 0.55  # a periodic tracking error
        if glitch:
            gy = (t * 37) % (H - 80)
            r.rect(0, gy, W, 26, (0.9, 0.95, 1.0, 0.16))
            r.rect(0, gy + 26, W, 4, (1.0, 0.1, 0.1, 0.18))
            for i in range(60):
                r.rect((i * 947 + int(t * 700)) % int(W), gy + (i * 13) % 30, 40 + (i * 31) % 160, 2, (1, 1, 1, 0.5))
        for i in range(24):  # snow
            nx = (i * 7919 + int(t * 60) * 131) % int(W)
            ny = (i * 104729 + int(t * 60) * 71) % int(H)
            r.rect(nx, ny, 3 + i % 4, 1.5, (1, 1, 1, 0.22))
        r.rect(0, 0, W, 10, (0, 0, 0, 0.35))
        r.rect(0, H - 10, W, 10, (0, 0, 0, 0.35))
        playing = bool(self.player.get("playing"))
        paused = bool(self.player.get("paused"))
        label = "PAUSE ||" if paused else ("PLAY >" if playing else "STOP []")
        self.txt(label, 40, 104, 24, (0.95, 0.95, 1.0))
        pos = self.player.get("pos", 0) if playing else self.t
        self.txt(f"SP  {int(pos) // 3600}:{int(pos) // 60 % 60:02d}:{int(pos) % 60:02d}", 40, 134, 15, (0.8, 0.9, 1.0))
        if int(t * 1.5) % 2 == 0:
            r.rect(22, 110, 12, 12, (1.0, 0.1, 0.1, 1.0))
        self.txt(time.strftime("%b %d %Y").upper(), 40, 156, 12, (1.0, 0.85, 0.3))

    # ---------- hover hologram: picture + synopsis for the anime / manga under the mouse ----------
    def screen_box(self, lo, hi):
        """Screen-space bounding box of a world-space box, or None when it is behind the camera."""
        W, H = self.size
        xs, ys = [], []
        for cx in (lo[0], hi[0]):
            for cy in (lo[1], hi[1]):
                for cz in (lo[2], hi[2]):
                    p = self.r.viewproj @ np.array([cx, cy, cz, 1.0])
                    if p[3] <= 0.05:
                        return None
                    xs.append((p[0] / p[3] + 1) / 2 * W)
                    ys.append((1 - p[1] / p[3]) / 2 * H)
        return min(xs), min(ys), max(xs), max(ys)

    def _card_target(self):
        """(key, kind, title, cover texture or None, screen anchor box or None) of what the hologram should describe."""
        if self.arcade_menu or self.adv_open or self.lib_typing or (self.typing and self.suggest):
            return None
        if self.mode == "world":
            if not (self.hover and self.hover[0] == "ped") or (self.dragged and self.down):  # hidden while orbiting
                return None
            p = self.scene.peds[self.hover[1]]
            anchor = self.screen_box((p["x"] - PED_W / 2, 0, p["z"] - PED_D / 2), (p["x"] + PED_W / 2, PED_H, p["z"] + PED_D / 2))
            return ("ped", p["id"], p["title"]), "anime", p["title"], p["poster"], anchor
        lib = self.lib
        if self.mode != "library" or not lib or lib.pick or lib.drag or not lib.books:
            return None
        over_ui = any(x <= self.mouse[0] <= x + w and y <= self.mouse[1] <= y + h for x, y, w, h, _ in self.hits)
        i = lib.pick_book(*lib.ray) if (lib.ray and not over_ui) else None
        anchor = None
        if i is not None:
            b = lib.books[i]
            y0 = lib.row_y[b["row"]] + 0.05
            anchor = self.screen_box((b["x"] - b["w"] / 2, y0, -library.BOOK_D / 2), (b["x"] + b["w"] / 2, y0 + b["h"], library.BOOK_D / 2))
        elif lib.near is not None:  # walking the shelves with the keyboard: describe the book the person stands at
            i = lib.near
        else:
            return None
        b = lib.books[i]
        if b.get("card_tex") is None:
            if b.get("poster_img") is not None:
                b["card_tex"] = self.r.make_texture(np.asarray(b["poster_img"]))
            elif not b.get("poster_loading"):
                self.fetch_book_poster(b)
        return ("book", lib.kind, b["id"]), lib.kind, b["title"], b.get("card_tex"), anchor

    def _blurb(self, kind, title):
        k = (kind, title)
        bl = self.blurbs.get(k)
        if bl is None or (bl["state"] == "err" and self.t - bl["t"] > 30):  # failed lookups retry after a while
            bl = self.blurbs[k] = {"state": "loading", "data": None, "t": self.t}

            def done(r, e, bl=bl):
                bl["state"], bl["data"], bl["t"] = ("err" if e else "ok" if r else "none"), r, self.t
            self.be.call("blurb", {"title": title, "kind": kind}, done)
        return bl

    def _wrap(self, s, px, width, max_lines):
        font = self.text.font(px * self.text.ratio)
        fits = lambda t: font.getlength(t) / self.text.ratio <= width  # noqa: E731
        lines, cur = [], ""
        for wd in s.split():
            if fits((cur + " " + wd).strip()):
                cur = (cur + " " + wd).strip()
                continue
            if cur:
                lines.append(cur)
            cur = wd
            while not fits(cur):  # one very long word: hard-break it
                cut = len(cur) - 1
                while cut > 1 and not fits(cur[:cut]):
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and not fits(last + "..."):
                last = last[:-1]
            lines[-1] = last.rstrip(" ,.;:-") + "..."
        return lines

    def hover_card(self, W, H):
        tgt = self._card_target()
        if tgt is None:
            self.card = None
            return
        key, kind, title, tex, anchor = tgt
        if not self.card or self.card["key"] != key:
            self.card = {"key": key, "since": self.t}
        age = self.t - self.card["since"]
        if age < 0.3:  # a short dwell, so sweeping the mouse across the shelves doesn't flash a card on every cover
            return
        bl = self._blurb(kind, title)
        a = min(1.0, (age - 0.3) / 0.18) * (0.97 + 0.03 * math.sin(self.t * 31))  # fade in, then a faint hologram flicker
        th, r = self.theme, self.r
        ink = lambda c, k=1.0: (*c[:3], (c[3] if len(c) > 3 else 1.0) * a * k)  # noqa: E731

        def text(s, x, y, px, col):
            t_, w, h = self.text.get(s, px, tuple(int(c * 255) for c in col[:3]))
            r.quad2d(t_, x, y, w, h, (1, 1, 1, a))
            return w, h

        # ---- layout (logical pixels) ----
        cw = 440 if W >= 900 else 360
        pad, thumb_w = 14, (112 if cw >= 440 else 92)
        thumb_h = thumb_w * 1.5
        tx = pad + thumb_w + 14
        col_w = cw - tx - pad
        d = bl["data"] or {}
        t_lines = self._wrap(title, 17, col_w, 2)
        meta = [m for m in (d.get("format"), str(d.get("year") or ""),
                            (f"{d['count']} {'eps' if kind == 'anime' else 'ch'}" if d.get("count") else ""), d.get("status")) if m]
        if bl["state"] == "ok":
            desc = self._wrap(d.get("desc") or "No synopsis yet.", 13, col_w, 7 if cw >= 440 else 6)
        elif bl["state"] == "loading":
            desc = ["receiving transmission" + "." * (1 + int(self.t * 3) % 3)]
        elif bl["state"] == "none":
            desc = ["No description found for this one."]
        else:
            desc = ["Couldn't reach AniList or MyAnimeList right now."]
        body_h = len(t_lines) * 21 + 6 + (18 if meta or d.get("score") else 0) + 8 + len(desc) * 18
        genres = d.get("genres") or []
        ch = pad + max(thumb_h, body_h) + (34 if genres else 6) + 16

        # ---- placement: beside the hovered cover (like a store flyout), never on top of it ----
        top, bottom = 66, H - 126  # under the top bar, above the player bar
        if anchor:
            ax0, ay0, ax1, ay1 = anchor
            x = ax1 + 18 if ax1 + 18 + cw <= W - 10 else ax0 - 18 - cw
            if x < 10:
                x = min(max(self.mouse[0] + 26, 10), W - cw - 10)
            y = min(max(ay0, top), max(bottom - ch, top))
        else:  # keyboard: top left, under the logo (clear of the manga shelf's REMOVED drawer tab)
            x, y = 34, (128 if self.mode == "library" else 112)
            ax0 = ay0 = ax1 = ay1 = None

        # ---- hologram ----
        e = th.edge
        if anchor and (ax1 + 2 <= x or x + cw <= ax0 - 2):  # a faint projection beam from the cover to the card
            bx0, bx1 = (ax1, x) if x > ax1 else (x + cw, ax0)
            by = min(max((ay0 + ay1) / 2, y + 12), y + ch - 12)
            r.rect(bx0, by - 0.75, bx1 - bx0, 1.5, ink(e, 0.55))
            r.rect(bx0 - 3, by - 3, 6, 6, ink(th.accent, 0.9))
        r.rect(x, y, cw, ch, ink((th.panel[0] * 0.6, th.panel[1] * 0.6, th.panel[2] * 0.6, 0.965)))
        r.rect(x, y, cw, 46, ink(e, 0.07))  # brighter "projector" band along the top
        for ry in range(int(y) + 2, int(y + ch), 3):  # scanlines
            r.rect(x, ry, cw, 1, ink(e, 0.045))
        sweep = (self.t * 70) % (ch + 40) - 20
        if 0 <= sweep <= ch - 8:
            r.rect(x, y + sweep, cw, 8, ink(e, 0.05))
        for rx, ry, rw, rh in ((x, y, cw, 1), (x, y + ch - 1, cw, 1), (x, y, 1, ch), (x + cw - 1, y, 1, ch)):
            r.rect(rx, ry, rw, rh, ink(e, 0.45))
        L = 16
        for cx, cy, sx, sy in ((x, y, 1, 1), (x + cw, y, -1, 1), (x, y + ch, 1, -1), (x + cw, y + ch, -1, -1)):  # corner brackets
            r.rect(cx if sx > 0 else cx - L, cy - (0 if sy > 0 else 2), L, 2, ink(th.accent))
            r.rect(cx - (0 if sx > 0 else 2), cy if sy > 0 else cy - L, 2, L, ink(th.accent))

        # cover
        px0, py0 = x + pad, y + pad
        if tex is not None:
            r.quad2d(tex, px0, py0, thumb_w, thumb_h, (0.92, 1.0, 1.0, a))
            for ry in range(int(py0), int(py0 + thumb_h), 3):
                r.rect(px0, ry, thumb_w, 1, ink(e, 0.06))
        else:
            r.rect(px0, py0, thumb_w, thumb_h, ink(e, 0.12))
            text("NO SIGNAL" if bl["state"] != "loading" else "...", px0 + 8, py0 + thumb_h / 2 - 8, 11, th.dim)
        for rx, ry, rw, rh in ((px0, py0, thumb_w, 1), (px0, py0 + thumb_h - 1, thumb_w, 1), (px0, py0, 1, thumb_h), (px0 + thumb_w - 1, py0, 1, thumb_h)):
            r.rect(rx, ry, rw, rh, ink(e, 0.6))

        # text column
        cx_, cy_ = x + tx, y + pad - 2
        for ln in t_lines:
            text(ln, cx_, cy_, 17, (1, 1, 1))
            cy_ += 21
        cy_ += 4
        if meta or d.get("score"):
            mw = 0
            if d.get("score"):
                sw, _ = text(f"{d['score']}%", cx_, cy_, 12, th.good)
                mw = sw + 10
            mfont = self.text.font(12 * self.text.ratio)
            while len(meta) > 1 and mfont.getlength("  -  ".join(meta)) / self.text.ratio > col_w - mw:
                meta.pop()  # drop status, then the count, until it fits
            text("  -  ".join(meta), cx_ + mw, cy_, 12, th.dim)
            cy_ += 18
        r.rect(cx_, cy_ + 2, col_w, 1, ink(e, 0.35))
        cy_ += 8
        for ln in desc:
            text(ln, cx_, cy_, 13, th.text if bl["state"] == "ok" else th.dim)
            cy_ += 18

        # genre chips along the bottom, like store tags
        gx, gy = x + pad, y + ch - 16 - 24
        for g in genres:
            gw = self.text.font(11 * self.text.ratio).getlength(g) / self.text.ratio + 16
            if gx + gw > x + cw - pad:
                break
            r.rect(gx, gy, gw, 20, ink(e, 0.2))
            r.rect(gx, gy + 19, gw, 1, ink(e, 0.6))
            text(g, gx + 6, gy + 1, 11, th.text)
            gx += gw + 6
        if d.get("src"):
            sw = self.text.font(10 * self.text.ratio).getlength("via " + d["src"]) / self.text.ratio
            text("via " + d["src"], x + cw - pad - sw - 6, y + ch - 17, 10, th.dim)

    def dino_hud(self, W, H):
        herd = self.herd()
        th = self.theme
        if self.dino_hover is not None:  # name tag by the cursor
            d = herd.dinos[self.dino_hover]
            tag = f"{d.name}  -  click to poke it"
            mx, my = self.mouse
            w = len(tag) * 7.6 + 20
            x = min(mx + 16, W - w - 8)
            self.panel(x, max(my - 34, 70), w, 26)
            self.txt(tag, x + 10, max(my - 31, 73), 12, th.accent)
        if self.dino_card and self.t - self.dino_card[1] < 10:  # info card for the last dinosaur you poked
            d = herd.dinos[self.dino_card[0]]
            x, y, w, h = 22, 112, 340, 156
            self.panel(x, y, w, h)
            self.txt(d.name.upper(), x + 14, y + 10, 17, th.accent)
            era = f"haunting since {d.era}" if self.theme.fx == "halloween" else (f"lives on {d.era}" if self.theme.fx == "forest" else d.era)
            self.txt(f"{d.diet}   |   {d.length}   |   {era}", x + 14, y + 38, 12, th.dim)
            words, lines, cur = d.fact.split(), [], ""
            for wd in words:
                if len(cur) + len(wd) > 42 and cur:
                    lines.append(cur)
                    cur = wd
                else:
                    cur = (cur + " " + wd).strip()
            lines.append(cur)
            for i, ln in enumerate(lines[:3]):
                self.txt(ln, x + 14, y + 64 + i * 20, 13, th.text)
            self.button("STOP FOLLOW (V)" if self.follow is not None else "FOLLOW (V)", x + 14, y + h - 40, 150, 28, self.toggle_follow, self.follow is not None)
            self.button("CLOSE", x + 176, y + h - 40, 80, 28, lambda: setattr(self, "dino_card", None))

    def roam_world(self):
        """Obstacles and the roaming band for wandering theme creatures (dinosaurs)."""
        if self.mode != "world":
            return {"circles": [(0, 0, 34)], "rects": [], "bounds": (40, 95)}
        circles = [(0, 0, 8)] + [(p["x"], p["z"], 5.6) for p in self.scene.peds]
        if self.theme.fx == "jurassic":
            circles.append((self.cam_ground[0], self.cam_ground[1], 16))  # nobody stands right under the camera
        rects = []
        f = self.scene.field
        if f:
            rects.append((f["cx"], f["cz"], f["w"] / 2 + 3, f["d"] / 2 + 3))
        far = max([math.hypot(p["x"], p["z"]) for p in self.scene.peds] + [8])
        plats = [(s_["cx"], s_["zf"] - s_["d"] / 2, s_["w"] / 2 + 1.0, s_["d"] / 2 + 1.0) for s_ in getattr(self.scene, "sections", [])]
        plats += [(0.0, 0.0, 6.0, 6.0)] + rects  # the root pedestal and an open episode field
        return {"circles": circles, "rects": rects, "bounds": (far + 8, far + 42), "platforms": plats}

    def mode_label(self):
        return self.audio.upper()

    def arcade_overlay(self, W, H):
        entries = [("snake", "1  SNAKE"), ("breakout", "2  BREAKOUT"), ("quiz", "3  POSTER QUIZ  (guess the anime)"),
                   ("kong", "4  BARREL CLIMB  (hammers, 5 stages)"), ("trivia", "5  ANIME TRIVIA"),
                   ("maze", "6  DATA MAZE  (find the anime item)"), ("galaga", "7  DINO GALAGA  (anime bosses)")]
        pw, ph = 460, 62 + len(entries) * 54 + 52
        x, y = W / 2 - pw / 2, H / 2 - ph / 2 - 40
        self.panel(x, y, pw, ph)
        self.txt("ARCADE", x + pw / 2, y + 14, 24, self.theme.logo, center=True)
        back = "library" if self.mode == "library" else None
        for i, (key, label) in enumerate(entries):
            self.button(label, x + 24, y + 62 + i * 54, pw - 48, 42, lambda k=key: self.start_game(k, back=back))
        self.txt("Esc closes", x + pw / 2, y + ph - 28, 12, self.theme.dim, center=True)

    def info_panel(self, W, H):
        f = self.scene.field
        if not f:
            return
        p = self.scene.peds[f["idx"]]
        lines = [(p["title"][:34], 16, (1, 1, 1), None), (f"{len(f['eps'])} episodes - {len(f['watched'])} watched", 12, self.theme.dim, None), ("", 8, self.theme.dim, None),
                 ("MANGA // allmanga.to", 12, self.theme.accent, None)]
        for m in self.info["manga"][:4]:
            lines.append((f"> {m['title'][:30]} ({m['chapters']} ch)", 13, self.theme.text, m["url"]))
        if not self.info["manga"]:
            lines.append(("  none found on allmanga", 12, self.theme.dim, None))
            lines.append(("> try MangaFire instead", 13, self.theme.good, core.mangafire_url(p["title"])))
        lines.append(("", 8, self.theme.dim, None))
        lines.append(("FAN EDITS // AMVs  (E)", 12, self.theme.accent, None))
        if self.edits is None:
            lines.append(("[ E ]  FIND FAN EDITS ON YOUTUBE", 12, self.theme.good, "edits"))
        elif self.edits == "loading":
            lines.append(("searching YouTube...", 12, self.theme.dim, None))
        else:
            for ed in self.edits[:6]:
                lines.append((f"> {ed['title'][:30]}  {ed['length']}", 12, self.theme.text, ed["url"]))
            if not self.edits:
                lines.append(("  none found", 12, self.theme.dim, None))
        lines.append(("", 8, self.theme.dim, None))
        rel = self.info["related"]
        if rel is None:
            lines.append(("[ R ]  LIGHT NOVELS / GAMES / FAN SITES", 12, self.theme.good, "load"))
        elif rel == "loading":
            lines.append(("searching related content...", 12, self.theme.dim, None))
        else:
            for key, head in (("novels", "LIGHT NOVELS"), ("games", "GAMES"), ("sites", "FAN SITES & WIKIS")):
                lines.append((head, 12, self.theme.accent, None))
                for it in rel[key][:4]:
                    lines.append((f"> {it['title'][:32]}", 12, self.theme.text, it["url"]))
                if not rel[key]:
                    lines.append(("  none found", 12, self.theme.dim, None))
        pw = 352
        ph = 20 + sum(int(l[1] * 1.3) + 9 for l in lines)
        x, y = W - pw - 14, 66
        self.panel(x, y, pw, ph)
        cy = y + 10
        for s, px, col, link in lines:
            if s:
                cb = None
                if link == "load":
                    cb = lambda *_: self.load_related()
                elif link == "edits":
                    cb = lambda *_: self.load_edits()
                elif link:
                    cb = lambda *_, u=link: webbrowser.open(u)
                self.txt(s, x + 14, cy, px, col, cb)
            cy += int(px * 1.3) + 9
        starred = p["id"] in self.starred
        self.button("UNSTAR  (F)" if starred else "* STAR: PLAN TO WATCH  (F)", x, y + ph + 8, pw, 34, lambda: self.toggle_star(p["id"], p["title"], p.get("poster_url", "")), starred)

    def player_bar(self, W, H):
        x, y, w, h = 14, H - 118, W - 28, 104
        self.panel(x, y, w, h)
        pl = self.player
        playing = pl.get("playing")
        title = f"{pl['anime']['title']} - EPISODE {pl['episode']}  [{pl.get('mode', '').upper()}]" if playing and pl.get("anime") else "NOTHING PLAYING"
        self.txt(title, x + 14, y + 8, 16, (1, 1, 1) if playing else self.theme.dim)
        # seek bar
        bx, by, bw = x + 14, y + 36, w - 150
        self.r.rect(bx, by, bw, 10, tuple(c * 0.25 for c in self.theme.edge[:3]) + (1,))
        frac = pl.get("pos", 0) / pl["duration"] if playing and pl.get("duration") else 0
        self.r.rect(bx, by, bw * min(frac, 1), 10, self.theme.text + (1,))
        self.hits.append((bx, by - 6, bw, 22, lambda mx, my: playing and self.control("seekpct", round(max(0, min(100, (mx - bx) / bw * 100)), 1))))
        fmt = lambda s: f"{int(s) // 60:02d}:{int(s) % 60:02d}"
        self.txt(f"{fmt(pl.get('pos', 0))} / {fmt(pl.get('duration', 0))}", bx + bw + 14, by - 4, 14, self.theme.text)
        # buttons (widths shrink on narrow windows so the whole row always fits)
        row = y + 60
        pos, dur = pl.get("pos", 0), pl.get("duration", 0)
        sk = pl.get("skip") or {}
        in_intro = playing and ((sk.get("intro") and sk["intro"][0] - 1 <= pos < sk["intro"][1]) or (not sk.get("intro") and pos < 240))
        in_outro = playing and ((sk.get("outro") and sk["outro"][0] - 1 <= pos < sk["outro"][1]) or (not sk.get("outro") and dur and pos > dur - 200))
        specs = [("<< PREV", lambda: self.control("prev"), 74, False), ("-10s", lambda: self.control("seek", -10), 58, False),
                 ("PAUSE" if not pl.get("paused") else "PLAY", lambda: self.control("pause"), 74, pl.get("paused", False)),
                 ("+10s", lambda: self.control("seek", 10), 58, False), ("NEXT >>", lambda: self.control("next"), 74, False),
                 ("SKIP INTRO", lambda: self.toggle_skip("intro"), 104, self.auto_intro), ("SKIP CREDITS", lambda: self.toggle_skip("outro"), 124, self.auto_outro),
                 (self.audio.upper(), self.toggle_mode, 56, self.audio == "dub"), ("STOP", lambda: self.control("stop"), 58, False),
                 ("FULLSCREEN", lambda: self.control("fullscreen"), 96, False), ("AUTO FS", self.toggle_autofs, 74, self.auto_fs),
                 ("SUBS", lambda: self.control("subs"), 58, False), ("MUTE", lambda: self.control("mute"), 58, False),
                 (f"{pl.get('speed', 1):g}x", lambda: self.control("speed", {0.75: 1.0, 1.0: 1.25, 1.25: 1.5, 1.5: 2.0}.get(pl.get("speed", 1.0), 0.75)), 52, False),
                 ("AUTO-NEXT", lambda: self.control("autonext", not pl.get("autonext", True)), 100, pl.get("autonext", True))]
        vol_w = 150
        avail = w - 28 - vol_w - 8 * len(specs)
        k = min(1.0, avail / sum(sp[2] for sp in specs))
        bx_ = x + 14
        for label, cb, wd, act in specs:
            wd = max(44, wd * k)
            self.button(label, bx_, row, wd, 32, cb, active=act)
            bx_ += wd + 8
        # volume
        vx, vw = x + w - vol_w - 6, 100
        self.txt("VOL", vx, row + 8, 13, self.theme.dim)
        self.r.rect(vx + 36, row + 12, vw, 8, tuple(c * 0.25 for c in self.theme.edge[:3]) + (1,))
        vol = pl.get("volume", 100) / 130
        self.r.rect(vx + 36, row + 12, vw * min(vol, 1), 8, self.theme.good + (1,))
        self.hits.append((vx + 36, row + 2, vw, 28, lambda mx, my: self.control("volume", round(max(0, min(130, (mx - vx - 36) / vw * 130))))))


def run_window():
    from rendercanvas.glfw import RenderCanvas, loop

    from .renderer import Renderer

    box = {}
    gpu = threading.Thread(target=lambda: box.__setitem__("r", Renderer()), name="gpu-init")  # Vulkan instance + pipelines...
    gpu.start()
    canvas = RenderCanvas(size=(1500, 900), title="ani-3d", update_mode="continuous", max_fps=60)  # ...while the window opens
    gpu.join()
    r = box["r"]
    print(f"ani-3d: {r.adapter.info.get('backend_type')} adapter = {r.adapter.info['device']}  (ready in {_time.perf_counter() - T0:.2f}s)", flush=True)
    ctx = canvas.get_wgpu_context()
    ctx.configure(device=r.device, format="bgra8unorm")
    app = App(r, canvas.get_pixel_ratio())
    last = [time.perf_counter()]

    selftest = float(os.environ.get("ANI3D_SELFTEST", "0"))  # seconds; types a search through the event system, then quits
    started, frames = time.perf_counter(), [0]

    def draw():
        now = time.perf_counter()
        dt, last[0] = min(now - last[0], 0.1), now
        tex = ctx.get_current_texture()
        app.frame(tex.create_view(), canvas.get_physical_size(), canvas.get_pixel_ratio(), dt)
        frames[0] += 1
        if frames[0] == 1:
            print(f"ani-3d: first frame after {_time.perf_counter() - T0:.2f}s", flush=True)
        if selftest:
            el = now - started
            if frames[0] == 30:
                for c in "frieren":
                    canvas.submit_event({"event_type": "char", "data": c, "modifiers": ()})
                canvas.submit_event({"event_type": "key_down", "key": "Enter", "modifiers": ()})
            if frames[0] == 400:
                app.start_game("snake")
                canvas.submit_event({"event_type": "key_down", "key": "ArrowDown", "modifiers": ()})
                canvas.submit_event({"event_type": "key_up", "key": "ArrowDown", "modifiers": ()})
                print(f"selftest: mode={app.mode} game={app.game.name}", flush=True)
            def ev(k):  # a full key press: down then up (a missing release would leave the key "held")
                canvas.submit_event({"event_type": "key_down", "key": k, "modifiers": ()})
                canvas.submit_event({"event_type": "key_up", "key": k, "modifiers": ()})
            if frames[0] == 520:
                app.exit_mode()
                app.open_library()
            if frames[0] == 760:
                print(f"selftest: mode={app.mode} sections={ {k: v[1] for k, v in app.lib.section_info.items()} }", flush=True)
                ev("Enter")  # pick the book next to the person
            if frames[0] == 1000:
                print(f"selftest: book open={bool(app.lib.pick)} spread={app.lib.bv.spread}", flush=True)
                ev("ArrowRight")
            if frames[0] == 1120:
                print(f"selftest: spread after flip={app.lib.bv.spread}", flush=True)
                ev("Escape")  # close the book
            if frames[0] == 1250:
                print(f"selftest: book closed={app.lib.pick is None}", flush=True)
                ev("k")  # barrel climb from the shelves
            if frames[0] == 1330:
                print(f"selftest: mode={app.mode} game={app.game.name if app.game else None}", flush=True)
                ev("Escape")
            if frames[0] == 1400:
                print(f"selftest: back in {app.mode}", flush=True)
                ev("m")  # switch to the manga shelf
            if frames[0] == 1900:
                print(f"selftest: mode={app.mode} kind={app.lib.kind} sections={ {k: v[1] for k, v in app.lib.section_info.items()} }", flush=True)
                for k, bk in enumerate(app.lib.books):
                    if bk["total"] > 20:
                        app.lib.px, app.lib.level = bk["x"], bk["row"]
                        break
            if frames[0] == 1960:
                ev("Enter")
            if frames[0] == 2200:
                bk = app.lib.books[app.lib.pick["i"]]
                print(f"selftest: opened manga '{bk['title']}' chapters={len(bk['all_eps'])}", flush=True)
                app.read_chapter(bk, bk["all_eps"][0])
            if frames[0] == 2500:
                print(f"selftest: reading mode={app.lib.bv.mode} pages={len(app.lib.bv.pages_urls)} images={len(app.lib.bv.imgs)} rtl={app.lib.bv.rtl}", flush=True)
                ev("ArrowLeft" if app.lib.bv.rtl else "ArrowRight")  # next page (manga read right to left by default)
            if frames[0] == 2550:
                z0 = app.lib.zoom
                canvas.submit_event({"event_type": "wheel", "dx": 0.0, "dy": -300.0, "x": 800.0, "y": 400.0, "buttons": (), "modifiers": ()})
                print(f"selftest: wheel zoom before={z0:.2f}", flush=True)
            if frames[0] == 2600:
                print(f"selftest: wheel zoom after={app.lib.zoom:.2f}", flush=True)
                ev("u")
            if frames[0] == 2630:
                print(f"selftest: hide_ui={app.hide_ui} hits={len(app.hits)}", flush=True)
                ev("u")
            if frames[0] == 2650:
                print(f"selftest: manga spread={app.lib.bv.spread} hide_ui={app.hide_ui}", flush=True)
                ev("Escape")
            if frames[0] == 2780:
                print(f"selftest: manga book closed={app.lib.pick is None}", flush=True)
                ev("Escape")
            if el > selftest:
                print(f"selftest: {frames[0]} frames, {frames[0] / el:.0f} fps, query={app.query!r}, peds={len(app.scene.peds)}, mode={app.mode}, theme={app.theme.key}", flush=True)
                canvas.close()

    canvas.request_draw(draw)
    canvas.add_event_handler(app.on_input, "pointer_down", "pointer_up", "pointer_move", "wheel", "key_down", "key_up", "char")
    loop.run()


def run_snapshot(path, query, select, size, extra=None, settle=3.0):
    """Headless: search, open an anime, wait for posters and render one frame to a PNG (used for testing)."""
    import wgpu

    from .renderer import Renderer

    r = Renderer()
    W, H = size
    app = App(r, 1.0)
    target = r.device.create_texture(size=(W, H, 1), format="bgra8unorm", usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
    app.query, app.typing = query, False
    app.search()
    start, stage, opened = time.perf_counter(), 0, None
    last = start
    while True:
        now = time.perf_counter()
        app.frame(target.create_view(), (W, H), 1.0, now - last)
        last = now
        peds = app.scene.peds
        elapsed = now - start
        if stage == 0 and peds and all(p["poster"] for p in peds[:8]) or (stage == 0 and elapsed > 25 and peds):
            stage, opened = 1, now
            if select is not None:
                app.open_ped(select)
        elif stage == 1 and (select is None or app.scene.field) and now - opened > 3.5:
            if extra:
                extra(app)
                stage, opened = 2, now
            else:
                break
        elif stage == 2 and now - opened > settle:
            break
        if elapsed > 60:
            break
        time.sleep(0.03)
    img = r.read_pixels(target, W, H)[:, :, [2, 1, 0, 3]]
    Image.fromarray(img).save(path)
    print("saved", path)
