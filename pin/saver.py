"""The screensaver's side of things: its settings file, its pin cache, and installing it.

Pin and the screensaver share one settings file and one image cache, so pins you
hide here stay out of the screensaver. Both keep the folder names the older
"Pinterest Saver" used, so existing installs keep their feed, cookie and pins.

  macOS    The saver runs inside legacyScreenSaver's sandbox, so its files live in
           that app's container:
             ~/Library/Containers/com.apple.ScreenSaver.Engine.legacyScreenSaver/Data/Library/
               Application Support/PinterestSaver/config.json     (camelCase keys)
               Caches/PinterestSaver/<source>/<md5 of image url>.img
           Reading it needs the one-time "access data from other apps" OK.
  Windows  %APPDATA%\\PinterestSaver\\settings.json               (PascalCase keys)
           %LOCALAPPDATA%\\PinterestSaver\\cache\\<source>\\<md5>.img

<source> is "home" for the cookie home feed, else the md5 of the normalized RSS URL.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

DEFAULT_FEED = "https://www.pinterest.com/pinterest/feed.rss"
CACHE_LIMIT = 200

# Our key -> (macOS key, Windows key, default)
FIELDS = {
    "feed": ("feed", "Feed", DEFAULT_FEED),
    "cookie": ("sessionCookie", "SessionCookie", ""),
    "speed": ("speed", "Speed", 26.0),
    "clock": ("showClock", "ShowClock", True),
    "clock24h": ("clock24h", "Clock24h", False),
    "tile": ("columnWidth", "TileSize", 300.0),
    "hidden": ("hiddenPins", "HiddenPins", []),
}

MAC_CONTAINER = "com.apple.ScreenSaver.Engine.legacyScreenSaver"


class AccessDenied(Exception):
    """macOS hasn't let Pin into the screensaver's container yet."""


# ---- paths ---------------------------------------------------------------

def _override():
    # Tests (and the screensaver's own harness) point everything at a scratch folder.
    return os.environ.get("PIN_SAVER_LIBRARY") or os.environ.get("PINTEREST_SAVER_LIBRARY")


def library():
    o = _override()
    if o:
        return o
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Containers/%s/Data/Library" % MAC_CONTAINER)
    return None


def config_path():
    lib = library()
    if sys.platform == "darwin" or _override():
        return os.path.join(lib, "Application Support", "PinterestSaver", "config.json")
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "PinterestSaver", "settings.json")


def cache_root():
    lib = library()
    if sys.platform == "darwin" or _override():
        return os.path.join(lib, "Caches", "PinterestSaver")
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "PinterestSaver", "cache")


def _windows_keys():
    return os.name == "nt" and not _override()


# ---- settings --------------------------------------------------------------

def load_config():
    """The saver's settings with our key names. Raises AccessDenied on macOS without permission."""
    path = config_path()
    raw = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except FileNotFoundError:
        _probe(os.path.dirname(os.path.dirname(path)))
    except PermissionError:
        raise AccessDenied()
    except (OSError, ValueError):
        raw = {}
    idx = 1 if _windows_keys() else 0
    cfg = {}
    for key, spec in FIELDS.items():
        v = raw.get(spec[idx], raw.get(spec[1 - idx]))
        cfg[key] = spec[2] if v is None else v
    if not isinstance(cfg["hidden"], list):
        cfg["hidden"] = []
    cfg["_raw"] = raw
    return cfg


def save_config(cfg):
    """Writes our keys back, keeping any keys the saver knows about that we don't."""
    path = config_path()
    idx = 1 if _windows_keys() else 0
    out = dict(cfg.get("_raw") or {})
    for key, spec in FIELDS.items():
        if key in cfg:
            out.pop(spec[1 - idx], None)
            out[spec[idx]] = cfg[key]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except PermissionError:
        raise AccessDenied()
    cfg["_raw"] = out


def _probe(folder):
    """Listing the container is what macOS gates; turn a refusal into AccessDenied."""
    if sys.platform != "darwin" or _override():
        return
    try:
        os.listdir(folder)
    except FileNotFoundError:
        pass
    except PermissionError:
        raise AccessDenied()


def check_access():
    """True if Pin can read and write the screensaver's files."""
    try:
        for d in (os.path.dirname(config_path()), cache_root()):
            os.makedirs(d, exist_ok=True)
            os.listdir(d)
        return True
    except PermissionError:
        return False
    except OSError:
        return True


# ---- sources ---------------------------------------------------------------

def normalize_feed_url(raw):
    """A username, 'user/board', a pinterest.com URL or a full .rss URL -> the RSS URL (or None)."""
    s = (raw or "").strip()
    if not s:
        return None
    if s.endswith(".rss"):
        return s if s.startswith("http") else "https://" + s
    path = s
    m = re.match(r"^[a-z]+://([^/]+)(/[^?#]*)?", s, re.I)
    if m and "pinterest." in m.group(1).lower():
        path = m.group(2) or ""
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) == 1:
        return "https://www.pinterest.com/%s/feed.rss" % parts[0]
    if len(parts) >= 2:
        return "https://www.pinterest.com/%s/%s.rss" % (parts[0], parts[1])
    return None


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def uses_home_feed(cfg):
    return bool((cfg.get("cookie") or "").strip())


def source_key(cfg):
    if uses_home_feed(cfg):
        return "home"
    return md5(normalize_feed_url(cfg.get("feed")) or cfg.get("feed") or "")


def cache_dir(cfg):
    return os.path.join(cache_root(), source_key(cfg))


def describe_source(cfg):
    if uses_home_feed(cfg):
        return "Your home feed"
    url = normalize_feed_url(cfg.get("feed"))
    if not url:
        return cfg.get("feed") or "No feed"
    parts = [p for p in url.split("pinterest.com/", 1)[-1].split("/") if p]
    if len(parts) >= 2 and parts[1] != "feed.rss":
        return "%s / %s" % (parts[0], parts[1].replace(".rss", ""))
    return parts[0] if parts else url


# ---- pins on disk ------------------------------------------------------------

def image_kind(head):
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def list_pins(cfg):
    """Every cached pin for the current source, newest first: dicts with id, path, mtime, hidden."""
    d = cache_dir(cfg)
    hidden = set(cfg.get("hidden") or [])
    out = []
    try:
        names = os.listdir(d)
    except FileNotFoundError:
        return []
    except PermissionError:
        raise AccessDenied()
    for name in names:
        if not name.endswith(".img"):
            continue
        p = os.path.join(d, name)
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_size < 64:
            continue
        out.append({"id": name, "path": p, "mtime": st.st_mtime, "size": st.st_size, "hidden": name in hidden})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def trim_cache(folder, keep=CACHE_LIMIT, hidden=()):
    """Same rule as the saver: keep at most `keep` files, dropping hidden ones first, then the oldest."""
    try:
        files = [os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".img")]
    except OSError:
        return
    if len(files) <= keep:
        return
    hidden = set(hidden)
    files.sort(key=lambda f: (os.path.basename(f) not in hidden, os.path.getmtime(f)))
    for f in files[: len(files) - keep]:
        try:
            os.remove(f)
        except OSError:
            pass


# ---- installing the screensaver ------------------------------------------------

def _resources():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return base


def bundled_saver():
    """The screensaver that ships inside this app, or None (running from source without a build)."""
    if sys.platform == "darwin":
        cands = [os.path.join(os.path.dirname(sys.executable), "..", "Resources", "saver", "Pin.saver"),
                 os.path.join(_resources(), "saver", "Pin.saver"),
                 os.path.join(_resources(), "saver", "mac", "build", "Pin.saver")]
    else:
        cands = [os.path.join(_resources(), "saver", "Pin.scr"),
                 os.path.join(_resources(), "saver", "windows", "publish", "Pin.scr")]
    for c in cands:
        if os.path.exists(c):
            return os.path.normpath(c)
    return None


def installed_saver_path():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Screen Savers/Pin.saver")
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "PinterestSaver", "Pin.scr")


OLD_MAC_SAVER = os.path.expanduser("~/Library/Screen Savers/PinterestSaver.saver")


def _version_of(path):
    if not path or not os.path.exists(path):
        return None
    if sys.platform == "darwin":
        import plistlib

        try:
            with open(os.path.join(path, "Contents", "Info.plist"), "rb") as f:
                return plistlib.load(f).get("CFBundleShortVersionString")
        except (OSError, ValueError):
            return None
    marker = path + ".version"
    try:
        with open(marker) as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def saver_state():
    """{'installed': version or None, 'bundled': version or None, 'old': bool, 'current': bool}"""
    from . import __version__

    bundled = bundled_saver()
    bv = _version_of(bundled) if sys.platform == "darwin" else (__version__ if bundled else None)
    iv = _version_of(installed_saver_path())
    return {
        "installed": iv,
        "bundled": bv,
        "old": sys.platform == "darwin" and os.path.exists(OLD_MAC_SAVER),
        "current": bool(iv) and (iv == bv or not bv),
        "active": _windows_active_saver_is_ours() if os.name == "nt" else None,
    }


def _windows_active_saver_is_ours():
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as k:
            v = winreg.QueryValueEx(k, "SCRNSAVE.EXE")[0]
        return os.path.normcase(os.path.abspath(v)) == os.path.normcase(os.path.abspath(installed_saver_path()))
    except Exception:
        return False


def install_saver():
    """Copies the bundled screensaver into place. Returns a short message for the UI."""
    from . import __version__

    src = bundled_saver()
    if not src:
        raise RuntimeError("This build doesn't include the screensaver.")
    dest = installed_saver_path()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if sys.platform == "darwin":
        tmp = dest + ".new"
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["/usr/bin/ditto", src, tmp], check=True)
        shutil.rmtree(dest, ignore_errors=True)
        os.rename(tmp, dest)
        subprocess.run(["/usr/bin/xattr", "-dr", "com.apple.quarantine", dest], stderr=subprocess.DEVNULL)
        # The old "Pinterest Saver" would show up twice in the list; Pin replaces it.
        shutil.rmtree(OLD_MAC_SAVER, ignore_errors=True)
        # macOS keeps the previous bundle loaded until these restart.
        subprocess.run(["/usr/bin/killall", "legacyScreenSaver", "WallpaperAgent"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Screensaver installed. Pick Pin in Screen Saver settings."
    tmp = dest + ".new"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)
    with open(dest + ".version", "w") as f:
        f.write(__version__)
    # Selects it as the screensaver and opens the Screen Saver dialog, the same as
    # right-click > Install on a .scr file.
    subprocess.Popen(["rundll32.exe", "desk.cpl,InstallScreenSaver", dest], creationflags=0x08000000)
    return "Screensaver installed and selected."


def update_installed_saver():
    """After Pin itself updates, bring an already-installed screensaver up to the bundled one."""
    st = saver_state()
    if st["installed"] and not st["current"] and st["bundled"]:
        try:
            if sys.platform == "darwin":
                install_saver()
            else:
                from . import __version__

                shutil.copyfile(bundled_saver(), installed_saver_path())
                with open(installed_saver_path() + ".version", "w") as f:
                    f.write(__version__)
            return True
        except Exception:
            return False
    return False


def start_saver():
    if sys.platform == "darwin":
        subprocess.Popen(["/usr/bin/open", "-a", "ScreenSaverEngine"])
    else:
        p = installed_saver_path()
        if os.path.exists(p):
            subprocess.Popen([p, "/s"])


def open_saver_settings():
    if sys.platform == "darwin":
        subprocess.Popen(["/usr/bin/open", "x-apple.systempreferences:com.apple.ScreenSaver-Settings.extension"])
    else:
        subprocess.Popen(["control.exe", "desk.cpl,,@screensaver"], creationflags=0x08000000)


def open_privacy_settings():
    if sys.platform == "darwin":
        subprocess.Popen(["/usr/bin/open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
