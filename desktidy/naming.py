"""Smart renaming: when a file's name says nothing ("scan0001.pdf", "Document1.docx", "download (3).pdf")
or doesn't match what the file contains, give it a name taken from its content.

Everything is offline: the title comes from the document metadata, the e-mail subject or the first heading.
When the file is going to the AI anyway and no title was found, the AI is asked for a name in the same
request (no extra call). The original name is always kept in moves.csv and `desktidy undo` restores it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import config
from . import content as ct

RENAMABLE = ct.DOCUMENT_EXT | {".rtf", ".eml", ".epub"} | (ct.IMAGE_EXT - {".ico"})
MAX_STEM = 60

_GENERIC_WORDS = (
    r"scan|scansione|scanned|document|documento|doc|file|untitled|senza titolo|unnamed|new document|"
    r"nuovo documento|download|downloads|export|output|print|stampa|image|immagine|img|photo|foto|pic|picture|"
    r"copy|copia|attachment|allegato|temp|tmp|test|prova|bozza|draft|presentation|presentazione|book|cartel|"
    r"foglio|sheet|libro|documento di word|microsoft word|letter|lettera|report|relazione|notes|note|appunti|"
    r"page|pagina|item|data|dati|form|modulo|invoice|fattura|receipt|ricevuta"
)
GENERIC = re.compile(rf"^(?:{_GENERIC_WORDS})?[\s_\-.()\[\]#0-9]*$", re.I)
HASH_OR_ID = re.compile(
    r"^(?:(?=(?:[^\d]*\d){2})[0-9a-fA-F]{8,}"                                   # hex hash with digits
    r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"  # UUID
    r"|(?=(?:[^\d]*\d){4})[A-Z0-9_\-]{8,})$"                                  # codes like A021_ORD26
)
JUNK_TITLE = re.compile(r"^(?:untitled|senza titolo|document\d*|documento\d*|slide \d+|powerpoint presentation|"
                        r"presentazione di powerpoint|microsoft word|pdf|title|titolo|none|null|\W*)$", re.I)
NOT_A_TITLE = re.compile(r"https?://|www\.|@\w+\.\w|^\W*(?:page|pagina|pag\.?)\s*\d|^\d+\s*(?:/|of|di)\s*\d+$", re.I)


@dataclass
class RenamePlan:
    new_stem: str | None = None     # offline name, ready to use
    fallback: str | None = None     # keyword-based name if nothing better comes up
    ask_ai: bool = False            # a name from the AI would help (only used if the AI is called anyway)
    reason: str = ""


def is_generic(stem: str) -> bool:
    s = re.sub(r"\s*\(\d+\)$", "", stem.strip())
    return bool(GENERIC.match(s) or HASH_OR_ID.match(s) or len(re.sub(r"[\W\d_]", "", s)) <= 2)


def _clean_title(t: str) -> str:
    t = re.sub(r"^\s*microsoft (?:word|excel|powerpoint)\s*-\s*", "", t, flags=re.I)
    t = re.sub(r"\.(?:docx?|xlsx?|pptx?|pdf|odt|txt)$", "", t.strip(), flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -_.:;,|")


def _title_score(line: str, position: int) -> float | None:
    line = _clean_title(line)
    if not line or NOT_A_TITLE.search(line) or JUNK_TITLE.match(line):
        return None
    words = re.findall(r"[^\W_]+", line)
    if not 2 <= len(words) <= 12 or len(line) > 110:
        return None
    letters = sum(c.isalpha() for c in line) / len(line)
    meaningful = [w for w in words
                  if len(w) >= 3 and not w.isdigit() and ct.stem(ct.normalize(w).strip()) not in ct.STOP_STEMS]
    if letters < 0.55 or len(meaningful) < 2:
        return None
    # headings are short, early and not sentences
    score = 3.0 - 0.3 * position + 0.25 * min(len(meaningful), 3) - 0.3 * max(0, len(words) - 6)
    if line.endswith((".", "?", "!")) and len(words) > 6:
        score -= 2
    if re.search(r"[.;!?]\s+\S", line):
        score -= 1.5  # two sentences on one line
    if line.istitle() or line.isupper():
        score += 0.5
    return score


def title(an: ct.Analysis) -> str | None:
    """The best title for the file: metadata/subject first, then the first heading-like line."""
    for t in an.titles:
        t = _clean_title(t)
        if t and not JUNK_TITLE.match(t) and not is_generic(t) and _title_score(t, 0) is not None:
            return t
    best, best_score = None, 0.5
    lines = [ln.strip() for ln in an.text.splitlines() if ln.strip()][:20]
    for i, line in enumerate(lines):
        s = _title_score(line, i)
        if s is not None and s > best_score:
            best, best_score = _clean_title(line), s
    return best


def to_stem(text: str) -> str:
    """'Relazione di laboratorio: Oscilloscopio' -> 'Relazione_di_laboratorio_Oscilloscopio' (max 60 chars)."""
    if text.isupper():
        text = text.title()
    stem = config.clean_name(text, is_dir=True)
    if len(stem) > MAX_STEM:
        stem = stem[:MAX_STEM].rsplit("_", 1)[0]
    return stem.strip("_.-")


def mismatch(an: ct.Analysis) -> bool:
    """The name has meaningful words, the content is long enough to judge, and none of them appear in it."""
    terms = [t for t in an.name_terms if not GENERIC.match(t)]
    if not terms or an.words < 80:
        return False
    vocabulary = set(an.counts)
    return not any(t in vocabulary or any(ct.near(t, v) for v in vocabulary if abs(len(v) - len(t)) <= 1)
                   for t in terms)


def plan(an: ct.Analysis, cfg: dict) -> RenamePlan:
    mode = config.rename_mode(cfg)
    if mode == "off" or an.is_dir or an.ext not in RENAMABLE or an.is_private or "icon" in an.tags:
        return RenamePlan()
    if an.ext in ct.IMAGE_EXT and not an.info.get("ocr"):
        return RenamePlan()  # an image is renamed only if it contains text
    generic = is_generic(an.stem)
    wrong = mode == "smart" and not generic and mismatch(an)
    if not (generic or wrong):
        return RenamePlan()
    why = "generic name" if generic else "name didn't match the content"
    found = title(an)
    if found:
        new = to_stem(found)
        if new and new.lower() != config.clean_name(an.stem, is_dir=True).lower():
            return RenamePlan(new_stem=new, reason=f"{why}; title: {found[:50]}")
        return RenamePlan()
    if not generic or an.words < 20:
        return RenamePlan()  # a mismatch without a clear title: better keep the user's name
    words = [an.original(s) for s, _ in an.keywords(3)]
    return RenamePlan(fallback=to_stem(" ".join(words)) if len(words) >= 2 else None, ask_ai=True,
                      reason=f"{why}; named after its keywords")


def final_name(original: str, new_stem: str | None, is_dir: bool = False) -> str:
    if is_dir or not new_stem:
        return config.clean_name(original, is_dir)
    return config.clean_name(new_stem + os.path.splitext(original)[1], False)
