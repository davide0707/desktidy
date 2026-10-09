"""Shared test tools: an isolated data folder, sample files and a test configuration."""

import json
import os
import shutil
import tempfile
import unittest
import zipfile

from desktidy import config


def native(p: str) -> str:
    """Test paths are written Windows-style ("dest\\Study\\Maths"): this system's separators."""
    return p.replace("\\", os.sep)


class IsolatedTest(unittest.TestCase):
    """Every test gets its own DESKTIDY_HOME: logs, spend and pinned folders never touch the real ones."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="desktidy_test_")
        self._home = os.environ.get("DESKTIDY_HOME")
        os.environ["DESKTIDY_HOME"] = os.path.join(self.tmp, "_data")
        # {HOME}, {DOCS}, {DESKTOP}... point inside the test folder too: no test may ever reach the real user folders
        self._builtins = dict(config.BUILTIN_VARIABLES)
        home = os.path.join(self.tmp, "home")
        config.BUILTIN_VARIABLES.update(HOME=home, **{k: os.path.join(home, v) for k, v in (
            ("DOCS", "Documents"), ("DOWNLOADS", "Downloads"), ("DESKTOP", "Desktop"), ("PICTURES", "Pictures"),
            ("VIDEOS", "Videos"), ("MUSIC", "Music"))})

    def tearDown(self):
        config.BUILTIN_VARIABLES.clear()
        config.BUILTIN_VARIABLES.update(self._builtins)
        if self._home is None:
            os.environ.pop("DESKTIDY_HOME", None)
        else:
            os.environ["DESKTIDY_HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, *parts):
        p = os.path.join(self.tmp, *map(native, parts))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def folder(self, *parts):
        p = os.path.join(self.tmp, *map(native, parts))
        os.makedirs(p, exist_ok=True)
        return p

    def write(self, name, text, folder="in"):
        p = self.path(folder, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def docx(self, name, paragraphs, title="", folder="in"):
        p = self.path(folder, name)
        body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                       f'2006/main"><w:body>{body}</w:body></w:document>')
            if title:
                z.writestr("docProps/core.xml", f'<cp:coreProperties xmlns:dc="http://purl.org/dc/elements/1.1/">'
                           f"<dc:title>{title}</dc:title></cp:coreProperties>")
        return p

    def pdf(self, name, lines, folder="in"):
        """Minimal PDF with real text (like the ones exported by Word)."""
        stream = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({x}) '" for x in lines) + " ET"
        objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
                   "/Resources << /Font << /F1 5 0 R >> >> >>",
                   f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
                   "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        out, offsets = "%PDF-1.4\n", []
        for i, o in enumerate(objects, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n{o}\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{q:010d} 00000 n \n" for q in offsets)
        out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
        p = self.path(folder, name)
        with open(p, "w", encoding="latin-1") as f:
            f.write(out)
        return p

    def image(self, name, w, h, exif=False, transparent=False, folder="in"):
        from PIL import Image
        p = self.path(folder, name)
        im = Image.new("RGBA" if transparent else "RGB", (w, h), (90, 120, 200, 0) if transparent else (90, 120, 200))
        if exif:
            e = Image.Exif()
            e[271], e[272] = "Google", "Pixel 8"
            im.save(p, exif=e)
        else:
            im.save(p)
        return p

    def config(self, **changes):
        """A rules.json whose destinations are all inside the temporary folder."""
        dest = os.path.join(self.tmp, "dest")
        cfg = {
            "variables": {"D": dest, "IN": os.path.join(self.tmp, "in"), "INSTALLERS": os.path.join(dest, "Installers")},
            "watched_folders": [{"path": "{IN}", "wait_seconds": 0, "include_folders": True}],
            "default_destination": "{D}\\00_Inbox\\To_Sort",
            "analysis": {"ocr": False, "similarity": True},
            "pinned_folders": {"ask": False, "min_required": 0},
            "ai": {"mode": "off", "candidate_folders": [{"path": "{D}", "depth": 2}]},
            "rules": [
                {"name": "Maths", "name_words": ["analisi 1", "calculus"], "content_words": ["calculus"],
                 "topics": ["derivative", "integral", "limit", "theorem", "asymptote", "derivata", "integrale"],
                 "destination": "{D}\\Study\\Maths"},
                {"name": "Notes", "name_words": ["notes", "appunti"], "generic": True, "destination": "{D}\\Study\\Notes"},
                {"name": "Payslips", "name_words": ["payslip"], "content_words": ["payslip"],
                 "topics": ["gross pay", "net pay", "tax", "deductions", "national insurance"], "min_topics": 3,
                 "destination": "{D}\\Personal\\Payslips", "private": True},
                {"name": "Screenshots", "extensions": [".png", ".jpg"], "name_words": ["screenshot"],
                 "recognize": ["screenshot"], "destination": "{D}\\Screenshots", "private": True},
                {"name": "Photos", "extensions": [".jpg", ".png"], "name_words": ["img", "whatsapp"],
                 "recognize": ["photo", "photo_folder"], "destination": "{D}\\Photos", "private": True},
                {"name": "PCB", "type": "both", "name_words": ["pcb", "gerber"],
                 "recognize": ["project_kicad", "gerber"], "destination": "{D}\\Projects\\PCB"},
                {"name": "Installers", "extensions": [".exe", ".msi"], "destination": "{INSTALLERS}"},
                {"name": "Python", "extensions": [".py"], "recognize": ["code_python"], "destination": "{D}\\Projects\\Python"},
            ],
        }
        cfg.update(changes)
        p = self.path("_data", "rules.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return config.load_config(p)

    def dest(self, *parts):
        return os.path.join(self.tmp, "dest", *parts)
