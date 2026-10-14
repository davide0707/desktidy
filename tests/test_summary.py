# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""The weekly summary: what it counts, when it comes (once a week, on the chosen day or the first pass after it),
and that a quiet week says nothing."""

import io
import os
from contextlib import redirect_stdout
from datetime import date
from unittest import mock

from desktidy import cli, config, deadlines, service, summary
from tests.helpers import IsolatedTest

MONDAY = date(2026, 10, 12)


def row(day, action, src, dst, reason):
    return {"time": f"{day} 10:00:00", "action": action, "source": src, "destination": dst, "reason": reason}


class TestWeek(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config()
        self.rows = [
            row("2026-10-11", "MOVED", "a", "C:\\Docs\\Bills\\a.pdf", "rule Bills; renamed (generic name)"),
            row("2026-10-08", "MOVED", "b", "C:\\Docs\\Bills\\b.pdf", "AI (high): bill"),
            row("2026-10-06", "MOVED", "c", "C:\\Docs\\Study\\c.pdf", "rule Study"),
            row("2026-10-05", "MOVED", "old", "C:\\Docs\\Study\\old.pdf", "rule Study"),     # 8 days ago: out
            row("2026-10-10", "DUPLICATE_TRASHED", "d", "C:\\Docs\\d.pdf", "identical"),
            row("2026-10-10", "RECYCLED", "e", "C:\\Docs\\e.pdf", "duplicate of C:\\Docs\\e.pdf"),
            row("2026-10-09", "RECYCLED", "f.exe", "Recycle Bin", "installer of App 1.0 (installed)"),
            row("2026-10-09", "UNDONE", "x", "y", "restored by desktidy undo"),
        ]
        deadlines.add(date(2026, 10, 15), "Electricity bill", "payment", "€ 84,20")
        deadlines.add(date(2026, 10, 30), "Rent", "payment")                                  # not this week
        self.write("left.txt", "x", folder="dest\\00_Inbox\\To_Sort")

    def week(self):
        with mock.patch.object(service, "read_moves", return_value=self.rows):
            return summary.week(self.cfg, MONDAY)

    def test_counts(self):
        s = self.week()
        self.assertEqual((s["from"], s["to"]), ("2026-10-06", "2026-10-12"))
        self.assertEqual((s["tidied"], s["renamed"], s["by_ai"]), (3, 1, 1))
        self.assertEqual(s["places"][0], ("Bills", 2))
        self.assertEqual((s["duplicates"], s["installers"], s["undone"]), (2, 1, 1))
        self.assertEqual([d["what"] for d in s["deadlines"]], ["Electricity bill"])
        self.assertEqual(s["pile"], 1)

    def test_message(self):
        title, body = summary.message(self.week())
        self.assertEqual(title, "DeskTidy: your week")
        self.assertIn("3 file(s) tidied, 1 renamed (Bills 2, Study 1)", body)
        self.assertIn("3 duplicate(s) and old installer(s)", body)
        self.assertIn("Electricity bill on 2026-10-15 (€ 84,20)", body)
        self.assertIn("1 file(s) wait in the to-sort pile", body)

    def test_a_quiet_week(self):
        self.rows = []
        deadlines.remove(deadlines.load()[0]["id"])
        self.assertTrue(summary.quiet(self.week()))

    def test_the_command(self):
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        with mock.patch.object(service, "read_moves", return_value=self.rows), \
                redirect_stdout(io.StringIO()) as out:
            cli.cmd_week([])
        self.assertIn("Your week", out.getvalue())
        with redirect_stdout(io.StringIO()):
            cli.cmd_week(["day", "venerdì"])
            cli.cmd_week(["off"])
        self.assertEqual(summary.settings(config.load_config()), {"weekly": False, "day": 4})


class TestWhen(IsolatedTest):
    def test_once_a_week_on_the_day(self):
        cfg = {}
        self.assertFalse(summary.due(cfg, date(2026, 10, 7)))      # Wednesday: the first call starts counting
        self.assertFalse(summary.due(cfg, date(2026, 10, 12)))     # Monday after 5 days: too soon
        self.assertTrue(summary.due(cfg, date(2026, 10, 19)))      # the next Monday
        summary.sent(date(2026, 10, 19))
        self.assertFalse(summary.due(cfg, date(2026, 10, 25)))
        self.assertTrue(summary.due(cfg, date(2026, 10, 27)))      # the PC was off on Monday: Tuesday
        summary.sent(date(2026, 10, 27))
        self.assertFalse(summary.due(cfg, date(2026, 11, 1)))      # Sunday
        self.assertTrue(summary.due(cfg, date(2026, 11, 2)))       # Monday, 6 days later: back on schedule

    def test_off_and_another_day(self):
        summary.sent(date(2026, 10, 12))
        self.assertFalse(summary.due({"summary": {"weekly": False}}, date(2026, 12, 1)))
        self.assertFalse(summary.due({"summary": {"day": "friday"}}, date(2026, 10, 16)))  # 4 days
        self.assertTrue(summary.due({"summary": {"day": "friday"}}, date(2026, 10, 23)))
