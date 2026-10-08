"""AI spend and credit, configuration helpers, and the command line (durations, aliases, pause, undo)."""

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta

from desktidy import cli, config, service, usage
from tests.helpers import IsolatedTest


class TestNames(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(config.clean_name("Calculus Notes (1).PDF"), "Calculus_Notes.pdf")
        self.assertEqual(config.clean_name("perché è così.docx"), "perche_e_cosi.docx")
        self.assertEqual(config.clean_name("  ###.txt"), "file.txt")
        self.assertEqual(config.clean_name("New folder (2)", is_dir=True), "New_folder")


class TestSpend(IsolatedTest):
    def cfg(self, **ai):
        return {"ai": {"mode": "moderate", **ai}}

    def test_record_and_totals(self):
        usd = usage.record("claude-haiku-4-5", 2, 2000, 40)
        self.assertAlmostEqual(usd, (2000 * 1 + 40 * 5) / 1e6)
        usage.record("claude-haiku-4-5", 1, 1000, 20, batch=True)
        u = usage.read()
        self.assertEqual((u["today_files"], u["total_files"]), (3, 3))
        self.assertEqual(u["models"]["claude-haiku-4-5"]["files"], 3)
        self.assertEqual(usage.between(u, date.today().isoformat())[0], 3)

    def test_batch_is_half_price(self):
        self.assertAlmostEqual(usage.cost("claude-haiku-4-5", 1000, 100, batch=True),
                               usage.cost("claude-haiku-4-5", 1000, 100) / 2)

    def test_daily_limit(self):
        self.assertEqual(config.daily_limit(self.cfg()), 30)
        self.assertEqual(config.daily_limit(self.cfg(max_files_per_day=5)), 5)
        usage.record("claude-haiku-4-5", 5, 10, 1)
        self.assertIn("daily limit", usage.block_reason(self.cfg(max_files_per_day=5)))
        self.assertIsNone(usage.block_reason(self.cfg()))

    def test_budget(self):
        usage.record("claude-haiku-4-5", 1, 1_000_000, 0)  # $1
        self.assertIn("budget", usage.block_reason(self.cfg(budget_usd=1.0)))
        self.assertIsNone(usage.block_reason(self.cfg(budget_usd=2.0)))

    def test_credit_left(self):
        usage.record("claude-haiku-4-5", 1, 1_000_000, 0)  # $1 before the balance was declared
        usage.set_credit(2.0)
        usage.record("claude-haiku-4-5", 1, 500_000, 0)    # $0.50 after
        self.assertAlmostEqual(usage.credit_left(usage.read()), 1.5)
        usage.record("claude-haiku-4-5", 1, 1_450_000, 0)
        self.assertIn("credit", usage.block_reason(self.cfg(budget_usd=100)))

    def test_warning_cleared_by_a_successful_call(self):
        usage.warn("credit exhausted")
        self.assertIn("warning", usage.read())
        usage.record("claude-haiku-4-5", 1, 10, 1)
        self.assertNotIn("warning", usage.read())


class TestConfig(IsolatedTest):
    def test_builtin_variables_and_safe_folders(self):
        cfg = config.Config({"variables": {"DOC": "C:\\mine"}})
        self.assertTrue(cfg.expand("{DOCS}\\Archive").startswith(self.tmp))   # tests never reach real folders
        self.assertEqual(config.Config({"variables": {"DOCS": "D:\\docs"}}).expand("{DOCS}\\x"), "D:\\docs\\x")
        with self.assertRaises(OSError):
            cfg.folder("{NOPE}\\Archive")
        with self.assertRaises(OSError):
            cfg.folder("relative\\path")
        self.assertEqual(cfg.folder("{DOC}\\x"), "C:\\mine\\x")

    def test_nested_variables(self):
        p = self.path("_data", "r.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"variables": {"A": "C:\\base", "B": "{A}\\sub"}, "rules": []}, f)
        self.assertEqual(config.load_config(p).expand("{B}\\x"), "C:\\base\\sub\\x")

    def test_first_run_creates_rules(self):
        cfg = config.load_config()
        self.assertTrue(os.path.exists(config.path("rules")))
        self.assertGreater(len(cfg["rules"]), 20)

    def test_cached_reads_follow_the_file(self):
        from desktidy import folders
        p = config.path("kept")
        config.write_json(p, [1])
        first = config.read_json_cached(p)
        self.assertIs(config.read_json_cached(p), first)      # parsed once
        with open(p, "w", encoding="utf-8") as f:              # changed by another process
            f.write("[1, 2, 3]")
        os.utime(p, ns=(1, 1))
        self.assertEqual(config.read_json_cached(p), [1, 2, 3])
        os.remove(p)
        self.assertEqual(config.read_json_cached(p, []), [])
        self.assertEqual(folders.active_pinned(), [])
        folders.pin(self.folder("Desktop", "Recipes"))
        self.assertEqual([x.name for x in folders.active_pinned()], ["Recipes"])
        folders.unpin(self.folder("Desktop", "Recipes"))
        self.assertEqual(folders.active_pinned(), [])

    def test_advice_command_works_offline(self):
        self.config(ai={"mode": "off", "candidate_folders": [{"path": "{D}", "depth": 2}]})
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        self.folder("dest", "Empty_one")
        out = self._run("advice")
        self.assertIn("No AI advice yet", out)
        self.assertIn("Empty_one", out)
        self.assertIs(cli.find_command("tips"), cli.cmd_advice)

    def _run(self, *argv):
        with redirect_stdout(io.StringIO()) as out:
            cli.run(list(argv))
        return out.getvalue()

    def test_update_keeps_a_backup(self):
        config.load_config()
        config.update_config(lambda d: d["ai"].__setitem__("mode", "off"))
        self.assertEqual(config.ai_mode(config.load_config()), "off")
        self.assertTrue(os.path.exists(config.path("rules") + ".bak"))


class TestDurations(unittest.TestCase):
    def close(self, end, seconds):
        self.assertIsNotNone(end)
        self.assertLess(abs((end - datetime.now()).total_seconds() - seconds), 5)

    def test_durations(self):
        for text, seconds in (("30m", 1800), ("2h", 7200), ("1h30m", 5400), ("1d", 86400), ("45", 2700),
                              ("2 hours", 7200)):
            self.close(cli.parse_duration(text), seconds)

    def test_clock_time(self):
        end = cli.parse_duration("23:59")
        self.assertEqual((end.hour, end.minute), (23, 59))
        earlier = (datetime.now() - timedelta(minutes=5)).strftime("%H:%M")
        self.assertGreater(cli.parse_duration(earlier), datetime.now())  # already past: tomorrow

    def test_invalid(self):
        for text in ("soon", "25:00", "10x", ""):
            self.assertIsNone(cli.parse_duration(text), text)


class TestCommands(IsolatedTest):
    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out:
            cli.run(list(argv))
        return out.getvalue()

    def test_aliases(self):
        self.assertIs(cli.find_command("1"), cli.cmd_setup)
        self.assertIs(cli.find_command("3"), cli.cmd_status)
        self.assertIs(cli.find_command("STATUS"), cli.cmd_status)
        self.assertIs(cli.find_command("balance"), cli.cmd_spend)
        self.assertIsNone(cli.find_command("nope"))
        self.assertEqual(cli.AI_ALIASES["only"], "ai-only")

    def test_split_line(self):
        self.assertEqual(cli.split_line('explain "C:\\a b\\c.pdf" --ai'), ["explain", "C:\\a b\\c.pdf", "--ai"])

    def test_pause_and_resume(self):
        self.run_cli("pause", "30m")
        paused, until = service.paused_until()
        self.assertTrue(paused and until)
        self.run_cli("resume")
        self.assertFalse(os.path.exists(config.path("pause")))
        self.assertIn("can't understand", self.run_cli("pause", "soon"))

    def test_undo_restores_name_and_place(self):
        original = self.write("scan0001.txt", "x")
        moved = self.path("dest", "Bills", "Invoice_2231.txt")
        os.replace(original, moved)
        service.record("MOVED", original, moved, "renamed")
        self.assertIn("Restored", self.run_cli("undo", "invoice"))
        self.assertTrue(os.path.exists(original))
        self.assertFalse(os.path.exists(moved))
        self.assertTrue(service.Service.is_kept(original))
        self.assertEqual(service.read_moves()[-1]["action"], "UNDONE")


if __name__ == "__main__":
    unittest.main()


class TestSetupCommand(IsolatedTest):
    def test_setup_accepts_rules_and_explains_what_is_missing(self):
        from unittest import mock

        from desktidy import folders
        self.config(pinned_folders={"ask": False, "min_required": 2})
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        with mock.patch("sys.stdin") as stdin, redirect_stdout(io.StringIO()) as out:
            stdin.isatty.return_value = False
            cli.run(["setup", "--accept"])
        self.assertIn("A name starting with ! is never touched", out.getvalue())
        self.assertIn("0/2", out.getvalue())
        self.assertEqual(folders.setup_missing(config.load_config()), "0 of 2 pinned folders")
