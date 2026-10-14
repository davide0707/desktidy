# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""The system layer: every platform module offers the whole interface, and the macOS / Linux pieces that are plain
Python (the Trash specification, user-dirs.dirs, .deb packages, .desktop files, launchd agents, API keys, the
`desktidy` command, the lock file) work as specified. Most of them run on every system; a few need a real Unix."""

import importlib
import io
import os
import plistlib
import re
import sys
import tarfile
import time
import unittest
from unittest import mock

from desktidy import config, linux, macos, posix, service, system
from tests.helpers import IsolatedTest


class TestInterface(unittest.TestCase):
    def test_every_system_offers_every_function(self):
        with open(os.path.join(os.path.dirname(system.__file__), "system.py"), encoding="utf-8") as f:
            names = re.findall(r'_get\("(\w+)"\)', f.read())
        self.assertGreater(len(names), 30)
        for module in (linux, macos):
            missing = [n for n in names if not hasattr(module, n) and not hasattr(posix, n)]
            self.assertEqual(missing, [], module.__name__)
        if system.WINDOWS:
            winapi = importlib.import_module("desktidy.winapi")
            self.assertEqual([n for n in names if not hasattr(winapi, n)], [])

    def test_user_folders_are_absolute(self):
        dirs = system.user_dirs()
        self.assertEqual(set(dirs), {"HOME", "DOCS", "DOWNLOADS", "DESKTOP", "PICTURES", "VIDEOS", "MUSIC"})
        self.assertTrue(all(os.path.isabs(p) for p in dirs.values()))
        self.assertTrue(all(p != dirs["HOME"] for k, p in dirs.items() if k != "HOME"))   # never the whole home

    def test_paths(self):
        self.assertEqual(config.native("a\\b/c"), os.path.join("a", "b", "c"))
        self.assertTrue(config.data_dir().is_absolute())


class TestLinuxUserDirs(IsolatedTest):
    def test_parse(self):
        text = ('# written by xdg-user-dirs-update\nXDG_DESKTOP_DIR="$HOME/Scrivania"\n'
                'XDG_DOCUMENTS_DIR="$HOME/Documenti"\nXDG_DOWNLOAD_DIR="/data/Scaricati"\n')
        found = linux.parse_user_dirs(text, "/home/me")
        self.assertEqual(found["XDG_DESKTOP_DIR"], os.path.normpath("/home/me/Scrivania"))
        self.assertEqual(found["XDG_DOWNLOAD_DIR"], os.path.normpath("/data/Scaricati"))

    def test_localised_and_disabled_folders(self):
        home = self.folder("home")
        with open(self.path("cfg", "user-dirs.dirs"), "w", encoding="utf-8") as f:
            f.write('XDG_DOCUMENTS_DIR="$HOME/Documenti"\nXDG_DESKTOP_DIR="$HOME/"\n')
        linux.user_dirs.cache_clear()
        try:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": os.path.join(self.tmp, "cfg")}), \
                    mock.patch("os.path.expanduser", return_value=home):
                dirs = linux.user_dirs()
        finally:
            linux.user_dirs.cache_clear()
        self.assertEqual(dirs["DOCS"], os.path.join(home, "Documenti"))
        self.assertEqual(dirs["DESKTOP"], os.path.join(home, "Desktop"))      # "$HOME/" means disabled
        self.assertEqual(dirs["DOWNLOADS"], os.path.join(home, "Downloads"))  # not listed: the usual name


class TestLinuxTrash(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.share = self.folder("share")
        p = mock.patch.dict(os.environ, {"XDG_DATA_HOME": self.share})
        p.start()
        self.addCleanup(p.stop)

    def test_files_and_folders_go_to_the_trash_with_their_origin(self):
        a = self.write("bill (1).pdf", "x", folder="tmp")
        b = self.write("bill (1).pdf", "y", folder="tmp2")
        folder = self.folder("tmp", "old project")
        self.write("inside.txt", "z", folder="tmp\\old project")
        for p in (a, b, folder):
            self.assertTrue(linux.recycle(p))
            self.assertFalse(os.path.exists(p))
        trash = os.path.join(self.share, "Trash")
        self.assertEqual(sorted(os.listdir(os.path.join(trash, "files"))), ["bill (1).2.pdf", "bill (1).pdf", "old project"])
        with open(os.path.join(trash, "info", "bill (1).pdf.trashinfo"), encoding="utf-8") as f:
            info = f.read()
        self.assertTrue(info.startswith("[Trash Info]\nPath="))
        self.assertIn("bill%20%281%29.pdf", info)                              # URL-encoded, as the spec says
        self.assertRegex(info, r"DeletionDate=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertTrue(os.path.exists(os.path.join(trash, "files", "old project", "inside.txt")))


class TestLinuxPieces(IsolatedTest):
    def test_desktop_exec_quoting(self):
        self.assertEqual(linux.desktop_exec(["/usr/bin/python3", "-m", "desktidy.service"]),
                         "/usr/bin/python3 -m desktidy.service")
        self.assertEqual(linux.desktop_exec(["/home/me/my apps/python", "50%"]), '"/home/me/my apps/python" 50%%')
        self.assertEqual(linux.desktop_exec(['/a"b']), '"/a\\\\"b"')

    def test_autostart_entry(self):
        on = linux.autostart_entry(["/venv/bin/desktidy-service"], "/data")
        self.assertIn("Exec=/venv/bin/desktidy-service\n", on)
        self.assertIn("Hidden=false", on)
        self.assertIn("Hidden=true", linux.autostart_entry(["x"], "/data", enabled=False))

    def test_xdg_autostart_on_off(self):
        cfg_home = self.folder("cfg")
        env = {"XDG_CONFIG_HOME": cfg_home, "DISPLAY": ":0"}
        with mock.patch.dict(os.environ, env), mock.patch.object(linux, "spawn", return_value=True):
            self.assertEqual(linux.autostart_info(), {"exists": False})
            self.assertTrue(linux.autostart_install(["/venv/bin/desktidy-service"], self.tmp))
            self.assertEqual(linux.autostart_info()["enabled"], True)
            self.assertTrue(linux.autostart_enable(False))
            self.assertEqual(linux.autostart_info()["enabled"], False)
            self.assertTrue(linux.autostart_enable(True))
            self.assertTrue(linux.autostart_info()["enabled"])
            self.assertTrue(linux.autostart_remove())
            self.assertFalse(os.path.exists(os.path.join(cfg_home, "autostart", "desktidy.desktop")))

    def test_deb_control(self):
        control = b"Package: code\nVersion: 1.95.0-1730153583\nMaintainer: Microsoft <code@example.com>\n"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            info = tarfile.TarInfo("./control")
            info.size = len(control)
            t.addfile(info, io.BytesIO(control))

        def member(name: str, data: bytes) -> bytes:
            head = f"{name:<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(data):<10}`\n".encode()
            return head + data + (b"\n" if len(data) % 2 else b"")
        p = self.path("dl", "code_1.95.0-1730153583_amd64.deb")
        with open(p, "wb") as f:
            f.write(b"!<arch>\n" + member("debian-binary", b"2.0\n") + member("control.tar.gz", buf.getvalue())
                    + member("data.tar.gz", b"x"))
        self.assertEqual(linux.deb_control(p), {"name": "code", "version": "1.95.0-1730153583",
                                                "company": "Microsoft <code@example.com>"})
        with open(self.path("dl", "fake.deb"), "wb") as f:
            f.write(b"not an archive")
        self.assertEqual(linux.deb_control(self.path("dl", "fake.deb")), {})

    def test_card_ids(self):
        self.assertEqual(linux.serial_of("1A2B-3C4D"), "1A2B3C4D")
        self.assertRegex(linux.serial_of("", "/dev/sdb1/media/me/NIKON"), r"^[0-9A-F]{8}$")
        self.assertEqual(linux._unescape_mount("/media/me/MY\\040CARD"), "/media/me/MY CARD")

    def test_terminal(self):
        with mock.patch.object(linux, "have", side_effect=lambda t: t == "konsole"), \
                mock.patch.dict(os.environ, {"TERMINAL": ""}):
            self.assertEqual(linux.terminal_command(["desktidy", "where"]), ["konsole", "-e", "desktidy", "where"])
        with mock.patch.object(linux, "have", return_value=None), mock.patch.dict(os.environ, {"TERMINAL": ""}):
            self.assertIsNone(linux.terminal_command(["desktidy"]))

    def test_notification_with_buttons(self):
        started = []
        with mock.patch.object(linux, "have", side_effect=lambda t: "/usr/bin/" + t), \
                mock.patch.object(linux, "spawn", side_effect=started.append):
            linux.notify("DeskTidy: 1 item tidied", "a.pdf -> Bills", [("Open", "desktidy:open?id=1a2b3c4d"),
                                                                       ("Undo", "desktidy:undo?ids=1a2b3c4d")])
            linux.notify("Plain", "no buttons")
        script = started[0][2]
        self.assertEqual(started[0][:2], ["sh", "-c"])
        self.assertIn("--action=0=Open", script)
        self.assertIn("1) u='desktidy:undo?ids=1a2b3c4d' ;;", script)
        self.assertIn("-m desktidy.gui url", script)
        self.assertNotIn("--action", " ".join(started[1]))


class TestMacPieces(IsolatedTest):
    def test_launchd_agent(self):
        data = macos.agent(["/venv/bin/desktidy-service"], "/data")
        self.assertEqual(data["Label"], macos.LABEL)
        self.assertTrue(data["RunAtLoad"])
        self.assertEqual(data["KeepAlive"], {"SuccessfulExit": False})   # restarted after a crash, not after a stop
        self.assertIn("/opt/homebrew/bin", data["EnvironmentVariables"]["PATH"])
        self.assertTrue(plistlib.dumps(data).startswith(b"<?xml"))

    def test_user_folders(self):
        self.assertTrue(macos.user_dirs()["VIDEOS"].endswith("Movies"))


class TestPosixPieces(IsolatedTest):
    def test_api_keys_in_a_private_file(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            self.assertIsNone(posix.api_key("GROQ_API_KEY"))
            posix.set_api_key("gsk_" + "x" * 40, "GROQ_API_KEY")
            self.assertEqual(posix.api_key("GROQ_API_KEY"), "gsk_" + "x" * 40)
            if not system.WINDOWS:
                self.assertEqual(os.stat(config.path("keys")).st_mode & 0o777, 0o600)
            posix.set_api_key(None, "GROQ_API_KEY")
            self.assertIsNone(posix.api_key("GROQ_API_KEY"))
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "from-env"}):
            self.assertEqual(posix.api_key("GROQ_API_KEY"), "from-env")

    def test_command_in_local_bin(self):
        home = self.folder("home")
        env = {"HOME": home, "USERPROFILE": home, "SHELL": "/bin/bash", "PATH": os.defpath}
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "platform", "linux"):
            self.assertTrue(posix.install_command([sys.executable, "-m", "desktidy"]))
            target = os.path.join(home, ".local", "bin", "desktidy")
            with open(target, encoding="utf-8") as f:
                self.assertIn("-m desktidy", f.read())
            with open(os.path.join(home, ".bashrc"), encoding="utf-8") as f:
                self.assertIn(".local/bin", f.read())
            self.assertTrue(posix.uninstall_command())
            self.assertFalse(os.path.exists(target))
            with open(os.path.join(home, ".bashrc"), encoding="utf-8") as f:
                self.assertNotIn(posix.MARK, f.read())

    def test_ocr_languages(self):
        with mock.patch.dict(os.environ, {"LANG": "it_IT.UTF-8", "LC_ALL": "", "LC_MESSAGES": "", "LANGUAGE": ""}):
            self.assertEqual(posix.ocr_languages({"eng", "ita", "osd"}), "ita+eng")
            self.assertEqual(posix.ocr_languages({"eng"}), "eng")

    @unittest.skipIf(system.WINDOWS, "a lock file is the macOS / Linux single instance")
    def test_single_instance_lock(self):
        name = "DeskTidyTest"
        self.assertFalse(posix.instance_running(name))
        self.assertTrue(posix.claim_single_instance(name))
        try:
            self.assertTrue(posix.instance_running(name))
            self.assertEqual(posix.instance_pid(name), os.getpid())
            self.assertFalse(posix.claim_single_instance(name))
        finally:
            os.close(posix._held.pop(name))
        self.assertFalse(posix.instance_running(name))


class TestServiceOnEverySystem(IsolatedTest):
    def test_shortcuts_launchers_and_hidden_files_are_skipped(self):
        folder = self.folder("in")
        for name in ("ok.txt", "app.desktop", "site.webloc", ".hidden.txt", ".DS_Store"):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                f.write("x")
        skipped = {e.name for e in os.scandir(folder) if service.Service.ignored(e, {})}
        self.assertIn("app.desktop", skipped)
        self.assertIn("site.webloc", skipped)
        self.assertIn(".DS_Store", skipped)
        self.assertNotIn("ok.txt", skipped)
        if not system.WINDOWS:
            self.assertIn(".hidden.txt", skipped)

    def test_move_to_another_disk_is_a_checked_copy(self):
        src = self.write("report.txt", "data " * 100)
        with mock.patch.object(service, "_same_disk", return_value=False):
            action, final = service.move(src, self.folder("other_disk"), "report.txt", False)
        self.assertEqual(action, "MOVED")
        self.assertFalse(os.path.exists(src))
        with open(final, encoding="utf-8") as f:
            self.assertEqual(f.read(), "data " * 100)

    def test_stop_signal(self):
        svc = service.Service(service.Options())
        svc.stopping = True
        start = time.time()
        self.assertFalse(svc.wait(30))
        self.assertLess(time.time() - start, 2)
