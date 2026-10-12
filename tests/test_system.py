"""System-facing features, tested without touching the real system: installers already installed (fake program
list), the archive, photo import (a fake memory card), the right-click menu (Windows: under a test registry key;
Linux: in a temporary folder), the desktidy: links, the settings editor (a real local server), the tray menu and
the update check (no network)."""

import io
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from unittest import mock

from desktidy import archive, config, editor, explorer, folders, importer, installers, service, system, tray, updates
from tests.helpers import IsolatedTest

OLD = time.time() - 60 * 86400


class TestInstallers(IsolatedTest):
    programs = [{"name": "GitHub Desktop", "version": "3.5.3", "publisher": "GitHub"},
                {"name": "Python 3.14.0 (64-bit)", "version": "3.14.150.0", "publisher": "PSF"},
                {"name": "Python Launcher", "version": "3.14.150.0", "publisher": "PSF"},
                {"name": "UltiMaker Cura", "version": "5.12.0", "publisher": "UltiMaker"}]

    def installer(self, name, days_old=30):
        p = self.path("dest", "Installers", name)
        with open(p, "wb") as f:
            f.write(b"\0" * 1_100_000)
        os.utime(p, (time.time() - days_old * 86400,) * 2)
        return p

    def test_similarity(self):
        self.assertGreaterEqual(installers.similarity(["GitHubDesktopSetup-x64"], "GitHub Desktop"), 0.6)
        self.assertGreaterEqual(installers.similarity(["Visual Studio Code"], "Microsoft Visual Studio Code (User)"), 0.6)
        self.assertLess(installers.similarity(["CMake"], "UltiMaker Cura"), 0.6)
        self.assertLess(installers.similarity(["Python 3.13.7 (64-bit)"], "Python Launcher"), 0.6)
        self.assertLess(installers.similarity(["STM32CubeIDE"], "STM32CubeProgrammer"), 0.6)

    def test_find(self):
        cfg = self.config()
        self.installer("GitHubDesktopSetup-x64.exe")
        self.installer("python-3.12.10-amd64.exe")
        self.installer("cmake-4.1.2-windows-x86_64.exe")                   # not installed
        self.installer("UltiMaker-Cura-5.13.0-win64.exe")                  # newer than installed: kept
        self.installer("Perplexity Setup 1.6.0.exe", days_old=1)           # just downloaded: kept
        with mock.patch.object(installers.system, "INSTALLER_EXT", {".exe", ".msi"}):   # Windows installers, anywhere
            found = {os.path.basename(c.path): c for c in installers.find(cfg, self.programs)}
        self.assertEqual(sorted(found), ["GitHubDesktopSetup-x64.exe", "python-3.12.10-amd64.exe"])
        self.assertEqual(found["python-3.12.10-amd64.exe"].installed, "Python 3.14.0 (64-bit)")
        self.assertFalse(found["python-3.12.10-amd64.exe"].same_version)
        with mock.patch.object(installers.system, "recycle", side_effect=lambda p: os.remove(p) or True):
            files, size = installers.clean(list(found.values()))
        self.assertEqual(files, 2)
        self.assertEqual([m["action"] for m in service.read_moves()], ["RECYCLED", "RECYCLED"])

    def test_mac_and_linux_installers(self):
        cfg = self.config()
        self.installer("Firefox 131.0.dmg")
        self.installer("code_1.95.0-1730153583_amd64.deb")
        self.installer("zoom_x86_64.rpm")                                   # not installed
        programs = [{"name": "Firefox", "version": "131.0", "publisher": "org.mozilla.firefox"},
                    {"name": "code", "version": "1.96.2-1734607745", "publisher": "Microsoft"}]
        with mock.patch.object(installers.system, "INSTALLER_EXT", {".dmg", ".pkg", ".deb", ".rpm"}), \
                mock.patch.object(installers.system, "installer_product", return_value={}):
            found = {os.path.basename(c.path): c for c in installers.find(cfg, programs)}
        self.assertEqual(sorted(found), ["Firefox 131.0.dmg", "code_1.95.0-1730153583_amd64.deb"])
        self.assertTrue(found["Firefox 131.0.dmg"].same_version)
        self.assertFalse(found["code_1.95.0-1730153583_amd64.deb"].same_version)   # 1.96 is installed


class TestArchive(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.desk = self.folder("Desktop")
        self.cfg = self.config(archive={"enabled": True, "after_days": 30, "folder": "{D}\\Archive",
                                        "sources": [self.desk]})

    def item(self, name, old=True, folder=False):
        p = os.path.join(self.desk, name)
        if folder:
            os.makedirs(p)
            self.write("inside.txt", "x", folder=os.path.join("Desktop", name))
            os.utime(os.path.join(p, "inside.txt"), (OLD,) * 2 if old else (time.time(),) * 2)
        else:
            with open(p, "w", encoding="utf-8") as f:
                f.write("x")
        os.utime(p, (OLD,) * 2 if old else (time.time(),) * 2)
        return p

    def test_candidates_and_run(self):
        self.item("old.txt")
        self.item("new.txt", old=False)
        self.item("!keep.txt")
        self.item("Old project", folder=True)
        self.item("Busy project", folder=True, old=False)
        pinned = self.item("Pinned", folder=True)
        folders.pin(pinned)
        names = sorted(os.path.basename(p) for p, _, _ in archive.candidates(self.cfg))
        self.assertEqual(names, ["Old project", "old.txt"])
        lines = archive.run(self.cfg)
        year = str(datetime.fromtimestamp(OLD).year)
        self.assertEqual(len(lines), 2)
        self.assertEqual(sorted(os.listdir(self.dest("Archive", year))), ["Old project", "old.txt"])
        self.assertEqual({m["action"] for m in service.read_moves()}, {"ARCHIVED"})

    def test_zip_and_undo(self):
        from desktidy import cli
        p = self.item("Old project", folder=True)
        cfg = self.config(archive={"enabled": True, "after_days": 30, "folder": "{D}\\Archive", "zip": True,
                                   "sources": [self.desk]})
        action, final = archive.archive_one(p, True, OLD, cfg)
        self.assertEqual(action, "ARCHIVED_ZIP")
        self.assertTrue(final.endswith("Old project.zip") and os.path.exists(final))
        self.assertFalse(os.path.exists(p))
        restored = cli.undo_move(service.read_moves()[-1])
        self.assertEqual(restored, p)
        self.assertTrue(os.path.exists(os.path.join(p, "inside.txt")))
        self.assertFalse(os.path.exists(final))


class TestImport(IsolatedTest):
    def card(self):
        from PIL import Image
        root = self.folder("card")
        dcim = self.folder("card", "DCIM", "100CANON")
        exif = Image.Exif()
        exif[306] = "2025:07:14 10:20:30"
        Image.new("RGB", (64, 48), (200, 100, 50)).save(os.path.join(dcim, "IMG_0001.JPG"), exif=exif)
        with open(os.path.join(dcim, "MVI_0002.MP4"), "wb") as f:
            f.write(b"\0" * 2048)
        os.utime(os.path.join(dcim, "MVI_0002.MP4"), (datetime(2025, 8, 1).timestamp(),) * 2)
        return root

    def test_copy_sorted_by_date_once(self):
        root = self.card()
        cfg = self.config(**{"import": {"photos": "{D}\\Pictures", "videos": "{D}\\Videos"}})
        self.assertEqual(len(importer.new_media(root, cfg)), 2)
        s = importer.run(root, cfg)
        self.assertEqual((s["copied"], s["failed"]), (2, 0))
        self.assertTrue(os.path.exists(self.dest("Pictures", "2025", "2025-07", "IMG_0001.JPG")))
        self.assertTrue(os.path.exists(self.dest("Videos", "2025", "2025-08", "MVI_0002.MP4")))
        self.assertTrue(os.path.exists(os.path.join(root, "DCIM", "100CANON", "IMG_0001.JPG")))  # the card is untouched
        self.assertEqual(importer.new_media(root, cfg), [])
        self.assertEqual(importer.run(root, cfg)["copied"], 0)

    def test_cards(self):
        root = self.card()
        with mock.patch.object(importer.system, "removable_drives",
                               return_value=[{"id": "E", "name": "E:", "label": "EOS", "serial": "1A2B", "root": root},
                                             {"id": "F", "name": "F:", "label": "USB", "serial": "3C4D",
                                              "root": self.folder("usb")}]):
            self.assertEqual([c["id"] for c in importer.cards({})], ["E"])

    def test_import_from_a_link(self):
        from desktidy import cli
        root = self.card()
        cfg = self.config(**{"import": {"photos": "{D}\\Pictures", "videos": "{D}\\Videos"}})
        os.replace(cfg.source, config.path("rules"))
        card = {"id": "1A2B3C4D", "name": "EOS", "label": "EOS", "serial": "1A2B3C4D", "root": root}
        with mock.patch.object(importer.system, "removable_drives", return_value=[card]), \
                mock.patch.object(cli.system, "notify"), mock.patch.object(cli.ui, "GUI", True), \
                mock.patch("sys.stdout", io.StringIO()):
            cli.run(["url", "desktidy:import?card=1A2B3C4D"])
        self.assertTrue(os.path.exists(self.dest("Pictures", "2025", "2025-07", "IMG_0001.JPG")))


@unittest.skipUnless(system.WINDOWS, "the Explorer menu lives in the Windows registry")
class TestExplorer(IsolatedTest):
    ROOT = "Software\\DeskTidyTest\\Classes"

    def tearDown(self):
        from desktidy import winapi
        winapi.reg_delete_tree("Software\\DeskTidyTest")
        super().tearDown()

    def test_install_and_uninstall(self):
        from desktidy import winapi
        explorer.install(self.ROOT)
        self.assertTrue(explorer.installed(self.ROOT))
        command = winapi.reg_read(f"{self.ROOT}\\*\\shell\\DeskTidy\\shell\\1tidy\\command")
        self.assertIn('tidy "%1"', command)
        self.assertEqual(winapi.reg_read(f"{self.ROOT}\\desktidy", "URL Protocol"), "")
        self.assertTrue(explorer.uninstall(self.ROOT))
        self.assertFalse(explorer.installed(self.ROOT))
        self.assertFalse(explorer.uninstall(self.ROOT))

    def test_organize_on_folders_and_backgrounds(self):
        from desktidy import winapi
        stale = f"{self.ROOT}\\Directory\\shell\\DeskTidy\\shell\\3versions"     # the layout of an older version
        winapi.reg_write(stale, {"MUIVerb": "Old versions here..."})
        explorer.install(self.ROOT)
        self.assertIsNone(winapi.reg_read(stale, "MUIVerb"))                      # reinstalling leaves nothing old
        self.assertIn('organize "%1" --pause',
                      winapi.reg_read(f"{self.ROOT}\\Directory\\shell\\DeskTidy\\shell\\3organize\\command"))
        for target in ("Directory\\Background", "DesktopBackground"):
            self.assertIn('organize "%V" --pause',
                          winapi.reg_read(f"{self.ROOT}\\{target}\\shell\\DeskTidy\\shell\\1organize\\command"))
        explorer.uninstall(self.ROOT)
        for target in explorer.MENU_TARGETS:
            self.assertIsNone(winapi.reg_read(f"{self.ROOT}\\{target}\\shell\\DeskTidy", "MUIVerb"), target)


class TestLinks(IsolatedTest):
    def test_links_are_checked(self):
        self.assertEqual(explorer.parse_url("desktidy:undo?ids=1a2b3c4d,0f0f0f0f"), ("undo", {"ids": "1a2b3c4d,0f0f0f0f"}))
        self.assertEqual(explorer.parse_url('"desktidy:where"'), ("where", {}))
        self.assertEqual(explorer.parse_url("desktidy:import?drive=E"), ("import", {"drive": "E"}))
        self.assertEqual(explorer.parse_url("desktidy:import?card=1A2B3C4D"), ("import", {"card": "1A2B3C4D"}))
        for bad in ("desktidy:delete?path=C:\\Windows", "desktidy:open?id=../../x", "desktidy:import?drive=C:\\x",
                    "http://evil/desktidy:undo", "desktidy:undo?ids=*", "desktidy:import?card=/etc/passwd"):
            self.assertIsNone(explorer.parse_url(bad), bad)


class TestLinuxMenus(IsolatedTest):
    def test_files_for_nautilus_nemo_dolphin(self):
        files = explorer.linux_menus(self.tmp)
        names = {os.path.relpath(p, self.tmp).replace(os.sep, "/") for p in files}
        self.assertIn("nautilus/scripts/DeskTidy/Tidy now", names)
        self.assertIn("nemo/actions/desktidy-explain.nemo_action", names)
        self.assertIn("kio/servicemenus/desktidy.desktop", names)
        script = files[os.path.join(self.tmp, "nautilus", "scripts", "DeskTidy", "Explain")]
        self.assertTrue(script.startswith("#!/bin/sh"))
        self.assertIn("terminal explain", script)
        dolphin = files[os.path.join(self.tmp, "kio", "servicemenus", "desktidy.desktop")]
        self.assertIn("X-KDE-Submenu=DeskTidy", dolphin)
        self.assertIn("pin-toggle %f", dolphin)
        organize = files[os.path.join(self.tmp, "nautilus", "scripts", "DeskTidy", "Organize this folder")]
        self.assertIn("terminal organize", organize)
        nemo = files[os.path.join(self.tmp, "nemo", "actions", "desktidy-organize.nemo_action")]
        self.assertIn("Extensions=dir;", nemo)


class TestEditor(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.config(ai={"mode": "limited", "provider": "groq"})
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        self.server = editor.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, path, body=None, token=True, host=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-DeskTidy-Token"] = self.server.token
        if host:
            headers["Host"] = host
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers=headers, method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as ex:
            with ex:
                return ex.code, ex.read().decode()

    def test_security(self):
        self.assertEqual(self.call("/")[0], 403)                                     # no token in the address
        status, page = self.call(f"/?t={self.server.token}")
        self.assertEqual(status, 200)
        self.assertIn(self.server.token, page)
        self.assertEqual(self.call("/api/state", token=False)[0], 403)
        self.assertEqual(self.call("/api/state", host="evil.example:80")[0], 403)    # DNS rebinding
        self.assertEqual(self.call("/api/save", {"rules": []}, token=False)[0], 403)

    def test_state_validate_save(self):
        status, body = self.call("/api/state")
        data = json.loads(body)["rules"]
        self.assertEqual(status, 200)
        bad = dict(data, rules=[{"name": "", "destination": ""}])
        status, body = self.call("/api/save", bad)
        self.assertEqual(status, 422)
        self.assertTrue(json.loads(body)["errors"])
        data["limits"] = {"files_per_day": 25}
        data["ai"]["max_files_per_day"] = "unlimited"
        status, body = self.call("/api/save", data)
        self.assertEqual(status, 200, body)
        saved = config.load_config()
        self.assertEqual(config.tidy_limit(saved), 25)
        self.assertIsNone(config.daily_limit(saved))
        self.assertTrue(os.path.exists(config.path("rules") + ".bak"))

    def test_organize_and_history_from_the_browser(self):
        from desktidy import ai, organize
        self.config(watched_folders=[{"path": "{DESKTOP}", "include_folders": False}],
                    ai={"mode": "limited", "provider": "groq"})                     # the Desktop is watched
        desktop = self.folder("home", "Desktop")
        for i in range(4):
            self.write(f"thesis_chapter_{i}.txt", "Thesis chapter on renewable energy policy. " * 20,
                       folder="home\\Desktop")
        for i in range(8):
            self.write(f"misc_{i}.txt", f"unrelated note number {i} " * 3, folder="home\\Desktop")
        no_ai = [mock.patch.object(ai, "ready", return_value=None),                  # never the real service
                 mock.patch.object(ai, "complete", side_effect=AssertionError("no AI in tests"))]
        for p in no_ai:
            p.start()
            self.addCleanup(p.stop)
        status, body = self.call("/api/organize")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertFalse(state["ai"]["ready"])
        self.assertIn(desktop, [s["path"] for s in state["spots"]])
        self.assertNotIn("key", json.dumps(state["ai"]).lower().replace("masked", ""))
        status, body = self.call("/api/organize/plan", {"folder": desktop, "offline": True})
        self.assertEqual(status, 200, body)
        groups = json.loads(body)["plan"]["groups"]
        n = next(i for i, g in enumerate(groups, 1) if "thesis" in g["title"].lower())
        status, body = self.call("/api/organize/preview", {"numbers": [n]})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["moves"], 4)
        self.assertEqual(sum(1 for x in os.listdir(desktop) if x.startswith("thesis")), 4)  # a preview moves nothing
        status, body = self.call("/api/organize/apply", {"numbers": [n]})
        self.assertEqual((status, json.loads(body)["moved"]), (200, 4))
        self.assertEqual(sum(1 for x in os.listdir(desktop) if x.startswith("thesis")), 0)
        moves = json.loads(self.call("/api/history")[1])["moves"]
        self.assertTrue(all(m["undoable"] for m in moves))
        status, body = self.call("/api/undo", {"id": moves[0]["id"]})
        self.assertEqual(status, 200, body)
        self.assertTrue(os.path.exists(json.loads(body)["restored"]))
        status, body = self.call("/api/organize/undo", {})                          # the rest comes back too
        self.assertEqual(status, 200, body)
        self.assertEqual(len(json.loads(body)["skipped"]), 1)                       # the one already back
        self.assertEqual(sum(1 for x in os.listdir(desktop) if x.startswith("thesis")), 4)
        self.assertEqual(organize.load()["groups"][n - 1].get("applied"), None)

    def test_organize_and_history_refuse(self):
        self.assertEqual(self.call("/api/history", token=False)[0], 403)
        self.assertEqual(self.call("/api/organize/apply", {"numbers": [1]}, token=False)[0], 403)
        self.assertEqual(self.call("/api/undo", {"id": "../../x"})[0], 422)
        self.assertEqual(self.call("/api/undo", {"id": "0123abcd"})[0], 404)
        self.assertEqual(self.call("/api/organize/plan", {"folder": "C:\\does\\not\\exist"})[0], 422)
        self.assertEqual(self.call("/api/organize/plan", {"folder": str(config.data_dir())})[0], 422)
        self.assertEqual(self.call("/api/organize/preview", {"numbers": [1]})[0], 422)   # no plan
        self.assertEqual(self.call("/api/organize/undo", {})[0], 409)
        self.assertEqual(self.call("/api/mkdir", ["a", "list"])[0], 400)              # not an object: no crash

    def test_validate(self):
        errors, warnings = editor.validate({"rules": [{"name": "X", "destination": "{NOPE}\\x"}], "watched_folders": [],
                                            "variables": {}, "default_destination": "C:\\x", "ai": {"mode": "always"}})
        self.assertTrue(any("unknown variable" in e for e in errors))
        self.assertTrue(any("unknown AI mode" in e for e in errors))
        self.assertTrue(any("never matches" in w for w in warnings))


class TestTray(IsolatedTest):
    def labels(self, model):
        out = []
        for entry in model:
            if entry is None:
                continue
            out.append(entry[0])
            if isinstance(entry[1], list):
                out += self.labels(entry[1])
        return out

    def test_menu_and_actions(self):
        self.config()
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        service.record("MOVED", "C:\\in\\a.pdf", "C:\\out\\Bills\\a.pdf", "test")
        labels = self.labels(tray.menu_model())
        self.assertIn("Pause for 1 hour", labels)
        self.assertTrue(any("a.pdf" in x for x in labels))
        tray.run_action(("pause", "1h"))
        self.assertTrue(service.paused_until()[0])
        self.assertIn("Resume", self.labels(tray.menu_model()))
        tray.run_action(("resume",))
        self.assertFalse(service.paused_until()[0])


class TestUpdates(IsolatedTest):
    def test_versions(self):
        self.assertTrue(updates.newer("1.10.0", "1.9.3"))
        self.assertFalse(updates.newer("1.2.0", "1.2.0"))
        self.assertFalse(updates.newer("", "1.2.0"))

    def test_check_notifies_once(self):
        release = json.dumps({"tag_name": "v99.0.0", "html_url": "https://example.org/r", "body": "news"}).encode()
        sent = []
        with mock.patch.object(updates.urllib.request, "urlopen", return_value=io.BytesIO(release)) as urlopen:
            urlopen.return_value.__enter__ = lambda s: s
            urlopen.return_value.__exit__ = lambda *a: False
            self.assertEqual(updates.check(lambda *a: sent.append(a))["version"], "99.0.0")
            urlopen.return_value = io.BytesIO(release)
            urlopen.return_value.__enter__ = lambda s: s
            urlopen.return_value.__exit__ = lambda *a: False
            updates.check(lambda *a: sent.append(a))
        self.assertEqual(len(sent), 1)
        self.assertFalse(updates.due({}))                                  # checked just now
        seen = config.read_json(config.path("updates"))
        seen["checked"] = (datetime.now() - timedelta(days=8)).isoformat()
        config.write_json(config.path("updates"), seen)
        self.assertTrue(updates.due({}))
        self.assertFalse(updates.due({"updates": {"check": False}}))

    def test_offline(self):
        with mock.patch.object(updates.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
            self.assertIsNone(updates.latest())
