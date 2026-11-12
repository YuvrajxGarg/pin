"""Smoke-test a built app: run its CLI against a scratch screensaver folder and check it
reports the right version and carries the screensaver.
    python tests/smoke_app.py <path to Pin executable>
"""
import json
import os
import subprocess
import sys
import tempfile

exe = sys.argv[1]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
want = open(os.path.join(root, "VERSION")).read().strip()
lib = tempfile.mkdtemp()
env = dict(os.environ, PIN_SAVER_LIBRARY=lib)
report = os.path.join(lib, "info.json")
r = subprocess.run([exe, "info", "--out", report], timeout=120, env=env)
assert os.path.isfile(report), "the app wrote no report (exit %s)" % r.returncode
with open(report, encoding="utf-8") as f:
    info = json.load(f)
print(json.dumps(info, indent=2))
assert info["version"] == want, "version %s, expected %s" % (info["version"], want)
assert info["bundled_saver"] and os.path.exists(info["bundled_saver"]), "the screensaver isn't inside the app"
assert info["pins"] == 0
print("smoke test passed: Pin %s with %s" % (info["version"], os.path.basename(info["bundled_saver"])))
