"""Smart renaming: generic names, names that don't match the content, titles."""

import unittest

from desktidy import content as ct
from desktidy import naming
from tests.helpers import IsolatedTest

LONG_INVOICE = ("Invoice 2231 from Northwind Energy\n" + "Customer number 55120, electricity supply for September, "
                "amount due 84.20, payment by direct debit, due date 30 October. " * 6)


class TestGeneric(unittest.TestCase):
    def test_generic_names(self):
        for stem in ("scan0001", "Document1", "download (3)", "IMG_2034", "untitled", "Senza titolo", "2026-10-07",
                     "a1b2c3d4e5f6", "A021_ORD26", "4779392A_Y12", "doc", "Presentazione1", "x"):
            self.assertTrue(naming.is_generic(stem), stem)

    def test_meaningful_names(self):
        for stem in ("presentazione_finale", "Thesis_signal_processing", "Calculus notes week 3", "STM32F4_manual",
                     "my cv", "recipe pasta"):
            self.assertFalse(naming.is_generic(stem), stem)


class TestTitle(IsolatedTest):
    def analysis(self, p):
        return ct.analyze(p, False, {"analysis": {"ocr": False}})

    def test_metadata_title_wins(self):
        p = self.docx("Document1.docx", ["some text here"], title="Lab report: RC filters")
        self.assertEqual(naming.title(self.analysis(p)), "Lab report: RC filters")

    def test_junk_metadata_is_ignored(self):
        p = self.docx("Document1.docx", ["Quarterly sales review", "Body text follows."], title="Microsoft Word - Document1")
        self.assertEqual(naming.title(self.analysis(p)), "Quarterly sales review")

    def test_first_heading(self):
        p = self.write("scan0001.txt", "\nPage 1\nInvoice 2231 from Northwind Energy\nCustomer 55120\n")
        self.assertEqual(naming.title(self.analysis(p)), "Invoice 2231 from Northwind Energy")

    def test_short_heading_beats_a_long_line(self):
        p = self.write("Documento3.txt", "Relazione di laboratorio\nMisura della resistenza su un circuito RC.\n"
                                         "Tensione e corrente misurate, incertezza di misura calcolata. Relazione finale\n")
        self.assertEqual(naming.title(self.analysis(p)), "Relazione di laboratorio")

    def test_sentences_are_not_titles(self):
        p = self.write("x.txt", "Today in class we looked at the derivative of a composite function and much more.\n")
        self.assertIsNone(naming.title(self.analysis(p)))


class TestPlan(IsolatedTest):
    cfg = {"rename": {"mode": "smart"}}

    def plan(self, p, cfg=None):
        return naming.plan(ct.analyze(p, False, {"analysis": {"ocr": False}}), cfg or self.cfg)

    def test_generic_name_gets_the_title(self):
        plan = self.plan(self.write("scan0001.txt", LONG_INVOICE))
        self.assertEqual(plan.new_stem, "Invoice_2231_from_Northwind_Energy")
        self.assertIn("generic", plan.reason)

    def test_mismatching_name_gets_the_title(self):
        plan = self.plan(self.write("holiday_photos_list.txt", LONG_INVOICE))
        self.assertEqual(plan.new_stem, "Invoice_2231_from_Northwind_Energy")
        self.assertIn("didn't match", plan.reason)

    def test_matching_name_is_kept(self):
        self.assertIsNone(self.plan(self.write("northwind_invoice.txt", LONG_INVOICE)).new_stem)

    def test_generic_mode_ignores_mismatches(self):
        self.assertIsNone(self.plan(self.write("holiday_photos.txt", LONG_INVOICE), {"rename": {"mode": "generic"}}).new_stem)

    def test_off(self):
        self.assertIsNone(self.plan(self.write("scan0001.txt", LONG_INVOICE), {"rename": {"mode": "off"}}).new_stem)

    def test_no_title_asks_the_ai_and_has_a_fallback(self):
        text = "milk eggs bread butter cheese apples bananas pasta rice tomatoes " * 4
        plan = self.plan(self.write("scan0002.txt", text))
        self.assertIsNone(plan.new_stem)
        self.assertTrue(plan.ask_ai)
        self.assertTrue(plan.fallback)

    def test_photos_are_never_renamed(self):
        self.assertIsNone(self.plan(self.image("IMG_0001.jpg", 640, 480, exif=True)).new_stem)

    def test_final_name(self):
        self.assertEqual(naming.final_name("scan0001.PDF", "Invoice_2231"), "Invoice_2231.pdf")
        self.assertEqual(naming.final_name("My File (1).txt", None), "My_File.txt")


if __name__ == "__main__":
    unittest.main()
