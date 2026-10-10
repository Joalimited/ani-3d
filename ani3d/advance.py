"""Advancements: Minecraft-style achievements generated from what you actually watch and read.

Every anime in the watch history gets its own ladder (first episode -> hooked -> ... -> completionist), and there are global
ones (episodes, days in a row, night owl, marathons, manga chapters) plus a few for the arcade. Unlocks are stored in the watch
database (`advancement` table), so they persist and are shared with ani-tui. The first evaluation on an existing history only
records what you had already earned silently, so a long history does not flood the screen with toasts.
"""
import datetime as dt
import sqlite3

from . import core

ANIME_TIERS = [(1, "FIRST CONTACT", "watch your first episode of {a}"), (3, "HOOKED", "watch 3 episodes of {a}"),
               (6, "SETTLING IN", "watch 6 episodes of {a}"), (12, "FAITHFUL", "watch 12 episodes of {a}"),
               (24, "DEVOTED", "watch 24 episodes of {a}"), (50, "VETERAN", "watch 50 episodes of {a}"),
               (100, "LEGEND OF {a}", "watch 100 episodes of {a}")]
TOTAL_TIERS = [(1, "THE JOURNEY BEGINS", "watch an episode"), (10, "WARMING UP", "watch 10 episodes"), (25, "SEASON PASS", "watch 25 episodes"),
               (50, "DEDICATED VIEWER", "watch 50 episodes"), (100, "CENTURION", "watch 100 episodes"), (250, "COUCH POTATO", "watch 250 episodes"),
               (500, "TRUE OTAKU", "watch 500 episodes"), (1000, "TOUCH GRASS?", "watch 1000 episodes")]
SERIES_TIERS = [(2, "VARIETY PACK", "watch 2 different anime"), (5, "SAMPLER", "watch 5 different anime"), (10, "CONNOISSEUR", "watch 10 different anime"),
                (25, "ARCHIVIST", "watch 25 different anime")]
MANGA_TIERS = [(1, "FIRST PAGE", "read a manga chapter"), (10, "PAGE TURNER", "read 10 manga chapters"), (50, "BOOKWORM", "read 50 manga chapters"),
               (200, "LIBRARIAN", "read 200 manga chapters")]
GAME_ADV = {"kong3": ("KONG CLIMBER", "reach stage 3 of the barrel climb"), "kong_hammer": ("HAMMER TIME", "smash 5 barrels with the hammer in one run"),
            "maze1": ("PATHFINDER", "find the item in the data maze"), "maze3": ("LOST AND FOUND", "clear 3 maze levels in a row"),
            "galaga_boss": ("BOSS SLAYER", "defeat an anime-character boss in Dino Galaga"), "galaga_w3": ("DINO ACE", "reach wave 3 in Dino Galaga"),
            "quiz": ("POSTER EXPERT", "score 600+ in the poster quiz"), "trivia": ("TRIVIA MASTER", "finish anime trivia with a 7-answer streak")}


def _tiers(prefix, count, tiers, who=""):
    out = []
    for need, title, desc in tiers:
        out.append({"key": f"{prefix}:{need}", "title": title.replace("{a}", who.upper()), "desc": desc.replace("{a}", who),
                    "have": min(count, need), "need": need, "done": count >= need})
    return out


def compute():
    """All advancements with progress: [{group, items: [{key, title, desc, have, need, done}]}], most recently watched anime first."""
    groups = []
    try:
        with core.db_connect() as con:
            hist = con.execute("SELECT COALESCE(anime_id, anime_name), anime_name, COUNT(DISTINCT episode), MAX(timestamp) "
                               "FROM history GROUP BY COALESCE(anime_id, anime_name) ORDER BY MAX(timestamp) DESC").fetchall()
            days = [r[0] for r in con.execute("SELECT DISTINCT date(timestamp) FROM history ORDER BY 1")]
            per_day = con.execute("SELECT MAX(c) FROM (SELECT COUNT(DISTINCT anime_id || ':' || episode) c FROM history GROUP BY date(timestamp))").fetchone()[0] or 0
            night = con.execute("SELECT COUNT(*) FROM history WHERE CAST(strftime('%H', timestamp, 'localtime') AS INTEGER) < 5").fetchone()[0]
            chapters = con.execute("SELECT COUNT(*) FROM manga_read").fetchone()[0]
            totals = {r[0]: r[1] for r in con.execute("SELECT anime_id, total FROM anime_total")}
    except sqlite3.Error:
        return []
    episodes = sum(r[2] for r in hist)
    streak = best = 0
    prev = None
    for d in days:
        try:
            cur = dt.date.fromisoformat(d)
        except ValueError:
            continue
        streak = streak + 1 if prev and (cur - prev).days == 1 else 1
        best = max(best, streak)
        prev = cur
    g = _tiers("ep", episodes, TOTAL_TIERS) + _tiers("series", len(hist), SERIES_TIERS) + _tiers("manga", chapters, MANGA_TIERS)
    g += [{"key": f"streak:{n}", "title": t, "desc": d, "have": min(best, n), "need": n, "done": best >= n}
          for n, t, d in ((2, "BACK AGAIN", "watch on 2 days in a row"), (3, "ROUTINE", "watch on 3 days in a row"), (7, "WEEK-LONG ARC", "watch 7 days in a row"))]
    g += [{"key": "marathon:5", "title": "MARATHON", "desc": "watch 5 episodes in one day", "have": min(per_day, 5), "need": 5, "done": per_day >= 5},
          {"key": "marathon:12", "title": "WEEKEND IS GONE", "desc": "watch 12 episodes in one day", "have": min(per_day, 12), "need": 12, "done": per_day >= 12},
          {"key": "night:1", "title": "NIGHT OWL", "desc": "watch something after midnight", "have": min(night, 1), "need": 1, "done": night >= 1}]
    groups.append({"group": "EVERYTHING YOU WATCH", "items": g})
    for aid, name, n, last in hist[:30]:
        items = _tiers(f"a:{aid}", n, ANIME_TIERS, name)
        tot = totals.get(aid) or 0
        if tot >= 3:
            items.append({"key": f"a:{aid}:done", "title": "COMPLETIONIST", "desc": f"finish all {tot} episodes of {name}", "have": min(n, tot), "need": tot, "done": n >= tot})
        groups.append({"group": name, "items": items})
    return groups


def game_items():
    have = unlocked()
    return [{"key": f"game:{k}", "title": t, "desc": d, "have": int(f"game:{k}" in have), "need": 1, "done": f"game:{k}" in have} for k, (t, d) in GAME_ADV.items()]


def unlocked():
    try:
        with core.db_connect() as con:
            return {r[0] for r in con.execute("SELECT key FROM advancement")}
    except sqlite3.Error:
        return set()


def _store(keys):
    try:
        with core.db_connect() as con:
            con.executemany("INSERT OR IGNORE INTO advancement (key) VALUES (?)", [(k,) for k in keys])
    except sqlite3.Error:
        pass


class Tracker:
    """Evaluates progress and tells the UI which advancements were just earned."""

    def __init__(self):
        self.have = unlocked()
        self.fresh = not self.have  # an empty table: the first pass is silent
        self.cache = []

    def refresh(self):
        """Re-evaluate from the database. Returns [(title, desc, group)] of advancements earned since the last call."""
        self.cache = compute()
        new = []
        for grp in self.cache + [{"group": "ARCADE", "items": game_items()}]:
            for it in grp["items"]:
                if it["done"] and it["key"] not in self.have:
                    self.have.add(it["key"])
                    new.append((it["title"], it["desc"], grp["group"], it["key"]))
        if new:
            _store([n[3] for n in new])
        if self.fresh:
            self.fresh = False
            return []
        return [n[:3] for n in new]

    def award(self, key):
        """A game-event advancement (see GAME_ADV). Returns (title, desc, 'ARCADE') the first time, else None."""
        full = f"game:{key}"
        if full in self.have or key not in GAME_ADV:
            return None
        self.have.add(full)
        _store([full])
        return GAME_ADV[key] + ("ARCADE",)

    def groups(self):
        if not self.cache:
            self.cache = compute()
        return self.cache + [{"group": "ARCADE", "items": game_items()}]

    def counts(self):
        items = [it for g in self.groups() for it in g["items"]]
        return sum(1 for it in items if it["done"]), len(items)
