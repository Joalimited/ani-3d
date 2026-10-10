"""Anime search/episodes/link across several sites, the same idea as the manga librarian: hianime is the first choice, but
miruro.to and AnimeHeaven are merged in, so a show that one site hosts only partly (or in poor quality) still plays.

* search   - every site is queried; entries that are the same show are merged, the site with the most episodes becomes the
             row's id and the others are remembered as its alternates (ALTS).
* episodes - the primary's list plus any episode numbers only an alternate has.
* link     - the primary is tried first; when it fails, or only has a stream under GOOD_HEIGHT, the alternates are tried and
             the best stream wins (a bad-quality stream is still returned when nothing better exists)."""
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

from . import scrape

AH = "https://animeheaven.me"
AH_PREFIX = "ah:"
GOOD_HEIGHT = 720          # below this a stream counts as bad quality and the alternates get a chance
LABELS = {"": "HiAnime", "mi": "Miruro", "ah": "AnimeHeaven"}
PREFERENCE = {"": 0, "ah": 1, "mi": 2}  # tie-break order when sites have the same number of episodes
ALTS = {}       # primary id -> [alternate ids]
COUNTS = {}     # id -> episode count (as far as it is known)
SOURCE = {}     # (anime id, episode) -> label of the site the last stream came from (for the UI)
_ah_eps = {}    # ah id -> {episode number: gate key}
_ah_title = {}  # ah id -> title


def src_of(anime_id):
    return anime_id.split(":", 1)[0] if ":" in anime_id else ""


def label(anime_id):
    return LABELS.get(src_of(anime_id), "?")


# ---------- AnimeHeaven (direct mp4 files, 1080p SubsPlease rips) ----------
def ah_search(query):
    """[(ah:<id>, title, poster)]."""
    r = scrape.client().get(f"{AH}/search.php", params={"s": query})
    if r.status_code >= 400:
        raise RuntimeError(f"AnimeHeaven HTTP {r.status_code}")
    out = []
    for m in re.finditer(r"<img class='coverimg' src='([^']*)' alt='[^']*'[^>]*></a><div class='similarname c'><a href='anime\.php\?([a-z0-9]+)' class='c'>([^<]*)<", r.text):
        title = scrape.htmllib.unescape(m.group(3)).strip()
        _ah_title[m.group(2)] = title
        out.append((AH_PREFIX + m.group(2), title, urljoin(AH + "/", m.group(1))))
    return out


def _ah_load(raw):
    if raw not in _ah_eps:
        r = scrape.client().get(f"{AH}/anime.php", params={raw: ""}, headers={"Referer": AH + "/"})
        if r.status_code >= 400:
            raise RuntimeError(f"AnimeHeaven HTTP {r.status_code}")
        eps = {}
        for key, num in re.findall(r"""gatea\(\s*"([0-9a-f]{32})"\s*\).*?watch2 bc '\s*>\s*([0-9.]+)\s*<""", r.text, re.S):
            eps.setdefault(num, key)
        _ah_eps[raw] = eps
    return _ah_eps[raw]


def ah_episodes(anime_id):
    eps = _ah_load(anime_id[len(AH_PREFIX):])
    return sorted(eps, key=float)


def ah_link(anime_id, ep):
    """(url, referer, subtitle, height). The mp4 is probed with a one-byte-range request, which also gives its quality: the
    file name that comes back in Content-Disposition carries it ("... (1080p) [CRC].mkv.mp4")."""
    key = _ah_load(anime_id[len(AH_PREFIX):]).get(ep)
    if not key:
        raise RuntimeError(f"AnimeHeaven has no episode {ep}")
    r = scrape.client().get(f"{AH}/gate.php", headers={"Referer": f"{AH}/anime.php?{anime_id[len(AH_PREFIX):]}", "Cookie": f"key={key}"})
    srcs = re.findall(r"<source src='(https://[^']+?video\.mp4\?[^'&]+&[^'&]+)'", r.text)
    if not srcs:
        raise RuntimeError("AnimeHeaven gave no stream")
    for url in srcs:  # the three mirrors carry the same file
        try:
            with scrape.client().stream("GET", url, headers={"Referer": AH + "/", "Range": "bytes=0-1023"}, timeout=10) as pr:
                if pr.status_code not in (200, 206):
                    continue
                pr.read()
                m = re.search(r"\((\d{3,4})p\)", pr.headers.get("content-disposition", ""))
                return url, AH + "/", "", int(m.group(1)) if m else 0
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("AnimeHeaven stream is not reachable")


# ---------- matching ----------
def akey(title):
    """Normalised identity of a show/season: strips format tags and punctuation but keeps season and part numbers."""
    t = scrape.htmllib.unescape(title or "").lower()
    t = re.sub(r"\((tv|dub|sub|subbed|dubbed|english dub|uncensored)[^)]*\)", " ", t)
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\s+season\b", r" s\1 ", t)
    t = re.sub(r"\bseason\s*(\d+)\b", r" s\1 ", t)
    t = re.sub(r"\bpart\s*(\d+)\b", r" p\1 ", t)
    t = re.sub(r"\bthe\b", " ", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def same_show(a, b):
    a, b = akey(a), akey(b)
    return bool(a) and a == b


def canon(n):
    """Episode numbers compared across sites: '01' == '1' == '1.0'."""
    try:
        f = float(n)
        return str(int(f)) if f == int(f) else str(f)
    except ValueError:
        return n


def _is_dub(title):
    return bool(re.search(r"\(dub|\bdub(bed)?\)?$", (title or "").lower()))


# ---------- search ----------
def _count(anime_id):
    """Episode count of any id (cached); 0 when unknown."""
    if anime_id not in COUNTS:
        try:
            COUNTS[anime_id] = len(_own_episodes(anime_id))
        except Exception:  # noqa: BLE001
            return 0
    return COUNTS[anime_id]


def _own_episodes(anime_id):
    s = src_of(anime_id)
    if s == "mi":
        return scrape.mi_episodes(anime_id)
    if s == "ah":
        return ah_episodes(anime_id)
    return [n for _, n in scrape.episodes(anime_id)]


def search(query):
    """[(id, title, poster)] - one row per show, hianime's order first."""
    fns = {"": scrape.search, "ah": ah_search, "mi": scrape.mi_search}
    with ThreadPoolExecutor(3) as ex:
        futs = {k: ex.submit(fn, query) for k, fn in fns.items()}
    got, errs = {}, {}
    for k, f in futs.items():
        try:
            got[k] = [r for r in f.result() if not _is_dub(r[1])]
        except Exception as e:  # noqa: BLE001
            got[k], errs[k] = [], e
    if not any(got.values()):
        raise next(iter(errs.values()), RuntimeError("no results"))
    want = akey(query)
    groups = []  # [{key, rows: {src: (id, title, poster)}}]
    for src in ("", "ah", "mi"):
        for rid, title, poster in got[src]:
            k = akey(title)
            g = next((g for g in groups if g["key"] == k), None)
            if g is None:
                # the extra sites list loosely related shows: only the close matches may start a row when hianime answered
                if src and got[""] and want not in k and k not in want:
                    continue
                g = {"key": k, "rows": {}}
                groups.append(g)
            g["rows"].setdefault(src, (rid, title, poster))
    merged = [g for g in groups if len(g["rows"]) > 1][:8]
    if merged:  # counts are only needed to pick between sites, so only for shows that more than one site has
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(_count, [r[0] for g in merged for r in g["rows"].values()]))
    out = []
    for g in groups:
        rows = g["rows"]
        order = sorted(rows, key=lambda s: PREFERENCE[s])
        lead = order[0]
        if len(rows) > 1:
            best = max(order, key=lambda s: (COUNTS.get(rows[s][0], 0), -PREFERENCE[s]))
            if COUNTS.get(rows[best][0], 0) > COUNTS.get(rows[lead][0], 0) * 1.25 + 2:  # clearly fuller: promote it
                lead = best
        rid, title, poster = rows[lead]
        ALTS[rid] = [rows[s][0] for s in order if s != lead]
        poster = poster or next((rows[s][2] for s in order if rows[s][2]), "")
        out.append((rid, title, poster))
    return out


# ---------- episodes ----------
def _num_key(n):
    try:
        return (0, float(n))
    except ValueError:
        return (1, 0.0)


def episodes(anime_id, title=""):
    """The primary's episodes plus numbers only an alternate has."""
    eps = list(_own_episodes(anime_id))
    COUNTS[anime_id] = len(eps)
    have = {canon(n) for n in eps}
    extra = {}
    for alt in alts(anime_id, title, lookup=False):
        try:
            for n in _own_episodes(alt):
                if canon(n) not in have:
                    extra[canon(n)] = n
        except Exception:  # noqa: BLE001
            continue
    if extra:
        eps = sorted(eps + list(extra.values()), key=_num_key)
    return eps


def alts(anime_id, title="", lookup=True):
    """Alternate ids for a show. Known from search; otherwise (history, deep links) found by title on the other sites."""
    if anime_id in ALTS or not lookup:
        return ALTS.get(anime_id, [])
    found = []
    if title:
        mine = src_of(anime_id)
        for src, fn in (("", scrape.search), ("ah", ah_search), ("mi", scrape.mi_search)):
            if src == mine:
                continue
            try:
                hit = next((r for r in fn(title) if not _is_dub(r[1]) and same_show(r[1], title)), None)
            except Exception:  # noqa: BLE001
                hit = None
            if hit:
                found.append(hit[0])
    ALTS[anime_id] = found
    return found


# ---------- link ----------
def _own_number(anime_id, ep):
    """The site's own spelling of an episode number ('01' on one site is '1' on another)."""
    mine = _own_episodes(anime_id)
    if ep in mine:
        return ep
    return next((n for n in mine if canon(n) == canon(ep)), ep)


def _try(anime_id, ep, mode):
    """(url, referer, subtitle, height) from one site; raises when it cannot stream the episode."""
    s = src_of(anime_id)
    if s != "mi":  # miruro numbers are plain 1..N
        ep = _own_number(anime_id, ep)
    if s == "mi":
        url, ref, sub = scrape.mi_link(anime_id, ep, mode)
        return url, ref, sub, scrape.QUALITY.get(url, 0)
    if s == "ah":
        if mode == "dub":
            title = _ah_title.get(anime_id[len(AH_PREFIX):], "")
            dub = next((r[0] for r in ah_search(title + " dub") if _is_dub(r[1]) and same_show(r[1], title)), None) if title else None
            if not dub:
                raise RuntimeError("AnimeHeaven has no dub of this show")
            return ah_link(dub, ep)
        return ah_link(anime_id, ep)
    url, ref, sub = scrape.link(anime_id, ep, mode)
    if not scrape._alive(url, ref):  # noqa: SLF001
        raise RuntimeError("hianime stream is not reachable")
    return url, ref, sub, scrape.QUALITY.get(url, 0)


def link(anime_id, ep, mode="sub", title=""):
    """(url, referer, subtitle, skip, source label): the first stream of at least GOOD_HEIGHT from the primary or its
    alternates; otherwise the best one found. Dub falls back to sub only when no site has the dub."""
    errors = []
    for md in ([mode, "sub"] if mode != "sub" else ["sub"]):
        best = None  # (height, id, result)
        ids = [anime_id]
        i = 0
        while i < len(ids):
            sid = ids[i]
            i += 1
            try:
                res = _try(sid, ep, md)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label(sid)}: {e}")
            else:
                h = res[3] or GOOD_HEIGHT  # unknown quality counts as good enough
                if best is None or h > best[0]:
                    best = (h, sid, res)
                if h >= GOOD_HEIGHT:
                    break
            if i == len(ids) and len(ids) == 1:  # the alternates are only looked up once the primary was not enough
                ids += alts(anime_id, title)
        if best:
            _, sid, (url, ref, sub, _h) = best
            skip = {k: list(v) for k, v in scrape.SKIP_INFO.get((sid, ep), {}).items()}
            SOURCE[(anime_id, ep)] = label(sid)
            return url, ref, sub, skip, label(sid)
    raise RuntimeError(f"No working stream for episode {ep}: " + "; ".join(errors[-4:]))


_resolved = {}


def resolve(title):
    """A real site id for a show known only by title (recommendations): the same-show search hit, else the first hit."""
    if title not in _resolved:
        rows = search(title)
        if not rows:
            raise RuntimeError(f"'{title}' was not found on any site")
        _resolved[title] = next((r[0] for r in rows if same_show(r[1], title)), rows[0][0])
    return _resolved[title]
