"""Daily limits, the search index (desktidy find), deadlines found in documents, and the AI's summary and date."""

import json
import os
from datetime import date, timedelta
from unittest import mock

from desktidy import ai, config, deadlines, index, service, usage
from tests.helpers import IsolatedTest

BILL = ("Bolletta della luce - Energia Nord\nPeriodo: settembre 2026\nTotale da pagare: 84,20 euro\n"
        "Da pagare entro il {due}. Pagamento con addebito diretto sul conto corrente. " * 3)


class TestLimits(IsolatedTest):
    def test_parse_and_defaults(self):
        self.assertEqual(config.parse_limit("30"), 30)
        for word in ("unlimited", "Illimitati", "none", "∞"):
            self.assertEqual(config.parse_limit(word), config.UNLIMITED)
        self.assertIsNone(config.parse_limit("lots"))
        self.assertIsNone(config.tidy_limit({}))                                   # default: no limit
        self.assertEqual(config.tidy_limit({"limits": {"files_per_day": 5}}), 5)
        self.assertEqual(config.daily_limit({"ai": {"mode": "moderate"}}), 30)
        self.assertIsNone(config.daily_limit({"ai": {"mode": "moderate", "max_files_per_day": "unlimited"}}))
        self.assertEqual(config.limit_text(None), "unlimited")

    def test_unlimited_ai(self):
        cfg = {"ai": {"mode": "ai-only", "max_files_per_day": "unlimited"}}
        usage.record("claude-haiku-4-5", 5000, 10, 1)
        self.assertGreater(usage.files_left_today(cfg), 10 ** 6)
        self.assertIsNone(usage.block_reason(cfg))

    def test_daily_tidy_limit(self):
        cfg = self.config(limits={"files_per_day": 2})
        for name in ("calculus 1.txt", "calculus 2.txt", "calculus 3.txt"):
            self.write(name, "x")
        svc = service.Service(service.Options())
        with mock.patch.object(service.winapi, "notify") as notify:
            svc.tick(cfg)
            self.assertEqual(len(os.listdir(os.path.join(self.tmp, "in"))), 1)   # 2 tidied, 1 waits
            svc.tick(cfg)
            self.assertEqual(len(os.listdir(os.path.join(self.tmp, "in"))), 1)
            self.assertEqual(notify.call_count, 1)                               # said once a day
        self.assertEqual(service.tidied_today(), 2)


class TestIndex(IsolatedTest):
    def test_search_by_content_with_plurals_and_accents(self):
        bill = self.write("scan0007.txt", BILL.format(due="30/10/2026"))
        recipe = self.write("pasta.txt", "Pasta al pomodoro: basilico, olio e parmigiano. " * 5)
        index.add(bill, summary="Bolletta luce settembre")
        index.add(recipe)
        hits = index.search("bollette luce")
        self.assertEqual([h.path for h in hits], [bill])
        self.assertEqual(hits[0].summary, "Bolletta luce settembre")
        self.assertIn(index.MARK[0], hits[0].snippet)
        self.assertEqual([h.path for h in index.search("perché pomodori")][:1], [recipe])  # OR fallback
        self.assertEqual(index.search(""), [])

    def test_moves_and_missing_files(self):
        p = self.write("notes.txt", "oscilloscope probe calibration " * 10)
        index.add(p)
        new = self.path("moved", "notes.txt")
        os.replace(p, new)
        index.moved(p, new)
        self.assertEqual(index.search("oscilloscope")[0].path, new)
        folder = os.path.dirname(new)
        os.rename(folder, folder + "2")
        index.moved_folder(folder, folder + "2")
        self.assertEqual(index.search("oscilloscope")[0].path, os.path.join(folder + "2", "notes.txt"))
        os.remove(os.path.join(folder + "2", "notes.txt"))
        self.assertEqual(index.search("oscilloscope"), [])                       # dropped on the way
        self.assertEqual(index.stats()["files"], 0)

    def test_refresh_indexes_existing_files_once(self):
        cfg = self.config()
        self.write("derivatives.txt", "the derivative of a composite function " * 10, folder="dest\\Study\\Maths")
        self.assertEqual(index.refresh(cfg)["added"], 1)
        self.assertEqual(index.refresh(cfg)["added"], 0)
        self.assertTrue(index.search("derivative"))

    def test_the_service_indexes_and_notes_deadlines(self):
        due = date.today() + timedelta(days=20)
        cfg = self.config()
        self.write("scan0007.txt", BILL.format(due=due.strftime("%d/%m/%Y")))
        with mock.patch.object(service.winapi, "notify"):
            service.Service(service.Options()).tick(cfg)
        final = service.read_moves()[0]["destination"]
        self.assertEqual(index.search("bolletta")[0].path, final)
        items = deadlines.load()
        self.assertEqual((items[0]["date"], items[0]["kind"], items[0]["path"]), (due.isoformat(), "payment", final))
        self.assertEqual(items[0]["amount"], "€ 84,20")


class TestDeadlines(IsolatedTest):
    today = date(2026, 10, 9)

    def found(self, text):
        return [(f.when.isoformat(), f.kind, f.amount) for f in deadlines.extract(text, self.today)]

    def test_extract(self):
        self.assertEqual(self.found(BILL.format(due="30/10/2026")), [("2026-10-30", "payment", "€ 84,20")])
        self.assertEqual(self.found("Fattura 12. Scadenza pagamento: 15 novembre 2026. Importo € 1.250,00"),
                         [("2026-11-15", "payment", "€ 1.250,00")])
        self.assertEqual(self.found("Invoice 2231. Amount due: $84.20. Payment due by October 30, 2026."),
                         [("2026-10-30", "payment", "$ 84.20")])
        self.assertEqual(self.found("Iscrizione: entro e non oltre il 20 ottobre presentare la domanda."),
                         [("2026-10-20", "deadline", "")])
        self.assertEqual(self.found("Il contratto scade il 2027-01-31."), [("2027-01-31", "deadline", "")])

    def test_not_deadlines(self):
        self.assertEqual(self.found("Consegnare entro 30 giorni dalla data 12/09/2026."), [])
        self.assertEqual(self.found("Data di scadenza 01/02/2025"), [])          # past
        self.assertEqual(self.found("Meeting on 30/10/2026 at 10:00"), [])       # a date, not a deadline
        self.assertEqual(self.found("Scade il 31/02/2027"), [])                  # no such day

    def test_reminders_once_per_threshold(self):
        item = deadlines.add(self.today + timedelta(days=7), "Electricity bill", "payment", "€ 84,20")
        sent = []
        notify = lambda *a: sent.append(a)  # noqa: E731
        cfg = {}
        self.assertEqual(len(deadlines.remind(cfg, notify, self.today)), 1)
        self.assertIn("Pay in 7 days", sent[0][0])
        self.assertEqual(deadlines.remind(cfg, notify, self.today), [])                       # not twice
        self.assertEqual(len(deadlines.remind(cfg, notify, self.today + timedelta(days=6))), 1)  # 1 day left
        deadlines.update(item["id"], done=True)
        self.assertEqual(deadlines.remind(cfg, notify, self.today + timedelta(days=7)), [])
        self.assertIsNone(deadlines.add(self.today + timedelta(days=7), "Electricity bill"))   # no duplicates

    def test_moves_keep_the_file_reachable(self):
        p = self.write("bill.txt", "x")
        item = deadlines.add(self.today + timedelta(days=30), "Bill", path=p)
        service.record("MOVED", p, self.path("dest", "bill.txt"), "test")
        self.assertEqual(deadlines.find(item["id"])["path"], self.path("dest", "bill.txt"))


class TestAIAnswerExtras(IsolatedTest):
    def test_summary_and_due(self):
        text = json.dumps({"files": [{"n": 1, "f": 1, "c": "h", "name": "", "why": "bill",
                                      "s": "Electricity bill  for September", "due": "2026-10-30"},
                                     {"n": 2, "f": 0, "c": "l", "name": "", "why": "?", "s": "", "due": "soon"}]})
        answers = ai.parse(text, 2, ["inbox", "C:\\bills"])
        self.assertEqual((answers[1].summary, answers[1].due), ("Electricity bill for September", "2026-10-30"))
        self.assertEqual(answers[2].due, "")
        self.assertIn('"due"', ai.JSON_SHAPE)
        self.assertIn("due", ai.SCHEMA["properties"]["files"]["items"]["required"])
