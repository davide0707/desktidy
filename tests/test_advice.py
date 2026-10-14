# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Organisation advice: the overview of the folders (what the AI would read), the offline findings, when the advice
is due and the parsing of the tips. No network: the request itself is tested in test_providers."""

import json
from datetime import datetime, timedelta
from unittest import mock

from desktidy import advice, config, service
from tests.helpers import IsolatedTest


class TestOverview(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(ai={"mode": "ai-only", "candidate_folders": [{"path": "{D}", "depth": 3}]})
        self.write("integrals.pdf", "x", folder="dest\\Study\\Maths")
        self.write("limits.pdf", "x", folder="dest\\Study\\Maths")
        self.write("passport_scan.pdf", "x", folder="dest\\Personal\\Payslips")   # private rule destination
        self.folder("dest", "Old_stuff")                                          # empty
        self.write("mystery.docx", "x", folder="dest\\00_Inbox\\To_Sort")

    def test_numbered_tree_without_private_names(self):
        ov = advice.overview(self.cfg)
        lines = ov.text.splitlines()
        maths = next(ln for ln in lines if ln.lstrip("0123456789").strip().startswith("Maths"))
        n = int(maths.split()[0])
        self.assertEqual(ov.folders[n - 1], self.dest("Study", "Maths"))
        self.assertIn("2f", maths)
        self.assertIn("pdf 2", maths)
        self.assertIn("limits.pdf", maths)
        self.assertNotIn("passport", ov.text)                  # names in private folders are never sent
        self.assertIn("private", next(ln for ln in lines if "Payslips" in ln))

    def test_findings(self):
        ov = advice.overview(self.cfg)
        self.assertTrue(any("To_Sort" in f and "could not place" in f for f in ov.findings))
        self.assertTrue(any("empty folder" in f and "Old_stuff" in f for f in ov.findings))
        self.assertIn("mystery.docx", ov.text)

    def test_undone_moves_are_reported(self):
        service.record("UNDONE", self.dest("Study", "Maths", "recipe.txt"), self.path("in", "recipe.txt"), "undo")
        self.assertIn("Moves the user undid", advice.overview(self.cfg).text)

    def test_big_overviews_are_cut(self):
        for i in range(120):
            self.write(f"a_rather_long_file_name_number_{i:03d}.txt", "x", folder=f"dest\\Archive\\Box_{i:03d}")
        ov = advice.overview(self.cfg)
        self.assertLessEqual(len(ov.text), advice.MAX_CHARS)


class TestParse(IsolatedTest):
    def test_parse(self):
        folder_list = ["C:\\a", "C:\\b"]
        text = "```json\n" + json.dumps({"tips": [
            {"k": "merge", "t": "Merge a and b", "d": "Same content.", "f": [1, 2, 2, 7]},
            {"k": "weird", "t": "Something", "d": "", "f": "x"},
            {"k": "rename", "t": "", "d": "no title"},
        ]}) + "\n```"
        tips = advice.parse(text, folder_list)
        self.assertEqual(len(tips), 2)
        self.assertEqual(tips[0]["paths"], ["C:\\a", "C:\\b"])
        self.assertEqual((tips[1]["kind"], tips[1]["paths"]), ("tip", []))
        self.assertEqual(advice.parse("not json", folder_list), [])


class TestDue(IsolatedTest):
    def moves(self, n):
        for i in range(n):
            service.record("MOVED", f"C:\\in\\{i}.txt", f"C:\\out\\{i}.txt", "test")

    def test_only_in_ai_only_mode_unless_asked(self):
        self.assertTrue(advice.enabled({"ai": {"mode": "ai-only"}}))
        self.assertFalse(advice.enabled({"ai": {"mode": "limited"}}))
        self.assertTrue(advice.enabled({"ai": {"mode": "limited", "advice": "on"}}))
        self.assertFalse(advice.enabled({"ai": {"mode": "ai-only", "advice": "off"}}))
        self.assertFalse(advice.enabled({"ai": {"mode": "off", "advice": "on"}}))

    def test_after_enough_files_and_days(self):
        cfg = {"ai": {"mode": "ai-only", "advice_after_files": 5}}
        self.moves(4)
        self.assertFalse(advice.due(cfg))                       # no overview yet
        self.moves(1)
        self.assertTrue(advice.due(cfg))
        now = datetime.now()
        config.write_json(config.path("advice"), {"at": now.isoformat(), "tried": now.isoformat(), "moves": 5})
        self.moves(10)
        self.assertFalse(advice.due(cfg))                       # advice given today
        week_ago = (now - timedelta(days=8)).isoformat()
        config.write_json(config.path("advice"), {"at": week_ago, "tried": week_ago, "moves": 5})
        self.assertTrue(advice.due(cfg))
        config.write_json(config.path("advice"), {"at": week_ago, "tried": now.isoformat(), "moves": 5})
        self.assertFalse(advice.due(cfg))                       # at most one attempt a day

    def test_no_key_records_the_attempt(self):
        cfg = config.load_config()
        with mock.patch("desktidy.ai.ready", return_value=None):
            self.assertIsNone(advice.generate(cfg, lambda m: None))
        self.assertIn("tried", advice.load())
