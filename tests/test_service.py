# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Full passes of the service in a test folder: it really moves, renames and restores, but only in there."""

import os
import time
from datetime import datetime
from unittest import mock

from desktidy import classifier, config, folders, service
from tests.helpers import IsolatedTest

try:
    from desktidy import ai
except ImportError:
    ai = None

INVOICE = ("Invoice 2231 from Northwind Energy\n" + "Customer number 55120, electricity supply for September, "
           "amount due 84.20, payment by direct debit, due date 30 October. " * 6)


class ServiceTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config()
        self.trashed = []
        patches = [mock.patch.object(service.system, "recycle", side_effect=self._recycle),
                   mock.patch.object(service.system, "notify")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.svc = service.Service(service.Options())

    def _recycle(self, p):
        self.trashed.append(p)
        os.remove(p)
        return True

    def inbox(self):
        return sorted(os.listdir(os.path.join(self.tmp, "in")))


class TestPass(ServiceTest):
    def test_moves_cleans_names_and_logs(self):
        self.write("Calculus (1).txt", "x")
        self.write("list.txt", "milk eggs")
        self.svc.tick(self.cfg)
        self.assertTrue(os.path.exists(self.dest("Study", "Maths", "Calculus.txt")))
        self.assertTrue(os.path.exists(self.dest("00_Inbox", "To_Sort", "list.txt")))
        moves = service.read_moves()
        self.assertEqual([m["action"] for m in moves], ["MOVED", "MOVED"])

    def test_renames_generic_names(self):
        self.write("scan0001.txt", INVOICE)
        self.svc.tick(self.cfg)
        self.assertTrue(os.path.exists(self.dest("00_Inbox", "To_Sort", "Invoice_2231_from_Northwind_Energy.txt")))
        self.assertIn("renamed", service.read_moves()[0]["reason"])

    def test_leaves_alone_bang_temporary_and_office_locks(self):
        for name in ("!draft calculus.txt", "download.pdf.crdownload", "~$document.docx"):
            self.write(name, "x")
        self.svc.tick(self.cfg)
        self.assertEqual(self.inbox(), ["!draft calculus.txt", "download.pdf.crdownload", "~$document.docx"])

    def test_duplicates_and_same_names(self):
        os.makedirs(self.dest("Study", "Maths"))
        with open(self.dest("Study", "Maths", "calculus.txt"), "w", encoding="utf-8") as f:
            f.write("same")
        self.write("calculus.txt", "same")          # identical: Recycle Bin
        self.svc.tick(self.cfg)
        self.assertEqual(len(self.trashed), 1)
        self.write("calculus.txt", "different")     # same name, other content: _v2
        self.svc.tick(self.cfg)
        self.assertTrue(os.path.exists(self.dest("Study", "Maths", "calculus_v2.txt")))

    def test_waits(self):
        cfg = self.config(watched_folders=[{"path": "{IN}", "wait_seconds": 3600}])
        self.write("calculus.txt", "x")
        self.svc.tick(cfg)
        self.assertEqual(self.inbox(), ["calculus.txt"])

    def test_pinned_folder_is_never_moved(self):
        pinned = self.folder("in", "pasta")
        folders.pin(pinned)
        self.write("pasta recipe.txt", "x")
        self.svc.tick(self.cfg)
        self.assertTrue(os.path.exists(os.path.join(pinned, "pasta_recipe.txt")))

    def test_dry_run_changes_nothing(self):
        said = []
        svc = service.Service(service.Options(dry_run=True, say=said.append))
        self.write("calculus.txt", "x")
        svc.tick(self.cfg)
        self.assertEqual(self.inbox(), ["calculus.txt"])
        self.assertIn(os.path.join("Study", "Maths"), said[0])
        self.assertFalse(os.path.exists(config.path("moves")))

    def test_stop_request(self):
        open(config.path("stop"), "w").close()
        start = time.time()
        self.assertFalse(self.svc.wait(30))
        self.assertLess(time.time() - start, 2)

    def test_pause_with_expiry(self):
        with open(config.path("pause"), "w", encoding="utf-8") as f:
            f.write("until=2000-01-01T00:00:00")
        self.assertEqual(service.paused_until(), (False, None))
        self.assertFalse(os.path.exists(config.path("pause")))

    def test_new_folder_suggestions(self):
        desktop = self.folder("Desktop")
        os.makedirs(os.path.join(desktop, "old"))
        cfg = self.config(pinned_folders={"ask": True, "ask_for_new_folders_in": [desktop], "wait_seconds": 0})
        self.svc.suggest_pins(cfg)                    # first run: folders that already exist are not asked
        self.assertTrue(self.svc.questions.empty())
        for name in ("pasta", "New folder", "!private"):
            os.makedirs(os.path.join(desktop, name))
        # the clock a little behind the folder's creation time, as with Python 3.10 on Windows: still suggested
        with mock.patch.object(folders.time, "time", return_value=os.stat(os.path.join(desktop, "pasta")).st_ctime - 0.01):
            self.svc.suggest_pins(cfg)
        self.assertEqual(self.svc.questions.get_nowait(), os.path.join(desktop, "pasta"))
        self.assertTrue(self.svc.questions.empty())
        self.svc.suggest_pins(cfg)                    # asked only once
        self.assertTrue(self.svc.questions.empty())


class TestAIBatch(ServiceTest):
    """The batch flow with a fake Anthropic: submit, keep the file in place, finish it when the answer arrives."""

    def setUp(self):
        super().setUp()
        if ai is None or not classifier.AI_AVAILABLE:  # desktidy.ai imports without it: the Claude provider needs it
            self.skipTest("anthropic is not installed")
        self.cfg = self.config(ai={"mode": "limited", "delivery": "batch", "gather_seconds": 0,
                                   "candidate_folders": [{"path": "{D}", "depth": 2}]})
        self.recipes = self.folder("dest", "Recipes")
        self.submitted = []
        self.answer = ai.Answer(self.recipes, "high", "Shopping_list", "groceries")
        fakes = [mock.patch.object(ai, "ready", return_value="sk-ant-test"),
                 mock.patch.object(ai, "submit", side_effect=self._submit),
                 mock.patch.object(ai, "collect", side_effect=self._collect)]
        for p in fakes:
            p.start()
            self.addCleanup(p.stop)

    def _submit(self, items, cfg, key, log):
        self.submitted.append(items)
        return {"id": "batch_1", "created": datetime.now().isoformat(timespec="seconds"), "model": "claude-haiku-4-5",
                "folders": [cfg.default_destination, self.recipes], "items": [i.to_dict() for i in items], "polled": 0.0}

    def _collect(self, job, log):
        log("collected")  # the service must hand over a callable, not the Logger object
        return True, {1: self.answer}

    def test_batch_round_trip(self):
        self.write("scan0002.txt", "milk eggs bread butter cheese apples bananas pasta rice tomatoes " * 4)
        self.svc.tick(self.cfg)
        self.assertEqual(len(self.submitted), 1)
        self.assertTrue(self.submitted[0][0].ask_name)
        self.assertEqual(self.inbox(), ["scan0002.txt"])           # waiting for the answer
        self.assertEqual(len(service.Service.pending_paths()), 1)
        self.svc.tick(self.cfg)                                      # answer arrives
        self.assertEqual(os.listdir(self.recipes), ["Shopping_list.txt"])
        self.assertIn("AI (high)", service.read_moves()[0]["reason"])
        self.assertEqual(service.Service.pending_paths(), set())

    def test_file_changed_while_waiting_is_decided_again(self):
        p = self.write("scan0003.txt", "milk eggs bread butter cheese apples bananas pasta rice tomatoes " * 4)
        self.svc.tick(self.cfg)
        with open(p, "a", encoding="utf-8") as f:
            f.write("more")
        os.utime(p, (time.time() + 5, time.time() + 5))
        self.svc.finish_jobs(self.cfg)
        self.assertEqual(self.inbox(), ["scan0003.txt"])
        self.assertEqual(service.Service.pending_paths(), set())

    def test_daily_limit_falls_back_offline(self):
        cfg = self.config(ai={"mode": "limited", "max_files_per_day": 0, "candidate_folders": [{"path": "{D}", "depth": 2}]})
        self.write("list.txt", "milk eggs bread")
        self.svc.tick(cfg)
        self.assertEqual(self.submitted, [])
        self.assertTrue(os.path.exists(self.dest("00_Inbox", "To_Sort", "list.txt")))

    def test_files_are_gathered_into_one_request(self):
        cfg = self.config(ai={"mode": "limited", "delivery": "batch", "gather_seconds": 60,
                              "candidate_folders": [{"path": "{D}", "depth": 2}]})
        self.write("a.txt", "milk eggs bread butter " * 10)
        self.svc.tick(cfg)
        self.assertEqual(self.submitted, [])                 # waits for company
        self.write("b.txt", "tomatoes basil olive oil " * 10)
        self.svc.tick(cfg)
        self.assertEqual(self.submitted, [])
        self.assertEqual(len(self.svc.ai_hold), 2)
        self.svc.ai_hold = {k: t - 61 for k, t in self.svc.ai_hold.items()}
        self.svc.tick(cfg)                                    # the oldest waited enough: both leave together
        self.assertEqual([sorted(os.path.basename(i.path) for i in chunk) for chunk in self.submitted],
                         [["a.txt", "b.txt"]])
        self.assertEqual(self.svc.ai_hold, {})

    def test_ai_fixes_a_name_that_does_not_match_the_content(self):
        cfg = self.config(ai={"mode": "ai-only", "delivery": "batch", "gather_seconds": 0,
                              "candidate_folders": [{"path": "{D}", "depth": 2}]})
        self.write("holiday_plans.txt", "Buy milk, eggs, bread, butter, cheese, apples and bananas for the week. " * 4)
        self.answer = ai.Answer(self.recipes, "high", "Weekly_shopping_list", "groceries")
        self.svc.tick(cfg)
        self.assertTrue(self.submitted[0][0].check_name)
        self.assertFalse(self.submitted[0][0].ask_name)
        self.svc.tick(cfg)
        self.assertEqual(os.listdir(self.recipes), ["Weekly_shopping_list.txt"])
        self.assertIn("didn't match the content", service.read_moves()[0]["reason"])

    def test_ai_name_must_be_meaningful_to_replace_the_users_name(self):
        cfg = self.config(ai={"mode": "ai-only", "delivery": "batch", "gather_seconds": 0,
                              "candidate_folders": [{"path": "{D}", "depth": 2}]})
        self.write("holiday_plans.txt", "Buy milk, eggs, bread, butter, cheese, apples and bananas for the week. " * 4)
        self.answer = ai.Answer(self.recipes, "high", "Document_1", "groceries")   # generic: rejected
        self.svc.tick(cfg)
        self.svc.tick(cfg)
        self.assertEqual(os.listdir(self.recipes), ["holiday_plans.txt"])

    def test_a_name_that_fits_is_not_sent_for_checking(self):
        cfg = self.config(ai={"mode": "ai-only", "delivery": "batch", "gather_seconds": 0,
                              "candidate_folders": [{"path": "{D}", "depth": 2}]})
        self.write("shopping_milk_eggs.txt", "Buy milk, eggs, bread, butter, cheese, apples and bananas. " * 4)
        self.svc.tick(cfg)
        self.assertFalse(self.submitted[0][0].check_name)


class TestFirstRunSetup(ServiceTest):
    """A fresh install moves nothing until the house rules are accepted and 2 folders are pinned."""

    def setUp(self):
        super().setUp()
        self.cfg = self.config(pinned_folders={"ask": False, "min_required": 2})

    def test_only_watches_until_setup_is_done(self):
        self.write("calculus.txt", "x")
        self.svc.tick(self.cfg)
        self.assertEqual(self.inbox(), ["calculus.txt"])
        self.assertIn("house rules", self.svc.state["setup_missing"])
        config.write_json(config.path("setup"), {"rules_accepted": "2026-10-07T20:00:00"})
        folders.pin(self.folder("Desktop", "Study"))
        self.svc.tick(self.cfg)
        self.assertEqual(self.inbox(), ["calculus.txt"])
        self.assertEqual(self.svc.state["setup_missing"], "1 of 2 pinned folders")
        folders.pin(self.folder("Desktop", "Work"))
        self.svc.tick(self.cfg)
        self.assertEqual(self.inbox(), [])
        self.assertIsNone(self.svc.state["setup_missing"])
