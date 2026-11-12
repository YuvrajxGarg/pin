"""Runs Pin's real Python API behind a local web server so the UI can be checked in a browser.

    PIN_SAVER_LIBRARY=/tmp/pin-lib python tools/dev_server.py 5198
    open http://127.0.0.1:5198/

Every pywebview call becomes POST /api/<method> with a JSON list of arguments, and
events Python sends (App.on) are polled from /events. Development only.
"""

import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pin import webapp  # noqa: E402

UI = os.path.join(ROOT, "pin", "ui")
events, lock = [], threading.Lock()


class FakeWindow(object):
    def evaluate_js(self, code):
        with lock:
            events.append(code)

    def create_file_dialog(self, *a, **k):
        return None


api = webapp.Api()
api._window = FakeWindow()

SHIM = """<script>
window.pywebview = { api: new Proxy({}, { get: (_, m) => (...args) =>
  fetch('/api/' + m, { method: 'POST', body: JSON.stringify(args) }).then(r => r.json()) }) };
setInterval(() => fetch('/events').then(r => r.json()).then(list => list.forEach(c => eval(c))), 300);
</script>"""


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=UI, **k)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/events":
            with lock:
                out, events[:] = events[:], []
            return self._json(out)
        if self.path in ("/", "/index.html"):
            with open(os.path.join(UI, "index.html"), encoding="utf-8") as f:
                html = f.read().replace('<script src="app.js">', SHIM + '<script src="app.js">')
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self):
        name = self.path.rsplit("/", 1)[-1]
        args = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"[]")
        if name.startswith("_") or not hasattr(api, name):
            return self._json({"error": "no such method"}, 404)
        try:
            return self._json(getattr(api, name)(*args))
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5198
    print("Pin dev server on http://127.0.0.1:%d/" % port, flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
