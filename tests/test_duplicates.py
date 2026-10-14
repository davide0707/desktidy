# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Duplicates across the user's folders: what counts as a copy, which copy stays, and that cleaning only ever
sends verified, unchanged copies to the Recycle Bin. Everything inside a temporary folder."""

import io
import os
from contextlib import redirect_stdout
from unittest import mock

from desktidy import cli, config, duplicates, folders, service
from tests.helpers import IsolatedTest

BIG = 600 * 1024   # above the 512 KB minimum


class DuplicateTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config()
        self.recycled = []
        p = mock.patch.object(duplicates.system, "recycle", side_effect=self._recycle)
        p.start()
        self.addCleanup(p.stop)

    def _recycle(self, path):
        self.recycled.append(path)
        os.remove(path)
        return True

    def blob(self, folder, name, content=b"a", size=BIG):
        p = self.path(*folder.split("\\"), name)
        with open(p, "wb") as f:
            f.write((content * (size // len(content) + 1))[:size])
        return p


class TestFind(DuplicateTest):
    def test_identical_files_in_different_folders(self):
        keep = self.blob("home\\Documents\\Travel", "japan.pdf")
        copy = self.blob("home\\Downloads", "japan (1).pdf")
        self.blob("home\\Pictures", "other.pdf", b"b")                     # same size, other bytes
        groups = duplicates.find(self.cfg)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].keep.path, keep)                        # Documents beats Downloads
        self.assertEqual([c.path for c in groups[0].extra], [copy])
        self.assertEqual(groups[0].wasted, BIG)

    def test_same_start_and_end_but_different_middle(self):
        size = 3 * duplicates.PART
        a = bytearray(b"x" * size)
        b = bytearray(a)
        b[size // 2] = ord("y")
        for name, data in (("a.bin", a), ("b.bin", b)):
            with open(self.path("home", "Documents", name), "wb") as f:
                f.write(data * 4)
        self.assertEqual(duplicates.find(self.cfg), [])

    def test_not_compared(self):
        self.blob("home\\Documents", "small.txt", size=1000)
        self.blob("home\\Desktop", "small.txt", size=1000)                 # too small
        self.blob("home\\Documents", "!keep.bin", b"1")
        self.blob("home\\Desktop", "!keep.bin", b"1")                      # hands off
        self.blob("home\\Documents\\app", "lib.bin", b"2")
        self.blob("home\\Documents\\app\\node_modules\\x", "lib.bin", b"2")  # dependencies
        self.blob("home\\Documents\\project", "data.bin", b"3")
        self.blob("home\\Documents\\project", ".git", size=10)
        self.blob("home\\Desktop", "data.bin", b"3")                       # the twin is inside a code project
        self.assertEqual(duplicates.find(self.cfg), [])

    def test_hard_links_are_one_file(self):
        a = self.blob("home\\Documents", "a.bin")
        os.link(a, self.path("home", "Desktop", "a_link.bin"))
        self.assertEqual(duplicates.find(self.cfg), [])

    def test_cloud_only_files_are_never_read(self):
        a = self.blob("home\\Documents", "a.bin")
        self.blob("home\\Desktop", "a.bin")
        with mock.patch.object(duplicates, "cloud_only", side_effect=lambda st: True), \
                mock.patch.object(duplicates, "_digest") as digest:
            self.assertEqual(duplicates.find(self.cfg), [])
        digest.assert_not_called()
        self.assertTrue(os.path.exists(a))

    def test_the_copy_to_keep(self):
        pinned = self.folder("home", "Documents", "Study")
        folders.pin(pinned)
        self.blob("home\\Documents", "notes.pdf")
        self.blob("home\\Documents\\Study", "copy of notes.pdf")
        self.blob("home\\Downloads", "notes.pdf")
        g = duplicates.find(self.cfg)[0]
        self.assertEqual(os.path.dirname(g.keep.path), pinned)            # a pinned folder wins over the name
        self.assertEqual(len(g.extra), 2)
        self.assertTrue(duplicates.COPY_NAME.search("photo (2)"))
        self.assertTrue(duplicates.COPY_NAME.search("relazione_copia"))
        self.assertFalse(duplicates.COPY_NAME.search("Report_2024"))


class TestClean(DuplicateTest):
    def test_recycles_and_logs(self):
        keep = self.blob("home\\Documents", "a.pdf")
        copy = self.blob("home\\Downloads", "a.pdf")
        files, size, notes = duplicates.clean(duplicates.find(self.cfg))
        self.assertEqual((files, size, notes), (1, BIG, []))
        self.assertEqual(self.recycled, [copy])
        self.assertTrue(os.path.exists(keep))
        m = service.read_moves()[-1]
        self.assertEqual((m["action"], m["source"], m["destination"]), ("RECYCLED", copy, keep))

    def test_a_file_changed_since_the_scan_stays(self):
        self.blob("home\\Documents", "a.pdf")
        copy = self.blob("home\\Downloads", "a.pdf")
        groups = duplicates.find(self.cfg)
        with open(copy, "r+b") as f:
            f.write(b"z")                                                  # edited in the meantime
        files, _, notes = duplicates.clean(groups)
        self.assertEqual(files, 0)
        self.assertTrue(os.path.exists(copy))
        self.assertIn("changed since the scan", notes[0])

    def test_the_copy_to_keep_gone_means_nothing_goes(self):
        keep = self.blob("home\\Documents", "a.pdf")
        copy = self.blob("home\\Downloads", "a.pdf")
        groups = duplicates.find(self.cfg)
        os.remove(keep)
        self.assertEqual(duplicates.clean(groups)[0], 0)
        self.assertTrue(os.path.exists(copy))

    def test_open_files_stay(self):
        self.blob("home\\Documents", "a.pdf")
        copy = self.blob("home\\Downloads", "a.pdf")
        with mock.patch.object(duplicates.system, "file_in_use", return_value=True):
            files, _, notes = duplicates.clean(duplicates.find(self.cfg))
        self.assertEqual(files, 0)
        self.assertTrue(os.path.exists(copy))
        self.assertIn("open in a program", notes[0])

    def test_the_command_asks_first(self):
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        self.blob("home\\Documents", "a.pdf")
        copy = self.blob("home\\Downloads", "a.pdf")
        with redirect_stdout(io.StringIO()) as out, mock.patch.object(cli.tidyup, "confirm", return_value=False):
            cli.cmd_duplicates(["clean"])
        self.assertTrue(os.path.exists(copy))
        self.assertIn("Nothing was changed", out.getvalue())
        with redirect_stdout(io.StringIO()) as out:
            cli.cmd_duplicates(["clean", "--yes"])
        self.assertFalse(os.path.exists(copy))
        self.assertIn("1 copy(ies) sent", out.getvalue())
