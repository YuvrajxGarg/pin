"""Pin's window: an HTML/CSS interface (pin/ui) in a native window via pywebview.

WebKit on macOS and Edge WebView2 on Windows, so both get the same UI.
"""

import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time

import webview

from . import __version__, feed, saver
from .settings import Settings, app_data_dir
from .updater import Updater

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    UI_DIR = os.path.join(sys._MEIPASS, "pin", "ui")

BG = "#0b0b0c"
THUMB_W = 360
VIEW_MAX = 1600
MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


def default_save_dir():
    pics = os.path.join(os.path.expanduser("~"), "Pictures")
    return os.path.join(pics if os.path.isdir(pics) else os.path.expanduser("~"), "Pin")


def _read_head(path, n=16):
    with open(path, "rb") as f:
        return f.read(n)


class Api(object):
    """Methods here are called from JS. Keep attributes _private: pywebview walks public ones."""

    def __init__(self):
        self._window = None
        self._settings = Settings()
        self._updater = Updater(self._settings, lambda st: self._emit("update", st))
        self._lock = threading.RLock()
        self._busy = False
        self._thumb_dir = os.path.join(app_data_dir(), "Thumbs")
        os.makedirs(self._thumb_dir, exist_ok=True)

    # ---- helpers ---------------------------------------------------------
    def _emit(self, event, payload):
        if self._window:
            try:
                self._window.evaluate_js("window.App && App.on(%s, %s)" % (json.dumps(event), json.dumps(payload)))
            except Exception:
                pass

    def _cfg(self):
        return saver.load_config()

    def _pin_path(self, pin_id, cfg=None):
        name = os.path.basename(str(pin_id))
        if not name.endswith(".img"):
            raise ValueError("not a pin")
        return os.path.join(saver.cache_dir(cfg or self._cfg()), name)

    def _public_cfg(self, cfg):
        return {
            "feed": cfg.get("feed") or "",
            "home": saver.uses_home_feed(cfg),
            "source": saver.describe_source(cfg),
            "speed": cfg.get("speed"), "clock": cfg.get("clock"), "clock24h": cfg.get("clock24h"),
            "tile": cfg.get("tile"), "hiddenCount": len(cfg.get("hidden") or []),
        }

    # ---- state -------------------------------------------------------------
    def info(self):
        return {"version": __version__, "platform": sys.platform, "settings": self._public_settings(),
                "update": self._updater.state(), "home": os.path.expanduser("~")}

    def _public_settings(self):
        s = {k: self._settings.get(k) for k in ("auto_check", "auto_install", "welcomed")}
        s["save_dir"] = self._settings.get("save_dir") or default_save_dir()
        return s

    def state(self):
        """Saver settings + every pin for the current source (without image data)."""
        try:
            cfg = self._cfg()
            pins = saver.list_pins(cfg)
        except saver.AccessDenied:
            return {"access": False, "saver": saver.saver_state()}
        return {
            "access": True,
            "config": self._public_cfg(cfg),
            "pins": [{"id": p["id"], "t": p["mtime"], "hidden": p["hidden"]} for p in pins],
            "saver": saver.saver_state(),
            "busy": self._busy,
        }

    # ---- images --------------------------------------------------------------
    def thumbs(self, ids):
        """{id: {src, ratio}} small JPEGs for the grid, cached on disk."""
        out = {}
        cfg = self._cfg()
        for pin_id in ids or []:
            try:
                out[pin_id] = self._thumb(self._pin_path(pin_id, cfg))
            except Exception:
                out[pin_id] = None
        return out

    def _thumb(self, path):
        st = os.stat(path)
        key = hashlib.md5(("%s|%d|%d" % (path, st.st_mtime, st.st_size)).encode()).hexdigest()
        cached = os.path.join(self._thumb_dir, key + ".json")
        try:
            with open(cached) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
        from PIL import Image

        with Image.open(path) as im:
            im.seek(0)
            w, h = im.size
            im = im.convert("RGB")
            im.thumbnail((THUMB_W, THUMB_W * 4))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82, optimize=True)
        res = {"src": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"),
               "ratio": (h / float(w)) if w else 1.0, "w": w, "h": h}
        try:
            with open(cached, "w") as f:
                json.dump(res, f)
        except OSError:
            pass
        return res

    def full(self, pin_id):
        """The pin at full size for the viewer."""
        path = self._pin_path(pin_id)
        with open(path, "rb") as f:
            data = f.read()
        kind = saver.image_kind(data[:16]) or "jpg"
        if len(data) > 6 * 1024 * 1024:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as im:
                im = im.convert("RGB")
                im.thumbnail((VIEW_MAX, VIEW_MAX))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=90)
            data, kind = buf.getvalue(), "jpg"
        return {"src": "data:%s;base64,%s" % (MIME[kind], base64.b64encode(data).decode("ascii")), "kind": kind.upper(),
                "bytes": len(data)}

    # ---- pin actions -------------------------------------------------------------
    def set_hidden(self, ids, hidden):
        with self._lock:
            try:
                cfg = self._cfg()
                cur = set(cfg.get("hidden") or [])
                ids = [os.path.basename(str(i)) for i in ids or []]
                cur = (cur | set(ids)) if hidden else (cur - set(ids))
                cfg["hidden"] = sorted(cur)
                saver.save_config(cfg)
            except saver.AccessDenied:
                return {"ok": False, "access": False}
        return {"ok": True, "hiddenCount": len(cur)}

    def save_pins(self, ids, choose=False):
        """Saves pins as normal image files. Returns {saved, dir} or None if the folder pick was cancelled."""
        folder = self._settings.get("save_dir") or default_save_dir()
        if choose:
            res = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=folder if os.path.isdir(folder) else "")
            if not res:
                return None
            folder = res[0] if isinstance(res, (list, tuple)) else res
            self._settings.set("save_dir", folder)
        os.makedirs(folder, exist_ok=True)
        cfg = self._cfg()
        saved, last = 0, None
        for pin_id in ids or []:
            try:
                src = self._pin_path(pin_id, cfg)
                kind = saver.image_kind(_read_head(src)) or "jpg"
                stem = "pin-" + os.path.basename(src)[:10]
                dst = os.path.join(folder, "%s.%s" % (stem, kind))
                n = 2
                while os.path.exists(dst):
                    dst = os.path.join(folder, "%s-%d.%s" % (stem, n, kind))
                    n += 1
                with open(src, "rb") as a, open(dst, "wb") as b:
                    b.write(a.read())
                saved += 1
                last = dst
            except Exception:
                continue
        return {"saved": saved, "dir": folder, "last": last}

    def copy_pin(self, pin_id):
        """Copies the image to the clipboard (macOS: NSPasteboard; Windows: via PowerShell)."""
        path = self._pin_path(pin_id)
        try:
            if sys.platform == "darwin":
                import AppKit

                img = AppKit.NSImage.alloc().initWithContentsOfFile_(path)
                pb = AppKit.NSPasteboard.generalPasteboard()
                pb.clearContents()
                pb.writeObjects_([img])
            elif os.name == "nt":
                from PIL import Image

                tmp = os.path.join(app_data_dir(), "clip.png")
                with Image.open(path) as im:
                    im.convert("RGBA").save(tmp)
                ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
                      "[System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile('%s'))" % tmp.replace("'", "''"))
                subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], creationflags=0x08000000, timeout=20)
            return True
        except Exception:
            return False

    def reveal_saved(self, path):
        self._reveal(path)

    def open_save_dir(self):
        d = self._settings.get("save_dir") or default_save_dir()
        os.makedirs(d, exist_ok=True)
        self._reveal(d)

    def choose_save_dir(self):
        res = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if res:
            self._settings.set("save_dir", res[0] if isinstance(res, (list, tuple)) else res)
        return self._public_settings()

    def _reveal(self, path):
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
            elif os.name == "nt":
                if os.path.isfile(path):
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                else:
                    os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            pass

    # ---- refreshing ---------------------------------------------------------------
    def refresh(self, start_over=False):
        if self._busy:
            return False
        self._busy = True
        threading.Thread(target=self._refresh, args=(bool(start_over),), daemon=True).start()
        return True

    def _refresh(self, start_over):
        self._emit("busy", {"busy": True})
        result = {"new": 0}
        try:
            cfg = self._cfg()
            pending = []
            last = [0.0]

            def on_pin(name):
                pending.append(name)
                if time.time() - last[0] > 0.6:
                    last[0] = time.time()
                    self._emit("new_pins", {"ids": pending[:]})
                    del pending[:]

            result = feed.refresh(cfg, on_pin=on_pin, start_over=start_over)
            if pending:
                self._emit("new_pins", {"ids": pending[:]})
        except saver.AccessDenied:
            result = {"error": "access"}
        except feed.FeedError as e:
            result = {"error": str(e)}
        except Exception as e:
            result = {"error": "Refresh failed: %s" % e}
        finally:
            self._busy = False
            self._emit("busy", {"busy": False})
            self._emit("refreshed", result)

    # ---- saver settings --------------------------------------------------------------
    def set_config(self, key, value):
        if key not in ("feed", "speed", "clock", "clock24h", "tile"):
            return None
        with self._lock:
            try:
                cfg = self._cfg()
                if key == "feed":
                    value = (value or "").strip() or saver.DEFAULT_FEED
                    if not saver.normalize_feed_url(value):
                        return {"error": "Use a username, username/board, or a Pinterest board link."}
                elif key in ("speed", "tile"):
                    value = float(value)
                else:
                    value = bool(value)
                cfg[key] = value
                saver.save_config(cfg)
                return self._public_cfg(cfg)
            except saver.AccessDenied:
                return {"error": "access"}

    def set_cookie(self, value):
        """Connects (or with '' disconnects) the personal home feed. The cookie never goes back to the UI."""
        with self._lock:
            try:
                cfg = self._cfg()
                v = (value or "").strip()
                if v.lower().startswith("_pinterest_sess="):
                    v = v.split("=", 1)[1]
                cfg["cookie"] = v.split(";", 1)[0].strip()
                saver.save_config(cfg)
                return self._public_cfg(cfg)
            except saver.AccessDenied:
                return {"error": "access"}

    def check_access(self):
        return saver.check_access()

    def open_privacy(self):
        saver.open_privacy_settings()

    # ---- screensaver -------------------------------------------------------------------
    def install_saver(self):
        try:
            return {"ok": True, "text": saver.install_saver(), "saver": saver.saver_state()}
        except Exception as e:
            return {"ok": False, "text": str(e), "saver": saver.saver_state()}

    def start_saver(self):
        saver.start_saver()

    def open_saver_settings(self):
        saver.open_saver_settings()

    # ---- app settings & updates -----------------------------------------------------------
    def set_setting(self, key, value):
        if key in ("auto_check", "auto_install", "welcomed"):
            self._settings.set(key, value)
            if key == "auto_install" and value and self._updater.phase == "available":
                threading.Thread(target=self._updater.stage_newest, daemon=True).start()
        return self._public_settings()

    def check_updates(self):
        return self._updater.check(manual=True)

    def download_update(self):
        threading.Thread(target=self._updater.stage_newest, daemon=True).start()

    def install_update(self):
        def go():
            if self._updater.install() == "open_page":
                self.open_url(self._updater.state()["page"])
        threading.Thread(target=go, daemon=True).start()

    def open_url(self, url):
        allowed = ("https://github.com/YuvrajxGarg/", "https://pin.pxlvzn.in", "https://www.pinterest.com/", "https://pxlvzn.in")
        if any(url.startswith(a) for a in allowed):
            import webbrowser

            webbrowser.open(url)


# ---- native window chrome -------------------------------------------------

def _style_mac(window):
    """Dark, transparent title bar with content running underneath (like Dwn and Tag)."""
    try:
        import AppKit
        from PyObjCTools import AppHelper

        def apply():
            w = window.native
            w.setStyleMask_(w.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
            w.setTitlebarAppearsTransparent_(True)
            w.setTitleVisibility_(AppKit.NSWindowTitleHidden)
            w.setAppearance_(AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua))
            w.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(0.043, 0.043, 0.047, 1.0))
            w.setMovableByWindowBackground_(False)
            try:
                w.contentView().superview().subviews().lastObject().setBackgroundColor_(AppKit.NSColor.clearColor())
            except Exception:
                pass
            if hasattr(w, "setToolbarStyle_"):
                w.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnifiedCompact)

        AppHelper.callAfter(apply)
    except Exception:
        pass


def _style_windows(window):
    """Dark title bar on Windows 10/11; caption colour matches the app on Windows 11."""
    try:
        import ctypes

        hwnd = window.native.Handle.ToInt32()
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
        caption = ctypes.c_int(0x000C0B0B)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)
    except Exception:
        pass


def main():
    api = Api()
    # A newer Pin brings a newer screensaver; keep an installed one in step.
    threading.Thread(target=saver.update_installed_saver, daemon=True).start()
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    window = webview.create_window(
        "Pin", url=os.path.join(UI_DIR, "index.html"), js_api=api,
        width=1180, height=760, min_size=(900, 600), background_color=BG, easy_drag=False,
    )
    api._window = window

    def quit_for_install():
        try:
            window.destroy()
        finally:
            t = threading.Timer(3.0, lambda: os._exit(0))
            t.daemon = True
            t.start()

    api._updater.on_quit_for_install = quit_for_install
    window.events.closing += lambda: api._updater.install_on_quit()
    window.events.loaded += lambda: api._updater.start()
    if sys.platform == "darwin":
        window.events.before_show += lambda: _style_mac(window)
    elif os.name == "nt":
        window.events.shown += lambda: _style_windows(window)
    webview.start(debug=bool(os.environ.get("PIN_DEBUG")))
    if os.name == "nt":
        # Skip Python's normal shutdown on Windows: tearing down pythonnet/WinForms can crash and
        # stall the update swap (same as Tag).
        os._exit(0)


if __name__ == "__main__":
    main()
