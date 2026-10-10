"""hianime scraping in pure Python (a port of the `ani` shell script's --api mode) so it works on Windows too."""
import base64
import gzip
import html as htmllib
import json
import re
from urllib.parse import quote_plus

import httpx

BASE = "https://hianime.at"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
KEY = b"otaku-embed-v1"  # the embed page ships its config as base64(json XOR this key)
_client = None


def client():
    global _client
    if _client is None:
        _client = httpx.Client(headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
    return _client


def get(url, referer=None):
    r = client().get(url, headers={"Referer": referer} if referer else None)
    if "Just a moment" in r.text[:4000]:
        raise RuntimeError("Blocked by Cloudflare - try again in a moment")
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} from {url}")
    return r.text


def _cards(page):
    page = page.split('id="main-sidebar"')[0]  # the sidebar repeats the markup
    out = []
    for chunk in page.replace("\n", " ").split('<div class="film-poster">')[1:]:
        m = re.search(r'<img src="([^"]*)".*?<h3 class="film-name">\s*<a href="[^"]*/([^"/]*)"\s*title="([^"]*)"', chunk)
        if m:
            out.append((m.group(2), htmllib.unescape(m.group(3)), m.group(1)))
    return out


def search(query):
    """[(anime_id, title, poster_url)] for a search term."""
    return _cards(get(f"{BASE}/search?keyword={quote_plus(query)}"))


def listing(name):
    """[(anime_id, title, poster_url)] of one of the site's lists: 'most-popular', 'top-airing', 'most-favorite'..."""
    return _cards(get(f"{BASE}/{name}"))


def episodes(anime_id):
    """[(episode_id, number)] in the site's order."""
    page = get(f"{BASE}/api/theme/episode/list/{anime_id.rsplit('-', 1)[-1]}").replace("\\", "")
    out = []
    for part in page.replace("ep-item", "\nep-item").split("\n"):
        m = re.search(r'data-number="([^"]*)".*data-id="([0-9]+)".*/watch/' + re.escape(anime_id) + r"[?]ep=", part)
        if m:
            out.append((m.group(2), m.group(1)))
    return out


def _deobfuscate(blob):
    raw = base64.b64decode(blob)
    return bytes(b ^ KEY[i % len(KEY)] for i, b in enumerate(raw)).decode("utf-8", "replace")


def link(anime_id, ep, mode="sub", quality="best"):
    """(video_url, referer, subtitle_url) for one episode, or raises."""
    eps = dict((n, i) for i, n in episodes(anime_id))
    if ep not in eps:
        raise RuntimeError("Episode not released!")
    servers = get(f"{BASE}/api/theme/episode/servers?episodeId={eps[ep]}").replace('\\"', '"').replace("server-item", "\nserver-item")
    h = None
    for line in servers.split("\n"):  # only the ZokoAnime embed is understood; the other servers use different players
        m = re.search(r'data-type="' + re.escape(mode) + r'".*data-server-name="ZokoAnime".*data-hash="([^"]*)"', line)
        if m:
            h = m.group(1)
            break
    if not h:
        raise RuntimeError(f"No sources found for {mode}!")
    embed = base64.b64decode(h).decode()
    refr = re.sub(r"^(https?://[^/]*).*", r"\1/", embed)
    blob = re.search(r'window\.__P="([^"]*)"', get(embed))
    if not blob:
        raise RuntimeError("Embed page changed")
    cfg = _deobfuscate(blob.group(1))
    try:  # some embeds ship intro/outro timestamps ("skip":{"intro":{"start":..,"end":..},"outro":{..}})
        sk = json.loads(cfg).get("skip") or {}
        SKIP_INFO[(anime_id, ep)] = {k: (float(sk[k]["start"]), float(sk[k]["end"])) for k in ("intro", "outro") if isinstance(sk.get(k), dict)}
    except (ValueError, KeyError, TypeError):
        pass
    m3u8 = re.search(r'"src":"([^"]*\.m3u8[^"]*)"', cfg)
    if not m3u8:
        raise RuntimeError("No stream in the embed config")
    master = m3u8.group(1).replace("\\/", "/")
    sub = ""
    try:
        for obj in re.findall(r"\{[^{}]*\}", cfg.split('"subtitles":[', 1)[1].split("]", 1)[0]):
            if '"default":true' in obj:
                sub = re.search(r'"src":"([^"]*)"', obj).group(1).replace("\\/", "/")
                break
    except (IndexError, AttributeError):
        pass
    text = get(master, referer=refr)
    base = master.rsplit("/", 1)[0] + "/"
    variants, lines = [], text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("#EXT-X-STREAM-INF"):
            res = re.search(r"RESOLUTION=\d+x(\d+)", ln)
            url = next((x for x in lines[i + 1:] if x and not x.startswith("#")), None)
            if url:
                variants.append((int(res.group(1)) if res else 0, url if url.startswith("http") else base + url))
    if not variants:
        QUALITY[master] = 0
        return master, refr, sub
    variants.sort(key=lambda v: -v[0])
    if quality == "worst":
        chosen = variants[-1]
    elif quality not in ("best", ""):
        chosen = next((v for v in variants if f"{v[0]}p" == quality), variants[0])
    else:
        chosen = variants[0]
    QUALITY[chosen[1]] = chosen[0]
    return chosen[1], refr, sub


# ---------- miruro.to: the fallback source (used when hianime has nothing, or can't stream an episode) ----------
MIRURO = "https://www.miruro.to"
MI_KEY = b"miruro/catalog"  # the site XORs its catalog responses with this key, then gzips them
MI_PREFIX = "mi:"
_mi_meta = {}  # anime id -> {"title", "episodes": n, "format"}
QUALITY = {}  # stream url -> pixel height (0 when the playlist does not say)
SKIP_INFO = {}  # (anime id, episode) -> {"intro": (start, end) | None, "outro": (start, end) | None}


def _mi_get(path, **query):
    r = client().get(MIRURO + "/api" + path, params=query, headers={"Referer": MIRURO + "/", "Accept": "*/*", "Sec-Fetch-Dest": "empty",
                                                                   "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"})
    if r.status_code >= 400:
        raise RuntimeError(f"miruro HTTP {r.status_code}")
    if r.headers.get("content-type", "").startswith("application/octet-stream"):
        raw = bytes(b ^ MI_KEY[i % len(MI_KEY)] for i, b in enumerate(r.content))
        return json.loads(gzip.decompress(raw))
    return r.json()


def _mi_title(t):
    return (t.get("english") or t.get("romaji") or t.get("native") or "?").replace("\u2019", "'")


def mi_search(query):
    """[(mi:<id>, title, cover_url)] from miruro, most popular first."""
    out = []
    for it in _mi_get("/v1/anime", q=query, limit=15, sort="-popularity").get("data", []):
        n = max([v or 0 for v in (it.get("episode_counts") or {}).values()] + [it.get("episode_count") or 0])
        _mi_meta[it["id"]] = {"title": _mi_title(it["title"]), "episodes": n, "format": it.get("format") or ""}
        out.append((MI_PREFIX + it["id"], _mi_title(it["title"]), it.get("cover_url") or ""))
    return out


def mi_episodes(anime_id):
    """Episode numbers for a miruro id (the site lists them by count: 1..N)."""
    raw = anime_id[len(MI_PREFIX):]
    meta = _mi_meta.get(raw)
    if not meta:
        d = _mi_get(f"/v1/anime/{raw}")
        n = max([v or 0 for v in (d.get("episode_counts") or {}).values()] + [d.get("episode_count") or 0])
        meta = _mi_meta[raw] = {"title": _mi_title(d["title"]), "episodes": n, "format": d.get("format") or ""}
    return [str(i) for i in range(1, max(meta["episodes"], 1) + 1)]


def _alive(url, referer):
    """True when the stream really plays: the playlist answers, and so does its first media segment. (Several of miruro's
    providers sit behind a Cloudflare challenge, or list segments that never arrive.)"""
    from urllib.parse import urljoin  # noqa: PLC0415

    try:
        hdr = {"Referer": referer}
        top = client().get(url, headers=hdr, timeout=8)
        if top.status_code != 200 or not top.text.startswith("#EXTM3U"):
            return False
        lines = [ln.strip() for ln in top.text.splitlines()]
        target, text, base = url, top.text, url
        for _ in range(2):  # master playlist -> variant playlist -> first segment
            uris = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
            if not uris:
                return False
            target = urljoin(base, uris[0].strip())
            if "#EXT-X-STREAM-INF" in text:
                r = client().get(target, headers=hdr, timeout=8)
                if r.status_code != 200:
                    return False
                text, base = r.text, target
                continue
            break
        with client().stream("GET", target, headers={**hdr, "Range": "bytes=0-2047"}, timeout=8) as r:
            return r.status_code in (200, 206) and len(r.read()) > 0
    except Exception:  # noqa: BLE001
        return False


def mi_link(anime_id, ep, mode="sub"):
    """(video_url, referer, subtitle_url) from miruro's play endpoint: the first provider whose HLS stream actually answers."""
    raw = anime_id[len(MI_PREFIX):]
    play = _mi_get(f"/v1/anime/{raw}/episodes/{ep}/play")
    order = [mode] + [t for t in ("sub", "ssub") if t != mode] if mode == "sub" else [mode, "sub", "ssub"]
    tried = 0
    for track in order:
        for t in play.get("tracks", []):
            if t.get("track") != track:
                continue
            for prov in t.get("providers", []):
                sub = ""
                for sb in prov.get("subtitles", []):
                    u = sb.get("url") or sb.get("file") or ""
                    if u and ("en" in str(sb.get("language", "")).lower() or "eng" in str(sb.get("label", "")).lower()):
                        sub = u
                        break
                for server in prov.get("servers", []):
                    streams = [s for s in server.get("streams", []) if s.get("url") and s.get("format", "hls") == "hls"]
                    streams.sort(key=lambda s: -((s.get("resolution") or {}).get("height") or 0))
                    ref = (server.get("headers") or {}).get("Referer", MIRURO + "/")
                    for st in streams[:1]:
                        tried += 1
                        if _alive(st["url"], ref):
                            QUALITY[st["url"]] = (st.get("resolution") or {}).get("height") or 0
                            return st["url"], ref, sub
    raise RuntimeError(f"No working miruro stream for episode {ep} ({mode}); tried {tried}")


def best_miruro(title):
    """Pick the miruro entry that best matches a title (exact normalised match first, else the most popular result)."""
    want = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    rows = mi_search(re.sub(r"\s*\((tv|movie|ova|ona|special)[^)]*\)", "", title, flags=re.I))
    for rid, name, _ in rows:
        if re.sub(r"[^a-z0-9]+", " ", name.lower()).strip() == want:
            return rid
    return rows[0][0] if rows else None
