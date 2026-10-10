"""Grouping of search / history rows into the labelled sections of the 3D world."""
import datetime as dt
import re

from . import scrape

MOVIE = re.compile(r"\bmovie\b|\bfilm\b|gekijouban|\(movie\)", re.I)
SPECIAL = re.compile(r"\b(ova|oad|ona|specials?|recap|mini anime|shorts?|picture drama|extras?|omake)\b", re.I)
SEQUEL = re.compile(r"\bseason\s*\d|\b\d+(st|nd|rd|th)\s+season|\bpart\s*\d|\bfinal season\b|\bcour\s*\d|\b(ii|iii|iv)\b$|\bs\d\b$", re.I)


def kind_of(row):
    """MAIN SERIES / SEQUELS / MOVIES / SPECIALS for one search row (miruro rows carry the site's own format)."""
    fmt = (scrape._mi_meta.get(row["id"].removeprefix(scrape.MI_PREFIX), {}) or {}).get("format", "") if row["id"].startswith(scrape.MI_PREFIX) else ""
    t = row["title"]
    if fmt == "MOVIE" or MOVIE.search(t):
        return "movie"
    if fmt in ("OVA", "ONA", "SPECIAL", "TV_SHORT", "MUSIC") or SPECIAL.search(t):
        return "special"
    if SEQUEL.search(t):
        return "sequel"
    return "main"


LABELS = [("main", "MAIN SERIES"), ("sequel", "SEASONS AND SEQUELS"), ("movie", "MOVIES"), ("special", "OVA / ONA / SPECIALS")]


def group_search(rows):
    buckets = {k: [] for k, _ in LABELS}
    for r in rows:
        buckets[kind_of(r)].append(r)
    return [(label, buckets[k]) for k, label in LABELS if buckets[k]]


def group_history(rows):
    """By how recently you watched: today / this week / this month / earlier (rows need a `last` timestamp)."""
    today = dt.date.today()
    buckets = [("TODAY", []), ("THIS WEEK", []), ("THIS MONTH", []), ("EARLIER", [])]
    for r in rows:
        try:
            age = (today - dt.date.fromisoformat(str(r.get("last") or "")[:10])).days
        except ValueError:
            age = 999
        buckets[0 if age <= 0 else 1 if age <= 7 else 2 if age <= 31 else 3][1].append(r)
    return [(label, rs) for label, rs in buckets if rs]
