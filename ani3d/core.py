"""Shared logic for ani-3d: scraping backend, watch db, posters, manga and related-content lookups (cross-platform)."""
import asyncio
import hashlib
import json
import os
import re
import time
import sqlite3
import urllib.parse

import httpx

from . import mangasrc, multisrc, paths, scrape

WATCH_DB = paths.watch_db()
SPEEDS = [0.75, 1.0, 1.25, 1.5, 2.0]
POSTER_DIR = os.path.join(paths.cache_dir(), "posters")
MANGA_API = "https://api.allanime.day/api"
MANGA_SITE = "https://allmanga.to"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0"
MANGA_QUERY = (
    "query($search:SearchInput,$limit:Int,$page:Int,$countryOrigin:VaildCountryOriginEnumType)"
    "{mangas(search:$search,limit:$limit,page:$page,countryOrigin:$countryOrigin)"
    "{edges{_id name englishName availableChapters}}}"
)


def fmt(sec):
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ---------- watch history (same sqlite db the ani script logs to) ----------
def db_connect():
    con = sqlite3.connect(WATCH_DB)
    con.execute(
        "CREATE TABLE IF NOT EXISTS history( id INTEGER PRIMARY KEY AUTOINCREMENT, anime_name TEXT, "
        "episode TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP )"
    )
    if "anime_id" not in [r[1] for r in con.execute("PRAGMA table_info(history)")]:
        con.execute("ALTER TABLE history ADD COLUMN anime_id TEXT")
    con.execute(
        "CREATE TABLE IF NOT EXISTS manga_read( manga_id TEXT, chapter TEXT, title TEXT, cover TEXT, "
        "ts DATETIME DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (manga_id, chapter) )"
    )
    if "title_jp" not in [r[1] for r in con.execute("PRAGMA table_info(manga_read)")]:
        con.execute("ALTER TABLE manga_read ADD COLUMN title_jp TEXT")
    con.execute(
        "CREATE TABLE IF NOT EXISTS shelf_override( kind TEXT, item_id TEXT, section TEXT, slot INTEGER, PRIMARY KEY (kind, item_id) )"
    )
    con.execute("CREATE TABLE IF NOT EXISTS manga_plan( manga_id TEXT PRIMARY KEY, title TEXT, cover TEXT, title_jp TEXT, "
                "ts DATETIME DEFAULT CURRENT_TIMESTAMP )")
    con.execute("CREATE TABLE IF NOT EXISTS shelf_hidden( kind TEXT, item_id TEXT, title TEXT, PRIMARY KEY (kind, item_id) )")
    if "title" not in [r[1] for r in con.execute("PRAGMA table_info(shelf_hidden)")]:
        con.execute("ALTER TABLE shelf_hidden ADD COLUMN title TEXT")
    if "purged" not in [r[1] for r in con.execute("PRAGMA table_info(shelf_hidden)")]:  # cleared from the REMOVED list for good
        con.execute("ALTER TABLE shelf_hidden ADD COLUMN purged INTEGER DEFAULT 0")
    con.execute("CREATE TABLE IF NOT EXISTS anime_total( anime_id TEXT PRIMARY KEY, total INTEGER )")
    con.execute(
        "CREATE TABLE IF NOT EXISTS resume( anime_id TEXT PRIMARY KEY, title TEXT, episode TEXT, position REAL DEFAULT 0, "
        "duration REAL DEFAULT 0, poster TEXT DEFAULT '', ts DATETIME DEFAULT CURRENT_TIMESTAMP )"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS advancement( key TEXT PRIMARY KEY, unlocked DATETIME DEFAULT CURRENT_TIMESTAMP )"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS watchlist( anime_id TEXT PRIMARY KEY, anime_name TEXT, poster TEXT, "
        "added DATETIME DEFAULT CURRENT_TIMESTAMP )"
    )
    return con


def wl_list():
    """The 'planning to watch' list (starred anime), newest first: [{id, title, poster, added}]."""
    try:
        with db_connect() as con:
            rows = con.execute("SELECT anime_id, anime_name, poster, added FROM watchlist ORDER BY added DESC, rowid DESC").fetchall()
        return [{"id": r[0], "title": r[1], "poster": r[2] or "", "added": r[3]} for r in rows]
    except sqlite3.Error:
        return []


def wl_add(anime_id, title, poster=""):
    try:
        with db_connect() as con:
            con.execute("INSERT OR REPLACE INTO watchlist (anime_id, anime_name, poster) VALUES (?,?,?)", (anime_id, title, poster))
    except sqlite3.Error:
        pass


def wl_remove(anime_id):
    try:
        with db_connect() as con:
            con.execute("DELETE FROM watchlist WHERE anime_id=?", (anime_id,))
    except sqlite3.Error:
        pass


def known_titles(limit=120):
    """Titles from your watch history and watch list (newest first): the local half of the search suggestions."""
    out = []
    try:
        with db_connect() as con:
            out += [r[0] for r in con.execute("SELECT anime_name FROM history GROUP BY anime_name ORDER BY MAX(timestamp) DESC LIMIT ?", (limit,))]
            out += [r[0] for r in con.execute("SELECT anime_name FROM watchlist ORDER BY added DESC LIMIT ?", (limit,))]
    except sqlite3.Error:
        pass
    return [t for t in dict.fromkeys(out) if t]


def total_set(anime_id, total):
    """Remember how many episodes an anime has (the completionist advancement needs it)."""
    if not anime_id or not total:
        return
    try:
        with db_connect() as con:
            con.execute("INSERT OR REPLACE INTO anime_total (anime_id, total) VALUES (?,?)", (anime_id, total))
    except sqlite3.Error:
        pass


def db_watched(anime_id, title):
    try:
        with db_connect() as con:
            rows = con.execute(
                "SELECT DISTINCT episode FROM history WHERE anime_id=? OR (anime_id IS NULL AND anime_name=?)",
                (anime_id, title),
            )
            return {r[0] for r in rows}
    except sqlite3.Error:
        return set()


def db_log(anime_id, title, ep):
    try:
        with db_connect() as con:
            con.execute("INSERT INTO history (anime_name, episode, anime_id) VALUES (?,?,?)", (title, ep, anime_id))
    except sqlite3.Error:
        pass


CACHE_DIR = paths.cache_dir()
_mem = {}  # key -> (expires, value)
_inflight = {}  # key -> asyncio.Task, so concurrent identical requests share one fetch


async def cached(key, ttl, fetch):
    """Memory + disk cache with a TTL. Concurrent callers for the same key share one fetch."""
    now = time.time()
    hit = _mem.get(key)
    if hit and hit[0] > now:
        return hit[1]
    path = os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest() + ".json")
    try:
        with open(path) as f:
            entry = json.load(f)
        if entry["expires"] > now:
            _mem[key] = (entry["expires"], entry["value"])
            return entry["value"]
    except (OSError, ValueError, KeyError):
        pass
    if key not in _inflight:
        async def run():
            try:
                value = await fetch()
                exp = time.time() + ttl
                _mem[key] = (exp, value)
                try:
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    with open(path, "w") as f:
                        json.dump({"expires": exp, "value": value}, f)
                except OSError:
                    pass
                return value
            finally:
                _inflight.pop(key, None)
        _inflight[key] = asyncio.ensure_future(run())
    return await asyncio.shield(_inflight[key])


def _scrape_sync(cmd, *args):
    """Search, episodes and links across hianime, miruro.to and AnimeHeaven (see multisrc.py): shows are merged, the site with
    the most episodes leads, and a stream that fails or is poor quality falls through to the next site.
    Returns the text the old `ani --api` shell mode printed."""
    if cmd == "search":
        rows = multisrc.search(args[0].replace("+", " "))
        return "\n".join(f"{i}\t{t}\t{p}" for i, t, p in rows)
    if cmd == "episodes":
        return "\n".join(multisrc.episodes(args[0], args[1] if len(args) > 1 else ""))
    if cmd == "link":
        aid, ep = args[0], args[1]
        mode = args[2] if len(args) > 2 else "sub"
        title = args[3] if len(args) > 3 else ""
        video, refr, sub, skip, source = multisrc.link(aid, ep, mode, title)
        return f"{video}\n{refr}\n{sub}\n{json.dumps(skip)}\n{source}\n"
    raise ValueError(f"unknown backend command: {cmd}")


async def _run_backend(*args):
    return await asyncio.to_thread(_scrape_sync, *args)


# search results change rarely, episode lists grow when new episodes air, stream links expire so are never cached
CACHE_TTL = {"search": 3600, "episodes": 600}


async def backend(*args):
    ttl = CACHE_TTL.get(args[0])
    if ttl:
        return await cached("ani:" + "\0".join(args), ttl, lambda: _run_backend(*args))
    return await _run_backend(*args)


# ---------- poster + manga lookup ----------
def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def base_title(title):
    """Strip season/part/format suffixes so the manga (which has no seasons) can be found."""
    t = re.sub(r"\((mini anime|tv|movie|ova|ona|special)[^)]*\)", "", title, flags=re.I)
    t = re.sub(r"\b(\d+(st|nd|rd|th)|final)\s+season\b", "", t, flags=re.I)
    t = re.sub(r"\bseason\s*\d+\b|\bpart\s*\d+\b|\bcour\s*\d+\b", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" :-") or title


async def fetch_poster(url):
    os.makedirs(POSTER_DIR, exist_ok=True)
    path = os.path.join(POSTER_DIR, hashlib.sha1(url.encode()).hexdigest() + ".jpg")
    if not os.path.exists(path):
        async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers={"User-Agent": UA}) as c:
            r = await c.get(url)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)
    return path


async def find_manga(title):
    """Search allmanga.to for the anime's manga. Returns [(id, name, chapters)], best match first (cached 1 day)."""
    found = await cached("manga:" + title, 86400, lambda: _find_manga(title))
    return [tuple(f) for f in found]


async def _find_manga(title):
    base = base_title(title)
    body = {
        "query": MANGA_QUERY,
        "variables": {"search": {"query": base}, "limit": 10, "page": 1, "countryOrigin": "ALL"},
    }
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA, "Referer": MANGA_SITE}) as c:
        r = await c.post(MANGA_API, json=body)
        r.raise_for_status()
    wanted = {norm(base), norm(title)}
    out = []
    for e in r.json()["data"]["mangas"]["edges"]:
        ch = e["availableChapters"] or {}
        n = max(ch.get("sub") or 0, ch.get("raw") or 0)
        if not n:
            continue
        names = [norm(e.get("englishName")), norm(e.get("name"))]
        score = 0 if any(x in wanted for x in names) else 1 if any(x.startswith(norm(base)) for x in names if x) else 2
        out.append((score, -n, e["_id"], e.get("englishName") or e["name"], n))
    out.sort()
    return [(i, name, n) for _, _, i, name, n in out[:6]]




# ---------- related content: light novels, games, fan sites ----------
BAD_GAME = re.compile(r"soundtrack|outfit|costume|dlc|season pass|bonus|wallpaper|artbook|demo\b|\bpack\b|skin|bundle|\bset\b|unlock|upgrade|add-on|bonus", re.I)
SKIP_DOMAINS = (
    "amazon.", "ebay.", "netflix.", "crunchyroll.", "youtube.", "youtu.be", "facebook.", "pinterest.",
    "imdb.", "myanimelist.", "anilist.", "kitsu.", "hianime", "aniwatch", "9anime", "gogoanime",
)


async def _get_json(c, url, **kw):
    r = await c.get(url, **kw)
    r.raise_for_status()
    return r.json()


async def _novels(c, title, base):
    out = []
    try:
        d = await _get_json(c, "https://kitsu.io/api/edge/manga", params={
            "filter[text]": base, "filter[subtype]": "novel", "page[limit]": 8})
        words = [w for w in norm(base).split() if len(w) > 2][:3]
        for e in d.get("data", []):
            a = e["attributes"]
            if words and not all(w in norm(json.dumps(a["titles"])) for w in words):
                continue
            name = a["titles"].get("en") or a["titles"].get("en_jp") or a["canonicalTitle"]
            out.append({"title": name, "url": f"https://kitsu.io/manga/{a['slug']}",
                        "note": f"Light novel · {a.get('volumeCount') or '?'} vol · Kitsu"})
    except Exception:
        pass
    try:  # AniList is often rate limited, so it's only a bonus
        q = "query($s:String){Page(perPage:8){media(search:$s,type:MANGA,format:NOVEL){title{romaji english} siteUrl volumes}}}"
        r = await c.post("https://graphql.anilist.co", json={"query": q, "variables": {"s": base}})
        for m in r.json()["data"]["Page"]["media"]:
            name = m["title"]["english"] or m["title"]["romaji"]
            out.append({"title": name, "url": m["siteUrl"], "note": f"Light novel · {m.get('volumes') or '?'} vol · AniList"})
    except Exception:
        pass
    seen, res = set(), []
    for n in out:
        k = norm(n["title"])
        if k not in seen:
            seen.add(k)
            res.append(n)
    return res[:8]


async def _games(c, title, base):
    words = [w for w in norm(base).split() if len(w) > 2][:3]
    out = []
    try:
        d = await _get_json(c, "https://store.steampowered.com/api/storesearch/", params={"term": base, "cc": "us", "l": "en"})
        for i in d.get("items", []):
            name = i["name"]
            if i.get("type") != "app" or BAD_GAME.search(name):
                continue
            if words and not all(w in norm(name) for w in words):
                continue
            price = i.get("price")
            note = f"${price['final'] / 100:.2f}" if price else "Free / n.a."
            out.append({"title": name, "url": f"https://store.steampowered.com/app/{i['id']}", "note": f"Steam · {note}"})
    except Exception:
        pass
    return out[:8]


async def _fandom(c, base):
    n = norm(base).split()
    slugs = {"".join(n), "-".join(n), "".join(w for w in n if w != "the")}
    out = []
    for slug in filter(None, slugs):
        try:
            r = await c.get(f"https://{slug}.fandom.com/api.php", params={"action": "query", "meta": "siteinfo", "format": "json"})
            if r.status_code == 200 and "sitename" in r.text:
                info = r.json()["query"]["general"]
                out.append({"title": info["sitename"], "url": info["base"].rsplit("/wiki/", 1)[0] + "/", "note": "Fan wiki · Fandom"})
        except Exception:
            pass
    return out


async def _wikipedia(c, base):
    try:
        d = await _get_json(c, "https://en.wikipedia.org/w/api.php", params={
            "action": "query", "list": "search", "srsearch": f"{base} anime", "srlimit": 3, "format": "json"})
        return [{"title": h["title"], "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(h["title"].replace(" ", "_")),
                 "note": "Wikipedia"} for h in d["query"]["search"]]
    except Exception:
        return []


async def _web(c, base):
    out = []
    for suffix, tag in (("anime fan site", "Fan site"), ("anime wiki forum community", "Community")):
        try:
            r = await c.get("https://html.duckduckgo.com/html/", params={"q": f"{base} {suffix}"})
            for href, name in re.findall(r'class="result__a" href="([^"]*)"[^>]*>(.*?)</a>', r.text, re.S):
                m = re.search(r"uddg=([^&]+)", href)
                url = urllib.parse.unquote(m.group(1)) if m else href
                if not url.startswith("http") or any(d in url for d in SKIP_DOMAINS):
                    continue
                out.append({"title": re.sub(r"<[^>]+>|&amp;|&#x27;", lambda x: "&" if x.group() == "&amp;" else "'" if x.group() != "" and x.group().startswith("&#") else "", name).strip(),
                            "url": url, "note": tag})
        except Exception:
            pass
    return out


async def related_content(title):
    """Light novels, games and fan websites for an anime. Each source fails soft. Returns {novels, games, sites}."""
    base = base_title(title)
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={"User-Agent": UA}) as c:
        novels, games, fandom, wiki, web = await asyncio.gather(
            _novels(c, title, base), _games(c, title, base), _fandom(c, base), _wikipedia(c, base), _web(c, base))
    sites, seen = [], set()
    for s in fandom + wiki + web:
        host = urllib.parse.urlparse(s["url"]).netloc.removeprefix("www.")
        if s["url"] not in seen and not (s["note"] in ("Fan site", "Community") and host in seen):
            seen.update({s["url"], host})
            sites.append(s)
    return {"novels": novels, "games": games, "sites": sites[:12]}


# ---------- manga (MangaDex public API: search, hosted chapters, page images) ----------
MD = "https://api.mangadex.org"
MD_HEADERS = {"User-Agent": "ani-3d/1.0 (personal anime library)"}
MD_RATING = ["safe", "suggestive"]
_md_gate = None


def _gate():
    """MangaDex allows ~5 requests a second; keep a few in flight at most."""
    global _md_gate
    if _md_gate is None:
        _md_gate = asyncio.Semaphore(4)
    return _md_gate


async def _md_get(path, params):
    async with _gate():
        async with httpx.AsyncClient(base_url=MD, headers=MD_HEADERS, timeout=25) as c:
            r = await c.get(path, params=params)
            r.raise_for_status()
            return r.json()


def _md_titles(a):
    """(english, japanese) title of a MangaDex attributes block. 'Japanese' is the romaji form, which the bundled font can draw."""
    t = a.get("title") or {}
    alts = {}
    for d in a.get("altTitles") or []:
        for lang, name in d.items():
            alts.setdefault(lang, name)
    en = t.get("en") or alts.get("en") or next(iter(t.values()), "?")
    jp = t.get("ja-ro") or alts.get("ja-ro") or alts.get("ja") or en
    if jp and not jp.isascii():  # kanji / kana: the bundled mono font has no glyphs for them
        jp = alts.get("ja-ro") or t.get("ja-ro") or en
    return en, jp


def _md_item(m):
    a = m["attributes"]
    en, jp = _md_titles(a)
    cover = next((x["attributes"]["fileName"] for x in m.get("relationships", []) if x["type"] == "cover_art" and "attributes" in x), None)
    return {"id": m["id"], "title": en, "title_en": en, "title_jp": jp,
            "cover": f"https://uploads.mangadex.org/covers/{m['id']}/{cover}.512.jpg" if cover else ""}


async def md_search(query, n=30):
    """Librarian search: manga matching a title that have hosted English chapters (cached 30 minutes)."""
    async def fetch():
        d = await _md_get("/manga", {"title": query, "limit": n, "hasAvailableChapters": "true", "availableTranslatedLanguage[]": "en",
                                      "contentRating[]": MD_RATING, "includes[]": "cover_art", "order[relevance]": "desc"})
        items = [_md_item(m) for m in d["data"]]
        want = norm(query)

        def rank(it):
            names = [norm(it["title_en"]), norm(it["title_jp"])]
            return (0 if want in names else 1 if any(x.startswith(want) for x in names) else 2, 1 if "doujinshi" in it["title_en"].lower() else 0)
        return sorted(items, key=rank)  # stable: relevance order is kept inside a rank
    return await cached("md:search:" + norm(query), 1800, fetch)


async def md_alt_titles(ids):
    """{manga id: (english, japanese)} for ids whose other-language title we don't have yet."""
    out = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 50):
        d = await _md_get("/manga", {"ids[]": ids[i:i + 50], "limit": 50, "contentRating[]": MD_RATING + ["erotica", "pornographic"]})
        for m in d["data"]:
            out[m["id"]] = _md_titles(m["attributes"])
    return out


def mangafire_url(title):
    """MangaFire search page for a title: the fallback when the hosted sources have nothing to read."""
    return "https://mangafire.to/filter?keyword=" + urllib.parse.quote_plus(base_title(title))


async def md_chapters(manga_id):
    """Hosted English chapters (no external links), ascending: [{id, chapter, pages}]. Cached for 30 minutes."""
    async def fetch():
        out, offset = [], 0
        while offset < 1500:
            d = await _md_get(f"/manga/{manga_id}/feed", {"translatedLanguage[]": "en", "includeExternalUrl": 0, "limit": 500, "offset": offset,
                                                          "order[chapter]": "asc", "contentRating[]": MD_RATING})
            for ch in d["data"]:
                at = ch["attributes"]
                if at.get("pages", 0) > 0 and not at.get("externalUrl") and at.get("chapter"):
                    out.append({"id": ch["id"], "chapter": at["chapter"], "pages": at["pages"]})
            offset += 500
            if offset >= d.get("total", 0):
                break
        seen, uniq = set(), []
        for c in out:  # several scanlation groups can host the same chapter: keep the first
            if c["chapter"] not in seen:
                seen.add(c["chapter"])
                uniq.append(c)

        def num(c):
            try:
                return float(c["chapter"])
            except ValueError:
                return 1e9
        return sorted(uniq, key=num)
    return await cached("md:chapters:" + manga_id, 1800, fetch)


async def md_probe(manga_id):
    """Cheap one-request check of how many hosted English chapters a manga has (cached 1 hour)."""
    async def fetch():
        d = await _md_get(f"/manga/{manga_id}/feed", {"translatedLanguage[]": "en", "includeExternalUrl": 0, "limit": 1, "contentRating[]": MD_RATING})
        return d.get("total", 0)
    return await cached("md:probe:" + manga_id, 3600, fetch)


async def md_popular(n=18):
    """Popular manga that actually have hosted chapters: [{id, title, cover}]."""
    async def fetch():
        d = await _md_get("/manga", {"limit": n + 12, "order[followedCount]": "desc", "hasAvailableChapters": "true", "availableTranslatedLanguage[]": "en",
                                      "contentRating[]": MD_RATING, "includes[]": "cover_art"})
        return [_md_item(m) for m in d["data"]]
    return await cached(f"md:popular:{n}", 3600, fetch)


async def md_for_title(title):
    """Best hosted manga match for an anime title, or None."""
    base = base_title(title)

    async def fetch():
        d = await _md_get("/manga", {"title": base, "limit": 6, "hasAvailableChapters": "true", "availableTranslatedLanguage[]": "en",
                                      "contentRating[]": MD_RATING, "includes[]": "cover_art", "order[relevance]": "desc"})
        items = [_md_item(m) for m in d["data"]]
        want = norm(base)
        for it in items:
            if norm(it["title"]) == want or norm(it["title"]).startswith(want):
                return it
        return None
    return await cached("md:title:" + base, 86400, fetch)


async def md_pages(chapter_id):
    """Page image URLs of a chapter (data-saver quality keeps them quick to load). Cached for 10 minutes."""
    async def fetch():
        d = await _md_get(f"/at-home/server/{chapter_id}", {})
        ch = d["chapter"]
        return [f"{d['baseUrl']}/data-saver/{ch['hash']}/{f}" for f in ch["dataSaver"]]
    return await cached("md:pages:" + chapter_id, 600, fetch)


async def fetch_manga_image(url):
    """Download one manga page (disk cached) and return its path."""
    path = os.path.join(CACHE_DIR, "manga", hashlib.sha1(url.encode()).hexdigest() + ".img")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ref = mangasrc.referer(url)
        async with _gate():
            async with httpx.AsyncClient(headers={**MD_HEADERS, **({"Referer": ref, "User-Agent": mangasrc.UA} if ref else {})}, timeout=30, follow_redirects=True) as c:
                r = await c.get(url)
                r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
    return path


# ---------- fuller sources: MangaPill / MangaKatana when MangaDex only hosts part of a series ----------
def _same_title(a, b):
    a, b = norm(base_title(a)), norm(base_title(b))
    return bool(a) and (a == b or (min(len(a), len(b)) >= 6 and (a in b or b in a) and min(len(a), len(b)) / max(len(a), len(b)) >= 0.75))


async def _extra_chapters(book_id):
    return await cached("xch:" + book_id, 1800, lambda: asyncio.to_thread(mangasrc.chapters, book_id))


async def _extra_search(query):
    return await cached("xs2:" + norm(query), 3600, lambda: asyncio.to_thread(mangasrc.search, query))


async def full_chapters(book):
    """(chapters, source label) for a book: MangaDex's list, or - when another site has clearly more of the series - that
    site's list. Each chapter carries `src` so pages are fetched from the right place."""
    src = book.get("src") or "md"
    if src != "md":
        return await _extra_chapters(book["id"]), mangasrc.LABELS[src]
    md = [dict(c, src="md") for c in await md_chapters(book["id"])]
    try:
        title = book.get("title_en") or book["title"]
        best = (0, None)
        cands = [it for it in await _extra_search(title) if _same_title(title, it["title"])][:5]
        for it in cands:
            if True:
                try:
                    chs = await _extra_chapters(it["id"])
                except Exception:  # noqa: BLE001
                    continue
                if len(chs) > best[0]:
                    best = (len(chs), (it, chs))
        if best[1] and best[0] > len(md) * 1.25 and best[0] >= len(md) + 3:
            it, chs = best[1]
            book["src"], book["alt_id"] = it["src"], it["id"]
            return chs, mangasrc.LABELS[it["src"]]
    except Exception:  # noqa: BLE001
        pass
    return md, "MangaDex"


async def probe_any(book_id):
    """Chapter count for a MangaDex id or an extra-source id (mp:/mk:)."""
    if ":" in book_id:
        return len(await _extra_chapters(book_id))
    return await md_probe(book_id)


async def chapter_pages(ch):
    if ch.get("src", "md") == "md":
        return await md_pages(ch["id"])
    return await cached("xpg:" + ch["id"], 600, lambda: asyncio.to_thread(mangasrc.pages, ch))


async def search_all(query, n=24):
    """Librarian search across MangaDex and the extra sites. Returns [{id, title, title_en, title_jp, cover, total, src}],
    one entry per series, preferring whichever source has the most chapters."""
    md_items = await md_search(query, n)
    probes = await asyncio.gather(*(md_probe(i["id"]) for i in md_items[:20]), return_exceptions=True)
    found = {}  # normalised title -> entry

    def offer(it, total):
        key = norm(base_title(it["title"]))
        cur = found.get(key)
        if total and (cur is None or total > cur["total"] * 1.25 + 2):
            found[key] = dict(it, total=total)
    for it, t in zip(md_items, probes):
        if not isinstance(t, Exception) and t:
            offer(dict(it, src="md"), t)
    extra = await _extra_search(query)
    want = norm(query)
    # the extra sites list loosely related series too: keep the close matches and count their chapters
    close = [it for it in extra if want in norm(it["title"]) or _same_title(query, it["title"])][:14]
    counts = await asyncio.gather(*(_extra_chapters(it["id"]) for it in close), return_exceptions=True)
    for it, chs in zip(close, counts):
        if not isinstance(chs, Exception) and chs:
            offer({"id": it["id"], "title": it["title"], "title_en": it["title"], "title_jp": it["title"], "cover": it["cover"], "src": it["src"]}, len(chs))
    return list(found.values())


def mr_add(manga_id, title, cover, chapter, title_jp=""):
    try:
        with db_connect() as con:
            con.execute("INSERT OR REPLACE INTO manga_read (manga_id, chapter, title, cover, title_jp) VALUES (?,?,?,?,?)",
                        (manga_id, chapter, title, cover, title_jp or ""))
            con.execute("DELETE FROM shelf_hidden WHERE kind='manga' AND item_id=? AND COALESCE(purged, 0)=1", (manga_id,))
            con.execute("DELETE FROM manga_plan WHERE manga_id=?", (manga_id,))  # started it: no longer just "going to read"
    except sqlite3.Error:
        pass


def mr_list():
    """Reading history grouped by manga, newest first: [{id, title, cover, chapters, last}]."""
    try:
        with db_connect() as con:
            rows = con.execute("SELECT manga_id, title, cover, group_concat(chapter, char(31)), max(ts), max(title_jp) FROM manga_read GROUP BY manga_id ORDER BY max(ts) DESC").fetchall()
        return [{"id": r[0], "title": r[1], "cover": r[2] or "", "chapters": (r[3] or "").split("\x1f"), "last": r[4], "title_jp": r[5] or ""} for r in rows]
    except sqlite3.Error:
        return []


# ---------- manga you plan to read (the GOING TO READ shelf) ----------
def mp_list():
    """[{id, title, cover, title_jp}] newest first."""
    try:
        with db_connect() as con:
            return [{"id": r[0], "title": r[1], "cover": r[2] or "", "title_jp": r[3] or ""}
                    for r in con.execute("SELECT manga_id, title, cover, title_jp FROM manga_plan ORDER BY ts DESC")]
    except sqlite3.Error:
        return []


def mp_set(manga_id, on, title="", cover="", title_jp=""):
    try:
        with db_connect() as con:
            if on:
                con.execute("INSERT OR REPLACE INTO manga_plan (manga_id, title, cover, title_jp) VALUES (?,?,?,?)", (manga_id, title, cover, title_jp or ""))
            else:
                con.execute("DELETE FROM manga_plan WHERE manga_id=?", (manga_id,))
    except sqlite3.Error:
        pass


# ---------- library shelf placement (books you dragged to another shelf) ----------
def shelf_overrides(kind):
    """{item id: (section, slot)}"""
    try:
        with db_connect() as con:
            return {r[0]: (r[1], r[2]) for r in con.execute("SELECT item_id, section, slot FROM shelf_override WHERE kind=?", (kind,))}
    except sqlite3.Error:
        return {}


def shelf_set(kind, item_id, section, slot):
    try:
        with db_connect() as con:
            con.execute("INSERT OR REPLACE INTO shelf_override (kind, item_id, section, slot) VALUES (?,?,?,?)", (kind, item_id, section, slot))
    except sqlite3.Error:
        pass


def hidden_ids(kind):
    """Books the user removed from the shelf."""
    try:
        with db_connect() as con:
            return {r[0] for r in con.execute("SELECT item_id FROM shelf_hidden WHERE kind=?", (kind,))}
    except sqlite3.Error:
        return set()


def hidden_list(kind):
    """[(id, title)] of removed books, most recently removed first."""
    try:
        with db_connect() as con:
            return [(r[0], r[1] or "(removed manga)") for r in con.execute(
                "SELECT item_id, title FROM shelf_hidden WHERE kind=? AND COALESCE(purged, 0)=0 ORDER BY rowid DESC", (kind,))]
    except sqlite3.Error:
        return []


def shelf_hide(kind, item_id, hide=True, title=""):
    try:
        with db_connect() as con:
            if hide:
                con.execute("INSERT OR REPLACE INTO shelf_hidden (kind, item_id, title, purged) VALUES (?,?,?,0)", (kind, item_id, title))
            else:
                con.execute("DELETE FROM shelf_hidden WHERE kind=? AND item_id=?", (kind, item_id))
    except sqlite3.Error:
        pass


def shelf_unhide_all(kind):
    """RESTORE ALL: everything still listed in the REMOVED drawer goes back (cleared books stay gone)."""
    try:
        with db_connect() as con:
            con.execute("DELETE FROM shelf_hidden WHERE kind=? AND COALESCE(purged, 0)=0", (kind,))
    except sqlite3.Error:
        pass


def shelf_unpurge(kind, ids):
    """A cleared book you look up or read again is allowed back on the shelf."""
    try:
        with db_connect() as con:
            con.executemany("DELETE FROM shelf_hidden WHERE kind=? AND item_id=? AND COALESCE(purged, 0)=1", [(kind, i) for i in ids])
    except sqlite3.Error:
        pass


def shelf_purge_removed(kind):
    """CLEAR LIST: forget every book in the REMOVED drawer for good - it stays off the shelf, leaves the list, and its
    reading progress and shelf placement are deleted. Returns how many were cleared."""
    try:
        with db_connect() as con:
            ids = [r[0] for r in con.execute("SELECT item_id FROM shelf_hidden WHERE kind=? AND COALESCE(purged, 0)=0", (kind,))]
            for iid in ids:
                if kind == "manga":
                    con.execute("DELETE FROM manga_read WHERE manga_id=?", (iid,))
                con.execute("DELETE FROM shelf_override WHERE kind=? AND item_id=?", (kind, iid))
            con.execute("UPDATE shelf_hidden SET purged=1 WHERE kind=?", (kind,))
            return len(ids)
    except sqlite3.Error:
        return 0


def shelf_clear(kind, item_id):
    try:
        with db_connect() as con:
            con.execute("DELETE FROM shelf_override WHERE kind=? AND item_id=?", (kind, item_id))
    except sqlite3.Error:
        pass


# ---------- fan edits (AMVs) ----------
async def fan_edits(title, n=10):
    """Fan edits / AMVs for an anime, scraped from YouTube search results: [{title, channel, length, url}] (cached 6 hours)."""
    base = base_title(title)

    async def fetch():
        out, seen = [], set()
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}) as c:
            for suffix in ("AMV", "fan edit"):
                try:
                    r = await c.get("https://www.youtube.com/results", params={"search_query": f"{base} {suffix}", "sp": "EgIQAQ%3D%3D"})
                    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});</script>", r.text, re.S)
                    if not m:
                        continue
                    data = json.loads(m.group(1))
                except Exception:  # noqa: BLE001
                    continue

                def walk(o):
                    if isinstance(o, dict):
                        if "videoRenderer" in o:
                            yield o["videoRenderer"]
                        for v in o.values():
                            yield from walk(v)
                    elif isinstance(o, list):
                        for v in o:
                            yield from walk(v)
                for v in walk(data):
                    vid = v.get("videoId")
                    if not vid or vid in seen:
                        continue
                    seen.add(vid)
                    t = "".join(x.get("text", "") for x in v.get("title", {}).get("runs", []))
                    t = re.sub(r"\s+", " ", re.sub(r"[^\x20-\x7e\u00a0-\u024f]+", " ", t)).strip()  # the bundled font has no CJK glyphs
                    ch = "".join(x.get("text", "") for x in (v.get("ownerText") or {}).get("runs", []))
                    ln = (v.get("lengthText") or {}).get("simpleText", "")
                    out.append({"title": t, "channel": ch, "length": ln, "url": f"https://www.youtube.com/watch?v={vid}"})
        return out[:n]
    return await cached("edits:" + norm(base), 21600, fetch)


# ---------- home: continue watching, recommendations, popular ----------
def resume_save(anime_id, title, ep, pos, dur, poster=""):
    """Remember where an episode was left off (the HOME screen's CONTINUE WATCHING row)."""
    if not anime_id:
        return
    try:
        with db_connect() as con:
            old = con.execute("SELECT poster FROM resume WHERE anime_id=?", (anime_id,)).fetchone()
            con.execute("INSERT OR REPLACE INTO resume (anime_id, title, episode, position, duration, poster) VALUES (?,?,?,?,?,?)",
                        (anime_id, title, ep, float(pos or 0), float(dur or 0), poster or (old[0] if old else "")))
    except sqlite3.Error:
        pass


def resume_advance(anime_id, title, next_ep):
    """An episode was finished: continue with the next one from the start, or drop the show when there is none."""
    try:
        with db_connect() as con:
            if next_ep:
                con.execute("UPDATE resume SET episode=?, position=0, duration=0, ts=CURRENT_TIMESTAMP WHERE anime_id=?", (next_ep, anime_id))
                if not con.total_changes:
                    con.execute("INSERT INTO resume (anime_id, title, episode) VALUES (?,?,?)", (anime_id, title, next_ep))
            else:
                con.execute("DELETE FROM resume WHERE anime_id=?", (anime_id,))
                con.execute("INSERT OR REPLACE INTO resume (anime_id, title, episode, position, duration) VALUES (?,?,'done',0,0)", (anime_id, title))
    except sqlite3.Error:
        pass


def continue_list(limit=12):
    """Shows you are partway through, newest first: [{id, title, poster, ep, pos, dur}]. Shows watched before resume points
    were recorded are included from the history (resuming their last episode from the start)."""
    out, seen = [], set()
    try:
        with db_connect() as con:
            for aid, title, ep, pos, dur, poster in con.execute(
                    "SELECT anime_id, title, episode, position, duration, poster FROM resume ORDER BY ts DESC LIMIT 40"):
                seen.add(aid)
                if ep != "done":
                    out.append({"id": aid, "title": title, "poster": poster or "", "ep": ep, "pos": pos or 0, "dur": dur or 0})
            done = {r[0] for r in con.execute("SELECT anime_id FROM resume WHERE episode='done'")}
            totals = dict(con.execute("SELECT anime_id, total FROM anime_total"))
            for aid, title, ep, n in con.execute(
                    "SELECT h.anime_id, h.anime_name, h.episode, (SELECT COUNT(DISTINCT episode) FROM history WHERE anime_id=h.anime_id) "
                    "FROM history h WHERE h.anime_id IS NOT NULL AND h.anime_id != '' AND h.id = "
                    "(SELECT id FROM history WHERE anime_id=h.anime_id ORDER BY timestamp DESC, id DESC LIMIT 1) "
                    "ORDER BY h.timestamp DESC LIMIT 40"):
                if aid in seen or aid in done or (totals.get(aid) and n >= totals[aid]):
                    continue
                seen.add(aid)
                out.append({"id": aid, "title": title, "poster": "", "ep": ep, "pos": 0, "dur": 0})
    except sqlite3.Error:
        pass
    return out[:limit]


ANILIST = "https://graphql.anilist.co"
_AL_FIELDS = "id title{romaji english} coverImage{large} format averageScore"


def _al_title(t):
    return (t.get("english") or t.get("romaji") or "").strip()


async def _anilist(query, variables=None):
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "ani-3d"}) as c:
        r = await c.post(ANILIST, json={"query": query, "variables": variables or {}})
        r.raise_for_status()
        return r.json()["data"]


async def anilist_top(n=24):
    """Highest rated shows with enough votes: [{title, poster}]."""
    async def fetch():
        d = await _anilist("query($n:Int){Page(perPage:$n){media(type:ANIME,sort:SCORE_DESC,format_in:[TV,MOVIE],popularity_greater:50000){%s}}}" % _AL_FIELDS, {"n": n})
        return [{"title": _al_title(m["title"]), "poster": m["coverImage"]["large"]} for m in d["Page"]["media"] if _al_title(m["title"])]
    return await cached(f"al:top:{n}", 6 * 3600, fetch)


async def recommended(seed_titles, exclude, n=18):
    """AniList's 'if you liked X' lists for the titles you watched, merged: [{title, poster}], best-supported first."""
    seeds = [t for t in dict.fromkeys(seed_titles)][:6]
    if not seeds:
        return []

    async def one(t):
        async def fetch():
            d = await _anilist("query($s:String){Media(search:$s,type:ANIME){recommendations(perPage:10,sort:RATING_DESC){nodes{rating mediaRecommendation{%s}}}}}" % _AL_FIELDS, {"s": t})
            return [{"title": _al_title(x["mediaRecommendation"]["title"]), "poster": x["mediaRecommendation"]["coverImage"]["large"],
                     "w": x.get("rating") or 0, "fmt": x["mediaRecommendation"].get("format")}
                    for x in ((d.get("Media") or {}).get("recommendations") or {}).get("nodes", []) if x.get("mediaRecommendation")]
        return await cached("al:rec:" + norm(t), 12 * 3600, fetch)
    got = await asyncio.gather(*(one(t) for t in seeds), return_exceptions=True)
    skip = {multisrc.akey(t) for t in list(exclude) + seeds} | {multisrc.akey(base_title(t)) for t in list(exclude) + seeds}
    score = {}
    for g in got:
        if isinstance(g, Exception):
            continue
        for rank, it in enumerate(g):
            k = multisrc.akey(it["title"])
            if not k or k in skip or it["fmt"] not in ("TV", "MOVIE", "ONA", None):
                continue
            cur = score.setdefault(k, {"title": it["title"], "poster": it["poster"], "s": 0.0})
            cur["s"] += 10 - rank + min(it["w"], 50) / 10
    return [{"title": v["title"], "poster": v["poster"]} for v in sorted(score.values(), key=lambda v: -v["s"])][:n]


def _clean_desc(s, cap=420):
    """Plain text from an AniList / MAL / MangaDex synopsis: no HTML, markdown, source credits or line breaks."""
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # markdown links
    s = re.sub(r"[*_~]{1,3}", "", s)
    s = re.sub(r"\(\s*source[^)]*\)|\[\s*written by[^\]]*\]|source:.*$", "", s, flags=re.I)
    s = s.replace("&quot;", '"').replace("&amp;", "&").replace("&#039;", "'").replace("&mdash;", "-").replace("&ndash;", "-")
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "—": "-", "–": "-", "…": "..."}))
    s = re.sub(r"[^\x00-\u024F\u2010-\u2027]", "", s)  # the bundled mono font has no CJK / symbol glyphs
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > cap:
        s = s[:cap].rsplit(" ", 1)[0].rstrip(",;:-") + "..."
    return s


_MAIN_FORMATS = {"TV", "MOVIE", "ONA", "OVA", "MANGA", "ONE_SHOT", "NOVEL"}


async def _blurb_anilist(t, kind):
    """Best AniList match: an exact title (any language / synonym), else the most popular main entry, not a chibi short or recap."""
    d = await _anilist("query($s:String,$k:MediaType){Page(perPage:8){media(search:$s,type:$k,sort:SEARCH_MATCH){title{romaji english} synonyms "
                       "description(asHtml:false) genres averageScore popularity seasonYear startDate{year} status episodes chapters format "
                       "coverImage{large}}}}", {"s": t, "k": kind.upper()})
    ms = [m for m in d["Page"]["media"] if m.get("description")]
    if not ms:
        return None
    want = norm(t)
    names = lambda m: {norm(m["title"].get("english")), norm(m["title"].get("romaji"))} | {norm(x) for x in m.get("synonyms") or []}  # noqa: E731
    m = next((m for m in ms if want in names(m)), None)
    if m is None:
        main = [m for m in ms[:5] if m.get("format") == "MOVIE" or (m.get("format") in _MAIN_FORMATS and (m.get("episodes") or 0) != 1)] or ms[:1]
        m = max(main, key=lambda m: m.get("popularity") or 0)
    return {"title": _al_title(m["title"]), "desc": _clean_desc(m["description"]), "genres": (m.get("genres") or [])[:4],
            "score": m.get("averageScore"), "year": m.get("seasonYear") or (m.get("startDate") or {}).get("year"),
            "status": (m.get("status") or "").replace("_", " ").title(), "count": m.get("episodes") if kind == "anime" else m.get("chapters"),
            "format": (m.get("format") or "").replace("_", " "), "cover": (m.get("coverImage") or {}).get("large", ""), "src": "AniList"}


async def _blurb_jikan(t, kind):
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "ani-3d"}) as c:
        r = await c.get(f"https://api.jikan.moe/v4/{kind}", params={"q": t, "limit": 1, "sfw": "true"})
        r.raise_for_status()
        rows = r.json().get("data") or []
    if not rows or not rows[0].get("synopsis"):
        return None
    m = rows[0]
    year = m.get("year") or ((m.get("aired") or m.get("published") or {}).get("prop", {}).get("from", {}) or {}).get("year")
    return {"title": m.get("title_english") or m.get("title") or t, "desc": _clean_desc(m["synopsis"]),
            "genres": [g["name"] for g in (m.get("genres") or [])][:4], "score": int(m["score"] * 10) if m.get("score") else None,
            "year": year, "status": m.get("status") or "", "count": m.get("episodes") if kind == "anime" else m.get("chapters"),
            "format": m.get("type") or "", "cover": ((m.get("images") or {}).get("jpg") or {}).get("large_image_url", ""), "src": "MyAnimeList"}


async def _blurb_mangadex(t):
    d = await _md_get("/manga", {"title": t, "limit": 1, "contentRating[]": MD_RATING, "includes[]": "cover_art", "order[relevance]": "desc"})
    if not d.get("data"):
        return None
    m = d["data"][0]
    a = m["attributes"]
    desc = (a.get("description") or {}).get("en") or ""
    if not desc:
        return None
    tags = [x["attributes"]["name"].get("en") for x in a.get("tags") or [] if x.get("attributes", {}).get("group") == "genre"]
    return {"title": _md_titles(a)[0], "desc": _clean_desc(desc), "genres": [g for g in tags if g][:4], "score": None, "year": a.get("year"),
            "status": (a.get("status") or "").title(), "count": None, "format": "Manga", "cover": _md_item(m)["cover"], "src": "MangaDex"}


async def media_blurb(title, kind="anime"):
    """What the hover card shows for an anime or manga: {title, desc, genres, score, year, status, count, format, cover, src}, or None.
    AniList first (it is often rate limited), then MyAnimeList via Jikan, then MangaDex for manga."""
    t = re.sub(r"\s+", " ", title).strip()
    base = base_title(t)

    async def fetch():
        tries = [lambda: _blurb_anilist(t, kind)] + ([lambda: _blurb_anilist(base, kind)] if base != t else []) + [lambda: _blurb_jikan(base, kind)]
        tries += [lambda: _blurb_mangadex(base)] if kind == "manga" else []
        err = None
        for go in tries:
            try:
                got = await go()
                if got:
                    return got
            except Exception as e:  # noqa: BLE001 - one source down is fine, try the next
                err = e
        if err:
            raise err  # nothing found AND something failed: don't cache, retry next hover
        return None
    return await cached(f"blurb2:{kind}:{norm(t)}", 3 * 86400, fetch)


async def home_data():
    """Everything the HOME screen shows: {continue, recommended, popular, airing} (lists of {id|None, title, poster, ...})."""
    cont = continue_list()
    pop_f = cached("home:pop", 1800, lambda: asyncio.to_thread(lambda: scrape.listing("most-popular")))
    air_f = cached("home:air", 1800, lambda: asyncio.to_thread(lambda: scrape.listing("top-airing")))
    watched_titles = [c["title"] for c in cont]
    with db_connect() as con:
        recent = [r[0] for r in con.execute("SELECT anime_name FROM history GROUP BY anime_name ORDER BY max(timestamp) DESC LIMIT 8")]
    seeds = list(dict.fromkeys(watched_titles + recent))
    rec_f = recommended(seeds, seeds) if seeds else anilist_top(18)
    pop, air, rec = await asyncio.gather(pop_f, air_f, rec_f, return_exceptions=True)
    ok = lambda v: [] if isinstance(v, Exception) else v  # noqa: E731
    return {
        "continue": cont,
        "recommended": [{"id": None, "title": x["title"], "poster": x["poster"]} for x in ok(rec)][:12],
        "popular": [{"id": i, "title": t, "poster": p} for i, t, p in ok(pop)][:18],
        "airing": [{"id": i, "title": t, "poster": p} for i, t, p in ok(air)][:12],
        "personal": bool(seeds),
    }
