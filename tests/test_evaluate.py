# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""desktidy ai test: the made-up documents, the scoring, and that the test is hermetic (your pinned folders stay
out, the temporary folder is deleted, nothing counts against the daily file limit). The AI is a fake."""

import io
import json
import os
import re
from contextlib import redirect_stdout
from unittest import mock

from desktidy import ai, cli, config, evaluate, folders
from tests.helpers import IsolatedTest


class EvaluateTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(ai={"mode": "limited", "provider": "groq", "redact": True})
        self.requests = []
        self.roots = []

    def answer(self, perfect: bool):
        """A fake service: right answers (from the cases), or always the first folder and no name."""
        def complete(params, cfg, key, log, files=1, shape=""):
            self.assertEqual(files, 0)                          # never booked against the daily file limit
            text = "".join(b["text"] for b in params["messages"][0]["content"] if b["type"] == "text")
            self.requests.append(text)
            folder_lines = text.split("Folders:\n")[1].split("\n\nFiles:")[0].splitlines()[1:]  # after "0 none fits"
            numbers = {}
            for line in folder_lines:                           # "4 ~\...\desktidy_ai_test_x\Personal\Bills"
                n, label = line.split(" ", 1)
                numbers[re.split(r"desktidy_ai_test_[^\\/]+[\\/]", label)[-1].replace("\\", "/")] = int(n)
            self.assertEqual(len(numbers), len(evaluate.FOLDERS))   # every test folder is offered
            rows = []
            for n, name in re.findall(r"^#(\d+) (.+) \(", text, re.M):    # greedy: "download (3).pdf (pdf...)"
                case = next(c for c in evaluate.CASES if c.file == name)
                f = numbers[case.folder] if case.folder else 0
                good = "_".join(group[0] for group in case.name) or "x"
                rows.append({"n": int(n), "f": f if perfect else 1, "c": "h", "name": good if perfect else "",
                             "why": "", "s": "", "due": case.due if perfect else "",
                             "d": case.date if perfect else ""})
            return json.dumps({"files": rows})
        return complete

    def evaluate(self, perfect=True, send=True):
        real_mkdtemp = evaluate.tempfile.mkdtemp

        def mkdtemp(**kw):
            self.roots.append(real_mkdtemp(**kw))
            return self.roots[-1]
        with mock.patch.object(ai, "complete", side_effect=self.answer(perfect)), \
                mock.patch.object(evaluate.tempfile, "mkdtemp", side_effect=mkdtemp):
            return evaluate.run(self.cfg, "key", lambda m: None, send=send)


class TestScoring(EvaluateTest):
    def test_perfect_answers_score_everything(self):
        report = self.evaluate(perfect=True)
        s = report["summary"]
        self.assertEqual(len(report["results"]), len(evaluate.CASES))
        self.assertEqual(s["folder"], (len(evaluate.CASES), len(evaluate.CASES)))
        for k in ("name", "date", "due"):
            self.assertEqual(s[k][0], s[k][1], k)
            self.assertGreater(s[k][1], 2, k)
        self.assertEqual(report["requests"], -(-len(evaluate.CASES) // ai.MAX_FILES_PER_REQUEST))

    def test_wrong_answers_are_counted_wrong(self):
        s = self.evaluate(perfect=False)["summary"]
        self.assertLess(s["folder"][0], 3)
        self.assertEqual(s["date"][0], 0)
        self.assertEqual(s["due"][0], 0)

    def test_generic_names_are_asked(self):
        results = {r.case.file: r for r in self.evaluate()["results"]}
        self.assertTrue(results["scan0001.pdf"].asked_name)
        self.assertEqual(results["notes.txt"].shown, "none")
        self.assertEqual(results["ricetta.txt"].shown, "Recipes")


class TestHermetic(EvaluateTest):
    def test_pinned_folders_and_the_temporary_folder(self):
        secret = self.folder("home", "Documents", "Divorce_lawyer")
        folders.pin(secret)
        self.evaluate()
        self.assertTrue(self.requests)
        self.assertFalse(any("Divorce" in r for r in self.requests))       # your folders are not shown to the AI
        self.assertEqual(folders.active_pinned()[0].path, secret)           # and are back afterwards
        self.assertTrue(self.roots and not any(os.path.exists(r) for r in self.roots))

    def test_made_up_numbers_are_masked(self):
        sent = []
        with mock.patch.object(ai, "_complete_openai", side_effect=lambda p, *a, **k: sent.append(p) or None):
            evaluate.run(self.cfg, "key", lambda m: None)
        text = json.dumps(sent)
        self.assertNotIn("RSSMRA80A01H501U", text)
        self.assertNotIn("0123 456", text)

    def test_dry_run_sends_nothing(self):
        with mock.patch.object(ai, "complete") as complete:
            report = evaluate.run(self.cfg, "", lambda m: None, send=False)
        complete.assert_not_called()
        self.assertEqual(report["documents"], len(evaluate.CASES))
        self.assertGreater(report["chars"], 1000)


class TestCommand(EvaluateTest):
    def test_the_command(self):
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        with mock.patch.object(ai, "ready", return_value="key"), \
                mock.patch.object(ai, "complete", side_effect=self.answer(True)), \
                redirect_stdout(io.StringIO()) as out:
            cli.cmd_ai(["test", "--yes"])
        self.assertRegex(out.getvalue(), rf"Folders \.+ {len(evaluate.CASES)}/{len(evaluate.CASES)}  \(100%\)")
        with mock.patch.object(ai, "complete") as complete, redirect_stdout(io.StringIO()) as out:
            cli.cmd_ai(["test", "--dry"])
        complete.assert_not_called()
        self.assertIn("Nothing was sent", out.getvalue())
