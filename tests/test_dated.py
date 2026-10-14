# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Dated destinations: {DOCS}/Bills/{YEAR}/{MONTH} filled in from the date of each document (read by the AI,
found offline in the text, or the day the file was last changed)."""

import os
import time
from datetime import date, datetime
from unittest import mock

from desktidy import ai, config, deadlines, editor, folders, organize, service
from desktidy import content as ct
from tests.helpers import IsolatedTest, native

INVOICE = ("Northwind Energy - Invoice 2231\nInvoice date: 03/11/2025\nCustomer 55120, electricity supply.\n"
           "Amount due 84.20, payment due by 30/11/2025.\n" + "Electricity supply for October, invoice. " * 6)


class TestPaths(IsolatedTest):
    def test_fill_in_and_fixed_part(self):
        p = native("C:\\Docs\\Bills\\{YEAR}\\{MONTH}")
        self.assertTrue(config.is_dated(p))
        self.assertFalse(config.is_dated(native("C:\\Docs\\Bills")))
        self.assertEqual(config.dated(p, date(2026, 3, 9)), native("C:\\Docs\\Bills\\2026\\03"))
        self.assertEqual(config.undated(p), native("C:\\Docs\\Bills"))
        self.assertEqual(config.undated(native("C:\\Docs\\Bills")), native("C:\\Docs\\Bills"))
        self.assertEqual(config.undated(native("C:\\Docs\\Bills_{YEAR}")), native("C:\\Docs"))

    def test_pattern_matches_what_it_produced_only(self):
        rx = config.dated_pattern(native("C:\\Docs\\Bills\\{YEAR}"))
        self.assertTrue(rx.match(native("C:\\Docs\\Bills\\2025")))
        self.assertTrue(rx.match(native("C:\\Docs\\Bills\\2025\\Scans")))
        self.assertFalse(rx.match(native("C:\\Docs\\Bills\\Old")))
        self.assertFalse(rx.match(native("C:\\Docs\\Bills")))
        self.assertFalse(rx.match(native("C:\\Docs\\Bills\\20255")))

    def test_dated_folders_on_disk(self):
        for f in ("2025\\10", "2025\\11", "2026\\01", "2026\\notes", "Old"):
            self.folder("dest", "Bills", *f.split("\\"))
        found = config.dated_folders(self.dest("Bills", "{YEAR}", "{MONTH}"))
        self.assertEqual(found, [self.dest("Bills", "2025", "10"), self.dest("Bills", "2025", "11"),
                                 self.dest("Bills", "2026", "01")])
        self.assertEqual(config.dated_folders(self.dest("Nowhere", "{YEAR}")), [])

    def test_a_variable_called_year_wins(self):
        cfg = self.config(variables={"D": self.dest(), "YEAR": "{D}\\Third_year"})
        self.assertFalse(config.is_dated(cfg.expand("{YEAR}\\Exams")))
        self.assertEqual(cfg.expand("{YEAR}\\Exams"), self.dest("Third_year", "Exams"))


class TestDocumentDate(IsolatedTest):
    TODAY = date(2026, 10, 12)

    def test_issue_date_not_the_deadline(self):
        text = "Fattura n. 2231 del 12/10/2026\nTotale da pagare 1.220,00 entro il 30/10/2026"
        self.assertEqual(deadlines.issue_date(text, self.TODAY), date(2026, 10, 12))

    def test_labelled_date_wins(self):
        text = "Printed 01/02/2026\nAcme Ltd\nInvoice date: 05/12/2025\nTotal 10.00"
        self.assertEqual(deadlines.issue_date(text, self.TODAY), date(2025, 12, 5))

    def test_words_and_formats(self):
        self.assertEqual(deadlines.issue_date("Milano, 3 marzo 2025\nGentile cliente", self.TODAY), date(2025, 3, 3))
        self.assertEqual(deadlines.issue_date("Report 2024-06-30 final", self.TODAY), date(2024, 6, 30))

    def test_no_date_future_dates_and_day_month_only(self):
        self.assertIsNone(deadlines.issue_date("Shopping list: milk, eggs", self.TODAY))
        self.assertIsNone(deadlines.issue_date("Conference on 12/12/2027", self.TODAY))
        self.assertIsNone(deadlines.issue_date("see you on 3 March", self.TODAY))

    def test_file_date_order(self):
        p = self.write("x.txt", INVOICE)
        old = datetime(2024, 1, 15).timestamp()
        os.utime(p, (old, old))
        an = ct.analyze(p, False)
        self.assertEqual(deadlines.file_date(p, an, "2023-05-06"), date(2023, 5, 6))   # the AI's
        self.assertEqual(deadlines.file_date(p, an, "not a date"), date(2025, 11, 3))  # the text's
        self.assertEqual(deadlines.file_date(p, an, "2999-01-01"), date(2025, 11, 3))  # the future is ignored
        self.assertEqual(deadlines.file_date(p, None), date(2024, 1, 15))              # the file's


class DatedTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config()
        rules = list(self.cfg["rules"]) + [{"name": "Bills", "name_words": ["invoice"], "content_words": ["invoice"],
                                            "destination": "{D}\\Bills\\{YEAR}"}]
        self.cfg = self.config(rules=rules)
        self.template = self.cfg.expand("{D}\\Bills\\{YEAR}")


class TestCatalog(DatedTest):
    def test_the_template_replaces_its_year_folders(self):
        self.write("Invoice_2201_Northwind.pdf", "x", folder="dest\\Bills\\2025")
        self.write("Invoice_2230_Northwind.pdf", "x", folder="dest\\Bills\\2026")
        rule_dests = sorted({self.cfg.expand(r["destination"]) for r in self.cfg["rules"]})
        candidates = folders.candidate_folders(self.cfg, rule_dests, self.cfg.default_destination)
        self.assertIn(self.template, candidates)
        self.assertNotIn(self.dest("Bills", "2025"), candidates)   # a new invoice must not land in last year's
        real = folders.real_folders(self.cfg, rule_dests, self.cfg.default_destination)
        self.assertIn(self.dest("Bills", "2025"), real)
        self.assertIn(self.dest("Bills", "2026"), real)
        self.assertNotIn(self.template, real)

    def test_similarity_reads_the_year_folders(self):
        self.write("Northwind_energy_october.pdf", "x", folder="dest\\Bills\\2025")
        self.write("Northwind_energy_november.pdf", "x", folder="dest\\Bills\\2026")
        folders._catalog["value"] = None
        rule_dests = sorted({self.cfg.expand(r["destination"]) for r in self.cfg["rules"]})
        an = ct.analyze(self.write("northwind_energy_december.txt", "x"), False)
        best = folders.catalog(self.cfg, rule_dests, self.cfg.default_destination).similar(an)[0]
        self.assertEqual(best[1], self.template)


class TestMove(DatedTest):
    def setUp(self):
        super().setUp()
        self.patch = mock.patch.object(service.system, "notify")
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_offline_by_the_date_in_the_text(self):
        self.write("invoice_northwind.txt", INVOICE)
        service.Service(service.Options()).tick(self.cfg)
        self.assertEqual(os.listdir(self.dest("Bills", "2025")), ["invoice_northwind.txt"])
        self.assertFalse(any("{" in m["destination"] for m in service.read_moves()))

    def test_the_ai_date_wins(self):
        p = self.write("invoice_northwind.txt", INVOICE)
        an = ct.analyze(p, False, self.cfg)
        item = ai.Item(p, False, os.path.dirname(p), 1, time.time(), self.template, "rule", "strong", None, None)
        item.analysis = an
        answer = ai.Answer(self.template, "high", "", "invoice", date="2024-02-29")
        service.Service(service.Options()).finish_item(item, answer, self.cfg)
        self.assertEqual(os.listdir(self.dest("Bills", "2024")), ["invoice_northwind.txt"])

    def test_preview_shows_the_real_folder(self):
        said = []
        self.write("invoice_northwind.txt", INVOICE)
        service.Service(service.Options(dry_run=True, say=said.append)).tick(self.cfg)
        self.assertIn(os.path.join("Bills", "2025"), said[0])
        self.assertNotIn("{YEAR}", said[0])

    def test_organize_places_each_file_by_its_date(self):
        desktop = self.folder("home", "Desktop")
        self.write("invoice_a.txt", INVOICE, folder="home\\Desktop")
        self.write("invoice_b.txt", INVOICE.replace("03/11/2025", "07/01/2026"), folder="home\\Desktop")
        with mock.patch.object(ai, "complete", return_value='{"groups": []}'):
            r = organize.plan_folder(desktop, self.cfg, "key", lambda m: None)
        targets = sorted(g["target"] for g in r["groups"])
        self.assertEqual(targets, [self.dest("Bills", "2025"), self.dest("Bills", "2026")])


class TestUnknownVariable(IsolatedTest):
    """A typo in rules.json ({STUDI}) must never create a folder literally called "{STUDI}"."""

    def setUp(self):
        super().setUp()
        self.cfg = self.config(rules=[{"name": "Notes", "name_words": ["appunti"], "destination": "{STUDI}\\Notes"}])
        self.patch = mock.patch.object(service.system, "notify")
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_the_service_leaves_the_file_and_says_why(self):
        p = self.write("appunti_lezione.txt", "x")
        svc = service.Service(service.Options())
        svc.tick(self.cfg)
        self.assertTrue(os.path.exists(p))
        self.assertIn("unknown variable", svc.state["last_error"])
        self.assertFalse(any("{" in name for name in os.listdir(os.getcwd())))

    def test_organize_proposes_nothing_there(self):
        desktop = self.folder("home", "Desktop")
        self.write("appunti_lezione.txt", "x", folder="home\\Desktop")
        said = []
        with mock.patch.object(ai, "complete", return_value='{"groups": []}'):
            r = organize.plan_folder(desktop, self.cfg, None, said.append)
        self.assertFalse(any("{" in g["target"] for g in r["groups"]))
        self.assertTrue(any("unknown variable" in s for s in said))
        bad = {"title": "x", "target": "{STUDI}\\Notes", "new": True, "source": "rules", "folder": desktop,
               "files": [os.path.join(desktop, "appunti_lezione.txt")]}
        plan, _ = organize.steps([bad], self.cfg)
        self.assertFalse(plan.ok)
        self.assertIn("unknown variable", plan.problems[0])


class TestChecks(DatedTest):
    def test_editor_accepts_dates_and_refuses_typos(self):
        data = dict(self.cfg)
        errors, _ = editor.validate(data)
        self.assertEqual(errors, [])
        data["rules"] = data["rules"] + [{"name": "Typo", "name_words": ["x"], "destination": "{D}\\X\\{YAER}"}]
        errors, _ = editor.validate(data)
        self.assertTrue(any("YAER" in e for e in errors))

    def test_the_ai_reads_the_document_date(self):
        text = '{"files":[{"n":1,"f":1,"c":"h","name":"","why":"","s":"","due":"","d":"2025-11-03"},' \
               '{"n":2,"f":1,"c":"h","name":"","why":"","s":"","due":"","d":"03/11/2025"}]}'
        answers = ai.parse(text, 2, ["inbox", self.template])
        self.assertEqual(answers[1].date, "2025-11-03")
        self.assertEqual(answers[2].date, "")                      # not YYYY-MM-DD: ignored
        self.assertIn('"d"', ai.JSON_SHAPE)
        self.assertIn("d", ai.SCHEMA["properties"]["files"]["items"]["required"])
