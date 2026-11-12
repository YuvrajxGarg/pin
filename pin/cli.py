"""Command line:  Pin info | Pin list | Pin refresh [--start-over] | Pin install-saver"""

import argparse
import json
import sys

from . import __version__, feed, saver


def main(argv=None):
    ap = argparse.ArgumentParser(prog="Pin", description="Pin: your Pinterest feed as a screensaver.")
    sub = ap.add_subparsers(dest="cmd")
    i = sub.add_parser("info", help="version, screensaver and source")
    i.add_argument("--out", help="write the JSON to this file (the Windows app has no console)")
    sub.add_parser("list", help="cached pins for the current source")
    r = sub.add_parser("refresh", help="fetch new pins now")
    r.add_argument("--start-over", action="store_true", help="drop cached pins first")
    sub.add_parser("install-saver", help="install the bundled screensaver")
    a = ap.parse_args(argv)

    if a.cmd == "info":
        out = {"version": __version__, "saver": saver.saver_state(), "bundled_saver": saver.bundled_saver()}
        try:
            cfg = saver.load_config()
            out["source"] = saver.describe_source(cfg)
            out["pins"] = len(saver.list_pins(cfg))
            out["hidden"] = len(cfg.get("hidden") or [])
        except saver.AccessDenied:
            out["access"] = False
        text = json.dumps(out, indent=2)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(text)
        print(text)
        return 0
    if a.cmd == "list":
        cfg = saver.load_config()
        for p in saver.list_pins(cfg):
            print(("hidden  " if p["hidden"] else "        ") + p["path"])
        return 0
    if a.cmd == "refresh":
        cfg = saver.load_config()
        try:
            res = feed.refresh(cfg, start_over=a.start_over)
        except feed.FeedError as e:
            print(e, file=sys.stderr)
            return 1
        print("%d new pins" % res["new"])
        return 0
    if a.cmd == "install-saver":
        print(saver.install_saver())
        return 0
    ap.print_help()
    return 0
