"""Extra manga sources for when MangaDex only hosts part of a series (or none of it): MangaPill, MangaKatana and MangaRead.

Both are plain HTML sites. A book id is `<prefix>:<path>` ("mp:723/chainsaw-man", "mk:chainsaw-man.21890"); chapters are
{id (a url path), chapter, src}. Page images need a Referer, see referer()."""
import html as htmllib
import re

import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
PILL, KATANA, READ = "https://mangapill.com", "https://mangakatana.com", "https://www.mangaread.org"
LABELS = {"mp": "MangaPill", "mk": "MangaKatana", "mr": "MangaRead", "md": "MangaDex"}
_client = None


def _c():
    global _client
    if _client is None:
        _client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=20)
    return _client


def _get(url, **kw):
    r = _c().get(url, **kw)
    if r.status_code >= 400 or "Just a moment" in r.text[:3000]:
        raise RuntimeError(f"{url}: HTTP {r.status_code}")
    return r.text


def _num(label):
    m = re.search(r"chapter\s*([0-9]+(?:\.[0-9]+)?)", label, re.I) or re.search(r"([0-9]+(?:\.[0-9]+)?)", label)
    return m.group(1).rstrip("0").rstrip(".") if m and "." in m.group(1) else (m.group(1) if m else None)


def _sort(chs):
    seen, out = set(), []
    for c in chs:
        if c["chapter"] and c["chapter"] not in seen:
            seen.add(c["chapter"])
            out.append(c)
    return sorted(out, key=lambda c: float(c["chapter"]))


# ---------------- search ----------------
def search(query, n=10):
    """[{id, title, cover, src}] from both sites (a failing site is skipped)."""
    out = []
    try:
        t = _get(PILL + "/search", params={"q": query})
        seen = set()
        for m in re.finditer(r'<a href="(/manga/(\d+/[^"]+))" class="relative block">\s*<figure[^>]*>\s*<img data-src="([^"]+)"', t):
            if m.group(2) in seen:
                continue
            seen.add(m.group(2))
            title = re.search(re.escape(f'<a href="{m.group(1)}"') + r'[^>]*>\s*<div[^>]*>([^<]+)<', t[m.end():])
            out.append({"id": "mp:" + m.group(2), "title": htmllib.unescape(title.group(1).strip()) if title else m.group(2).split("/")[-1].replace("-", " ").title(),
                        "cover": m.group(3), "src": "mp"})
            if len(seen) >= n:
                break
    except Exception:  # noqa: BLE001
        pass
    try:
        t = _get(KATANA + "/", params={"search": query, "search_by": "book_name"})
        if 'id="book_list"' in t:
            for m in list(re.finditer(r'<img src="([^"]+)" alt="\[Cover\]">.*?<a href="https://mangakatana\.com/manga/([^"]+)" target="_blank">([^<]+)</a>', t, re.S))[:n]:
                out.append({"id": "mk:" + m.group(2), "title": htmllib.unescape(m.group(3).strip()), "cover": m.group(1), "src": "mk"})
        elif "/manga/" in t and "og:url" in t:  # a single hit redirects straight to the series page
            m = re.search(r'og:url" content="https://mangakatana\.com/manga/([^"]+)"', t)
            ti = re.search(r'<h1 class="heading">([^<]+)<', t)
            if m and ti:
                out.append({"id": "mk:" + m.group(1), "title": htmllib.unescape(ti.group(1).strip()), "cover": "", "src": "mk"})
    except Exception:  # noqa: BLE001
        pass
    try:
        t = _get(READ + "/", params={"s": query, "post_type": "wp-manga"})
        for m in list(re.finditer(r'<img[^>]+(?:data-src|src)="([^"]+)"[^>]*>.{0,600}?<h3 class="h4">\s*<a href="' + re.escape(READ) + r'/manga/([^/"]+)/">([^<]+)</a>', t, re.S))[:n]:
            out.append({"id": "mr:" + m.group(2), "title": htmllib.unescape(m.group(3).strip()), "cover": m.group(1), "src": "mr"})
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------------- chapters / pages ----------------
def chapters(book_id):
    """Ascending, de-duplicated chapters of a series."""
    src, path = book_id.split(":", 1)
    if src == "mp":
        t = _get(f"{PILL}/manga/{path}")
        chs = [{"id": h, "chapter": _num(lab), "src": "mp"} for h, lab in re.findall(r'href="(/chapters/[^"]+)"[^>]*>\s*([^<]+)<', t)]
    elif src == "mk":
        t = _get(f"{KATANA}/manga/{path}")
        base = f"{KATANA}/manga/{path}/c"
        chs = [{"id": h, "chapter": _num(lab), "src": "mk"} for h, lab in re.findall(r'<div class="chapter">\s*<a href="([^"]+)">([^<]+)</a>', t) if h.startswith(base)]
    elif src == "mr":
        url = f"{READ}/manga/{path}/"
        pat = r'<li class="wp-manga-chapter[^"]*">\s*<a href="([^"]+)">\s*([^<]+?)\s*</a>'
        t = _get(url)
        found = re.findall(pat, t)
        if not found:
            r = _c().post(url + "ajax/chapters/", headers={"X-Requested-With": "XMLHttpRequest"})
            found = re.findall(pat, r.text)
        chs = [{"id": h, "chapter": _num(lab), "src": "mr"} for h, lab in found]
    else:
        raise ValueError(book_id)
    return _sort(chs)


def pages(ch):
    """Image URLs of one chapter."""
    if ch["src"] == "mp":
        t = _get(PILL + ch["id"])
        urls = re.findall(r'<img[^>]+data-src="([^"]+)"', t)
        return [u for u in urls if "/file/" in u or "mangap" in u]
    if ch["src"] == "mr":
        t = _get(ch["id"])
        return [u for u in re.findall(r'class="wp-manga-chapter-img"[^>]*?(?:data-src|src)="\s*([^"\s]+)', t) if u.startswith("http")] or \
            re.findall(r'<img[^>]+(?:data-src|src)="\s*(https?://[^"\s]+/WP-manga/data/[^"\s]+)', t)
    t = _get(ch["id"])
    arrs = re.findall(r"var \w+=\[((?:'[^']*',?)+)\]", t)
    return re.findall(r"'([^']*)'", max(arrs, key=len)) if arrs else []


def referer(url):
    if "mangakatana" in url:
        return KATANA + "/"
    if "mangaread.org" in url:
        return READ + "/"
    if "readdetectiveconan" in url or "mangap" in url:
        return PILL + "/"
    return None
