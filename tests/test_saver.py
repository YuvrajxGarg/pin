import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pin import feed, saver  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


class Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"PIN_SAVER_LIBRARY": self.dir})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)


class FeedUrlTests(unittest.TestCase):
    def test_normalize(self):
        n = saver.normalize_feed_url
        self.assertEqual(n("nasa"), "https://www.pinterest.com/nasa/feed.rss")
        self.assertEqual(n("nasa/space/"), "https://www.pinterest.com/nasa/space.rss")
        self.assertEqual(n("https://www.pinterest.com/nasa/space-pics/"), "https://www.pinterest.com/nasa/space-pics.rss")
        self.assertEqual(n("https://in.pinterest.com/nasa/"), "https://www.pinterest.com/nasa/feed.rss")
        self.assertEqual(n("www.pinterest.com/nasa/feed.rss"), "https://www.pinterest.com/nasa/feed.rss")
        self.assertIsNone(n("  "))

    def test_cache_key_matches_the_screensaver(self):
        # The Swift and C# savers hash the normalized URL; this value comes from the Swift build.
        cfg = {"feed": "pinterest", "cookie": ""}
        self.assertEqual(saver.source_key(cfg), "b07377cc1e860678167e68a4db9a3557")
        self.assertEqual(saver.source_key({"feed": "x", "cookie": "abc"}), "home")

    def test_extract_and_upgrade(self):
        text = ('<img src="https://i.pinimg.com/236x/ab/cd/ef/abcdef.jpg"> '
                'https:\\/\\/i.pinimg.com\\/originals\\/12\\/34\\/x.png https://i.pinimg.com/236x/ab/cd/ef/abcdef.jpg')
        urls = feed.extract_image_urls(text)
        self.assertEqual(len(urls), 2)
        self.assertEqual(feed.hi_res(urls[0]), "https://i.pinimg.com/736x/ab/cd/ef/abcdef.jpg")
        self.assertEqual(feed.hi_res(urls[1]), "https://i.pinimg.com/736x/12/34/x.png")

    def test_cookie_header(self):
        self.assertEqual(feed.cookie_header("abc=="), "_pinterest_sess=abc==")
        self.assertEqual(feed.cookie_header("_pinterest_sess=abc; x=1"), "_pinterest_sess=abc; x=1")


class ConfigTests(Scratch):
    def test_round_trip_keeps_unknown_keys(self):
        path = saver.config_path()
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            json.dump({"feed": "nasa", "speed": 40, "hiddenPins": ["a.img"], "futureKey": 1}, f)
        cfg = saver.load_config()
        self.assertEqual(cfg["speed"], 40)
        self.assertEqual(cfg["hidden"], ["a.img"])
        self.assertTrue(cfg["clock"])  # default
        cfg["hidden"] = ["a.img", "b.img"]
        saver.save_config(cfg)
        with open(path) as f:
            raw = json.load(f)
        self.assertEqual(raw["hiddenPins"], ["a.img", "b.img"])
        self.assertEqual(raw["futureKey"], 1)

    def test_windows_keys(self):
        with mock.patch.object(saver, "_windows_keys", return_value=True):
            cfg = saver.load_config()
            cfg["tile"] = 400.0
            cfg["hidden"] = ["z.img"]
            saver.save_config(cfg)
            with open(saver.config_path()) as f:
                raw = json.load(f)
            self.assertEqual(raw["TileSize"], 400.0)
            self.assertEqual(raw["HiddenPins"], ["z.img"])
            self.assertNotIn("hiddenPins", raw)

    def test_list_and_trim(self):
        cfg = saver.load_config()
        d = saver.cache_dir(cfg)
        os.makedirs(d)
        for i in range(5):
            p = os.path.join(d, "%d.img" % i)
            with open(p, "wb") as f:
                f.write(JPEG)
            os.utime(p, (1000 + i, 1000 + i))
        cfg["hidden"] = ["4.img"]
        pins = saver.list_pins(cfg)
        self.assertEqual([p["id"] for p in pins], ["4.img", "3.img", "2.img", "1.img", "0.img"])
        self.assertTrue(pins[0]["hidden"])
        saver.trim_cache(d, keep=3, hidden=cfg["hidden"])
        left = sorted(os.listdir(d))
        self.assertEqual(left, ["1.img", "2.img", "3.img"])

    def test_refresh_skips_hidden_and_downloads_new(self):
        cfg = saver.load_config()
        hidden_url = "https://i.pinimg.com/736x/aa/hidden.jpg"
        cfg["hidden"] = [saver.md5(hidden_url) + ".img"]
        body = ("https://i.pinimg.com/236x/aa/one.jpg https://i.pinimg.com/236x/aa/hidden.jpg").encode()

        def fake_get(url, headers=None, timeout=20):
            if url.endswith(".rss"):
                return 200, body
            return 200, JPEG

        with mock.patch.object(feed, "_get", side_effect=fake_get):
            r = feed.refresh(cfg)
            self.assertEqual(r["new"], 1)
            r = feed.refresh(cfg)
            self.assertEqual(r["new"], 0)
        names = os.listdir(saver.cache_dir(cfg))
        self.assertEqual(names, [saver.md5("https://i.pinimg.com/736x/aa/one.jpg") + ".img"])


class ApiTests(Scratch):
    def setUp(self):
        super().setUp()
        self.appdata = tempfile.mkdtemp()
        self.p2 = mock.patch("pin.settings.app_data_dir", return_value=self.appdata)
        self.p2.start()
        self.p3 = mock.patch("pin.webapp.app_data_dir", return_value=self.appdata)
        self.p3.start()
        self.p4 = mock.patch("pin.updater.app_data_dir", return_value=self.appdata)
        self.p4.start()

    def tearDown(self):
        for p in (self.p2, self.p3, self.p4):
            p.stop()
        shutil.rmtree(self.appdata, ignore_errors=True)
        super().tearDown()

    def test_state_thumbs_hide_save(self):
        try:
            from PIL import Image
            from pin import webapp
        except ImportError:
            self.skipTest("needs pywebview and Pillow")
        cfg = saver.load_config()
        d = saver.cache_dir(cfg)
        os.makedirs(d)
        Image.new("RGB", (300, 450), (200, 40, 40)).save(os.path.join(d, "a.img"), "JPEG")
        Image.new("RGB", (300, 300), (40, 200, 40)).save(os.path.join(d, "b.img"), "PNG")
        api = webapp.Api()
        st = api.state()
        self.assertTrue(st["access"])
        self.assertEqual(len(st["pins"]), 2)
        self.assertNotIn("cookie", json.dumps(st["config"]))
        th = api.thumbs(["a.img", "../../etc/passwd"])
        self.assertAlmostEqual(th["a.img"]["ratio"], 1.5)
        self.assertIsNone(th["../../etc/passwd"])
        self.assertTrue(api.set_hidden(["a.img"], True)["ok"])
        self.assertEqual(saver.load_config()["hidden"], ["a.img"])
        api.set_hidden(["a.img"], False)
        self.assertEqual(saver.load_config()["hidden"], [])
        out = tempfile.mkdtemp()
        api._settings.set("save_dir", out)
        r = api.save_pins(["a.img", "b.img"])
        self.assertEqual(r["saved"], 2)
        self.assertEqual(sorted(os.path.splitext(n)[1] for n in os.listdir(out)), [".jpg", ".png"])
        shutil.rmtree(out)


if __name__ == "__main__":
    unittest.main()
