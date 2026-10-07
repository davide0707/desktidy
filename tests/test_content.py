"""Understanding content without AI: words, document text, images, code, folders and zip files."""

import codecs
import os
import unittest
import zipfile

from desktidy import content as ct
from tests.helpers import IsolatedTest

NO_OCR = {"analysis": {"ocr": False}}


class TestWords(unittest.TestCase):
    def test_stem_joins_singular_and_plural(self):
        for a, b in (("esercizio", "esercizi"), ("lezione", "lezioni"), ("invoice", "invoices"), ("slides", "slide")):
            self.assertEqual(ct.stem(a), ct.stem(b), (a, b))

    def test_near_allows_one_typo(self):
        self.assertTrue(ct.near("segretria", "segreteria"))   # missing letter
        self.assertTrue(ct.near("analisi", "anailsi"))        # swapped letters
        self.assertFalse(ct.near("invoice", "voice"))
        self.assertFalse(ct.near("receipt", "recipes"))

    def test_typo_in_name(self):
        an = ct.Analysis("C:\\x\\analis 1.txt", False)
        self.assertIsNone(an.in_name(["analisi 1"], "exact"))
        self.assertEqual(an.in_name(["analisi 1"], "fuzzy"), "analisi 1")

    def test_camel_case_name(self):
        self.assertEqual(ct.Analysis("C:\\x\\NordVPNSetup.exe", False).in_name(["nord"]), "nord")


class TestDocuments(IsolatedTest):
    def test_docx_text_and_title(self):
        an = ct.analyze(self.docx("doc.docx", ["Payslip for September", "Deductions"], title="Payslip 09"), False, NO_OCR)
        self.assertGreater(an.count("payslip"), 0)
        self.assertIn("Payslip 09", an.titles)

    def test_pdf_text(self):
        an = ct.analyze(self.pdf("scan.pdf", ["University of Bologna", "Lecture timetable"]), False, NO_OCR)
        self.assertIn("PDF", an.info["kind"])
        self.assertGreater(an.count("university of bologna"), 0)

    def test_type_detected_from_bytes(self):
        an = ct.analyze(self.pdf("document", ["Invoice number 12"]), False, NO_OCR)
        self.assertEqual(an.ext, ".pdf")
        self.assertGreater(an.count("invoice"), 0)

    def test_encodings(self):
        p = self.path("in", "u16.txt")
        with open(p, "wb") as f:
            f.write(codecs.BOM_UTF16_LE + "perché derivata".encode("utf-16-le"))
        self.assertIn("derivata", ct.read_text(p))
        p = self.path("in", "w.txt")
        with open(p, "wb") as f:
            f.write("città è perché".encode("cp1252"))
        self.assertIn("città", ct.read_text(p))


class TestCode(unittest.TestCase):
    def test_python_in_a_txt(self):
        text = "import os\n\ndef main():\n    for f in os.listdir('.'):\n        print(f)\n\nif __name__ == '__main__':\n    main()\n"
        self.assertIn("code_python", ct.code_tags(text, ".txt"))

    def test_c_in_a_txt(self):
        text = "#include <stdio.h>\n\nint main(void) {\n    int x = 3;\n    printf(\"%d\", x);\n    return 0;\n}\n"
        self.assertIn("code_c", ct.code_tags(text, ".txt"))

    def test_plain_text_is_not_code(self):
        self.assertEqual(ct.code_tags("Shopping list:\nmilk\neggs\nbread\ncall Marco\n", ".txt"), set())


class TestImages(IsolatedTest):
    def test_screenshot_from_size(self):
        an = ct.analyze(self.image("image.png", 1920, 1080), False, NO_OCR)
        self.assertIn("screenshot", an.tags)
        self.assertTrue(an.is_private)

    def test_photo_from_exif(self):
        an = ct.analyze(self.image("x.jpg", 800, 600, exif=True), False, NO_OCR)
        self.assertIn("photo", an.tags)
        self.assertIn("Pixel 8", an.info["camera"])

    def test_transparent_icon(self):
        self.assertIn("icon", ct.analyze(self.image("logo.png", 128, 128, transparent=True), False, NO_OCR).tags)


class TestContainers(IsolatedTest):
    def test_kicad_folder(self):
        for n in ("board.kicad_pro", "board.kicad_pcb", "board.kicad_sch"):
            self.write(n, "x", folder=os.path.join("in", "board"))
        self.assertIn("project_kicad", ct.analyze(os.path.join(self.tmp, "in", "board"), True, NO_OCR).tags)

    def test_gerber_zip(self):
        p = self.path("in", "order.zip")
        with zipfile.ZipFile(p, "w") as z:
            for n in ("b-F_Cu.gtl", "b-B_Cu.gbl", "b-F_Mask.gts", "b.drl"):
                z.writestr(n, "G04*")
        self.assertIn("gerber", ct.analyze(p, False, NO_OCR).tags)

    def test_python_project_folder(self):
        d = os.path.join("in", "project")
        self.write("main.py", "print(1)", folder=d)
        self.write("utils.py", "x = 1", folder=d)
        self.write("requirements.txt", "pypdf", folder=d)
        tags = ct.analyze(os.path.join(self.tmp, d), True, NO_OCR).tags
        self.assertTrue({"project_python", "project_code"} <= tags)


if __name__ == "__main__":
    unittest.main()
