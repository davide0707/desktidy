"""The new commands, as a user types them: limit, ai max, find, deadlines, tidy, handsoff, undo by id, the
desktidy: links, advice apply and undo, and the console-less entry point used by Explorer and notifications."""

import io
import os
from contextlib import redirect_stdout
from datetime import date, timedelta
from unittest import mock

from desktidy import advice, cli, config, deadlines, folders, index, service
from tests.helpers import IsolatedTest


class CommandTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config()
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        self.cfg = config.load_config()
        p = mock.patch.object(cli.system, "notify")
        self.notify = p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(service.system, "notify")
        q.start()
        self.addCleanup(q.stop)

    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out, mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = False
            cli.run(list(argv))
        return out.getvalue()


class TestLimitCommands(CommandTest):
    def test_limit(self):
        self.assertIn("At most 30", self.run_cli("limit", "30"))
        self.assertEqual(config.tidy_limit(config.load_config()), 30)
        self.assertIn("No daily limit", self.run_cli("limit", "illimitati"))
        self.assertIsNone(config.tidy_limit(config.load_config()))
        self.assertIn("Type a number", self.run_cli("limit", "0"))
        self.assertIn("no limit", self.run_cli("limit"))

    def test_ai_max(self):
        self.run_cli("ai", "max", "unlimited")
        self.assertIsNone(config.daily_limit(config.load_config()))
        self.run_cli("ai", "max", "45")
        self.assertEqual(config.daily_limit(config.load_config()), 45)
        self.run_cli("ai", "max", "auto")
        self.assertEqual(config.daily_limit(config.load_config()), 0)          # mode off: no AI


class TestFilesCommands(CommandTest):
    def test_find(self):
        p = self.write("derivatives.txt", "the derivative of a composite function " * 10, folder="dest\\Maths")
        index.add(p, summary="Notes on derivatives")
        out = self.run_cli("find", "derivatives")
        self.assertIn("derivatives.txt", out)
        self.assertIn("Notes on derivatives", out)
        self.assertIn("Nothing found", self.run_cli("find", "zebra"))

    def test_tidy_handsoff_and_undo_by_id(self):
        p = self.write("calculus exam.txt", "x")
        self.assertIn("Study", self.run_cli("tidy", p))
        moved = self.dest("Study", "Maths", "calculus_exam.txt")
        self.assertTrue(os.path.exists(moved))
        row = service.read_moves()[-1]
        self.assertIn("Restored", self.run_cli("undo", service.move_id(row)))
        self.assertTrue(os.path.exists(p))
        self.run_cli("handsoff", p)
        self.assertTrue(os.path.exists(self.path("in", "!calculus exam.txt")))
        self.assertIn("starts with !", self.run_cli("tidy", self.path("in", "!calculus exam.txt")))
        self.run_cli("handsoff", self.path("in", "!calculus exam.txt"))
        self.assertTrue(os.path.exists(p))

    def test_links(self):
        p = self.write("calculus.txt", "x")
        self.run_cli("tidy", p)
        row = service.read_moves()[-1]
        self.run_cli("url", f"desktidy:undo?ids={service.move_id(row)}")
        self.assertTrue(os.path.exists(p))
        with mock.patch.object(cli.system, "reveal") as reveal:
            self.run_cli("url", f"desktidy:open?id={service.move_id(row)}")
        reveal.assert_called_once()
        self.assertIn("Unknown DeskTidy link", self.run_cli("url", "desktidy:format?drive=C"))

    def test_deadlines(self):
        when = date.today() + timedelta(days=12)
        self.run_cli("deadlines", "add", when.isoformat(), "Pay", "the", "rent")
        out = self.run_cli("deadlines")
        self.assertIn("Pay the rent", out)
        self.assertIn("in 12 days", out)
        self.run_cli("deadlines", "done", "1")
        self.assertTrue(deadlines.load()[0]["done"])
        self.assertIn("No upcoming deadlines", self.run_cli("deadlines"))
        self.assertIn("Usage", self.run_cli("deadlines", "add", "someday", "x"))


class TestAdviceApply(CommandTest):
    def test_apply_and_undo(self):
        self.write("a.txt", "a", folder="dest\\Bills")
        self.write("b.txt", "b", folder="dest\\Bollette")
        config.write_json(config.path("advice"), {"at": "2026-10-09T10:00:00", "tips": [
            {"kind": "merge", "title": "One folder for bills", "detail": "", "paths": [self.dest("Bills"),
                                                                                    self.dest("Bollette")],
             "new_name": ""}]})
        out = self.run_cli("advice", "apply", "1", "--yes")
        self.assertIn("Done", out)
        self.assertEqual(sorted(os.listdir(self.dest("Bills"))), ["a.txt", "b.txt"])
        self.assertIn("Undone", self.run_cli("advice", "undo"))
        self.assertEqual(os.listdir(self.dest("Bollette")), ["b.txt"])
        self.assertIn("advice apply 1", self.run_cli("advice"))
        self.assertTrue(advice.load()["tips"])


class TestEntryPoints(CommandTest):
    def test_gui_shows_problems_in_a_message_box(self):
        with mock.patch.object(cli.system, "message") as message, mock.patch("sys.argv", ["desktidyw", "tidy", "C:\\nope.txt"]):
            cli.main_gui()
        message.assert_called_once()
        self.assertIn("Not found", message.call_args[0][0])
        cli.GUI = False

    def test_pause_keeps_the_window_open(self):
        with mock.patch("builtins.input", return_value="") as wait, redirect_stdout(io.StringIO()):
            cli.run(["limit", "--pause"])
        wait.assert_called_once()

    def test_pin_toggle(self):
        folder = self.folder("Desktop", "Recipes")
        self.run_cli("pin-toggle", folder)
        self.assertEqual([p.path for p in folders.active_pinned()], [folder])
        self.run_cli("pin-toggle", folder)
        self.assertEqual(folders.active_pinned(), [])

    def test_every_command_has_a_unique_number_and_name(self):
        numbers = [c[0] for c in cli.COMMANDS]
        self.assertEqual(numbers, list(range(1, len(cli.COMMANDS) + 1)))
        names = [c[1] for c in cli.COMMANDS] + [a for c in cli.COMMANDS for a in c[4]]
        self.assertEqual(len(names), len(set(names)))
        self.assertIs(cli.find_command("find"), cli.cmd_find)
        self.assertIs(cli.find_command("scadenze"), cli.cmd_deadlines)
        self.assertIs(cli.find_command("url"), cli.cmd_url)


class TestExplainPrivacy(CommandTest):
    """explain --ai follows house rule 5 like the service: a private file goes to the AI only in the "all" mode."""

    PAYSLIP = "Payslip for March: gross pay 2400, net pay 1800, tax, deductions, national insurance. " * 5

    def explain(self, mode):
        config.update_config(lambda d: d["ai"].update(mode=mode, provider="ollama"))
        p = self.write("payslip_march.txt", self.PAYSLIP)
        with mock.patch("desktidy.ai.ask", return_value={}) as ask, mock.patch.object(cli.files, "confirm", return_value=True):
            out = self.run_cli("explain", p, "--ai")
        return out, ask

    def test_not_sent_in_ai_only(self):
        out, ask = self.explain("ai-only")
        ask.assert_not_called()
        self.assertIn("Not sent to the AI", out)

    def test_sent_when_the_user_chose_always_ai(self):
        out, ask = self.explain("all")
        ask.assert_called_once()
        self.assertIn("you chose Always AI", out)

    def test_a_dated_destination_shows_this_files_folder(self):
        config.update_config(lambda d: d["rules"].insert(0, {"name": "Bills", "name_words": ["invoice"],
                                                             "destination": "{D}\\Bills\\{YEAR}"}))
        p = self.write("invoice_northwind.txt", "Invoice date: 03/11/2025\nAmount due 84.20 " * 3)
        out = self.run_cli("explain", p)
        self.assertIn(os.path.join("Bills", "2025"), out)
        self.assertNotIn("{YEAR}", out)
