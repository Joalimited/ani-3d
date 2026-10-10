"""The library: a bookshelf in three sections (Watching / Planning to watch / Watched) built from your watch history and
star list, plus a tiny person who walks, climbs and pulls books out. A picked book opens like a real one (see book.py)."""
import math

import numpy as np

from . import core, mathx
from .book import S, TOTAL, BookView, book_thickness, lerp, tilt_for
from .games import book_boxes, step_book, tip_book, voxel_person
from .scene import box, ease

BOOK_H, BOOK_D = 3.5, 2.0
VOL_W, VOL_H, FACE_W = 0.62, 3.2, 2.2  # a tankobon volume: thin spine, all the same height; face-out ones show their cover
CREAM, BRASS = (0.94, 0.92, 0.86), (0.85, 0.66, 0.28)
SHELF_W = 21.0  # manga volumes are thin: a narrower case keeps the shelves full
PERSON_Z = 2.9
ROW_GAP = 4.7
SECTIONS = [("watching", "WATCHING"), ("planning", "PLANNING TO WATCH"), ("watched", "WATCHED")]  # bottom -> top
MANGA_SECTIONS = [("search", "LIBRARIAN'S PICKS"), ("reading", "READING"), ("plan", "GOING TO READ"), ("anime", "MANGA OF YOUR ANIME"), ("popular", "POPULAR ON MANGADEX"), ("done", "FINISHED")]
LIBRARIAN_X = -SHELF_W / 2 - 4.2  # where the librarian's desk stands (manga shelf, ground row)
GOLD = (1.0, 0.82, 0.2)


def _h(s):
    v = 0
    for ch in s:
        v = (v * 131 + ord(ch)) % 1000003
    return v


class Library:
    def __init__(self, app, rows, wl, kind="anime", groups=None):
        self.app = app
        self.raw_rows, self.raw_wl = rows, wl
        self.kind, self.groups_in = kind, groups
        self.sections = MANGA_SECTIONS if kind == "manga" else SECTIONS
        self.search_label = None  # heading of the librarian's section ("LIBRARIAN: <query>")
        self.mangafire = None  # the last query the librarian could not find on MangaDex (the MangaFire button uses it)
        self.last_removed, self.hidden_count, self.hidden_items = None, 0, []
        self.drawer, self.drawer_t, self.drawer_scroll, self.pulse = False, 0.0, 0, -9.0  # the "removed" side drawer
        self.drag = self.drag_candidate = None  # {"i": book, "x", "y", "row"} while a book is being carried
        self.name = "MANGA LIBRARY" if kind == "manga" else "LIBRARY"
        self.facing, self.moving = 1, False
        self.auto, self.pick, self.bv = None, None, None  # pick = {"i": book index, "u": animation seconds, "closing": bool}
        self.ray = None
        self.near = None
        self.falling = []  # books you removed, tipping off the shelf and dropping to the floor
        self._dirty = False
        self.zoom, self.pan, self.focus = 1.0, [0.0, 0.0], "spread"  # reader view: zoom, pan offset (world units), page focus
        self.px, self.level, self.py = 0.0, 0, 0.3
        self.layout()
        if self.books:
            first = next((b for b in self.books if b["section"] in ("watching", "reading", "search")), self.books[0])
            self.px, self.level, self.py = first["x"], first["row"], self.row_y[first["row"]]

    # ---------- layout ----------
    def layout(self, focus=None):
        th = self.app.theme
        starred = {w["id"] for w in self.raw_wl}
        history_ids = {r["id"] for r in self.raw_rows}
        groups = {"watching": [], "watched": [], "planning": []}
        if self.kind == "manga":
            self.groups_in.setdefault("plan", [])
            groups = {k: list(v) for k, v in self.groups_in.items()}  # same book dicts, so progress/chapter data survive a relayout
            starred = {m["id"] for m in core.mp_list()}  # manga: the star means "going to read"
        for rw in ([] if self.kind == "manga" else sorted(self.raw_rows, key=lambda r: r.get("last") or "", reverse=True)):
            watched, total = len(set(rw["episodes"])), rw.get("total") or 0
            groups["watched" if total and watched >= total else "watching"].append(
                {"id": rw["id"], "title": rw["title"], "episodes": rw["episodes"], "all_eps": rw.get("all_eps") or [], "total": total, "last": rw.get("last"), "poster_url": ""})
        for w in ([] if self.kind == "manga" else self.raw_wl):
            if w["id"] not in history_ids:
                groups["planning"].append({"id": w["id"], "title": w["title"], "episodes": [], "all_eps": w.get("all_eps") or [], "total": w.get("total") or 0, "last": None, "poster_url": w.get("poster", "")})
        hidden = core.hidden_ids(self.kind)  # books the user removed from the shelf
        self.hidden_items = core.hidden_list(self.kind)
        self.hidden_count = len(self.hidden_items)
        for lst in groups.values():
            lst[:] = [bk for bk in lst if bk["id"] not in hidden]
        # books you dragged to another shelf stay there (stored in the watch database)
        ov = core.shelf_overrides(self.kind)
        valid = {k for k, _ in self.sections}
        moved = []
        for lst in groups.values():
            for bk in list(lst):
                if bk["id"] in ov and ov[bk["id"]][0] in valid:
                    lst.remove(bk)
                    moved.append(bk)
        for bk in sorted(moved, key=lambda b: ov[b["id"]][1]):
            sec, slot = ov[bk["id"]]
            groups.setdefault(sec, []).insert(min(slot, len(groups[sec])), bk)
        self.books, self.rows, self.section_info = [], [], {}
        for key, label in self.sections:
            if key == "search" and not groups.get("search"):
                continue  # the librarian's shelf only exists after a search
            if key == "search" and self.search_label:
                label = self.search_label
            row = len(self.rows)
            self.rows.append({"section": key, "label": label})
            x = -SHELF_W / 2 + 0.4
            for k_, bk in enumerate(groups.get(key, [])):
                watched = len(set(bk["episodes"]))
                face = k_ == 0  # the first volume of every section stands face-out, cover showing, like a shop shelf
                w = FACE_W if face else VOL_W
                if x + w > SHELF_W / 2 - 0.2:
                    row = len(self.rows)
                    self.rows.append({"section": key, "label": ""})
                    x = -SHELF_W / 2 + 0.4
                if self.kind == "manga":  # shelf titles: English by default, Japanese (romaji) when toggled
                    bk["title"] = (bk.get("title_jp") or bk.get("title_en") or bk["title"]) if self.app.manga_jp else (bk.get("title_en") or bk["title"])
                hh = _h(bk["title"])
                shade = 0.75 + (hh % 5) * 0.08
                base = th.books[hh % len(th.books)]
                length = max(len(bk["all_eps"]), bk.get("total") or 0)  # manga: the chapter count is known before the list loads
                thick = 1.0 + 0.9 * min(max(watched, length // 12) / 30, 1.0)  # how fat the book is when opened
                bk.update({"watched": watched, "thick": thick, "x": x + w / 2, "row": row, "w": w, "h": VOL_H + (hh % 3) * 0.06, "section": key, "face": face,
                           "starred": bk["id"] in starred, "color": tuple(min(1.0, c * shade) for c in base),
                           "white_spine": hh % 5 < 3})  # most manga have white spines with a coloured band; some are all colour
                self.books.append(bk)
                x += w + (0.22 if face else 0.03)
            self.section_info[key] = (label, len(groups.get(key, [])))
        self.row_y = [0.3 + ROW_GAP * i for i in range(len(self.rows))]
        # "next up": the most recently watched book in Watching that isn't finished
        self.next_up = next((i for i, b in enumerate(self.books) if b["section"] in ("watching", "reading") and (not b["total"] or b["watched"] < b["total"])), None)
        if focus:
            tgt = next((b for b in self.books if b["id"] == focus), None)
            if tgt:
                self.px, self.level = tgt["x"], tgt["row"]
        self.level = min(self.level, len(self.rows) - 1)
        self.py = self.row_y[self.level]

    def extend(self, group, books):
        """Add books to a shelf section after it was built (the manga shelf fills 'popular' in the background).
        Held back while a book is open so the open book's index can't shift."""
        self.groups_in.setdefault(group, []).extend(books)
        self._dirty = True
        if not self.pick:
            self._apply_extend()

    def _apply_extend(self):
        self._dirty = False
        focus = self.books[self.near]["id"] if self.near is not None else None
        self.layout(focus)
        self.lib_fresh = True

    def set_search(self, query, books):
        """The librarian's results become their own shelf (the bottom one) and the person walks over to it."""
        self.groups_in["search"] = books
        core.shelf_unpurge(self.kind, [b["id"] for b in books])  # asking the librarian for it brings a cleared book back
        self.search_label = f"LIBRARIAN: {query[:22].upper()}"
        self.mangafire = None
        self.layout()
        first = next((b for b in self.books if b["section"] == "search"), None)
        if first:
            self.auto = (first["x"], first["row"])

    def remove_book(self, i):
        """Take a book off the shelf (it is only hidden: UNDO / RESTORE bring it back; reading progress is kept)."""
        b = self.books[i]
        core.shelf_hide(self.kind, b["id"], True, b.get("title_en") or b["title"])
        self.last_removed = b
        self.pulse = self.app.t
        if self.pick and self.pick["i"] == i:
            self.pick["closing"] = True
            self.bv.spread = self.bv.target = 0
            self.bv.flip = None
        self.app.status = f"Removed '{b['title'][:40]}'  -  Z undoes it, or pick it from the REMOVED drawer on the left"
        if not self.pick:
            self.falling.append(tip_book({"x": b["x"], "y0": self.row_y[b["row"]] + 0.05, "z": 0.0, "w": b["w"], "h": b["h"], "d": BOOK_D,
                                          "color": b["color"]}, 0.8, 0.0, 0.6))
            self.relayout()

    def undo_remove(self):
        b = getattr(self, "last_removed", None)
        if not b or self.pick:
            return
        core.shelf_hide(self.kind, b["id"], False)
        self.last_removed = None
        self.app.status = f"Put '{b['title'][:40]}' back on the shelf"
        self.layout(b["id"])

    def restore_one(self, item_id, title):
        core.shelf_hide(self.kind, item_id, False)
        if self.last_removed and self.last_removed["id"] == item_id:
            self.last_removed = None
        self.app.status = f"Put '{title[:40]}' back on the shelf"
        if not self.pick:
            self.layout(item_id)

    def clear_removed(self):
        """CLEAR LIST in the drawer: the first click arms it, a second click within 4 s forgets the removed books for good."""
        if self.app.t - getattr(self, "_clear_armed", -9) > 4:
            self._clear_armed = self.app.t
            self.app.status = "Click CLEAR LIST again to forget these books for good (their reading progress is deleted too)"
            return
        self._clear_armed = -9
        n = core.shelf_purge_removed(self.kind)
        self.last_removed = None
        self.hidden_items, self.hidden_count = [], 0
        self.app.status = f"Cleared {n} removed book{'s' if n != 1 else ''} - they won't come back to the shelf"

    def restore_all(self):
        core.shelf_unhide_all(self.kind)
        self.last_removed = None
        self.app.status = "Restored every removed book"
        self.layout()

    def apply_titles(self):
        """EN/JP toggle: relabel every book (spines, covers, info pages) without rebuilding the shelf."""
        for bk in self.books:
            bk["title"] = (bk.get("title_jp") or bk.get("title_en") or bk["title"]) if self.app.manga_jp else (bk.get("title_en") or bk["title"])
        if self.bv:
            self.bv.art.clear()
            self.bv.pending.clear()
            self.bv.cover_tex, self.bv._cover_fut = None, None

    # ---------- drag and drop between shelves ----------
    def pick_book(self, origin, direction):
        """Index of the book under the ray (shelved books only), or None."""
        best, bi = 1e9, None
        for i, b in enumerate(self.books):
            y0 = self.row_y[b["row"]] + 0.05
            lo = (b["x"] - b["w"] / 2, y0, -BOOK_D / 2)
            hi = (b["x"] + b["w"] / 2, y0 + b["h"], BOOK_D / 2)
            tmin, tmax = 0.0, 1e9
            ok = True
            for a in range(3):
                d = direction[a]
                if abs(d) < 1e-9:
                    if not (lo[a] <= origin[a] <= hi[a]):
                        ok = False
                        break
                    continue
                t1, t2 = (lo[a] - origin[a]) / d, (hi[a] - origin[a]) / d
                tmin, tmax = max(tmin, min(t1, t2)), min(tmax, max(t1, t2))
            if ok and tmax >= tmin and tmin < best:
                best, bi = tmin, i
        return bi

    def drag_point(self, origin, direction):
        """Where the ray meets the plane in front of the shelf: (x, y), or None."""
        if abs(direction[2]) < 1e-6:
            return None
        t = (1.6 - origin[2]) / direction[2]
        return (origin[0] + direction[0] * t, origin[1] + direction[1] * t) if t > 0 else None

    def target_row(self, y):
        return min(range(len(self.rows)), key=lambda r: abs(self.row_y[r] + BOOK_H / 2 - y))

    def start_drag(self, origin, direction):
        i = self.drag_candidate
        self.drag_candidate = None
        pt = self.drag_point(origin, direction)
        if i is None or pt is None:
            return False
        self.drag = {"i": i, "x": pt[0], "y": pt[1], "row": self.target_row(pt[1])}
        self.app.status = f"Carrying '{self.books[i]['title'][:40]}' - drop it on any shelf"
        return True

    def drag_move(self, origin, direction):
        pt = self.drag_point(origin, direction)
        if self.drag and pt:
            self.drag.update(x=pt[0], y=pt[1], row=self.target_row(pt[1]))

    def drop(self):
        """Put the carried book on the shelf it hovers over and remember the placement."""
        d, self.drag = self.drag, None
        if not d:
            return
        b = self.books[d["i"]]
        section = self.rows[d["row"]]["section"]
        others = [(o["row"], o["x"]) for o in self.books if o["section"] == section and o is not b]
        slot = sum(1 for r_, x in others if (r_, x) < (d["row"], max(-SHELF_W / 2, min(SHELF_W / 2, d["x"]))))
        if self.kind == "manga" and (section == "plan") != (b.get("section") == "plan"):  # dragged onto / off Going To Read
            core.mp_set(b["id"], section == "plan", b.get("title_en") or b["title"], b.get("poster_url", ""), b.get("title_jp", ""))
            b["starred"] = section == "plan"
        core.shelf_set(self.kind, b["id"], section, slot)
        label = dict(self.sections).get(section, section)
        self.app.status = f"'{b['title'][:40]}' now lives on the {label.title()} shelf"
        self.layout(b["id"])  # also walks the person to the book's new spot

    def walk_to(self, i):
        b = self.books[i]
        self.auto = (b["x"], b["row"])
        self.app.status = f"Walking to '{b['title'][:40]}' - press Enter to pull it out"

    def librarian_near(self):
        return self.kind == "manga" and self.level == 0 and self.px < -SHELF_W / 2 + 4

    def relayout(self):
        """After a star toggle: re-read the watch list and rebuild the shelves, keeping the person where they were."""
        from .app import core  # lazy: app imports this module

        focus = self.books[self.near]["id"] if self.near is not None else None
        self.raw_wl = self.app.wl_with_data(core.wl_list(), self.raw_wl)
        self.layout(focus)

    # ---------- logic ----------
    def toggle_plan(self, b, on=None):
        """Manga: put a book on (or take it off) the GOING TO READ shelf. Books you've started stay on Reading."""
        on = (b["id"] not in {m["id"] for m in core.mp_list()}) if on is None else on
        core.mp_set(b["id"], on, b.get("title_en") or b["title"], b.get("poster_url", ""), b.get("title_jp", ""))
        b["starred"] = on
        started = bool(b.get("episodes"))
        if not started:  # move the book between shelves (it stays put while it's open in your hands)
            for lst in self.groups_in.values():
                if b in lst:
                    lst.remove(b)
            self.groups_in.setdefault("plan" if on else ("search" if b.get("section") == "search" else "popular"), []).insert(0, b)
            core.shelf_clear(self.kind, b["id"])  # a dragged-to placement would fight the new shelf
        self.app.status = (f"'{b['title'][:40]}' is on your Going To Read shelf" if on else f"Took '{b['title'][:40]}' off Going To Read") + \
            ("" if not started else " (you've already started it, so it stays on Reading)")
        if not self.pick:
            self.layout(b["id"])
        else:
            self._dirty = True  # re-shelve when the book is closed

    def toggle_star(self, b):
        if self.kind == "manga":
            return self.toggle_plan(b)
        self.app.toggle_star(b["id"], b["title"], b.get("poster_url", ""))
        b["starred"] = b["id"] in self.app.starred
        if self.bv:
            self.bv.art.clear()
        keep = self.pick["i"] if self.pick else None
        if not self.pick:
            self.relayout()
        elif keep is not None and not b["starred"] and b["section"] == "planning":
            self.app.status = "Removed from your watch list (it leaves the shelf when you close the book)"

    def key(self, k):
        pk = self.pick
        if pk:
            if k in ("=", "+"):
                self.zoom = min(self.zoom * 1.25, 4.0)
                return
            if k in ("-", "_"):
                self.zoom = max(self.zoom / 1.25, 0.6)
                return
            if k == "0":
                self.zoom, self.pan, self.focus = 1.0, [0.0, 0.0], "spread"
                return
            if k == "z":
                self.cycle_focus()
                return
            if pk["u"] >= TOTAL - 0.05 and self.bv.key(k):
                return
            if k in ("Enter", "e"):
                if pk["u"] < TOTAL - 0.05:
                    pk["u"] = TOTAL  # skip ahead to the open book
                elif self.kind == "manga":
                    self.app.read_chapter(self.books[pk["i"]], self.bv.next_ep() if self.bv.mode == "toc" else self.bv.chapter)
                else:
                    self.app.open_history_book(self.books[pk["i"]])
            elif k in ("Escape", "Backspace"):
                pk["closing"] = True
                self.bv.spread = self.bv.target = 0
                self.bv.flip = None
            elif k == "f":
                self.toggle_star(self.books[pk["i"]])
            elif k in ("x", "Delete") and self.kind == "manga":
                self.remove_book(pk["i"])
            return
        if k in ("Enter", "e") and self.near is not None:
            self.pick = {"i": self.near, "u": 0.0, "closing": False}
            self.bv = BookView(self.app, self.books[self.near], self.kind, self.app.manga_rtl)
            if self.kind == "manga":
                self.app.ensure_chapters(self.books[self.near])  # fetch the chapter list while the book is opening
            self.zoom, self.pan, self.focus = 1.0, [0.0, 0.0], "spread"
            self.auto = None
            self.app.fetch_book_poster(self.books[self.near])
        elif k == "c" and self.next_up is not None:
            b = self.books[self.next_up]
            self.auto = (b["x"], b["row"])
            self.app.status = f"Walking to your next-up book: {b['title']}"
        elif k == "f" and self.near is not None:
            self.toggle_star(self.books[self.near])
        elif k in ("x", "Delete") and self.kind == "manga" and self.near is not None:
            self.remove_book(self.near)
        elif k == "z" and self.kind == "manga":
            self.undo_remove()
        elif k == "/" and self.kind == "manga":
            self.app.lib_typing, self.app.swallow = True, "/"
        elif k == "p" and self.kind == "manga":
            self.app.toggle_manga_direction()
        elif k == "j" and self.kind == "manga":
            self.app.toggle_titles()
        elif k == "k":
            self.app.start_game("kong", back="library")
        elif k == "m":
            self.app.open_library("anime" if self.kind == "manga" else "manga")

    def cycle_focus(self):
        """Z: whole spread -> the page you read first -> the other page -> whole spread."""
        first = self.bv.first_side() if self.bv else "L"
        other = "L" if first == "R" else "R"
        self.focus = {"spread": first, first: other, other: "spread"}[self.focus]
        self.pan = [0.0, 0.0]
        self.app.status = {"spread": "Whole spread", "L": "Zoomed on the left page", "R": "Zoomed on the right page"}[self.focus] + "  (Z to cycle, wheel to zoom, drag to pan)"

    def zoom_by(self, dy):
        self.zoom = min(max(self.zoom / 1.0015 ** dy, 0.6), 4.0)

    def pan_by(self, dx, dy):
        s = self.app.scene.cam.dist * 0.0016
        self.pan[0] -= dx * s
        self.pan[1] += dy * s

    def click(self, origin, direction):
        if not self.pick and not self.drag:
            if self.kind == "manga" and abs(direction[2]) > 1e-6:  # click the librarian: ask a question
                t = (PERSON_Z - 0.5 - origin[2]) / direction[2]
                x, y = origin[0] + direction[0] * t, origin[1] + direction[1] * t
                if t > 0 and abs(x - LIBRARIAN_X) < 3.4 and self.row_y[0] - 0.5 < y < self.row_y[0] + 6.5:
                    self.app.lib_typing = True
                    return True
            i = self.pick_book(origin, direction)
            if i is not None:
                self.walk_to(i)
                return True
        if self.pick and self.pick["u"] >= TOTAL - 0.05 and self.bv:
            hit = self.bv.hit(origin, direction)
            if hit:
                if self.kind == "manga":
                    self.app.read_chapter(self.books[self.pick["i"]], hit[0])
                else:
                    self.app.play_from_book(self.books[self.pick["i"]], hit[0])
                return True
        return False

    def update(self, dt, keys):
        self.falling = [bk for bk in self.falling if step_book(bk, dt, 0.0)]
        goal = 1.0 if (self.drawer and not self.pick) else 0.0
        self.drawer_t += (goal - self.drawer_t) * (1 - math.exp(-dt * 12))
        pk = self.pick
        if pk:
            pk["u"] = min(TOTAL, max(0.0, pk["u"] + dt * (-2.2 if pk["closing"] else 1.0)))
            if pk["u"] >= TOTAL:
                self.bv.update(self.app.t)
            if pk["closing"] and pk["u"] <= 0:
                self.pick, self.bv = None, None
                if getattr(self, "_dirty", False):
                    self._apply_extend()
                else:
                    self.relayout()
            return
        move = ((keys & {"ArrowRight", "d"}) and 1 or 0) - ((keys & {"ArrowLeft", "a"}) and 1 or 0)
        if self.auto:
            tx, tl = self.auto
            if tl != self.level and abs(self.py - self.row_y[self.level]) < 0.05:
                self.level += 1 if tl > self.level else -1
            if abs(self.px - tx) > 0.15 and self.level == tl:
                move = 1 if tx > self.px else -1
            elif self.level == tl and abs(self.py - self.row_y[tl]) < 0.05:
                self.auto = None
        else:
            if self.app.pressed & {"ArrowUp", "w"}:
                self.level = min(self.level + 1, len(self.rows) - 1)
            if self.app.pressed & {"ArrowDown", "s"}:
                self.level = max(self.level - 1, 0)
        self.app.pressed = set()
        self.moving = move != 0 or abs(self.py - self.row_y[self.level]) > 0.05
        if move:
            self.facing = move
            self.px = max(-SHELF_W / 2, min(SHELF_W / 2, self.px + move * 9 * dt))
        self.py += (self.row_y[self.level] - self.py) * (1 - math.exp(-dt * 7))
        self.near = None
        for i, b in enumerate(self.books):
            if b["row"] == self.level and abs(self.px - b["x"]) <= b["w"] / 2 + 0.25:
                self.near = i
                break
        # manga: count the real number of chapters (all sources) for the book you stand at, so the shelf shows the whole series
        if self.kind == "manga" and self.near is not None:
            if self.near != getattr(self, "_dwell_i", None):
                self._dwell_i, self._dwell_t = self.near, 0.0
            self._dwell_t += dt
            b = self.books[self.near]
            if self._dwell_t > 0.6 and b.get("chapters") is None and not b.get("_loading"):
                self.app.ensure_chapters(b, quiet=True)

    def display(self):
        """Where the opened book is held: centre of the screen, in front of the shelf."""
        return self.px, 6.6 + self.level * 0.8, 7.0

    def camera(self):
        rows = len(self.rows)
        base = (self.px * 0.45, 5.4 + self.level * 0.9, 0.0)
        far = 27 + max(0, rows - 3) * 3.5
        if not self.pick:
            return (base, 0.0, math.radians(9), far)
        f = ease(self.pick["u"] / 0.9)
        dx, dy, dz = self.display()
        zoom = self.zoom
        if self.focus != "spread" and self.bv:  # fit one page to the screen
            dx += (1 if self.focus == "R" else -1) * (self.bv.LP / 2 + 0.03)
            zoom *= 1.9
        goal = (dx + self.pan[0], dy + self.pan[1], dz - 1.0)
        tgt = tuple(lerp(a, b, f) for a, b in zip(base, goal))
        dist = lerp(far, (19.0 if self.kind == "manga" else 15.5) / zoom, f)
        return (tgt, 0.0, lerp(math.radians(9), math.radians(11), f), max(dist, 6.0))

    # ---------- drawing ----------
    def build(self, r, text, th, t):
        out = self.bookcase(r, text, th, t)
        if self.drag:  # the shelf the carried book would land on
            out.append(box(0, self.row_y[self.drag["row"]] - 0.05, 0.3, SHELF_W + 1.0, 0.16, 2.8, th.accent, 1.6))
        for i, b in enumerate(self.books):
            if self.pick and self.pick["i"] == i:
                continue  # that book is in the person's hands
            if self.drag and self.drag["i"] == i:
                continue
            s = ease((t - self.app.lib_t0 - 0.03 * i) / 0.5)
            if s <= 0:
                continue
            hot = i == self.near
            y0 = self.row_y[b["row"]] + 0.05
            hgt = b["h"] * s
            cy = y0 + hgt / 2
            out += self.volume(r, text, th, b, y0, s, hot)
            frac = b["watched"] / b["total"] if b["total"] else 0.0
            if frac > 0 and not b.get("face"):  # progress ribbon: a bookmark tassel hanging out of the top, length = how far you are
                out.append(box(b["x"] + b["w"] * 0.22, y0 + hgt + 0.1, BOOK_D / 2 - 0.25, 0.1, 0.24, 0.06, th.ep_seen, 0.9))
                out.append(box(b["x"] - b["w"] / 2 - 0.02, y0 + hgt * (1 - min(frac, 1) / 2), BOOK_D / 2 - 0.2, 0.04, hgt * min(frac, 1), 0.12, th.ep_seen, 0.8))
            if b["starred"]:
                out.append(box(b["x"], y0 + b["h"] * s + 0.4, 0.2, 0.55, 0.55, 0.3, GOLD, 1.4, yaw=math.pi / 4 + 0.3 * math.sin(t * 2)))
            if i == self.next_up:
                out.append(box(b["x"], y0 + b["h"] + 1.2 + 0.25 * math.sin(t * 3), 0.3, 0.5, 0.5, 0.5, th.ep_play, 1.3, yaw=t * 2))
        for bk in self.falling:
            out += book_boxes(bk, 0.3)
        if self.drag:
            b = self.books[self.drag["i"]]
            sway = 0.12 * math.sin(t * 7)
            out.append(box(self.drag["x"], self.drag["y"], 2.0, b["w"], b["h"], BOOK_D, b["color"], 1.0, sway))
            self.spine(r, text, b, mathx.translate(self.drag["x"], self.drag["y"], 2.0) @ mathx.rot_y(sway), 1.0, (1, 1, 1, 1))
        if self.pick:
            out += self.open_book(r, text, th, t)
        if self.kind == "manga":
            out += self.librarian(r, text, th, t)
        out += self.person(t, th)
        return out

    def librarian(self, r, text, th, t):
        """The librarian: glasses, a bun, a desk with a lamp. Click her (or press /) to search for a manga."""
        out = []
        x, y, z = LIBRARIAN_X, self.row_y[0], PERSON_Z - 0.3
        sc = 1.25  # she is a little bigger than the person who browses, so she reads from across the room
        out.append(box(x, y + 0.9, z + 1.4, 4.4, 1.8, 1.8, th.wood, 0.25))  # desk
        out.append(box(x - 1.3, y + 2.1, z + 1.4, 1.1, 0.6, 0.9, (0.9, 0.7, 0.2), 0.7))  # stack of books
        out.append(box(x - 1.3, y + 2.6, z + 1.4, 0.9, 0.4, 0.8, (0.7, 0.2, 0.2), 0.7))
        out.append(box(x + 1.5, y + 2.6, z + 1.4, 0.15, 1.5, 0.15, (0.7, 0.7, 0.75), 0.4))  # lamp stand
        out.append(box(x + 1.5, y + 3.5, z + 1.4, 0.9, 0.45, 0.9, (1.0, 0.9, 0.5), 1.9))
        out += voxel_person(th, x, y, z - 0.2, 1, math.sin(t * 2) * 0.05, int(t * 0.5) % 2 == 0 and not self.app.lib_typing, sc)
        hy = y + 2.05 * sc
        out.append(box(x - 0.28 * sc, hy, z + 0.2 + 0.35 * sc, 0.34 * sc, 0.26 * sc, 0.1, (0.1, 0.1, 0.12), 0.0))  # glasses
        out.append(box(x + 0.28 * sc, hy, z + 0.2 + 0.35 * sc, 0.34 * sc, 0.26 * sc, 0.1, (0.1, 0.1, 0.12), 0.0))
        out.append(box(x, hy, z + 0.2 + 0.35 * sc, 0.12, 0.06, 0.1, (0.1, 0.1, 0.12), 0.0))
        out.append(box(x, y + 2.9 * sc, z - 0.5, 0.65 * sc, 0.55 * sc, 0.6 * sc, (0.55, 0.3, 0.2), 0.2))  # hair bun
        sign, w, h = text.get("LIBRARIAN  -  click or press /", 36, tuple(int(c * 255) for c in th.accent))
        ww = min(7.5, 0.62 * w / h)
        r.quad3d(sign, mathx.translate(x - ww / 2, y + 5.2, z + 0.9) @ mathx.scale(ww, -ww * h / w, 1))
        if self.app.lib_typing:
            msg = f"Looking for: {self.app.lib_query}{'|' if int(t * 2) % 2 == 0 else ' '}"
            bub, w, h = text.get(msg[-34:], 34, (30, 30, 40))
            ww = min(7.0, 0.5 * w / h)
            hh = ww * h / w
            out.append(box(x + 4.0, y + 6.4, z + 0.8, ww + 0.8, hh + 0.5, 0.2, (0.96, 0.96, 0.9), 0.9, 0.0, 0.2))
            r.quad3d(bub, mathx.translate(x + 4.0 - ww / 2, y + 6.4 + hh / 2, z + 0.92) @ mathx.scale(ww, -hh, 1))
        return out

    def bookcase(self, r, text, th, t):
        """A proper bookcase: plank back, side pilasters, plinth and crown molding, shelves with a front lip and a warm light
        strip under each one, brass plaques with the section names, bookends and a little decoration on top."""
        out = []
        wood = th.wood
        dark = tuple(c * 0.6 for c in wood)
        light = tuple(min(1.0, c * 1.35 + 0.04) for c in wood)
        top = self.row_y[-1] + BOOK_H + 1.4
        n_pl = 12
        for k in range(n_pl):  # back panel: vertical planks in slightly different shades
            pw = (SHELF_W + 1.2) / n_pl
            shade = 0.5 + 0.08 * ((k * 7) % 3)
            out.append(box(-SHELF_W / 2 - 0.6 + pw * (k + 0.5), top / 2, -1.25, pw - 0.04, top, 0.3, tuple(c * shade for c in wood), 0.03, 0.0, 0.2))
        for sx in (-1, 1):  # sides: a panel with a pilaster on the front edge
            out.append(box(sx * (SHELF_W / 2 + 0.6), top / 2, 0, 0.5, top, 2.8, wood, 0.12, 0.0, 0.3))
            out.append(box(sx * (SHELF_W / 2 + 0.68), top / 2, 1.45, 0.7, top, 0.2, light, 0.12, 0.0, 0.3))
            for yy in (0.6, top - 0.6):
                out.append(box(sx * (SHELF_W / 2 + 0.68), yy, 1.55, 0.85, 0.3, 0.1, dark, 0.1, 0.0, 0.3))
        out.append(box(0, 0.08, 0.0, SHELF_W + 2.6, 0.16, 2.9, dark, 0.08, 0.0, 0.3))  # plinth
        out.append(box(0, top, 0, SHELF_W + 1.7, 0.4, 2.8, wood, 0.12, 0.0, 0.3))  # crown molding, stepped
        out.append(box(0, top + 0.3, 0.1, SHELF_W + 2.3, 0.2, 3.1, light, 0.12, 0.0, 0.3))
        out.append(box(0, top + 0.48, 0.15, SHELF_W + 2.7, 0.16, 3.3, dark, 0.1, 0.0, 0.3))
        warm = (1.0, 0.82, 0.5)
        for i, y in enumerate(self.row_y):
            out.append(box(0, y - 0.15, 0, SHELF_W + 1.2, 0.3, 2.8, wood, 0.15, 0.0, 0.3))  # shelf board
            out.append(box(0, y - 0.13, 1.42, SHELF_W + 1.2, 0.36, 0.12, light, 0.15, 0.0, 0.3))  # front lip
            light_y = (self.row_y[i + 1] - 0.36) if i + 1 < len(self.row_y) else top - 0.24
            out.append(box(0, light_y, 1.15, SHELF_W + 0.8, 0.05, 0.12, warm, 1.7, 0.0, 0.0))  # light strip under the shelf above
            run = [b for b in self.books if b["row"] == i]
            if run:  # metal bookends holding the row
                end = max(b["x"] + b["w"] / 2 for b in run) + 0.12
                if end < SHELF_W / 2 - 0.3:
                    out.append(box(end, y + 1.1, 0.0, 0.1, 2.2, 1.5, (0.25, 0.25, 0.28), 0.25, 0.0, 0.3))
                    out.append(box(end - 0.35, y + 0.04, 0.0, 0.8, 0.06, 1.5, (0.25, 0.25, 0.28), 0.25, 0.0, 0.3))
        # brass plaques on the shelf lip naming each section
        for i, rw in enumerate(self.rows):
            if rw["label"]:
                n = self.section_info[rw["section"]][1]
                msg = f"{rw['label']} ({n})" if (n or self.kind == "manga") else f"{rw['label']} (0) - press F on a book"
                tex, w, h = text.get(msg, 44, (40, 26, 8))
                hh = 0.5
                ww = min(hh * w / h, 9.0)
                hh = ww * h / w
                px = SHELF_W / 2 - 0.8 - ww / 2
                py = max(self.row_y[i] - 0.13, hh / 2 + 0.2)  # the bottom one sits just above the plinth
                out.append(box(px, py, 1.5, ww + 0.5, hh + 0.16, 0.06, BRASS, 0.55, 0.0, 0.3))
                r.quad3d(tex, mathx.translate(px - ww / 2, py + hh / 2, 1.54) @ mathx.scale(ww, -hh, 1))
        # on top: a potted plant and a little stack of volumes lying flat
        px, py = SHELF_W / 2 - 3.0, top + 0.56
        out.append(box(px, py + 0.6, 0.2, 1.2, 1.2, 1.2, (0.72, 0.36, 0.2), 0.2, 0.0, 0.3))
        out.append(box(px, py + 1.22, 0.2, 1.25, 0.1, 1.25, (0.3, 0.2, 0.12), 0.1, 0.0, 0.0))
        for k in range(7):
            a = k / 7 * math.tau + 0.3
            out.append(box(px + math.cos(a) * 0.5, py + 1.9 + 0.25 * (k % 2), 0.2 - math.sin(a) * 0.5, 1.3, 0.12, 0.42, (0.25, 0.55, 0.2), 0.2, a,
                           0.2, 0.0, 0.0, 0.5 + 0.06 * math.sin(t * 1.3 + k)))
        sx = -SHELF_W / 2 + 3.0
        for k in range(4):
            col = th.books[k % len(th.books)]
            out.append(box(sx + 0.05 * (k % 2), py + 0.13 + k * 0.26, 0.2, VOL_H, 0.24, BOOK_D, CREAM, 0.1, 0.12 * (k - 1.5), 0.3))
            out.append(box(sx + 0.05 * (k % 2) - VOL_H / 2 + 0.3, py + 0.13 + k * 0.26, 0.2, 0.5, 0.25, BOOK_D + 0.01, col, 0.3, 0.12 * (k - 1.5), 0.0))
        return out

    def volume(self, r, text, th, b, y0, s, hot):
        """One manga volume on the shelf: spine out (white or coloured, a colour band with the volume number at the top,
        the title down the middle, a publisher mark at the bottom), or face-out showing the cover art."""
        out = []
        x, w, h = b["x"], b["w"], b["h"] * s
        col = b["color"]
        glow = 0.12 + (0.9 if hot else 0)
        tint = (1, 1, 1, 1) if s > 0.8 else (1, 1, 1, 0)
        if b.get("face"):
            z, depth, lean = 0.45, 0.34, -0.07
            yc = y0 + h / 2
            out.append(box(x, yc, z, w, h, depth, col, glow, 0.0, 0.3, lean))
            out.append(box(x + 0.03, yc, z - 0.02, w - 0.08, h - 0.06, depth + 0.02, CREAM, 0.1, 0.0, 0.0, lean))  # page block
            tex = b.get("card_tex")
            if tex is None:
                if b.get("poster_img") is not None:
                    tex = b["card_tex"] = self.app.r.make_texture(np.asarray(b["poster_img"]))
                elif not b.get("poster_loading"):
                    self.app.fetch_book_poster(b)
            M = mathx.translate(x, yc, z) @ mathx.rot_x(lean) @ mathx.translate(-w / 2 + 0.05, h / 2 - 0.05, depth / 2 + 0.012)
            if tex is not None:
                r.quad3d(tex, M @ mathx.scale(w - 0.1, -(h - 0.1), 1), tint)
            else:  # no art yet: the title printed on the cover
                tt, tw, tht = text.get(b["title"][:22], 40, (255, 255, 255))
                ww = min(w - 0.3, 0.32 * tw / tht)
                r.quad3d(tt, M @ mathx.translate(0.1, -0.4, 0) @ mathx.scale(ww, -ww * tht / tw, 1), tint)
            return out
        base = CREAM if b.get("white_spine") else col
        out.append(box(x, y0 + h / 2, 0, w, h, BOOK_D, base, glow, 0.0, 0.3))
        out.append(box(x, y0 + h - 0.015, -0.05, w * 0.82, 0.04, BOOK_D * 0.9, (0.98, 0.97, 0.92), 0.1, 0.0, 0.0))  # page edges on top
        band = 0.62 * s
        fz = BOOK_D / 2 + 0.006
        out.append(box(x, y0 + h - 0.16 - band / 2, fz, w + 0.004, band, 0.012, col if b.get("white_spine") else CREAM, 0.35, 0.0, 0.0))
        out.append(box(x, y0 + 0.32 * s, fz, w * 0.5, w * 0.5 * s, 0.012, col if b.get("white_spine") else CREAM, 0.35, 0.0, 0.0))  # publisher mark
        if s > 0.8:
            vol = str(max(1, (b.get("total") or len(b.get("all_eps") or []) or 9) // 9))  # ~9 chapters a volume
            vt, vw, vh = text.get(vol, 40, (20, 20, 24) if not b.get("white_spine") else (255, 255, 255))
            nh = 0.3
            nw = nh * vw / vh
            if nw > w * 0.9:
                nw, nh = w * 0.9, w * 0.9 * vh / vw
            r.quad3d(vt, mathx.translate(x - nw / 2, y0 + h - 0.16 - band / 2 + nh / 2, fz + 0.01) @ mathx.scale(nw, -nh, 1), tint)
            ink = (25, 25, 30) if b.get("white_spine") else (255, 255, 255)
            self.spine(r, text, b, mathx.translate(x, y0 + 0.62 + (h - 0.62 - 0.16 - band) / 2, 0), 1.0, tint, avail=h - band - 0.95, color=ink)
        return out

    def spine(self, r, text, b, M, scale, tint, avail=None, color=(255, 255, 255)):
        tex, tw_px, th_px = text.get(b["title"][:26], 40, color)
        sw = VOL_W if b.get("face") else b["w"]
        texth = min(sw * 0.62, 0.85)
        texw = texth * tw_px / th_px
        room = avail if avail is not None else b["h"] * 0.92
        if texw > room:
            texw, texth = room, room * th_px / tw_px
        m = M @ mathx.translate(0, 0, BOOK_D * scale / 2 + 0.05) @ mathx.rot_z(math.pi / 2) @ mathx.translate(-texw / 2 * scale, texth / 2 * scale, 0) @ mathx.scale(texw * scale, -texth * scale, 1)
        r.quad3d(tex, m, tint)

    def open_book(self, r, text, th, t):
        pk = self.pick
        b = self.books[pk["i"]]
        u = pk["u"]
        dx, dy, dz = self.display()
        if u < 0.9:  # the closed book slides off the shelf, turns to face you, leans back and grows to reading size
            a = ease(u / 0.9)
            sx, sy = b["x"], self.row_y[b["row"]] + 0.05 + b["h"] / 2
            pos = (lerp(sx, dx, a), lerp(sy, dy, a) + math.sin(a * math.pi) * 0.8, lerp(0.0, dz, a))
            yaw = -math.pi / 2 * a
            if self.bv.rtl:
                yaw = math.pi / 2 * a  # right-to-left binding: the spine ends up on the right
            P = book_thickness(b)
            bv = self.bv
            dims = (lerp(b["w"], P, a), lerp(b["h"], bv.HC, a), lerp(BOOK_D, bv.WC, a))
            sc = lerp(1.0, S, a)
            tilt = tilt_for(u)
            self.spine(r, text, b, mathx.translate(*pos) @ mathx.rot_x(tilt) @ mathx.rot_y(yaw), sc, (1, 1, 1, 1))
            return [box(*pos, *dims, b["color"], 1.0, yaw, 0.3, tilt, 1.0)]
        return self.bv.build(r, text, th, t, u, (dx, dy, dz))

    def person(self, t, th):
        out = []
        x, y, z = self.px, self.py, PERSON_Z
        sc = 0.75
        swing = math.sin(t * 12) * 0.35 if self.moving and not self.pick else 0.0
        skin, shirt, hair = (0.96, 0.80, 0.66), th.ped_sel, th.core
        f = self.facing
        for dx in (-0.55, 0.55):  # rolling ladder
            out.append(box(x + dx, y / 2 + 0.1, 1.55, 0.1, y + 0.2, 0.1, th.wood, 0.1))
        for ry in [k * 0.9 for k in range(1, int(y / 0.9) + 1)]:
            out.append(box(x, ry, 1.55, 1.1, 0.08, 0.1, th.wood, 0.1))
        holding = bool(self.pick)
        out.append(box(x - 0.4 * sc, y + 0.45 * sc, z + swing * 0.5, 0.56 * sc, 0.9 * sc, 0.6 * sc, (0.15, 0.15, 0.3), 0.0))
        out.append(box(x + 0.4 * sc, y + 0.45 * sc, z - swing * 0.5, 0.56 * sc, 0.9 * sc, 0.6 * sc, (0.15, 0.15, 0.3), 0.0))
        out.append(box(x, y + 1.3 * sc, z, 0.95 * sc, 0.95 * sc, 0.55 * sc, shirt, 0.2))
        out.append(box(x, y + 2.1 * sc, z, 0.75 * sc, 0.7 * sc, 0.7 * sc, skin, 0.1))
        out.append(box(x, y + 2.5 * sc, z, 0.85 * sc, 0.25 * sc, 0.8 * sc, hair, 0.3))
        out.append(box(x + f * 0.42 * sc, y + 2.05 * sc, z + 0.3 * sc, 0.12, 0.12, 0.15, skin, 0.0))
        arm_y = y + (1.95 if holding else 1.3) * sc
        for sx in (-1, 1):
            out.append(box(x + sx * 0.62 * sc, arm_y, z + (0.35 * sc if holding else 0), 0.24 * sc, 0.8 * sc, 0.24 * sc, skin, 0.05))
        return out

    # ---------- HUD ----------
    def removed_drawer(self, app, W, H):
        """A slide-out drawer on the left edge listing removed books: restore any one of them, or all."""
        th = app.theme
        pw, top = 320, 150
        ph = H - top - 144
        x = -pw + pw * (self.drawer_t * self.drawer_t * (3 - 2 * self.drawer_t))
        # the tab sticks out of the drawer's right edge and is always visible
        glow = self.pulse > -1 and app.t - self.pulse < 1.6
        tab_label = f"REMOVED ({self.hidden_count})" if self.hidden_count else "REMOVED"
        app.r.rect(x + pw, top, 34, 190, (*th.edge[:3], 0.85 if glow and int(app.t * 6) % 2 == 0 else 0.45))
        app.button("<" if self.drawer else ">", x + pw, top, 34, 34, lambda: setattr(self, "drawer", not self.drawer), self.drawer)
        for i, ch in enumerate(tab_label[:11]):  # vertical label, one letter per line
            app.txt(ch, x + pw + 17, top + 38 + i * 13, 12, (1, 1, 1), center=True)
        app.hits.append((x + pw, top + 34, 34, 156, lambda *_: setattr(self, "drawer", not self.drawer)))
        if self.drawer_t < 0.02:
            return
        app.r.rect(x, top, pw, ph, (0.01, 0.015, 0.03, 0.96))
        app.panel(x, top, pw, ph)
        app.txt("REMOVED FROM SHELF", x + 16, top + 12, 16, th.accent)
        if self.hidden_items:
            half = (pw - 40) / 2
            app.button(f"RESTORE ALL ({len(self.hidden_items)})", x + 16, top + 42, half, 30, self.restore_all)
            armed = app.t - getattr(self, "_clear_armed", -9) < 4
            app.button("SURE? CLICK AGAIN" if armed else "CLEAR LIST", x + 24 + half, top + 42, half, 30, self.clear_removed, armed)
        else:
            app.txt("Nothing removed.", x + 16, top + 50, 13, th.dim)
            app.txt("Press X on a book to take it off.", x + 16, top + 72, 11, th.dim)
        rows = max(1, int((ph - 96) // 46))
        self.drawer_scroll = max(0, min(self.drawer_scroll, max(0, len(self.hidden_items) - rows)))
        for k, (iid, title) in enumerate(self.hidden_items[self.drawer_scroll:self.drawer_scroll + rows]):
            ry = top + 84 + k * 46
            app.r.rect(x + 12, ry, pw - 24, 40, (0, 0, 0, 0.4))
            app.txt(title[:30], x + 20, ry + 4, 13, (1, 1, 1))
            app.button("RESTORE", x + pw - 108, ry + 21, 90, 18, lambda iid=iid, title=title: self.restore_one(iid, title))
        if len(self.hidden_items) > rows:
            app.txt(f"{self.drawer_scroll + 1}-{min(self.drawer_scroll + rows, len(self.hidden_items))} of {len(self.hidden_items)}  (wheel scrolls)", x + 16, top + ph - 22, 10, th.dim)

    def section_here(self):
        return self.rows[self.level]["section"]

    def hud(self, app, W, H):
        th = app.theme
        label = dict(self.sections)[self.section_here()]
        app.txt(f"THE LIBRARY  -  {label}", W / 2, 66, 18, th.accent, center=True)
        if self.pick:
            b = self.books[self.pick["i"]]
            star = "  [*]" if b["starred"] else ""
            app.txt(f"{b['title'][:44]}{star}", W / 2, 92, 16, (1, 1, 1), center=True)
            if self.pick["u"] >= TOTAL - 0.05:
                bv = self.bv
                if self.kind == "manga":
                    direction = "right to left" if bv.rtl else "left to right"
                    msg = f"arrows / A D turn page ({direction})   [ ] chapters   O list   G direction   wheel/+/- zoom   Z fit page   U hide UI   Esc close" if bv.mode == "read" else "click a chapter to read it   C continue page   Enter continue reading   G direction   wheel zoom   Esc close"
                else:
                    msg = "A/D or arrows flip   W/S jump 5   C continue page   click an episode to play   F star   Enter open anime   Esc close"
                app.txt(msg, W / 2, 118, 12, th.dim, center=True)
                n = bv.n_spreads()
                cx, y = W / 2, H - 70
                ld = bv.left_delta()
                for x, lbl, cb in [(cx - 215, "|<" if not bv.rtl else ">|", lambda: bv.jump(not bv.rtl)), (cx - 150, "<", lambda: bv.go(ld)),
                                   (cx + 94, ">", lambda: bv.go(-ld)), (cx + 159, ">|" if not bv.rtl else "|<", lambda: bv.jump(bv.rtl))]:
                    app.button(lbl, x, y, 56, 34, cb)
                lab = f"SPREAD {bv.target + 1}/{n}"
                if bv.mode == "read":
                    lab = f"CH {bv.chapter}  -  {bv.target + 1}/{n}"
                app.txt(lab, cx, y + 8, 14, th.text, center=True)
                app.button("HIDE UI (U)", W - 560, y - 42, 110, 34, lambda: app.on_key("u"))
                for i, (lbl, cb) in enumerate([("ZOOM -", lambda: self.key("-")), ("ZOOM +", lambda: self.key("=")), ("FIT PAGE (Z)", lambda: self.key("z")), ("RESET", lambda: self.key("0"))]):
                    app.button(lbl, W - 440 + i * 108 - (8 if i == 2 else 0), y - 42, 100 + (16 if i == 2 else 0), 34, cb)
                if bv.manga:
                    app.button("READ: R>L" if bv.rtl else "READ: L>R", 22, y, 120, 34, lambda: bv.key("g"))
                    bk = self.books[self.pick["i"]]
                    app.button("OPEN IN DOCUMENT READER", 22, y - 42, 232, 34, lambda: app.export_chapter(bk, bv.chapter if bv.mode == "read" else None))
                    app.button("MANGAFIRE", 22, y - 84, 120, 34, lambda: app.open_mangafire(bk["title"]))
                    app.button("REMOVE FROM SHELF (X)", 150, y - 84, 206, 34, lambda: self.remove_book(self.pick["i"]))
                if bv.manga and bv.mode == "read":
                    app.button("CHAPTERS (O)", cx - 330, y, 100, 34, lambda: bv.key("o"))
                    app.button("[ PREV", cx + 240, y, 80, 34, lambda: bv.key("["))
                    app.button("NEXT ]", cx + 326, y, 80, 34, lambda: bv.key("]"))
                if bv.hover:
                    ep = bv.hover[0]
                    unit = "Chapter" if bv.manga else "Episode"
                    app.txt(f"{unit} {ep}{' (done)' if ep in bv.watched() else ''}  -  click to {'read' if bv.manga else 'play'}", 22, H - 36, 15, th.accent)
            return
        keys = ("A/D walk   W/S climb   Enter open   C next-up   " + ("/ librarian   F going to read   X remove   Z undo   J titles   P pages   M anime shelf" if self.kind == "manga" else "F star   M manga shelf")
                + "   drag books between shelves   K barrels   Esc leave")
        if len(keys) * 7.9 > W - 40:  # too wide for the window: two centred lines
            parts = keys.split("   ")
            half = (len(parts) + 1) // 2
            app.txt("   ".join(parts[:half]), W / 2, 92, 13, th.dim, center=True)
            app.txt("   ".join(parts[half:]), W / 2, 108, 13, th.dim, center=True)
        else:
            app.txt(keys, W / 2, 92, 13, th.dim, center=True)
        if self.near is not None:
            b = self.books[self.near]
            pct = f"{100 * b['watched'] // b['total']}%" if b["total"] else "?"
            star = ("  [going to read]" if self.kind == "manga" else "  [starred]") if b["starred"] else ""
            if self.kind == "manga":
                src = f"  via {b['source']}" if b.get("source") and b["source"] != "MangaDex" else ""
                loading = "" if b.get("chapters") is not None else " (counting...)"
                app.txt(f"{b['title'][:46]}   -   {b['watched']}/{b['total'] or '?'} chapters ({pct}){loading}{src}{star}", 40, H - 70, 15, th.accent)
            else:
                app.txt(f"{b['title'][:46]}   -   {b['watched']}/{b['total'] or '?'} episodes ({pct}){star}", 22, H - 70, 15, th.accent)
        elif self.next_up is not None and self.section_here() == "watching":
            app.txt(f"Next up: {self.books[self.next_up]['title'][:48]}   (press C to walk there)", 22, H - 70, 15, th.good)
        elif not self.books:
            app.txt("Nothing here yet - watch something, or star anime (F in the world view) to plan them.", 22, H - 70, 15, th.accent)
        if self.kind == "manga":
            ry = H - 116
            app.button("ASK THE LIBRARIAN (/)", W - 232, ry, 214, 34, lambda: setattr(app, "lib_typing", True), app.lib_typing)
            app.button("TITLES: " + ("JP" if app.manga_jp else "EN"), W - 346, ry, 104, 34, app.toggle_titles)
            app.button("PAGES: " + ("R>L" if app.manga_rtl else "L>R"), W - 462, ry, 108, 34, app.toggle_manga_direction)
            if self.mangafire:
                app.button("NOT ON MANGADEX - TRY MANGAFIRE", W - 700, ry, 230, 34, lambda: app.open_mangafire(self.mangafire))
            if self.near is not None:
                app.button("REMOVE FROM SHELF (X)", 40, H - 116, 206, 34, lambda: self.remove_book(self.near))
            self.removed_drawer(app, W, H)
        app.button("BARREL CLIMB", W - 190, H - 74, 170, 34, lambda: app.start_game("kong", back="library"))
        app.button("ANIME SHELF" if self.kind == "manga" else "MANGA SHELF (M)", W - 390, H - 74, 190, 34, lambda: app.open_library("anime" if self.kind == "manga" else "manga"))
        if self.near is not None and self.kind != "manga":
            b = self.books[self.near]
            app.button("UNSTAR" if b["starred"] else "STAR IT", W - 500, H - 74, 100, 34, lambda: self.toggle_star(b))
        elif self.near is not None:
            b = self.books[self.near]
            app.button("NOT GOING TO READ" if b["starred"] else "GOING TO READ (F)", 256, H - 116, 220, 34, lambda: self.toggle_plan(b))
