"""Tools that change folders: applying organisation tips (and undoing them), grouping the to-sort pile, old
versions of a document, and learning rules from the user's corrections. All inside temporary folders."""

import json
import os
import time
from datetime import datetime, timedelta
from unittest import mock

from desktidy import config, folders, groups, learn, ops, service, versions
from tests.helpers import IsolatedTest


class TestApplyTips(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(rules=[{"name": "Bills", "name_words": ["bill"], "destination": "{D}\\Bollette"}])
        self.write("a.txt", "keep", folder="dest\\Bills")
        self.write("a.txt", "other", folder="dest\\Bollette")
        self.write("b.txt", "b", folder="dest\\Bollette\\2026")
        folders.pin(self.dest("Bollette"))

    def test_merge_follow_and_undo(self):
        tip = {"kind": "merge", "title": "One folder for bills", "paths": [self.dest("Bills"), self.dest("Bollette")]}
        plan = ops.plan(tip, self.cfg)
        self.assertTrue(plan.ok, plan.problems)
        self.assertEqual(plan.steps[-2], {"op": "rmdir", "path": self.dest("Bollette")})
        self.assertEqual(plan.steps[-1]["op"], "follow")
        entry = ops.apply(plan, self.cfg, tip)
        self.assertEqual(sorted(os.listdir(self.dest("Bills"))), ["2026", "a.txt", "a_v2.txt"])
        self.assertFalse(os.path.exists(self.dest("Bollette")))
        rules = config.load_config(self.cfg.source)["rules"]
        self.assertEqual(rules[0]["destination"], "{D}\\Bills")                  # the rule follows, with its variable
        self.assertEqual([p.path for p in folders.active_pinned()], [self.dest("Bills")])
        self.assertEqual(ops.current_path(self.dest("Bollette", "2026", "b.txt")), self.dest("Bills", "2026", "b.txt"))
        self.assertTrue(entry["changes"])
        ops.undo_last(self.cfg)
        self.assertEqual(sorted(os.listdir(self.dest("Bollette"))), ["2026", "a.txt"])
        self.assertEqual(os.listdir(self.dest("Bills")), ["a.txt"])
        self.assertEqual(config.load_config(self.cfg.source)["rules"][0]["destination"], "{D}\\Bollette")
        self.assertEqual([p.path for p in folders.active_pinned()], [self.dest("Bollette")])
        self.assertIsNone(ops.undo_last(self.cfg))

    def test_rename_create_cleanup(self):
        rename = ops.plan({"kind": "rename", "paths": [self.dest("Bills")], "new_name": "Old bills"}, self.cfg)
        ops.apply(rename, self.cfg)
        self.assertTrue(os.path.isdir(self.dest("Old_bills")))
        create = ops.plan({"kind": "create", "paths": [self.dest()], "new_name": "Recipes"}, self.cfg)
        ops.apply(create, self.cfg)
        self.assertIn(self.dest("Recipes"), [p.path for p in folders.active_pinned()])
        os.makedirs(self.dest("Empty"))
        cleanup = ops.plan({"kind": "cleanup", "paths": [self.dest("Empty"), self.dest("Old_bills")]}, self.cfg)
        self.assertEqual([s["op"] for s in cleanup.steps], ["rmdir"])            # only the empty one

    def test_refusals(self):
        for tip in ({"kind": "archive", "paths": [os.path.join(self.tmp, "in")]},          # a watched folder
                    {"kind": "rename", "paths": [self.cfg.default_destination], "new_name": "X"},
                    {"kind": "merge", "paths": [self.dest("Bills"), self.dest("Bills", "x")]},
                    {"kind": "split", "paths": [self.dest("Bills")]},                    # needs judgement
                    {"kind": "rename", "paths": [self.dest("Bills")], "new_name": "Bollette"}):  # name taken
            self.assertFalse(ops.plan(tip, self.cfg).ok, tip)

    def test_failure_rolls_back(self):
        plan = ops.plan({"kind": "merge", "paths": [self.dest("Bills"), self.dest("Bollette")]}, self.cfg)
        real = ops._do
        calls = []

        def flaky(step):
            calls.append(step)
            if len(calls) == 2:
                raise OSError("locked")
            real(step)
        with mock.patch.object(ops, "_do", side_effect=flaky), self.assertRaises(OSError):
            ops.apply(plan, self.cfg)
        self.assertEqual(sorted(os.listdir(self.dest("Bollette"))), ["2026", "a.txt"])  # back as before
        self.assertEqual(ops.journal(), [])


class TestGroups(IsolatedTest):
    def test_pile_groups_and_apply(self):
        cfg = self.config()
        inbox = "dest\\00_Inbox\\To_Sort"
        for i, extra in enumerate(("blink led", "uart serial", "timer interrupt", "adc reading")):
            self.write(f"board_session_{i}.txt", f"STM32 Nucleo board: GPIO HAL {extra}. STM32 Nucleo pins and GPIO clock. " * 6,
                       folder=inbox)
        self.write("shopping.txt", "milk eggs bread butter cheese apples bananas " * 6, folder=inbox)
        self.write("poem.txt", "the moon over the silent sea and the wind " * 6, folder=inbox)
        found = groups.find(cfg)
        self.assertEqual(len(found), 1)
        g = found[0]
        self.assertEqual(len(g.files), 4)
        self.assertIn("nucleo", g.label.lower())                      # "stm32" splits into "stm" + "32"
        self.assertFalse(g.existing)
        moved = groups.apply(g, cfg, pin=True)
        self.assertEqual(len(moved), 4)
        self.assertEqual(sorted(os.listdir(os.path.dirname(moved[0]))), [f"board_session_{i}.txt" for i in range(4)])
        self.assertIn(os.path.dirname(moved[0]), [p.path for p in folders.active_pinned()])
        self.assertTrue(all(m["action"] == "MOVED" for m in service.read_moves()))


class TestVersions(IsolatedTest):
    def test_split(self):
        self.assertEqual(versions.split("Report_final_v2"), ("report", True))
        self.assertEqual(versions.split("Relazione definitiva (1)"), ("relazione", True))
        self.assertEqual(versions.split("Report - Copy"), ("report", True))
        self.assertEqual(versions.split("Lesson_2"), ("lesson 2", False))

    def test_family_keeps_the_newest(self):
        text = "Lab report on RC filters: cutoff frequency, Bode plot, measured attenuation and phase. " * 5
        old = self.write("Report.txt", text, folder="dest\\Lab")
        mid = self.write("Report_v2.txt", text + " more", folder="dest\\Lab")
        new = self.write("Report_final.txt", text + " final", folder="dest\\Lab")
        for i, p in enumerate((old, mid, new)):
            os.utime(p, (time.time() - 300 + i * 100,) * 2)
        self.write("Lesson_1.txt", "integrals " * 40, folder="dest\\Lab")
        self.write("Lesson_2.txt", "derivatives " * 40, folder="dest\\Lab")
        found = versions.in_folder(self.dest("Lab"))
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].keep, sorted(found[0].older)), (new, sorted([old, mid])))
        self.assertEqual(versions.family_of(new).keep, new)
        versions.apply(found[0])
        self.assertEqual(sorted(os.listdir(self.dest("Lab", versions.FOLDER))), ["Report.txt", "Report_v2.txt"])

    def test_same_name_different_content_is_not_a_version(self):
        self.write("Budget.txt", "rent food transport insurance savings " * 10, folder="dest\\X")
        self.write("Budget_old.txt", "telescope lens mirror eyepiece focus " * 10, folder="dest\\X")
        self.assertEqual(versions.in_folder(self.dest("X")), [])


class TestLearn(IsolatedTest):
    def test_corrections_become_a_rule(self):
        cfg = self.config()
        text = "Oscilloscope probe calibration, trigger level and timebase measurement in the lab. " * 6
        for name in ("scope_session.txt", "probe_check.txt"):
            wrong = self.write(name, text, folder="dest\\Study\\Notes")
            service.record("MOVED", self.path("in", name), wrong, "no rule matched")
            right = self.path("dest", "Study", "Lab", name)
            os.replace(wrong, right)                                       # the user puts it where it belongs
        proposals = learn.scan(cfg)
        self.assertEqual(len(proposals), 1)
        rule = proposals[0]["rule"]
        self.assertEqual(rule["destination"], "{D}\\Study\\Lab")
        self.assertIn("oscilloscope", [w.lower() for w in rule["topics"]])
        self.assertEqual(learn.scan(cfg), [])                              # each move is looked at once
        learn.accept(1)
        with open(cfg.source, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["rules"][0]["destination"], "{D}\\Study\\Lab")
        self.assertEqual(learn.load()["proposals"], [])

    def test_a_correction_into_a_private_folder_makes_a_private_rule(self):
        cfg = self.config()
        text = "Monthly salary statement, overtime hours and holiday allowance for the employee. " * 6
        for name in ("march_statement.txt", "april_statement.txt"):
            wrong = self.write(name, text, folder="dest\\Study\\Notes")
            service.record("MOVED", self.path("in", name), wrong, "no rule matched")
            os.replace(wrong, self.path("dest", "Personal", "Payslips", name))   # a private rule's folder
        rule = learn.scan(cfg)[0]["rule"]
        self.assertTrue(rule.get("private"))

    def test_corrections_into_year_folders_make_a_dated_rule(self):
        cfg = self.config()
        rules = list(cfg["rules"]) + [{"name": "Bills", "name_words": ["bill"], "destination": "{D}\\Bills\\{YEAR}"}]
        cfg = self.config(rules=rules)
        text = "Water supply statement, meter reading and consumption in cubic metres. " * 6
        for name, year in (("water_march.txt", "2025"), ("water_april.txt", "2026")):
            wrong = self.write(name, text, folder="dest\\Study\\Notes")
            service.record("MOVED", self.path("in", name), wrong, "no rule matched")
            os.replace(wrong, self.path("dest", "Bills", year, name))
        proposals = learn.scan(cfg)
        self.assertEqual(len(proposals), 1)                                # 2025 and 2026 count together
        self.assertEqual(proposals[0]["rule"]["destination"], "{D}\\Bills\\{YEAR}")

    def test_a_file_left_where_it_was_teaches_nothing(self):
        cfg = self.config()
        p = self.write("x.txt", "hello " * 30, folder="dest\\Study\\Notes")
        service.record("MOVED", self.path("in", "x.txt"), p, "test")
        self.assertEqual(learn.scan(cfg), [])
        self.assertEqual(learn.load()["corrections"], [])


class TestLearnFromTheAI(IsolatedTest):
    """Five files the AI put in the same folder, still there days later: a rule, so the next ones go offline."""

    TEXT = "Telescope eyepiece, focal length, mirror collimation and star charts for the night. " * 6

    def ai_moves(self, count, days_ago=5, folder="dest\\Hobby\\Astronomy", reason="AI (high): astronomy"):
        when = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
        rows = []
        for i in range(count):
            p = self.write(f"sky_notes_{i}.txt", self.TEXT, folder=folder)
            rows.append({"time": when, "action": "MOVED", "source": self.path("in", f"sky_notes_{i}.txt"),
                         "destination": p, "reason": reason})
        return rows

    def scan(self, cfg, rows):
        with mock.patch.object(service, "read_moves", return_value=rows):
            return learn.scan(cfg)

    def test_a_rule_from_the_ai(self):
        cfg = self.config()
        proposals = self.scan(cfg, self.ai_moves(5))
        self.assertEqual(len(proposals), 1)
        p = proposals[0]
        self.assertEqual(p["source"], "ai")
        self.assertEqual(p["count"], 5)
        self.assertEqual(p["rule"]["destination"], "{D}\\Hobby\\Astronomy")
        self.assertIn("eyepiece", [w.lower() for w in p["rule"]["topics"]])
        self.assertNotIn("private", p["rule"])
        self.assertTrue(p["rule"]["name"].startswith("Learned from the AI"))
        self.assertEqual(self.scan(cfg, self.ai_moves(5)), [])            # each move once, each rule once

    def test_not_enough_not_settled_not_the_ai(self):
        cfg = self.config()
        self.assertEqual(self.scan(cfg, self.ai_moves(4)), [])             # 4 < 5
        self.assertEqual(self.scan(cfg, self.ai_moves(5, days_ago=1, folder="dest\\Hobby\\A")), [])  # too recent
        self.assertEqual(self.scan(cfg, self.ai_moves(5, folder="dest\\Hobby\\B", reason="no rule matched")), [])

    def test_what_the_rules_already_place_teaches_nothing(self):
        cfg = self.config()
        rows = []
        when = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(5):
            p = self.write(f"calculus_{i}.txt", "derivative integral limit theorem " * 20, folder="dest\\Study\\Maths")
            rows.append({"time": when, "action": "MOVED", "source": "x", "destination": p, "reason": "AI (high): maths"})
        self.assertEqual(self.scan(cfg, rows), [])
        self.assertEqual(learn.load()["ai_examples"], [])

    def test_a_file_moved_since_is_not_an_example(self):
        cfg = self.config()
        rows = self.ai_moves(5)
        os.remove(rows[0]["destination"])
        self.assertEqual(self.scan(cfg, rows), [])                         # 4 left
        self.assertEqual(len(learn.load()["ai_examples"]), 4)
