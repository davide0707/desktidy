"""Understand files and folders WITHOUT AI: everything runs on the PC, for free, and nothing is sent anywhere.

What it can do:
  - extract text from PDF, Word/Excel/PowerPoint (old .doc too), LibreOffice, RTF, HTML, e-mail, notebooks,
    epub, plain text and source code; read scanned PDFs and images with the OCR of the system (Windows OCR,
    macOS Vision, Tesseract on Linux)
  - recognise photos (camera EXIF data), screenshots, icons, source code pasted into a .txt, and the kind of
    project inside folders and zip files (Python, web, STM32, KiCad, gerber, 3D printing, photos, music...)
  - collect title candidates (document metadata, e-mail subject, first heading) used to rename files
  - compare words ignoring plural/singular and single typos ("analis 1" ~ "analisi 1", "invoices" ~ "invoice")
"""

from __future__ import annotations

import codecs
import html
import logging
import os
import re
import stat
import tempfile
import zipfile
import zlib
from collections import Counter, OrderedDict
from functools import lru_cache

from . import system
from .config import strip_accents

logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_TEXT = 120_000  # characters analysed per file
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".xml", ".yaml", ".yml", ".ini", ".cfg",
            ".conf", ".toml", ".tex", ".bib", ".srt", ".vtt", ".py", ".pyw", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs",
            ".java", ".js", ".mjs", ".ts", ".jsx", ".tsx", ".go", ".rs", ".php", ".rb", ".kt", ".swift", ".sh", ".bat",
            ".cmd", ".ps1", ".sql", ".ino", ".m", ".r", ".lua", ".asm", ".s", ".vhd", ".vhdl", ".v", ".sv", ".css",
            ".scss"}
HTML_EXT = {".html", ".htm", ".xhtml", ".mht"}
OFFICE_EXT = {".docx", ".docm", ".dotx", ".pptx", ".ppsx", ".xlsx", ".xlsm", ".odt", ".odp", ".ods"}
OLD_OFFICE_EXT = {".doc", ".xls", ".ppt"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".ico"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".m4v", ".3gp"}
PRINT_3D_EXT = {".stl", ".gcode", ".3mf", ".obj", ".step", ".stp", ".f3d"}
GERBER_EXT = {".gbr", ".gtl", ".gbl", ".gto", ".gbo", ".gts", ".gbs", ".gm1", ".gko", ".drl", ".xln"}
FONT_EXT = {".ttf", ".otf", ".woff", ".woff2"}
# formats where it makes sense to look for "what it is about" (topics); not in code or data
DOCUMENT_EXT = {".pdf", ".docx", ".docm", ".doc", ".odt", ".rtf", ".txt", ".md", ".markdown", ".pptx", ".ppsx",
                ".ppt", ".odp", ".xlsx", ".xls", ".ods", ".html", ".htm", ".epub", ".eml", ".tex"}
SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "__pycache__", ".idea", ".vscode", "build", "dist",
             "debug", "release", ".pio", "out", ".next"}
PROJECT_MARKERS = {".git", "package.json", "pyproject.toml", "requirements.txt", "setup.py", "cmakelists.txt",
                   "makefile", ".project", ".cproject", "platformio.ini", "cargo.toml", "go.mod", "next.config.js",
                   "next.config.mjs", "vite.config.js", "vite.config.ts", "index.html", "tsconfig.json"}

STOPWORDS = set("""
a ad al allo ai agli all alla alle con col coi da dal dallo dai dagli dall dalla dalle di del dello dei degli
dell della delle in nel nello nei negli nell nella nelle su sul sullo sui sugli sull sulla sulle per tra fra
il lo la i gli le l un uno una e ed o od ma se che chi cui non piu come dove quando anche ancora gia poi
quindi pero sono sei siamo siete era erano essere stato stata stati state ha hai hanno abbiamo avete avere
aveva questo questa questi queste quello quella quelli quelle mio mia miei mie tuo tua suo sua nostro vostro
loro ci vi si ne mi ti me te lui lei noi voi io tu esso essa molto poco tutto tutti tutte ogni altro altra
altri altre stesso stessa cosa fare fatto puo deve devono sia via ecc etc pag pagina pagine circa sempre dopo
prima mentre senza sopra sotto dentro fuori oppure invece ovvero cioe nuovo nuova nuovi nuove copia documento
documenti oggi ieri domani visto vista visti viste vedere detto dire modo caso volta volte parte bene male
grazie ciao the of and to in is it that for on with as at by from this be are was were or an not but have has
had they you we he she his her its their our your which will would can could should there what all any each
more most other some such than then them these those so if into about up out no only own same too very just
also how why when where who whom do does did done been being over under again once here both few nor off new
copy page pages file files img image pdf txt doc docx final finale definitivo bozza draft www http https com
html
""".split())


# ---------------------------------------------------------------- words
def normalize(s: str) -> str:
    """Lowercase, no accents, only letters and digits, letters split from digits: ' stm 32 cubeprg '."""
    s = re.sub(r"[^a-z0-9]+", " ", strip_accents(s).lower())
    s = re.sub(r"(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])", " ", s)
    return " " + s + " "


def split_camel(s: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)  # NordInstaller -> Nord Installer


def find_word(text: str, words: list[str]) -> str | None:
    """Exact match (after normalize) of one of the words/phrases: returns the first one found."""
    for w in words:
        k = normalize(w).strip()
        if k and re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", text):
            return w
    return None


def stem(w: str) -> str:
    """Tiny Italian/English stemmer: drops plurals and the final vowel, so "esercizio"/"esercizi",
    "lezione"/"lezioni", "invoice"/"invoices", "matematiche"/"matematica" compare equal."""
    if len(w) < 5 or not w.isalpha():
        return w
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if len(w) >= 6 and w.endswith(("io", "ia", "ie", "ii")):
        w = w[:-2]
    elif len(w) >= 5 and w[-1] in "aeiou":
        w = w[:-1]
    if w.endswith(("ch", "gh")) and len(w) >= 5:
        w = w[:-1]
    return w


STOP_STEMS = {stem(w) for w in STOPWORDS}


@lru_cache(maxsize=8192)
def stems(phrase: str) -> tuple[str, ...]:
    return tuple(stem(w) for w in normalize(phrase).split())


def near(a: str, b: str) -> bool:
    """Equal, or one typo apart (one letter added, removed, changed, or two swapped)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1 or min(la, lb) < 5 or not (a.isalpha() and b.isalpha()):
        return False
    i = 0
    while i < min(la, lb) and a[i] == b[i]:
        i += 1
    if la == lb:
        return a[i + 1:] == b[i + 1:] or (i + 1 < la and a[i] == b[i + 1] and a[i + 1] == b[i] and a[i + 2:] == b[i + 2:])
    return a[i + 1:] == b[i:] if la > lb else a[i:] == b[i + 1:]


def phrase_in(sequence: tuple[str, ...], phrase: tuple[str, ...], fuzzy: bool = False) -> bool:
    n = len(phrase)
    if not n:
        return False
    for i in range(len(sequence) - n + 1):
        if all(sequence[i + j] == phrase[j] or (fuzzy and near(sequence[i + j], phrase[j])) for j in range(n)):
            return True
    return False


def informative(text: str) -> list[str]:
    """Stems of the words that carry meaning (no stopwords, numbers, 1-3 letter tokens)."""
    return [s for s in (stem(w) for w in normalize(text).split())
            if len(s) >= 4 and not s.isdigit() and s not in STOP_STEMS]


# ---------------------------------------------------------------- analysis result
class Analysis:
    def __init__(self, path: str, is_dir: bool):
        self.path = path
        self.is_dir = is_dir
        self.name = os.path.basename(path)
        self.ext = "" if is_dir else os.path.splitext(self.name)[1].lower()
        self.stem = self.name if is_dir else os.path.splitext(self.name)[0]
        camel = split_camel(self.stem)
        self.name_norm = normalize(self.stem) + normalize(camel)  # for exact matching
        self.name_seqs = [tuple(stem(w) for w in normalize(x).split()) for x in {self.stem, camel}]
        self.name_terms = informative(camel)
        self.text = ""
        self.titles: list[str] = []   # title candidates, best sources first (metadata, subject...)
        self.tags: set[str] = set()   # what was recognised: photo, screenshot, code_python, project_web...
        self.info: dict = {}          # readable details: kind, pages, camera, ocr...
        self.is_document = is_dir or self.ext in DOCUMENT_EXT or self.ext == ".zip"

    def finish(self) -> Analysis:
        self.text = self.text[:MAX_TEXT]
        words = normalize(self.text).split()
        self.words = len(words)
        stemmed = [stem(w) for w in words]
        self.seq = " " + " ".join(stemmed) + " "
        self.start = " " + " ".join(stemmed[:60]) + " "
        self.counts = Counter(stemmed)
        originals: dict[str, Counter] = {}
        for w, s in zip(words, stemmed):
            originals.setdefault(s, Counter())[w] += 1
        self._originals = originals
        return self

    @property
    def is_private(self) -> bool:
        return bool(self.tags & {"photo", "screenshot", "photo_folder"})

    def original(self, s: str) -> str:
        c = self._originals.get(s)
        return c.most_common(1)[0][0] if c else s

    def count(self, phrase: str) -> int:
        """How many times the word/phrase appears in the content (plural and singular count together)."""
        p = stems(phrase)
        if not p:
            return 0
        if len(p) == 1:
            return self.counts.get(p[0], 0)
        return len(re.findall(r"(?<= )" + re.escape(" ".join(p)) + r"(?= )", self.seq))

    def in_name(self, words: list[str], mode: str = "exact") -> str | None:
        """First word/phrase of the list found in the name. mode: exact, stem (plural/singular), fuzzy (one typo)."""
        if mode == "exact":
            return find_word(self.name_norm, words)
        for w in words:
            p = stems(w)
            if p and any(phrase_in(seq, p, fuzzy=(mode == "fuzzy")) for seq in self.name_seqs):
                return w
        return None

    def keywords(self, n: int = 20) -> list[tuple[str, int]]:
        out = []
        for s, c in self.counts.most_common():
            if len(s) >= 4 and not s.isdigit() and s not in STOP_STEMS:
                out.append((s, c))
                if len(out) >= n:
                    break
        return out

    def describe(self) -> str:
        """One readable line: kind, pages, OCR, camera, words."""
        parts = [self.info.get("kind", self.ext or "file")]
        if self.info.get("ocr"):
            parts.append("text read with OCR")
        if self.info.get("camera"):
            parts.append(f"camera: {self.info['camera']}")
        if self.words:
            parts.append(f"{self.words} words")
        return ", ".join(parts)


_cache: OrderedDict = OrderedDict()


def analyze(path: str, is_dir: bool | None = None, cfg: dict | None = None) -> Analysis:
    """Analyse a file or folder (cached until it changes)."""
    st = os.stat(path)
    if is_dir is None:
        is_dir = stat.S_ISDIR(st.st_mode)
    key = (path, st.st_size, st.st_mtime_ns, is_dir)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    options = (cfg or {}).get("analysis", {})
    an = Analysis(path, is_dir)
    try:
        if is_dir:
            _folder(an)
        else:
            _file(an, options)
    except Exception as ex:  # an unreadable file must never stop anything: the name still decides
        an.info["error"] = f"{type(ex).__name__}: {ex}"
    an.finish()
    _cache[key] = an
    if len(_cache) > 300:
        _cache.popitem(last=False)
    return an


# ---------------------------------------------------------------- files
_SIGNATURES = ((b"%PDF", ".pdf"), (b"\x89PNG", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"),
               (b"PK\x03\x04", ".zip"), (b"MZ", ".exe"), (b"\xd0\xcf\x11\xe0", ".doc"), (b"{\\rtf", ".rtf"))


def _real_type(path: str) -> str:
    """Type from the first bytes, for files without an extension."""
    with open(path, "rb") as f:
        head = f.read(8)
    return next((ext for sig, ext in _SIGNATURES if head.startswith(sig)), "")


def _file(an: Analysis, options: dict) -> None:
    ext = an.ext
    if not ext:
        ext = _real_type(an.path)
        if ext:
            an.info["real_type"] = ext
            an.ext = ext
            an.is_document = ext in DOCUMENT_EXT
    if ext == ".pdf":
        _pdf(an, options)
    elif ext in OFFICE_EXT:
        an.text, title = _office_text(an.path)
        an.titles += [title] if title else []
        an.info["kind"] = "Office/LibreOffice document"
    elif ext in OLD_OFFICE_EXT:
        an.text = _ole_text(an.path)
        an.info["kind"] = "Office document (old format)"
    elif ext in HTML_EXT:
        raw = read_text(an.path)
        title = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
        an.titles += [html.unescape(title.group(1)).strip()] if title else []
        an.text = _strip_tags(raw)
        an.info["kind"] = "web page"
    elif ext == ".rtf":
        an.text = _rtf_text(read_text(an.path))
        an.info["kind"] = "RTF document"
    elif ext == ".eml":
        an.text, subject = _email_text(an.path)
        an.titles += [subject] if subject else []
        an.info["kind"] = "e-mail"
    elif ext == ".ipynb":
        an.text = _notebook_text(an.path)
        an.tags |= {"code", "code_python"}
        an.info["kind"] = "Jupyter notebook"
    elif ext == ".epub":
        an.text, title = _epub_text(an.path)
        an.titles += [title] if title else []
        an.info["kind"] = "epub book"
    elif ext in TEXT_EXT:
        an.text = read_text(an.path)
        an.info["kind"] = "text"
        if ext in (".txt", ".md", ".markdown", ".log"):
            an.tags |= code_tags(an.text, ext)
    elif ext in IMAGE_EXT:
        _image(an, options)
    elif ext == ".zip":
        _zip(an)


def read_text(path: str, limit: int = MAX_TEXT) -> str:
    """Text in any common encoding: UTF-8 (with or without BOM), UTF-16, Windows-1252."""
    with open(path, "rb") as f:
        b = f.read(limit)
    if b.startswith(codecs.BOM_UTF8):
        return b[3:].decode("utf-8", "ignore")
    if b.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return b.decode("utf-16", "ignore")
    if b and b.count(b"\x00") > len(b) // 4:
        return b.decode("utf-16-le", "ignore") if b[1:2] == b"\x00" else ""  # UTF-16 without BOM, or binary
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError as e:
        if e.start >= len(b) - 3:
            return b[:e.start].decode("utf-8", "ignore")  # a character cut in half by the read limit
        return b.decode("cp1252", "ignore")


def _strip_tags(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def _office_text(path: str) -> tuple[str, str]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        parts = [n for n in names if n in ("word/document.xml", "xl/sharedStrings.xml", "content.xml")
                 or re.match(r"word/(header|footer|footnotes)\d*\.xml$", n) or re.match(r"ppt/slides/slide\d+\.xml$", n)]
        parts.sort(key=lambda n: (len(n), n))  # slides in order
        raw = " ".join(z.read(n)[:1_500_000].decode("utf-8", "ignore") for n in parts[:60])
        core = z.read("docProps/core.xml").decode("utf-8", "ignore") if "docProps/core.xml" in names else ""
        if not core and "meta.xml" in names:
            core = z.read("meta.xml").decode("utf-8", "ignore")
    title = re.search(r"<dc:title>(.*?)</dc:title>", core, re.S)
    raw = re.sub(r"</(?:w:p|a:p|text:p|text:h)>", "\n", raw)
    return re.sub(r"[ \t]+", " ", _strip_tags(raw)), html.unescape(title.group(1)).strip() if title else ""


def _ole_text(path: str) -> str:
    """Old .doc/.xls/.ppt: recover the text runs (UTF-16 and ASCII) from the binary file."""
    with open(path, "rb") as f:
        b = f.read(8_000_000)
    pieces = [m.decode("utf-16-le", "ignore") for m in re.findall(rb"(?:[\x20-\x7e\xa0-\xff]\x00){4,}", b)]
    pieces += [m.decode("cp1252", "ignore") for m in re.findall(rb"[\x20-\x7e\xa0-\xff]{6,}", b)]
    return "\n".join(pieces)


def _rtf_text(s: str) -> str:
    s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "ignore"), s)
    s = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), s)
    return re.sub(r"\\[a-zA-Z]+-?\d* ?|[{}]", " ", s)


def _email_text(path: str) -> tuple[str, str]:
    import email
    from email import policy
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    subject = str(msg.get("subject", "")).strip()
    parts = [subject, str(msg.get("from", ""))]
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        parts.append(_strip_tags(content) if body.get_content_subtype() == "html" else content)
    return "\n".join(parts), subject


def _notebook_text(path: str) -> str:
    import json
    with open(path, encoding="utf-8", errors="ignore") as f:
        nb = json.load(f)
    return "\n".join("".join(c.get("source", [])) for c in nb.get("cells", []))


def _epub_text(path: str) -> tuple[str, str]:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm", ".opf"))][:15]
        raw = [z.read(n)[:300_000].decode("utf-8", "ignore") for n in names]
    title = next((m.group(1) for r in raw if (m := re.search(r"<dc:title[^>]*>(.*?)</dc:title>", r, re.S))), "")
    return " ".join(_strip_tags(r) for r in raw), html.unescape(title).strip()


# ---------------------------------------------------------------- PDF
def _pdf(an: Analysis, options: dict) -> None:
    try:
        from pypdf import PdfReader
    except ImportError:
        an.text = _pdf_fallback(an.path)
        an.info["kind"] = "PDF"
        return
    r = PdfReader(an.path)
    if r.is_encrypted:
        r.decrypt("")
    pages = len(r.pages)
    try:
        meta = r.metadata or {}
        if meta.get("/Title"):
            an.titles.append(str(meta["/Title"]).strip())
        extra = " ".join(str(meta.get(k) or "") for k in ("/Subject", "/Keywords"))
    except Exception:
        extra = ""
    texts, total = [], 0
    for page in r.pages[:10]:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        texts.append(t)
        total += len(t)
        if total > MAX_TEXT:
            break
    an.text = "\n".join(texts) + ("\n" + extra if extra.strip() else "")
    an.info["kind"] = f"PDF, {pages} page{'s' if pages != 1 else ''}"
    an.info["pages"] = pages
    if total < 100 and pages:  # scanned PDF: images only
        an.tags.add("scan")
        an.info["kind"] += " (scanned)"
        if options.get("ocr", True):
            for page in r.pages[:2]:
                images = sorted(page.images, key=lambda i: len(i.data), reverse=True)
                if images:
                    an.text += "\n" + ocr_bytes(images[0].data)
            if an.text.strip():
                an.info["ocr"] = True


def _pdf_fallback(path: str) -> str:
    """Without pypdf: text from the compressed streams (works with many simple PDFs)."""
    with open(path, "rb") as f:
        data = f.read(10_000_000)
    blocks, total = [], 0
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            b = zlib.decompress(m.group(1))
        except zlib.error:
            b = m.group(1)
        blocks.append(b)
        total += len(b)
        if total > 4_000_000:
            break
    strings = re.findall(rb"\(((?:\\.|[^\\)])*)\)", b" ".join(blocks))
    return b" ".join(strings).decode("latin-1", "ignore")


# ---------------------------------------------------------------- images
SCREEN_SIZES = {(1920, 1080), (1366, 768), (1536, 864), (1440, 900), (1600, 900), (1280, 720), (1280, 800),
                (1920, 1200), (2560, 1440), (2560, 1600), (2880, 1800), (3840, 2160), (3440, 1440), (2736, 1824),
                (3000, 2000), (2256, 1504), (1080, 1920), (1080, 2340), (1080, 2400), (1170, 2532), (1179, 2556),
                (1284, 2778), (1290, 2796), (720, 1600), (1440, 3200),
                (2560, 1664), (2880, 1864), (2940, 1912), (3024, 1964), (3456, 2234), (4480, 2520), (5120, 2880),
                (6016, 3384)}  # the last ones: MacBook Air / Pro, iMac and Studio / Pro Display (Retina pixels)
PHOTO_NAME = re.compile(r"^(?:img|pxl|dsc|dscn|dji|gopr|mvimg)[_-]?\d{4}|^\d{8}_\d{6}|^whatsapp image", re.I)
SCREENSHOT_NAME = re.compile(r"screenshot|schermata|screen ?shot|cattura|snip|bildschirmfoto|capture d.?(?:e|é)cran"
                             r"|captura de pantalla", re.I)


@lru_cache(maxsize=1)
def screen_sizes() -> frozenset:
    """The common screen sizes and the real screens of this computer (asked once)."""
    try:
        return frozenset(SCREEN_SIZES | system.screen_sizes())
    except Exception:
        return frozenset(SCREEN_SIZES)


def _xp_text(v) -> str:
    return bytes(v).decode("utf-16-le", "ignore").strip("\x00") if isinstance(v, (bytes, tuple, list)) else str(v)


def _image(an: Analysis, options: dict) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(an.path) as im:
        w, h = im.size
        fmt = im.format or an.ext.strip(".").upper()
        transparent = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        exif = im.getexif()
        make, model, software = exif.get(271), exif.get(272), str(exif.get(305) or "")
        try:
            taken = exif.get_ifd(0x8769).get(36867)
        except Exception:
            taken = None
        texts = [str(exif.get(270) or "")] + [_xp_text(exif[t]) for t in (0x9C9B, 0x9C9F, 0x9C9E) if t in exif]
    an.info["kind"] = f"{fmt} image {w}x{h}"
    if make or model or taken:
        an.tags.add("photo")
        an.info["camera"] = " ".join(str(x).strip() for x in (make, model) if x) or "yes"
    elif PHOTO_NAME.search(an.stem):
        an.tags.add("photo")
    elif SCREENSHOT_NAME.search(an.stem) or re.search(r"snip|screenshot|greenshot|sharex|lightshot|flameshot|"
                                                      r"spectacle", software, re.I):
        an.tags.add("screenshot")
    elif fmt == "PNG" and (w, h) in screen_sizes():
        an.tags.add("screenshot")
        an.info["screenshot_hint"] = "same size as a screen"
    elif an.ext == ".ico" or (transparent and max(w, h) <= 512):
        an.tags.add("icon")
    an.text = "\n".join(t for t in texts if t.strip())
    if options.get("ocr", True) and not an.tags and os.path.getsize(an.path) < 30_000_000:
        found = ocr_file(an.path)
        if found.strip():
            an.text += "\n" + found
            an.info["ocr"] = True
    an.is_document = bool(an.info.get("ocr"))


# ---------------------------------------------------------------- OCR (offline: Windows OCR, macOS Vision, Tesseract)
def _ocr_png(png: str) -> str:
    return system.ocr(png)


def _ocr_image(im) -> str:
    from PIL import Image
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGBA")
        background = Image.new("RGB", im.size, "white")
        background.paste(im, mask=im.split()[-1])
        im = background
    im.thumbnail((2600, 2600))
    fd, png = tempfile.mkstemp(suffix=".png", prefix="desktidy_ocr_")
    os.close(fd)
    try:
        im.save(png, "PNG")
        return _ocr_png(png)
    finally:
        try:
            os.remove(png)
        except OSError:
            pass


def ocr_file(path: str) -> str:
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.seek(0)
            return _ocr_image(im.copy())
    except Exception:
        return ""


def ocr_bytes(data: bytes) -> str:
    try:
        import io

        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return _ocr_image(im.copy())
    except Exception:
        return ""


# ---------------------------------------------------------------- source code inside a .txt
_CODE_SIGNS = {
    "code_python": r"^\s*(?:def|class)\s+\w+.*:\s*$|^\s*(?:import\s+\w+|from\s+[\w.]+\s+import\s)"
                   r"|__name__\s*==\s*['\"]__main__|^\s*print\(|^\s*(?:elif|except|with)\b.*:\s*$",
    "code_c": r"^\s*#\s*(?:include|define|ifndef|endif|pragma)\b|\bint\s+main\s*\(|\b(?:printf|scanf|malloc|free|"
              r"HAL_\w+|Serial\.\w+|digitalWrite|pinMode)\s*\(|\b(?:uint8_t|uint16_t|uint32_t|void|struct)\b",
    "code_web": r"<\s*(?:html|div|script|body|head|span)\b|\bfunction\s+\w*\s*\(|\b(?:const|let|var)\s+\w+\s*="
                r"|console\.log|document\.\w+|=>\s*[{(]|\bimport\s+.+\s+from\s+['\"]",
    "code_shell": r"^\s*(?:@echo off|echo |set |if exist|sudo |apt |pip install|npm |cd |git )|^#!/|Get-\w+|Write-Host",
    "code_sql": r"\b(?:SELECT\s+.+\s+FROM|INSERT\s+INTO|CREATE\s+TABLE|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b",
}


def code_tags(text: str, ext: str = "") -> set[str]:
    lines = [r for r in text.splitlines()[:500] if r.strip()]
    if len(lines) < 3:
        return set()
    code_like = sum(1 for r in lines if r.rstrip().endswith((";", "{", "}", ":", ")", ",")) or r.startswith(("    ", "\t")))
    sample = "\n".join(lines)
    points = {t: len(re.findall(p, sample, re.M)) for t, p in _CODE_SIGNS.items()}
    best = max(points, key=points.get)
    threshold = 0.4 if ext in (".md", ".markdown") else 0.25
    if points[best] >= 3 and code_like / len(lines) >= threshold:
        return {"code", best}
    return set()


# ---------------------------------------------------------------- folders and zip files
def container_tags(extensions: Counter, file_names: list[str]) -> set[str]:
    """What a folder or zip holds, from the types and names of the files inside."""
    total = sum(extensions.values())
    tags: set[str] = set()
    if not total:
        return tags
    share = lambda kinds: sum(extensions[e] for e in kinds) / total  # noqa: E731
    names = {n.lower() for n in file_names}
    if names & PROJECT_MARKERS:
        tags.add("project_code")
    if names & {"package.json", "next.config.js", "next.config.mjs", "vite.config.js", "vite.config.ts"} or \
            share({".html", ".css", ".js", ".jsx", ".ts", ".tsx"}) >= 0.5:
        tags.add("project_web")
    python_markers = names & {"requirements.txt", "pyproject.toml", "setup.py"}
    if extensions[".py"] and (share({".py", ".pyw", ".ipynb"}) >= 0.3 or python_markers):
        tags.add("project_python")
    if extensions[".ioc"] or (".cproject" in names and any("stm32" in n for n in names)):
        tags.add("project_stm32")
    if extensions[".kicad_pro"] or extensions[".kicad_pcb"] or extensions[".kicad_sch"]:
        tags.add("project_kicad")
    if sum(extensions[e] for e in GERBER_EXT) >= 3:
        tags.add("gerber")
    if share(PRINT_3D_EXT) >= 0.5:
        tags.add("print_3d")
    if total >= 3 and share(IMAGE_EXT | {".dng", ".raw", ".cr2", ".nef"}) >= 0.7:
        tags.add("photo_folder")
    if total >= 2 and share(AUDIO_EXT) >= 0.7:
        tags.add("audio_folder")
    if share(VIDEO_EXT) >= 0.6:
        tags.add("video_folder")
    if share(FONT_EXT) >= 0.6:
        tags.add("font")
    if any(re.search(r"(?:^|[_\-. ])(?:setup|install(?:er)?)[^/\\]*\.exe$", n) for n in names) or \
            any(extensions[e] for e in (".msi", ".pkg", ".deb", ".rpm")):
        tags.add("installer")
    return tags


def _folder(an: Analysis) -> None:
    names, extensions, bases, docs = [], Counter(), [], []
    for folder, subdirs, files in os.walk(an.path):
        rel = os.path.relpath(folder, an.path)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        bases += [d.lower() for d in subdirs if d.lower() in PROJECT_MARKERS]
        subdirs[:] = [d for d in subdirs if d.lower() not in SKIP_DIRS and not d.startswith(".")] if depth < 4 else []
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            extensions[ext] += 1
            bases.append(f)
            if len(names) < 300:
                names.append(os.path.relpath(os.path.join(folder, f), an.path))
            readable = re.match(r"readme|leggimi", f, re.I) or ext in (".txt", ".md", ".docx", ".pdf")
            if depth <= 1 and len(docs) < 4 and readable:
                docs.append(os.path.join(folder, f))
        if sum(extensions.values()) > 3000:
            break
    docs.sort(key=lambda p: not re.match(r"readme|leggimi", os.path.basename(p), re.I))
    texts = []
    for p in docs[:4]:
        try:
            if os.path.getsize(p) < 5_000_000:
                texts.append(analyze(p, False, {"analysis": {"ocr": False}}).text[:6000])
        except OSError:
            pass
    an.text = "\n".join(names) + "\n" + "\n".join(texts)
    an.tags |= container_tags(extensions, bases)
    an.info["kind"] = f"folder with {sum(extensions.values())} files"
    an.info["main_types"] = ", ".join(f"{e or '(none)'} {n}" for e, n in extensions.most_common(4))


def _zip(an: Analysis) -> None:
    with zipfile.ZipFile(an.path) as z:
        entries = z.infolist()
        names = [i.filename for i in entries if not i.is_dir()]
        extensions = Counter(os.path.splitext(n)[1].lower() for n in names)
        bases = [os.path.basename(n.rstrip("/")) for n in names] + \
                [p for n in names for p in n.split("/")[:-1] if p.lower() in PROJECT_MARKERS]
        texts = []
        for i in entries:
            if re.search(r"(?:^|/)(?:readme|leggimi)[^/]*\.(?:md|txt)$", i.filename, re.I) and i.file_size < 200_000:
                texts.append(z.read(i).decode("utf-8", "ignore")[:6000])
                break
    an.text = "\n".join(names[:300]) + "\n" + "\n".join(texts)
    an.tags |= container_tags(extensions, bases)
    an.info["kind"] = f"zip archive with {len(names)} files"
    an.info["main_types"] = ", ".join(f"{e or '(none)'} {n}" for e, n in extensions.most_common(4))
