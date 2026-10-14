# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Organize: the crowded folders, what the AI reads (never private files), the plan, applying it and undoing it.
The AI is a fake that answers from the item names it is shown."""

import json
import os
import re
from unittest import mock

from desktidy import ai, cli, config, folders, ops, organize, service
from tests.helpers import IsolatedTest

THESIS = "Chapter on renewable energy policy for the thesis, literature review and research method. " * 5
JAPAN = "Kyoto Osaka Tokyo hotel booking, train pass, temples to visit during the trip to Japan. " * 5


class OrganizeTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(watched_folders=[{"path": "{DESKTOP}", "include_folders": False},
                                                {"path": "{IN}", "include_folders": True}],
                               ai={"mode": "limited", "provider": "groq",
                                   "candidate_folders": [{"path": "{D}", "depth": 2}]})
        self.desktop = self.folder("home", "Desktop")
        self.recipes = self.folder("dest", "Recipes")
        self.requests = []
        self.groups = []          # what the fake AI answers: [(title, folder name or "", new name, [item names])]

    def put(self, name, text="x", folder="home\\Desktop"):
        return self.write(name, text, folder=folder)

    def fake_complete(self, params, cfg, key, log, files=0, shape=""):
        text = params["messages"][0]["content"][0]["text"]
        self.requests.append(text)
        items = dict((name, int(n)) for n, name in re.findall(r"^(\d+) (\S+) \(", text.split("Items (i):")[1], re.M))
        dests = text.split("Existing folders (f):")[1].split("\n\n")[0].strip().splitlines()
        rows = []
        for title, existing, new, names in self.groups:
            f = next((int(ln.split()[0]) for ln in dests if existing and ln.endswith(existing)), 0)
            rows.append({"t": title, "f": f, "n": new, "i": [items[n] for n in names if n in items], "why": "same topic"})
        return "```json\n" + json.dumps({"groups": rows}) + "\n```"

    def plan(self, folder=None):
        with mock.patch.object(ai, "complete", side_effect=self.fake_complete):
            return organize.plan_folder(folder or self.desktop, self.cfg, "key", lambda m: None)


class TestCrowded(OrganizeTest):
    def test_lists_crowded_folders_only(self):
        for i in range(11):
            self.put(f"file_{i}.txt")
        self.put("!keep.txt")
        self.put("game.lnk")
        for i in range(15):
            self.write(f"main_{i}.c", "x", folder="home\\Documents\\firmware")
        self.write(".git", "x", folder="home\\Documents\\firmware")
        for i in range(3):
            self.write(f"ch{i}.txt", "x", folder="home\\Documents\\Thesis")
        spots = organize.crowded(self.cfg)
        self.assertEqual([s.path for s in spots], [self.desktop])
        self.assertEqual(spots[0].files, 11)                         # "!" names and shortcuts don't count

    def test_folders_that_stay(self):
        pinned = self.folder("home", "Desktop", "Study")
        folders.pin(pinned)
        self.folder("home", "Desktop", "!private")
        self.write("pyvenv.cfg", "home = C:\\Python", folder="home\\Desktop\\tool\\.venv")
        self.folder("home", "Desktop", "Holiday")
        self.put("a.txt")
        names = sorted(os.path.basename(p) for p, _ in organize.loose(self.desktop, self.cfg))
        self.assertEqual(names, ["Holiday", "a.txt"])

    def test_new_folders_go_to_documents_for_downloads_and_the_pile(self):
        self.assertEqual(organize.new_base(self.desktop, self.cfg), self.desktop)
        self.assertEqual(organize.new_base(self.path("in"), self.cfg), self.cfg.expand("{DOCS}"))
        self.assertEqual(organize.new_base(self.cfg.default_destination, self.cfg), self.cfg.expand("{DOCS}"))


class TestProgramFolders(OrganizeTest):
    """Folders that belong to a program (game saves, settings, snippets) are never organised or moved: found in
    the real Documents folder of a Windows PC during testing (Call of Duty, Rockstar Games, Visual Studio)."""

    def setUp(self):
        super().setUp()
        folders._apps.clear()
        for i in range(12):
            self.write(f"config_{i}.cfg", "x", folder="home\\Documents\\Call of Duty\\players\\487451467")
            self.write(f"data_{i}.dat", "x", folder="home\\Documents\\SomeLauncher\\cache")
            self.write(f"letter_{i}.docx", "x", folder="home\\Documents\\Letters")
        for i in range(30):
            self.write(f"App {i}.lnk", "x", folder="home\\Desktop")             # shortcuts don't count
        self.write("notes.txt", "x", folder="home\\Desktop")
        self.docs = self.cfg.expand("{DOCS}")

    def test_by_name_and_by_content(self):
        self.assertTrue(folders.app_owned(os.path.join(self.docs, "Call of Duty", "players", "487451467")))
        self.assertTrue(folders.app_owned(os.path.join(self.docs, "SomeLauncher")))           # .dat files
        self.assertFalse(folders.app_owned(os.path.join(self.docs, "Letters")))
        self.assertFalse(folders.app_owned(self.desktop))
        self.assertTrue(folders.APP_NAMES.match("Visual Studio 2022"))
        self.assertTrue(folders.APP_NAMES.match("My Games"))
        self.assertFalse(folders.APP_NAMES.match("Thesis"))

    def test_never_crowded_never_moved(self):
        cfg = self.config(watched_folders=[{"path": "{DESKTOP}"}, {"path": "{DOCS}"}])
        paths = [s.path for s in organize.crowded(cfg)]
        self.assertIn(os.path.join(self.docs, "Letters"), paths)
        self.assertFalse(any("Call of Duty" in p or "SomeLauncher" in p for p in paths))
        for i in range(10):
            self.write(f"to_sort_{i}.txt", "x", folder="home\\Documents")
        names = [os.path.basename(p) for p, _ in organize.loose(self.docs, cfg)]
        self.assertIn("Letters", names)
        self.assertNotIn("Call of Duty", names)
        self.assertNotIn("SomeLauncher", names)

    def test_advice_refuses_to_move_them(self):
        from desktidy import ops
        why = ops._refuse(os.path.join(self.docs, "SomeLauncher"), self.cfg)
        self.assertIn("belongs to a program", why)

    def test_duplicates_leave_them_alone(self):
        from desktidy import duplicates
        big = b"z" * (600 * 1024)
        for folder in ("home\\Documents\\SomeLauncher", "home\\Documents\\Letters"):
            with open(self.path(*folder.split("\\"), "same.bin"), "wb") as f:
                f.write(big)
        self.assertEqual(duplicates.find(self.cfg), [])


class TestPlan(OrganizeTest):
    def setUp(self):
        super().setUp()
        for n in ("thesis_ch1.txt", "thesis_ch2.txt", "thesis_sources.txt"):
            self.put(n, THESIS)
        for n in ("kyoto_hotels.txt", "rail_pass.txt"):
            self.put(n, JAPAN)
        self.put("carbonara.txt", "Spaghetti, eggs, pecorino, guanciale, black pepper. " * 5)
        self.put("payslip_march.txt", "Payslip March: gross pay 2400, net pay 1800, tax, deductions. " * 5)
        self.put("calculus_exercises.txt", "Exercises on derivative and integral. " * 5)
        self.put("random.txt", "nothing in common " * 10)
        self.groups = [("Thesis", "", "Thesis", ["thesis_ch1.txt", "thesis_ch2.txt", "thesis_sources.txt"]),
                       ("Trip to Japan", "", "Trip to Japan", ["kyoto_hotels.txt", "rail_pass.txt"]),
                       ("Alone", "", "Alone", ["random.txt"]),
                       ("Recipes", "Recipes", "", ["carbonara.txt"])]

    def test_groups_new_and_existing_folders(self):
        r = self.plan()
        by_title = {g["title"]: g for g in r["groups"]}
        thesis = by_title["Thesis"]
        self.assertEqual(thesis["target"], os.path.join(self.desktop, "Thesis"))
        self.assertTrue(thesis["new"])
        self.assertEqual(len(thesis["files"]), 3)
        self.assertEqual(by_title["Trip to Japan"]["target"], os.path.join(self.desktop, "Trip_to_Japan"))
        self.assertEqual(by_title["Recipes"]["target"], self.recipes)  # an existing folder that fits
        self.assertFalse(by_title["Recipes"]["new"])
        self.assertNotIn("Alone", by_title)                            # a new folder for one file: no
        self.assertEqual(r["left"], 1)

    def test_private_files_never_reach_the_ai(self):
        r = self.plan()
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("payslip", self.requests[0].lower())
        ruled = {os.path.basename(g["target"]): g for g in r["groups"] if g["source"] == "rules"}
        self.assertEqual([os.path.basename(f) for f in ruled["Payslips"]["files"]], ["payslip_march.txt"])
        self.assertIn("Maths", ruled)                                  # what the rules place, offline

    def test_always_ai_reads_private_documents_too(self):
        self.cfg = self.config(watched_folders=[{"path": "{DESKTOP}"}],
                               ai={"mode": "all", "provider": "groq", "candidate_folders": [{"path": "{D}", "depth": 2}]})
        self.plan()
        self.assertIn("payslip_march.txt", self.requests[0])

    def test_the_ai_reads_little(self):
        self.plan()
        line = next(ln for ln in self.requests[0].splitlines() if "thesis_ch1.txt" in ln)
        self.assertLess(len(line), 400)
        self.assertIn("renewable", line)

    def test_requests_of_many_items_reuse_the_names(self):
        for i in range(4):
            self.put(f"thesis_extra_{i}.txt", THESIS)
        self.groups = [("Thesis", "", "Thesis", [f"thesis_extra_{i}.txt" for i in range(4)]
                        + ["thesis_ch1.txt", "thesis_ch2.txt", "thesis_sources.txt"])]
        with mock.patch.object(organize, "CHUNK", 4):
            r = self.plan()
        self.assertGreater(len(self.requests), 1)
        self.assertIn("New folders already planned", self.requests[1])
        thesis = [g for g in r["groups"] if g["source"] == "ai"]
        self.assertEqual(len(thesis), 1)
        self.assertEqual(len(thesis[0]["files"]), 7)

    def test_no_answer(self):
        with mock.patch.object(ai, "complete", return_value=None):
            r = organize.plan_folder(self.desktop, self.cfg, "key", lambda m: None)
        self.assertTrue(r["failed"])
        self.assertTrue(all(g["source"] == "rules" for g in r["groups"]))


class TestApply(OrganizeTest):
    def setUp(self):
        super().setUp()
        for n in ("thesis_ch1.txt", "thesis_ch2.txt", "thesis_sources.txt"):
            self.put(n, THESIS)
        self.put("carbonara.txt", "Spaghetti, eggs, pecorino, guanciale. " * 5)
        self.write("carbonara.txt", "an older one", folder="dest\\Recipes")
        self.groups = [("Thesis", "", "Thesis", ["thesis_ch1.txt", "thesis_ch2.txt", "thesis_sources.txt"]),
                       ("Recipes", "Recipes", "", ["carbonara.txt"])]
        organize.save([self.plan()], self.cfg)
        self.thesis = os.path.join(self.desktop, "Thesis")

    def test_apply_all_then_undo(self):
        organize.apply([1, 2], self.cfg, pin=True)
        self.assertEqual(sorted(os.listdir(self.thesis)), ["thesis_ch1.txt", "thesis_ch2.txt", "thesis_sources.txt"])
        self.assertEqual(sorted(os.listdir(self.recipes)), ["carbonara.txt", "carbonara_v2.txt"])  # nothing lost
        self.assertTrue(any(os.path.normcase(p.path) == os.path.normcase(self.thesis) for p in folders.active_pinned()))
        moves = service.read_moves()
        self.assertEqual(len(moves), 4)
        self.assertTrue(all(m["action"] == "MOVED" and m["reason"].startswith("organize:") for m in moves))
        self.assertTrue(all(g.get("applied") for g in organize.load()["groups"]))

        entry = organize.undo(self.cfg)
        self.assertEqual(entry["skipped"], [])
        self.assertFalse(os.path.exists(self.thesis))                  # the new folder, empty again, is gone
        self.assertIn("carbonara.txt", os.listdir(self.desktop))
        self.assertEqual(os.listdir(self.recipes), ["carbonara.txt"])
        self.assertFalse(folders.active_pinned())
        self.assertEqual(sum(1 for m in service.read_moves() if m["action"] == "UNDONE"), 4)
        self.assertTrue(service.Service.is_kept(os.path.join(self.desktop, "thesis_ch1.txt")))
        self.assertFalse(any(g.get("applied") for g in organize.load()["groups"]))

    def test_one_group(self):
        organize.apply([2], self.cfg)
        self.assertFalse(os.path.exists(self.thesis))
        self.assertNotIn("carbonara.txt", os.listdir(self.desktop))
        with self.assertRaises(ValueError):
            organize.apply([2], self.cfg)                              # already done

    def test_undo_goes_on_when_a_file_was_moved_meanwhile(self):
        organize.apply([1], self.cfg)
        os.replace(os.path.join(self.thesis, "thesis_ch2.txt"), self.path("elsewhere", "thesis_ch2.txt"))
        entry = organize.undo(self.cfg)
        self.assertEqual(len(entry["skipped"]), 1)
        self.assertIn("thesis_ch1.txt", os.listdir(self.desktop))
        self.assertIn("thesis_sources.txt", os.listdir(self.desktop))

    def test_a_taken_name_is_not_overwritten_on_undo(self):
        organize.apply([1], self.cfg)
        self.put("thesis_ch1.txt", "a new file with the old name")
        organize.undo(self.cfg)
        self.assertIn("thesis_ch1_v2.txt", os.listdir(self.desktop))

    def test_undo_only_the_latest_change(self):
        organize.apply([1], self.cfg)
        config.write_json(config.path("ops"), ops.journal() + [
            {"id": "x", "at": "2026-10-12T10:00:00", "title": "Merge", "tip": {"kind": "merge"}, "steps": [],
             "changes": [], "undone": False}])
        self.assertIsNone(organize.undo(self.cfg))
        self.assertTrue(os.path.isdir(self.thesis))

    def test_files_gone_since_the_plan(self):
        os.remove(os.path.join(self.desktop, "thesis_ch2.txt"))
        plan, notes = organize.steps(organize.load()["groups"][:1], self.cfg)
        self.assertEqual(sum(1 for s in plan.steps if s["op"] == "move"), 2)
        self.assertTrue(any("thesis_ch2.txt" in n for n in notes))


class TestOffline(OrganizeTest):
    """No AI (rules only, no key, --offline): the offline engine groups by names and words in common."""

    def setUp(self):
        super().setUp()
        for n in ("thesis_ch1.txt", "thesis_ch2.txt", "thesis_sources.txt"):
            self.put(n, THESIS)
        for n in ("kyoto_hotels.txt", "kyoto_rail_pass.txt", "kyoto_temples.txt"):
            self.put(n, JAPAN)
        self.put("payslip_march.txt", "Payslip March: gross pay 2400, net pay 1800, tax, deductions. " * 5)
        self.put("random.txt", "nothing in common " * 10)

    def plan_offline(self):
        with mock.patch.object(ai, "complete", side_effect=AssertionError("no AI offline")):
            return organize.plan_folder(self.desktop, self.cfg, None, lambda m: None)

    def test_groups_without_the_ai(self):
        r = self.plan_offline()
        offline = [g for g in r["groups"] if g["source"] == "offline"]
        self.assertEqual(sorted(len(g["files"]) for g in offline), [3, 3])
        for g in offline:
            names = {os.path.basename(f).split("_")[0] for f in g["files"]}
            self.assertEqual(len(names), 1, g["files"])                   # thesis with thesis, kyoto with kyoto
            self.assertEqual(os.path.dirname(g["target"]), self.desktop)   # new folders where the files are
            self.assertTrue(g["new"])
        self.assertTrue(any(g["source"] == "rules" for g in r["groups"]))  # the payslip, by the rules
        self.assertEqual(r["left"], 1)
        self.assertFalse(r["failed"])

    def test_private_items_are_grouped_offline(self):
        self.cfg = self.config(watched_folders=[{"path": "{DESKTOP}"}],
                               rules=[{"name": "Mine", "name_words": ["kyoto"], "destination": "{DESKTOP}",
                                       "private": True}])
        self.assertEqual(organize.survey(self.desktop, self.cfg).private, 3)               # not to the AI
        self.assertEqual(organize.survey(self.desktop, self.cfg, offline=True).private, 0)  # offline: grouped
        r = self.plan_offline()
        self.assertTrue(any("kyoto_hotels.txt" in " ".join(g["files"]) for g in r["groups"]))

    def test_the_command_falls_back_and_says_so(self):
        self.cfg = self.config(watched_folders=[{"path": "{DESKTOP}"}], ai={"mode": "off"})
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        out = []
        with mock.patch.object(cli.tidyup, "info", side_effect=out.append), mock.patch("sys.stdout"), \
                mock.patch("sys.stdin") as stdin, mock.patch.object(ai, "complete") as complete:
            stdin.isatty.return_value = False
            cli.cmd_organize(["desktop"])
        complete.assert_not_called()
        self.assertTrue(any("offline engine" in m for m in out))
        self.assertEqual(organize.load()["service"], organize.OFFLINE)
        self.assertTrue(organize.load()["groups"])

    def test_offline_on_request_even_with_an_ai(self):
        self.cfg = self.config(watched_folders=[{"path": "{DESKTOP}"}], ai={"mode": "limited", "provider": "ollama"})
        os.replace(self.path("_data", "rules.json"), config.path("rules"))
        with mock.patch("sys.stdout"), mock.patch("sys.stdin") as stdin, mock.patch.object(ai, "complete") as complete:
            stdin.isatty.return_value = False
            cli.cmd_organize(["desktop", "--offline"])
        complete.assert_not_called()
        self.assertEqual(organize.load()["service"], organize.OFFLINE)


class TestDatedTargets(OrganizeTest):
    def test_every_new_level_is_undone(self):
        for n, day in (("bill_a.txt", "03/11/2025"), ("bill_b.txt", "07/01/2026")):
            self.put(n, f"Invoice date: {day}\nAmount due 10.00 " * 3)
        group = {"title": "Bills", "target": self.dest("Money", "Bills", "{YEAR}"), "new": True, "source": "offline",
                 "folder": self.desktop, "files": [os.path.join(self.desktop, n) for n in ("bill_a.txt", "bill_b.txt")]}
        config.write_json(config.path("organize"), {"groups": [group], "folders": []})
        plan, _ = organize.steps([group], self.cfg, pin=True)
        made = [s["path"] for s in plan.steps if s["op"] == "mkdir"]
        self.assertEqual(made, [self.dest("Money"), self.dest("Money", "Bills"), self.dest("Money", "Bills", "2025"),
                                self.dest("Money", "Bills", "2026")])
        self.assertFalse(any(s["op"] == "pin" for s in plan.steps))       # a dated folder is never pinned
        organize.apply([1], self.cfg)
        self.assertEqual(os.listdir(self.dest("Money", "Bills", "2025")), ["bill_a.txt"])
        self.assertEqual(os.listdir(self.dest("Money", "Bills", "2026")), ["bill_b.txt"])
        organize.undo(self.cfg)
        self.assertFalse(os.path.exists(self.dest("Money")))               # nothing left behind
        self.assertEqual(sorted(os.listdir(self.desktop)), ["bill_a.txt", "bill_b.txt"])


class TestParse(IsolatedTest):
    def test_numbers_are_checked(self):
        text = json.dumps({"groups": [
            {"t": "A", "f": 0, "n": "Città d'arte", "i": [1, 2, 2, 99], "why": ""},
            {"t": "B", "f": 0, "n": "B", "i": [2, 3], "why": ""},          # 2 is taken already
            {"t": "C", "f": 7, "n": "", "i": [4], "why": ""},              # no folder 7, no name
            {"t": "D", "f": 1, "n": "", "i": "x", "why": ""},
        ]})
        rows = organize.parse(text, 4, 2)
        self.assertEqual([(r["name"], r["items"]) for r in rows], [("Citta_d_arte", [1, 2]), ("B", [3])])
        self.assertEqual(organize.parse("not json", 4, 2), [])


class TestCommand(IsolatedTest):
    def test_names(self):
        number = next(c[0] for c in cli.COMMANDS if c[1] == "organize")
        for name in ("organize", "organise", "riordina", str(number)):
            self.assertIs(cli.find_command(name), cli.cmd_organize)


class TestAlwaysAI(IsolatedTest):
    """desktidy ai rules / desktidy ai all: the two big choices."""

    def mode(self):
        return config.ai_mode(config.load_config())

    def test_rules_and_always(self):
        self.config(ai={"mode": "limited", "provider": "ollama"})
        with mock.patch("sys.stdout"):
            cli.cmd_ai(["sempre"])
            self.assertEqual(self.mode(), "all")
            cli.cmd_ai(["rules"])
        self.assertEqual(self.mode(), "off")

    def test_a_cloud_service_is_named_and_asked_first(self):
        self.config(ai={"mode": "limited", "provider": "groq"})
        said = []
        with mock.patch.object(cli.ai_cmds, "warn", side_effect=said.append), mock.patch.object(cli.ai_cmds, "hint"), \
                mock.patch.object(cli.ui, "INTERACTIVE", True), mock.patch.object(cli.ai_cmds, "confirm", return_value=False):
            cli.cmd_ai(["all"])
        self.assertEqual(self.mode(), "limited")              # the user said no
        self.assertIn("Groq", said[0])
