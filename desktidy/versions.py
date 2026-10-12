"""Old versions of the same document: "Report.docx", "Report_v2.docx", "Report_final.docx",
"Report_final_REALLY.docx", "Report (1).docx". The newest one stays where it is; the older ones can go into an
"_old_versions" subfolder, so the folder shows one file per document and nothing is lost.

  desktidy versions [folder]          families of versions (in the destination folders, or in one folder)
  desktidy versions apply <n>|all     move the older versions into <folder>\\_old_versions (undo works)

A family is: same folder, same extension, the same name once version words are removed (v2, rev3, final,
definitivo, bozza, copy, "(1)"...), and at least one name that really has such a word. When the files have text,
they must also share most of their key terms, so "Lesson_1" and "Lesson_2" are never taken for versions.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import config, folders
from . import content as ct

FOLDER = "_old_versions"
MARKER = re.compile(
    r"^(?:v\d+(?:\.\d+)*|ver\d*|version|vers|rev\d*|r\d|final[ei]?|def|definitiv[oa]|ultim[oa]|bozza|draft|old|"
    r"vecchi[oa]|new|nuov[oa]|copy|copia|ok|davvero|really|corrett[oa]|corrected|fixed|updated|aggiornat[oa]|"
    r"last|latest|good|buon[oa])$")
COPY_SUFFIX = re.compile(r"(?:\s*\(\d+\)|\s*-\s*(?:copy|copia)(?:\s*\(\d+\))?)$", re.I)
MIN_SHARED_TERMS = 0.5


@dataclass
class Family:
    folder: str
    base: str
    keep: str               # the newest: stays
    older: list[str]        # go into _old_versions

    @property
    def name(self) -> str:
        return os.path.basename(self.keep)


def split(stem: str) -> tuple[str, bool]:
    """('report', True) for 'Report_final_v2'; the bool says whether a version marker was there."""
    marked = bool(COPY_SUFFIX.search(stem))
    stem = COPY_SUFFIX.sub("", stem)
    tokens = [t for t in re.split(r"[\s_\-.()\[\]]+", config.strip_accents(stem).lower()) if t]
    kept = [t for t in tokens if not MARKER.match(t)]
    return " ".join(kept), marked or len(kept) < len(tokens)


def _related(paths: list[str]) -> bool:
    """Files with text must share at least half of their key terms (with the newest one)."""
    keywords = []
    for p in paths:
        try:
            an = ct.analyze(p, False, {"analysis": {"ocr": False}})
        except OSError:
            return False
        if an.words >= 30:
            keywords.append({s for s, _ in an.keywords(20)})
    if len(keywords) < 2:
        return True  # no text to compare (images, binaries): the names decide
    first = keywords[0]
    return all(len(first & k) >= MIN_SHARED_TERMS * min(len(first), len(k)) for k in keywords[1:])


def in_folder(folder: str) -> list[Family]:
    try:
        entries = [e for e in os.scandir(folder) if e.is_file() and not e.name.startswith(("!", "~$", "."))]
    except OSError:
        return []
    families: dict[tuple[str, str], list[tuple[float, str, bool]]] = {}
    for e in entries:
        stem, ext = os.path.splitext(e.name)
        base, marked = split(stem)
        if len(base.replace(" ", "")) < 3:
            continue
        families.setdefault((base, ext.lower()), []).append((e.stat().st_mtime, e.path, marked))
    out = []
    for (base, _), members in families.items():
        if len(members) < 2 or not any(m for _, _, m in members):
            continue
        members.sort(reverse=True)  # newest first
        paths = [p for _, p, _ in members]
        if _related(paths):
            out.append(Family(folder, base, paths[0], paths[1:]))
    return out


def family_of(path: str) -> Family | None:
    """The family a file just moved into its folder belongs to (only the files with the same base name are read)."""
    folder = os.path.dirname(path)
    if os.path.basename(folder).lower() == FOLDER:
        return None
    stem, ext = os.path.splitext(os.path.basename(path))
    base, _ = split(stem)
    if len(base.replace(" ", "")) < 3:
        return None
    try:
        members = []
        for e in os.scandir(folder):
            if not e.is_file() or e.name.startswith(("!", "~$", ".")):
                continue
            if os.path.splitext(e.name)[1].lower() == ext.lower():
                b, m = split(os.path.splitext(e.name)[0])
                if b == base:
                    members.append((e.stat().st_mtime, e.path, m))
    except OSError:
        return None
    if len(members) < 2 or not any(m for _, _, m in members):
        return None
    members.sort(reverse=True)
    paths = [p for _, p, _ in members]
    return Family(folder, base, paths[0], paths[1:]) if _related(paths) else None


def find(cfg: config.Config, folder: str | None = None) -> list[Family]:
    """Families in one folder, or in every destination folder (code projects and _old_versions excluded)."""
    if folder:
        return in_folder(folder)
    rule_dests = sorted({cfg.expand(r["destination"]) for r in cfg["rules"]})
    out = []
    for f in folders.real_folders(cfg, rule_dests, cfg.default_destination):
        if os.path.basename(f).lower() != FOLDER:
            out += in_folder(f)
    return out


def apply(family: Family, subfolder: str = FOLDER) -> list[str]:
    """Move the older versions into <folder>\\_old_versions (logged: `desktidy undo` puts them back)."""
    from .service import move, record
    target = os.path.join(family.folder, subfolder)
    done = []
    for path in family.older:
        if os.path.exists(path):
            action, final = move(path, target, os.path.basename(path), False)
            record(action, path, final, f"older version of {family.name}")
            done.append(final)
    return done
