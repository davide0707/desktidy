# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""The AI request: compact, several files per request, short folder list; and the answer parsing.
No network: nothing here calls Anthropic."""

import json
import os

from desktidy import classifier, naming
from desktidy import content as ct
from tests.helpers import IsolatedTest

try:
    from desktidy import ai
except ImportError:  # anthropic not installed
    ai = None


class TestRequest(IsolatedTest):
    def setUp(self):
        super().setUp()
        if ai is None:
            self.skipTest("anthropic is not installed")
        self.cfg = self.config(ai={"mode": "limited", "candidate_folders": [{"path": "{D}", "depth": 2}]})
        for f in ("Study\\Maths", "Study\\Notes", "Personal\\Payslips", "Projects\\PCB", "Recipes"):
            os.makedirs(self.dest(f), exist_ok=True)

    def item(self, name, text):
        p = self.write(name, text)
        an = ct.analyze(p, False, self.cfg)
        return ai.item_for(p, False, os.path.dirname(p), an, classifier.decide(p, False, self.cfg, an),
                           naming.plan(an, self.cfg), self.cfg)

    def test_always_ai_names_what_the_rules_would_rename(self):
        text = "Fattura n. 2231 del 12/10/2026\nCliente: Mario Rossi - Codice cliente 55120\n" + "Totale da pagare. " * 30
        offline = self.item("scan0001.txt", text)
        self.assertTrue(offline.new_stem)                    # an offline title: the AI is not asked for a name
        self.assertFalse(offline.ask_name)
        self.cfg = self.config(ai={"mode": "all", "provider": "groq", "candidate_folders": [{"path": "{D}", "depth": 2}]})
        always = self.item("scan0001.txt", text)
        self.assertTrue(always.ask_name)                     # always AI: the AI names it
        self.assertIsNone(always.new_stem)
        self.assertEqual(always.fallback_stem, offline.new_stem)   # the offline title if the AI has no answer
        answer = ai.Answer(None, "high", "Fattura_2231_Acme_Srl_2026-10-12", "invoice")
        self.assertEqual(ai.name_for(always, answer), "Fattura_2231_Acme_Srl_2026-10-12")

    def test_dated_documents_get_kind_number_issuer_and_date(self):
        params, _ = ai.build([self.item("a.txt", "boil the pasta " * 10)], self.cfg)
        self.assertIn("YYYY-MM-DD", params["system"])
        self.assertIn("Fattura_2231_Acme_Srl_2026-10-12", params["system"])

    def test_two_files_share_one_request(self):
        items = [self.item("a.txt", "boil the pasta, add tomato sauce and basil " * 10),
                 self.item("b.txt", "the derivative of a composite function " * 10)]
        params, folder_list = ai.build(items, self.cfg)
        self.assertEqual(folder_list[0], self.cfg.default_destination)
        text = "".join(b["text"] for b in params["messages"][0]["content"] if b["type"] == "text")
        self.assertIn("#1 a.txt", text)
        self.assertIn("#2 b.txt", text)
        self.assertEqual(text.count("Folders:"), 1)
        self.assertEqual(params["model"], "claude-haiku-4-5")
        self.assertLess(params["max_tokens"], 300)

    def test_excerpt_is_short(self):
        item = self.item("long.txt", "word " * 20000)
        params, _ = ai.build([item], self.cfg)
        size = sum(len(b.get("text", "")) for b in params["messages"][0]["content"])
        self.assertLess(size, 3000)

    def test_folder_list_is_a_shortlist(self):
        for i in range(80):
            os.makedirs(self.dest("Archive", f"Box_{i:02d}"), exist_ok=True)
        item = self.item("x.txt", "an unrelated text about nothing in particular " * 5)
        _, folder_list = ai.build([item], self.cfg)
        self.assertLessEqual(len(folder_list), 31)

    def test_rename_flag(self):
        item = self.item("scan0002.txt", "milk eggs bread butter cheese apples bananas pasta rice tomatoes " * 4)
        self.assertTrue(item.ask_name)
        params, _ = ai.build([item], self.cfg)
        self.assertIn("scan0002.txt", params["messages"][0]["content"][0]["text"])
        self.assertIn(" rename", params["messages"][0]["content"][0]["text"])

    def test_name_check_flag(self):
        self.cfg = self.config(ai={"mode": "ai-only", "candidate_folders": [{"path": "{D}", "depth": 2}]})
        item = self.item("holiday_plans.txt", "Buy milk, eggs, bread, butter, cheese and apples for the week. " * 4)
        self.assertTrue(item.check_name and not item.ask_name)
        text = ai.build([item], self.cfg)[0]["messages"][0]["content"][0]["text"]
        self.assertIn("holiday_plans.txt", text)
        self.assertIn(" name?", text)
        ok = ai.Answer(None, "h", "Weekly_shopping_list", "food")
        self.assertEqual(ai.name_for(item, ok), "Weekly_shopping_list")
        self.assertIsNone(ai.name_for(item, ai.Answer(None, "h", "Holiday_plans", "same")))
        self.assertIsNone(ai.name_for(item, ai.Answer(None, "h", "", "fits")))
        item.check_name = False
        self.assertIsNone(ai.name_for(item, ok))                 # not asked: ignored

    def test_item_survives_a_restart(self):
        item = self.item("a.txt", "some text " * 10)
        again = ai.Item.from_dict(json.loads(json.dumps(item.to_dict())))
        self.assertEqual(again.path, item.path)
        self.assertEqual(again.folders, item.folders)


class TestParse(IsolatedTest):
    def setUp(self):
        super().setUp()
        if ai is None:
            self.skipTest("anthropic is not installed")

    def test_parse(self):
        folder_list = ["C:\\inbox", "C:\\a", "C:\\b"]
        text = json.dumps({"files": [
            {"n": 1, "f": 2, "c": "h", "name": "Grocery list!", "why": "shopping"},
            {"n": 2, "f": 0, "c": "l", "name": "", "why": "unclear"},
            {"n": 3, "f": 99, "c": "h", "name": "", "why": "bad index"},
            {"n": "x", "f": 1, "c": "h", "name": "", "why": "bad"},
        ]})
        answers = ai.parse(text, 3, folder_list)
        self.assertEqual(answers[1].folder, "C:\\b")
        self.assertEqual(answers[1].confidence, "high")
        self.assertEqual(answers[1].name, "Grocery_list")
        self.assertIsNone(answers[2].folder)
        self.assertIsNone(answers[3].folder)
        self.assertEqual(len(answers), 3)

    def test_garbage(self):
        self.assertEqual(ai.parse("not json", 2, ["a"]), {})
