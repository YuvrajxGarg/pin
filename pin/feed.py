"""Fetches pins the same way the screensaver does, into the same cache.

A public feed or board comes from Pinterest's RSS (no login). With a
`_pinterest_sess` cookie it reads the logged-in home feed instead: first the
UserHomefeedResource JSON the web app uses, then the homepage's hydration markup
as a fallback. Image URLs are pulled out with one regex and upgraded to the 736px
variant; each file is named md5(url).img so the saver and Pin agree on names.
"""

import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import saver

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
PIN_RE = re.compile(r"https://i\.pinimg\.com/(?:[0-9]+x|originals)/[A-Za-z0-9/_\-]+\.(?:jpg|jpeg|png|gif|webp)")
SIZE_RE = re.compile(r"/(?:[0-9]+x|originals)/")
MAX_PER_FETCH = 120


class FeedError(Exception):
    pass


def _ctx():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get(url, headers=None, timeout=20):
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        return r.status, r.read()


def cookie_header(raw):
    raw = raw.strip()
    return raw if "_pinterest_sess=" in raw else "_pinterest_sess=" + raw


def _authed(cookie, accept="application/json, text/html", xhr=True):
    h = {
        "Cookie": cookie_header(cookie),
        "Referer": "https://www.pinterest.com/",
        "Accept": accept,
        # Without the pws-handler header the resource router answers "Invalid Resource Request".
        "x-pinterest-pws-handler": "www/index.js",
        "x-pinterest-source-url": "/",
        "x-pinterest-appstate": "active",
    }
    if xhr:
        h["X-Requested-With"] = "XMLHttpRequest"
    return h


def extract_image_urls(text):
    seen, out = set(), []
    for m in PIN_RE.finditer(text.replace("\\/", "/")):
        u = m.group(0)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def hi_res(url):
    return SIZE_RE.sub("/736x/", url, count=1)


def fetch_urls(cfg):
    """Image URLs for the configured source. Raises FeedError with a readable message."""
    cookie = (cfg.get("cookie") or "").strip()
    if cookie:
        opts = json.dumps({"options": {"field_set_key": "react_grid_pin", "in_nux": False, "prependPartner": False},
                           "context": {}}, separators=(",", ":"))
        url = ("https://www.pinterest.com/resource/UserHomefeedResource/get/?source_url=%2F&data="
               + urllib.parse.quote(opts, safe=""))
        try:
            code, body = _get(url, _authed(cookie))
            urls = extract_image_urls(body.decode("utf-8", "replace")) if 200 <= code < 300 else []
        except Exception:
            urls = []
        if urls:
            return urls
        try:
            _, body = _get("https://www.pinterest.com/", _authed(cookie, accept="text/html", xhr=False))
        except Exception as e:
            raise FeedError("Couldn't reach Pinterest (%s)" % _reason(e))
        urls = extract_image_urls(body.decode("utf-8", "replace"))
        if not urls:
            raise FeedError("Couldn't load your home feed. The session cookie may have expired.")
        return urls
    feed = saver.normalize_feed_url(cfg.get("feed"))
    if not feed:
        raise FeedError("That feed doesn't look right: %s" % (cfg.get("feed") or "(empty)"))
    try:
        _, body = _get(feed)
    except Exception as e:
        raise FeedError("Couldn't load the feed (%s)" % _reason(e))
    urls = extract_image_urls(body.decode("utf-8", "replace"))
    if not urls:
        raise FeedError("No pins in that feed. Is the profile or board public?")
    return urls


def _reason(e):
    code = getattr(e, "code", None)
    if code == 404:
        return "not found"
    if code:
        return "HTTP %s" % code
    r = getattr(e, "reason", None) or e
    return str(r)[:80]


def refresh(cfg, on_pin=None, start_over=False):
    """Fetches the source once and downloads pins not on disk yet.

    on_pin(filename) is called for each new file. start_over removes the cached
    pins first (hidden ones stay hidden). Returns {"new": n, "seen": m}.
    """
    folder = saver.cache_dir(cfg)
    os.makedirs(folder, exist_ok=True)
    hidden = set(cfg.get("hidden") or [])
    if start_over:
        for n in os.listdir(folder):
            if n.endswith(".img"):
                try:
                    os.remove(os.path.join(folder, n))
                except OSError:
                    pass

    urls = fetch_urls(cfg)[:MAX_PER_FETCH]
    todo, seen = [], set()
    for raw in urls:
        big = hi_res(raw)
        if big in seen:
            continue
        seen.add(big)
        name = saver.md5(big) + ".img"
        if name in hidden:
            continue
        path = os.path.join(folder, name)
        if os.path.exists(path):
            try:
                os.utime(path, None)  # current pins shouldn't be the first evicted
            except OSError:
                pass
            continue
        todo.append((big, raw, path))

    new = []

    def one(job):
        big, raw, path = job
        for u in (big, raw) if big != raw else (big,):
            try:
                code, data = _get(u, timeout=25)
            except Exception:
                continue
            if 200 <= code < 300 and saver.image_kind(data[:16]):
                tmp = path + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
                return os.path.basename(path)
        return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        for name in pool.map(one, todo):
            if name:
                new.append(name)
                if on_pin:
                    on_pin(name)

    saver.trim_cache(folder, hidden=hidden)
    return {"new": len(new), "seen": len(seen)}
