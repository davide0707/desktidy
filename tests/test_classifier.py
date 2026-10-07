"""Where a file goes: name, content, recognised kinds, generic rules, pinned folders, AI modes."""

import os
import unittest

from desktidy import classifier, config, folders
from desktidy import content as ct
from tests.helpers import IsolatedTest


class TestDecisions(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config()

    def where(self, p):
        an = ct.analyze(p, os.path.isdir(p), self.cfg)
        d = classifier.decide(p, os.path.isdir(p), self.cfg, an)
        return (os.path.relpath(d.dest, self.dest()) if d.dest else None), d.reason

    def test_name(self):
        self.assertEqual(self.where(self.write("Calculus - exam.txt", "x"))[0], "Study\\Maths")

    def test_typo_in_name(self):
        dest, reason = self.where(self.write("analis 1.txt", "hello"))
        self.assertEqual(dest, "Study\\Maths")
        self.assertIn("similar", reason)

    def test_content_without_words_in_the_name(self):
        p = self.write("stuff.txt", "We computed the derivative, then an integral and a famous limit. "
                                    "Exercise: find the oblique asymptote.")
        dest, reason = self.where(p)
        self.assertEqual(dest, "Study\\Maths")
        self.assertIn("about", reason)

    def test_generic_rule_gives_way_to_content(self):
        p = self.write("notes_misc.txt", "Today the derivative and the integral, the mean value theorem and a limit.")
        self.assertEqual(self.where(p)[0], "Study\\Maths")

    def test_generic_rule_stays_when_content_says_nothing(self):
        self.assertEqual(self.where(self.write("notes_misc.txt", "milk eggs bread"))[0], "Study\\Notes")

    def test_private_from_content(self):
        p = self.docx("doc1.docx", ["Gross pay 2,000", "Tax and national insurance deductions", "Net pay 1,600"])
        d = classifier.decide(p, False, self.cfg, ct.analyze(p, False, self.cfg))
        self.assertTrue(d.dest.endswith("Payslips"))
        self.assertTrue(d.private)

    def test_recognised_kinds(self):
        self.assertEqual(self.where(self.image("image.png", 1920, 1080))[0], "Screenshots")
        self.assertEqual(self.where(self.image("x.jpg", 640, 480, exif=True))[0], "Photos")
        code = "import os\n\ndef main():\n    print(os.getcwd())\n\nif __name__ == '__main__':\n    main()\n"
        self.assertEqual(self.where(self.write("note.txt", code))[0], "Projects\\Python")

    def test_project_folder(self):
        for n in ("a.kicad_pro", "a.kicad_pcb"):
            self.write(n, "x", folder=os.path.join("in", "power_supply"))
        self.assertEqual(self.where(os.path.join(self.tmp, "in", "power_supply"))[0], "Projects\\PCB")

    def test_programs_only_go_to_installers(self):
        self.assertEqual(self.where(self.write("pcb_tool_setup.exe", "MZ"))[0], "Installers")

    def test_no_rule(self):
        self.assertEqual(self.where(self.write("list.txt", "milk eggs bread")), (None, "no rule matched"))


class TestPinnedFolders(IsolatedTest):
    def setUp(self):
        super().setUp()
        self.cfg = self.config()
        self.pasta = self.folder("Desktop", "pasta")
        folders.pin(self.pasta, ["carbonara"])

    def where(self, p):
        return classifier.decide(p, False, self.cfg).dest

    def test_by_name(self):
        self.assertEqual(self.where(self.write("baked pasta recipe.pdf", "x")), self.pasta)

    def test_by_extra_word(self):
        self.assertEqual(self.where(self.write("Carbonara.txt", "eggs")), self.pasta)

    def test_by_content(self):
        p = self.write("recipe.txt", "Cook the pasta in plenty of salted water. Drain the pasta al dente.")
        self.assertEqual(self.where(p), self.pasta)

    def test_unpin(self):
        self.assertTrue(folders.unpin(self.pasta))
        self.assertNotEqual(self.where(self.write("pasta.txt", "x")), self.pasta)
        self.assertEqual(folders.active_pinned(), [])


class TestAIModes(unittest.TestCase):
    def decision(self, strength, private=False):
        return classifier.Decision("x" if strength != "none" else None, "", strength, private)

    def test_modes(self):
        if not classifier.AI_AVAILABLE:
            self.skipTest("anthropic is not installed")
        an = ct.Analysis("C:\\x\\a.txt", False)
        expected = {"off": (False, False, False), "limited": (True, False, False),
                    "moderate": (True, True, False), "ai-only": (True, True, True)}
        for mode, wanted in expected.items():
            got = tuple(classifier.wants_ai(self.decision(s), an, {"ai": {"mode": mode}}) for s in ("none", "weak", "strong"))
            self.assertEqual(got, wanted, mode)

    def test_never_for_private_files(self):
        an = ct.Analysis("C:\\x\\a.txt", False)
        self.assertFalse(classifier.wants_ai(self.decision("none", private=True), an, {"ai": {"mode": "ai-only"}}))

    def test_unknown_mode_means_off(self):
        self.assertEqual(config.ai_mode({"ai": {"mode": "boh"}}), "off")


if __name__ == "__main__":
    unittest.main()
