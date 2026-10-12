"""Destination folders: the list of candidates, what each one is about, pinned folders, and the short list
of likely folders sent to the AI (instead of the whole tree: most of the tokens saved come from here).

A PINNED folder is a folder the user chose (e.g. "pasta" on the Desktop). New files that talk about it end up
there: by name (the folder name or the extra words chosen), by content, or because they resemble the files
already inside it (its "context", learned automatically).
"""

from __future__ import annotations

import math
import os
import re
import time
from collections import Counter
from datetime import date

from . import config, system
from . import content as ct
from .config import inside

LOOKS_LIKE_FILE = (".exe", ".msi", ".zip", ".7z", ".rar", ".iso")
DONT_DESCEND = {"node_modules", "venv", ".venv", "__pycache__", "debug", "release", "build", "dist", "src", "core",
                "drivers", "middlewares", "utilities", "inc", "lib", "include", "scripts", "assets", "public", "static"}
PROJECT_MARKERS = {".git", "package.json", ".project", "pyvenv.cfg", "requirements.txt", "cmakelists.txt",
                   "makefile", "pyproject.toml"}
GENERIC_WORDS = {"nuova", "nuovo", "cartella", "new", "folder", "file", "files", "varie", "vari", "altro", "altri",
                 "misc", "temp", "tmp", "copia", "copy", "backup", "roba", "cose", "stuff", "documenti", "doc", "docs"}
DEFAULT_FOLDER_NAMES = re.compile(r"^(?:nuova cartella|new folder|untitled folder|cartella senza titolo|senza titolo|"
                                  r"neuer ordner|nouveau dossier|nueva carpeta)(?: \(\d+\)| \d+)?$", re.I)


# ---------------------------------------------------------------- candidate destinations
def candidate_folders(cfg: config.Config, rule_destinations: list[str], default: str) -> list[str]:
    """Every possible destination: the folders under ai.candidate_folders (to the given depth), the rule
    destinations and the pinned folders. The first one is always the default destination."""
    found: set[str] = set()
    for entry in cfg.ai.get("candidate_folders", []):
        root, max_depth = (cfg.expand(entry["path"]), entry.get("depth", 2)) if isinstance(entry, dict) \
            else (cfg.expand(entry), 2)
        if not os.path.isdir(root):
            continue
        stack = [(root, 0)]
        while stack:
            folder, depth = stack.pop()
            found.add(folder)
            if depth >= max_depth:
                continue
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            if {e.name.lower() for e in entries} & PROJECT_MARKERS:
                continue  # a code project can be chosen as a whole, not its inner folders
            parent = os.path.basename(folder).lower()
            for e in entries:
                n = e.name.lower()
                try:
                    if not e.is_dir(follow_symlinks=False) or n.startswith((".", "_", "$", "!")) or n in DONT_DESCEND:
                        continue
                    if n.endswith(LOOKS_LIKE_FILE) or parent.startswith(n) or inside(e.path, config.data_dir()):
                        continue  # "x\x" extracted twice, folders named like a file, our own data
                    if system.is_hidden(e):  # hidden / system / link
                        continue
                except OSError:
                    continue
                stack.append((e.path, depth + 1))
    found |= set(rule_destinations)
    found |= {p.path for p in active_pinned()}
    found.discard(default)
    templates = [config.dated_pattern(d) for d in rule_destinations if config.is_dated(d)]
    if templates:  # Bills/{YEAR} is offered, not the Bills/2025, Bills/2026 it made: a new file goes by its own date
        found = {p for p in found if config.is_dated(p) or not any(t.match(os.path.normpath(p)) for t in templates)}
    return [default] + sorted(found, key=str.lower)[: cfg.ai.get("max_candidate_folders", 400)]


# ---------------------------------------------------------------- folders that belong to a program
APP_NAMES = re.compile(
    r"^(?:my games|saved games|.+ games|visual studio(?: code)? ?\d*|windowspowershell|powershell|outlook files|"
    r"onenote notebooks|custom office templates|my web sites|iisexpress|sql server management studio.*|"
    r"call of duty.*|battlefield.*|electronic arts|ea sports.*|ubisoft|paradox interactive|klei|bioware|"
    r"rockstar games|cd projekt red|fifa ?\d*|euro truck simulator.*|american truck simulator|zoom|"
    r"arduino|processing|fiddler2|wondershare.*|autodesk.*|ansys.*|matlab|labview data|national instruments)$",
    re.I)
PERSONAL_EXT = (ct.DOCUMENT_EXT | ct.OFFICE_EXT | ct.OLD_OFFICE_EXT | ct.IMAGE_EXT | ct.AUDIO_EXT | ct.VIDEO_EXT
                | ct.PRINT_3D_EXT | ct.GERBER_EXT | {".csv", ".zip", ".rar", ".7z", ".tar", ".gz", ".mobi", ".azw3",
                                                     ".psd", ".ai", ".svg", ".dwg", ".dxf", ".kicad_pcb", ".kicad_sch",
                                                     ".blend", ".exe", ".msi", ".iso", ".apk", ".dmg", ".pkg", ".deb",
                                                     ".rpm", ".ipynb", ".key", ".pages", ".numbers", ".vcf", ".ics"})
NOT_COUNTED = {".lnk", ".url", ".desktop", ".webloc", ".inetloc"}
APP_SAMPLE = 300               # files looked at to tell a program's folder from yours
_apps: dict = {}


def _by_name(path: str) -> bool:
    """The folder, or one above it inside the home folder, is named like a program's (My Games, Visual Studio 2022)."""
    home = os.path.normcase(os.path.expanduser("~"))
    p = os.path.normpath(path)
    while p and os.path.normcase(p) != home and os.path.dirname(p) != p:
        if APP_NAMES.match(os.path.basename(p)):
            return True
        p = os.path.dirname(p)
    return False


def _by_content(path: str) -> bool:
    """Mostly files that are not documents, pictures, music or videos (.cfg, .dat, .sav, .json, no extension)."""
    personal = total = 0
    stack = [(path, 0)]
    while stack and total < APP_SAMPLE:
        folder, depth = stack.pop()
        try:
            with os.scandir(folder) as found:
                entries = list(found)
        except OSError:
            continue
        for e in entries:
            name = e.name.lower()
            if name.startswith((".", "~$", "$")) or name in ("desktop.ini", "thumbs.db"):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth < 3:
                        stack.append((e.path, depth + 1))
                elif e.is_file(follow_symlinks=False):
                    ext = os.path.splitext(name)[1]
                    if ext in NOT_COUNTED:
                        continue
                    total += 1
                    personal += ext in PERSONAL_EXT
            except OSError:
                continue
    return total >= 3 and personal < 0.3 * total


def app_owned(path: str) -> bool:
    """A folder that belongs to a program (game saves, settings, code snippets, a launcher's data): DeskTidy never
    organises, moves or deduplicates it. By name, or by content. Remembered for 10 minutes."""
    key = os.path.normcase(os.path.normpath(path))
    hit = _apps.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    result = _by_name(path) or _by_content(path)
    if len(_apps) > 5000:
        _apps.clear()
    _apps[key] = (time.time(), result)
    return result


def real_folders(cfg: config.Config, rule_destinations: list[str], default: str) -> list[str]:
    """candidate_folders() with every dated destination replaced by the folders it has produced (Bills/2025,
    Bills/2026...): what exists on disk, for the search index, versions, learning and the overview."""
    out: list[str] = []
    for p in candidate_folders(cfg, rule_destinations, default):
        out += config.dated_folders(p) if config.is_dated(p) else [p]
    return list(dict.fromkeys(out))


def aliases(cfg: config.Config) -> list[tuple[str, str]]:
    home = os.path.expanduser("~")
    result = [(cfg.expand("{DOCS}"), ""), (home, "~")]
    for var, label in (("{INSTALLERS}", "Installers"),):
        p = cfg.expand(var)
        if "{" not in p:
            result.insert(0, (p, label))
    return result


def label(p: str, alias_list=()) -> str:
    for base, name in alias_list:
        if os.path.normcase(p) == os.path.normcase(base):
            return name or p
        if os.path.normcase(p).startswith(os.path.normcase(base).rstrip(os.sep) + os.sep):
            rest = p[len(base.rstrip(os.sep)) + 1:]
            return os.path.join(name, rest) if name else rest
    return p


# ---------------------------------------------------------------- similarity with existing folders
def _name_profile(p: str) -> Counter:
    """What a folder is about according to names: its own name, its parent's and what it contains (200 entries).
    A dated destination (Bills/{YEAR}) is about its fixed part and the files of its latest dated folders."""
    c: Counter = Counter()
    named = config.undated(p)
    for s in ct.informative(ct.split_camel(os.path.basename(named))):
        c[s] += 3
    for s in ct.informative(ct.split_camel(os.path.basename(os.path.dirname(named)))):
        c[s] += 1
    entries = []
    for folder in reversed(config.dated_folders(p)) if config.is_dated(p) else [p]:
        try:
            with os.scandir(folder) as found:
                entries += [e for e in found if not e.name.startswith((".", "~$", "$"))][:200 - len(entries)]
        except OSError:
            continue
        if len(entries) >= 200:
            break
    for e in entries:
        for s in set(ct.informative(ct.split_camel(os.path.splitext(e.name)[0]))):
            c[s] += 1
    return c


class Catalog:
    """TF-IDF-like profiles of the destination folders, to find the ones most similar to a file."""

    def __init__(self, folders: list[str]):
        self.profiles = {p: _name_profile(p) for p in folders}
        self.df: Counter = Counter()
        for profile in self.profiles.values():
            self.df.update(profile.keys())
        self.n = max(1, len(self.profiles))
        self.norms = {p: math.sqrt(sum((v * self.idf(w)) ** 2 for w, v in prof.items())) or 1.0
                      for p, prof in self.profiles.items()}

    def idf(self, w: str) -> float:
        return math.log(1 + self.n / (self.df[w] or 1))

    def similar(self, an: ct.Analysis, exclude=()) -> list[tuple[float, str, list[str]]]:
        """[(score 0-1, folder, shared words)], most similar first."""
        vec: Counter = Counter()
        for w in an.name_terms:
            vec[w] += 3
        for w, n in an.keywords(40):
            vec[w] += 1 + math.log(n)
        if not vec:
            return []
        norm = math.sqrt(sum((v * self.idf(w)) ** 2 for w, v in vec.items())) or 1.0
        results = []
        for p, prof in self.profiles.items():
            if any(inside(p, e) for e in exclude):
                continue
            shared = [w for w in vec if w in prof]
            if not shared:
                continue
            weight = {w: vec[w] * prof[w] * self.idf(w) ** 2 for w in shared}
            results.append((sum(weight.values()) / (norm * self.norms[p]), p,
                            sorted(shared, key=weight.get, reverse=True)[:4]))
        results.sort(reverse=True)
        return results


_catalog: dict = {"at": 0.0, "key": None, "value": None}


def catalog(cfg: config.Config, rule_destinations: list[str], default: str) -> Catalog:
    """Folder catalog for similarity (rebuilt at most every 15 minutes)."""
    key = (tuple(sorted(rule_destinations)), default, cfg.source)
    if _catalog["value"] is None or _catalog["key"] != key or time.time() - _catalog["at"] > 900:
        inbox_parent = os.path.dirname(default)
        folders = [p for p in candidate_folders(cfg, rule_destinations, default)
                   if not inside(p, default) and not inside(p, inbox_parent)]  # never the "to sort" area
        _catalog.update(at=time.time(), key=key, value=Catalog(folders))
    return _catalog["value"]


def shortlist(an: ct.Analysis, cfg: config.Config, ranked: list[str], rule_destinations: list[str],
              default: str, limit: int = 30) -> list[str]:
    """The folders worth showing to the AI for this file: the offline candidates first, then the most similar
    folders, the pinned ones and the top-level areas (so a general answer is always possible)."""
    out: list[str] = []

    def add(p):
        if p and os.path.normcase(p) not in {os.path.normcase(x) for x in out}:
            out.append(p)

    for p in ranked:
        add(p)
    for _, p, _ in catalog(cfg, rule_destinations, default).similar(an)[:limit]:
        add(p)
    for p in active_pinned():
        add(p.path)
    for entry in cfg.ai.get("candidate_folders", []):
        root = cfg.expand(entry["path"] if isinstance(entry, dict) else entry)
        add(root if os.path.isdir(root) else None)
    out = [p for p in out if os.path.normcase(p) != os.path.normcase(default)]
    return out[:limit]


# ---------------------------------------------------------------- pinned folders
def load_pinned() -> dict:
    d = config.read_json(config.path("pinned"))
    if not isinstance(d, dict):
        d = {"pinned": [], "never_ask": [], "seen": [], "_first_run": True}
    for k in ("pinned", "never_ask", "seen"):
        d.setdefault(k, [])
    return d


def save_pinned(d: dict) -> None:
    config.write_json(config.path("pinned"), {k: v for k, v in d.items() if not k.startswith("_")})


def pin(folder: str, words=()) -> dict:
    folder = os.path.abspath(folder)
    d = load_pinned()
    d["pinned"] = [v for v in d["pinned"] if os.path.normcase(v["path"]) != os.path.normcase(folder)]
    entry = {"path": folder, "words": [w.strip() for w in words if w.strip()], "since": date.today().isoformat()}
    d["pinned"].append(entry)
    d["never_ask"] = [p for p in d["never_ask"] if os.path.normcase(p) != os.path.normcase(folder)]
    save_pinned(d)
    _contexts.pop(os.path.normcase(folder), None)
    return entry


def unpin(folder: str) -> bool:
    d = load_pinned()
    before = len(d["pinned"])
    d["pinned"] = [v for v in d["pinned"] if os.path.normcase(v["path"]) != os.path.normcase(folder)]
    if os.path.normcase(folder) not in map(os.path.normcase, d["never_ask"]):
        d["never_ask"].append(folder)  # don't suggest it again
    save_pinned(d)
    return len(d["pinned"]) < before


def never_ask(folder: str) -> None:
    d = load_pinned()
    d["never_ask"].append(os.path.abspath(folder))
    save_pinned(d)


class Pinned:
    def __init__(self, entry: dict):
        self.path = entry["path"]
        self.name = os.path.basename(self.path.rstrip("\\/"))
        self.words = list(entry.get("words", []))
        parts = ct.normalize(ct.split_camel(self.name)).split()
        self.phrase = tuple(ct.stem(w) for w in parts)
        self.significant = [ct.stem(w) for w in parts if len(w) >= 3 and not w.isdigit() and w not in GENERIC_WORDS]
        self.extra = [(w, ct.stems(w)) for w in self.words if ct.stems(w)]

    def name_match(self, an: ct.Analysis) -> str | None:
        """The file name contains the whole folder name (or all its meaningful words) or one of the extra words."""
        for seq in an.name_seqs:
            if ct.phrase_in(seq, self.phrase, fuzzy=True):
                return self.name
            if len(self.significant) > 1 and all(any(ct.near(w, s) for w in seq) for s in self.significant):
                return self.name
            for w, p in self.extra:
                if ct.phrase_in(seq, p, fuzzy=True):
                    return w
        return None

    def terms(self) -> list[tuple[str, tuple[str, ...]]]:
        seen, out = set(), []
        for text, p in [(self.name, self.phrase)] + [(x, (x,)) for x in self.significant] + self.extra:
            if p and p not in seen:
                seen.add(p)
                out.append((text, p))
        return out

    def score(self, an: ct.Analysis) -> tuple[float, str]:
        """(points, reason): how much the CONTENT of the file talks about this folder."""
        found = {}
        for text, p in self.terms():
            n = an.count(" ".join(p)) if len(p) > 1 else an.counts.get(p[0], 0)
            if n:
                found[text if len(p) > 1 or text in self.words else an.original(p[0])] = (n, p)
        points, reasons = 0.0, []
        if found:
            total = sum(n for n, _ in found.values())
            in_title = any((" " + " ".join(p) + " ") in an.start for _, p in found.values())
            if total >= 2 or in_title or len(found) >= 2:
                points = 2 * len(found) + math.log2(1 + total) + (2 if in_title else 0)
                reasons.append("talks about " + ", ".join(f"'{t}'" for t in list(found)[:3]))
        learned = context(self.path)
        if learned:
            shared = [w for w, _ in an.keywords(40) if w in learned]
            if len(shared) >= 3:
                points += 0.75 * len(shared)
                reasons.append("like the files inside (" + ", ".join(an.original(w) for w in shared[:4]) + ")")
        return points, "; ".join(reasons)


_parsed: dict = {"data": None, "value": []}


def active_pinned() -> list[Pinned]:
    """The pinned folders that exist. Called for every file and folder at every pass, so pinned.json is parsed
    (and its names stemmed) again only when it changes."""
    data = config.read_json_cached(config.path("pinned"))
    if data is not _parsed["data"]:
        entries = data.get("pinned", []) if isinstance(data, dict) else []
        _parsed.update(data=data, value=[Pinned(v) for v in entries if isinstance(v, dict) and v.get("path")])
    return [p for p in _parsed["value"] if os.path.isdir(p.path)]


def setup_missing(cfg: dict) -> str | None:
    """What is still missing before DeskTidy may move files (house rules accepted, enough pinned folders)."""
    needed = config.pinned_minimum(cfg)
    if needed <= 0:
        return None
    if not (config.read_json(config.path("setup"), {}) or {}).get("rules_accepted"):
        return "the house rules have not been accepted yet"
    have = len(active_pinned())
    if have < needed:
        return f"{have} of {needed} pinned folders"
    return None


def holds_pinned(folder: str, pinned: list[Pinned] | None = None) -> bool:
    """True if `folder` is a pinned folder or contains one (such folders are never moved)."""
    return any(inside(p.path, folder) for p in (active_pinned() if pinned is None else pinned))


_contexts: dict = {}


def _signature(folder: str) -> tuple[int, float]:
    n, latest = 0, 0.0
    for current, subdirs, files in os.walk(folder):
        subdirs[:] = [s for s in subdirs if not s.startswith(".") and s.lower() not in ct.SKIP_DIRS]
        n += len(files)
        try:
            latest = max(latest, os.stat(current).st_mtime)
        except OSError:
            pass
        if n > 2000:
            break
    return n, latest


def context(folder: str) -> set[str]:
    """The learned "context" of a pinned folder: typical words of its file names and of its first documents.
    Recomputed when the content changes, at most every 10 minutes."""
    key = os.path.normcase(folder)
    old = _contexts.get(key)
    if old and time.time() - old[1] < 600:
        return old[2]
    sig = _signature(folder)
    if old and old[0] == sig:
        _contexts[key] = (sig, time.time(), old[2])
        return old[2]
    counts: Counter = Counter()
    read, seen = 0, 0
    for current, subdirs, files in os.walk(folder):
        subdirs[:] = [s for s in subdirs if not s.startswith(".") and s.lower() not in ct.SKIP_DIRS]
        for f in files:
            seen += 1
            if seen > 300:
                break
            for s in set(ct.informative(ct.split_camel(os.path.splitext(f)[0]))):
                counts[s] += 1
            p = os.path.join(current, f)
            ext = os.path.splitext(f)[1].lower()
            if read < 15 and (ext in ct.DOCUMENT_EXT or ext in ct.TEXT_EXT):
                try:
                    if os.path.getsize(p) < 5_000_000:
                        for s, _ in ct.analyze(p, False, {"analysis": {"ocr": False}}).keywords(25):
                            counts[s] += 1
                        read += 1
                except OSError:
                    pass
        if seen > 300:
            break
    learned = {s for s, _ in counts.most_common(60)}
    _contexts[key] = (sig, time.time(), learned)
    return learned


def context_words(folder: str, n: int = 12) -> list[str]:
    return sorted(context(folder))[:n]


# ---------------------------------------------------------------- new folders to suggest ("pin it?")
def suggestions(cfg: config.Config, include_seen: bool = False, wait: bool = True) -> list[str]:
    """New folders (e.g. on the Desktop) to suggest for pinning: not pinned, never refused, with a real name
    (not "New folder") and at least pinned_folders.wait_seconds old. On the very first run, the folders that
    already exist are only remembered, not suggested."""
    options = cfg.get("pinned_folders", {})
    roots = [cfg.expand(p) for p in options.get("ask_for_new_folders_in", ["{DESKTOP}"])]
    min_age = options.get("wait_seconds", 60) if wait else 0
    d = load_pinned()
    known = {os.path.normcase(p) for p in d["never_ask"] + ([] if include_seen else d["seen"])} | \
            {os.path.normcase(v["path"]) for v in d["pinned"]}
    new, first_run = [], d.get("_first_run", False)
    for root in roots:
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False) or e.name.startswith((".", "!", "$", "~")):
                    continue
                if system.is_hidden(e) or DEFAULT_FOLDER_NAMES.match(e.name):
                    continue
                if os.path.normcase(e.path) in known or time.time() - e.stat().st_ctime < min_age:
                    continue
            except OSError:
                continue
            new.append(e.path)
    if first_run and not include_seen:
        d["seen"] += new
        save_pinned(d)
        return []
    return new
