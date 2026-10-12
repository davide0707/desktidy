"""The to-sort pile, grouped: the files DeskTidy could not place often have something in common ("8 files talk
about stm32, nucleo, gpio"). This module finds those groups offline and proposes where they should go: an
existing folder that looks like them, or a new folder (that can be pinned, so the next ones go there by themselves).
cluster() does the same for any list of items: `desktidy organize` uses it when there is no AI.

  desktidy groups                       the groups found in the to-sort folder
  desktidy groups apply 2 [--pin]       move group 2 where proposed (every move can be undone)
  desktidy groups apply 2 --to <folder> move it somewhere else

How: each file becomes a vector of its name words, key terms and recognised kinds (weighted by how rare they are in
the pile); files more similar than a threshold are linked, and linked files form a group. Free and private.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from dataclasses import dataclass, field

from . import config, folders
from . import content as ct

THRESHOLD = 0.30            # cosine similarity that links two files
MIN_FILES = 3
EXISTING_FOLDER = 0.35      # similarity with an existing folder good enough to propose it
MAX_FILES = 300


@dataclass
class Group:
    files: list[str]
    words: list[str]                 # what they have in common, readable
    target: str                      # proposed folder
    existing: bool                   # the target already exists
    terms: Counter = field(default_factory=Counter, repr=False)

    @property
    def label(self) -> str:
        return ", ".join(self.words) or "similar files"


class _Profile:
    """The bits of an Analysis that the folder catalog needs, for a whole group."""

    def __init__(self, terms: Counter):
        self.name_terms: list[str] = []
        self._terms = terms

    def keywords(self, n: int = 20) -> list[tuple[str, int]]:
        return [(t, max(1, round(v))) for t, v in self._terms.most_common(n) if not t.startswith(("#", "."))]

    def original(self, s: str) -> str:
        return s


def _vector(an: ct.Analysis) -> Counter:
    v: Counter = Counter()
    for t in an.name_terms:
        v[t] += 3
    for s, n in an.keywords(20):
        v[s] += 1 + math.log(n)
    for tag in an.tags:
        v["#" + tag] += 4
    if an.ext and an.ext not in ct.DOCUMENT_EXT:
        v[an.ext] += 1.5
    return v


def _pile(cfg: config.Config) -> list[tuple[str, ct.Analysis]]:
    inbox = cfg.default_destination
    try:
        entries = [e for e in os.scandir(inbox) if e.is_file() and not e.name.startswith(("!", "~$", "."))]
    except OSError:
        return []
    entries.sort(key=lambda e: e.stat().st_mtime, reverse=True)
    out = []
    for e in entries[:MAX_FILES]:
        try:
            out.append((e.path, ct.analyze(e.path, False, {"analysis": {"ocr": False}})))
        except OSError:
            continue
    return out


def find(cfg: config.Config, min_files: int | None = None) -> list[Group]:
    """The groups of the to-sort folder, biggest first."""
    return cluster(_pile(cfg), cfg, min_files)


def cluster(pile: list[tuple[str, ct.Analysis]], cfg: config.Config, min_files: int | None = None,
            base: str | None = None) -> list[Group]:
    """Groups of related items, biggest first, each with a proposed folder: an existing one that looks like them,
    or a new one (in `base` when given; otherwise next to the most similar folder, or in Documents). Offline."""
    min_files = min_files or cfg.get("groups", {}).get("min_files", MIN_FILES)
    if len(pile) < min_files:
        return []
    vectors = [_vector(an) for _, an in pile]
    df: Counter = Counter()
    for v in vectors:
        df.update(v.keys())
    n = len(vectors)
    idf = {t: math.log(1 + n / c) for t, c in df.items()}
    weighted = [{t: w * idf[t] for t, w in v.items()} for v in vectors]
    norms = [math.sqrt(sum(x * x for x in w.values())) or 1.0 for w in weighted]
    parent = list(range(n))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            shared = weighted[i].keys() & weighted[j].keys()
            if shared and sum(weighted[i][t] * weighted[j][t] for t in shared) / (norms[i] * norms[j]) >= THRESHOLD:
                parent[root(i)] = root(j)
    members: dict[int, list[int]] = {}
    for i in range(n):
        members.setdefault(root(i), []).append(i)
    rule_dests = sorted({cfg.expand(r["destination"]) for r in cfg["rules"]})
    catalog = folders.catalog(cfg, rule_dests, cfg.default_destination)
    groups = []
    for idx in sorted(members.values(), key=len, reverse=True):
        if len(idx) < min_files:
            continue
        total: Counter = Counter()
        presence: Counter = Counter()
        for i in idx:
            total.update(weighted[i])
            presence.update(weighted[i].keys())
        common = [t for t, _ in total.most_common() if presence[t] >= max(2, 0.6 * len(idx))]
        words = []
        for t in common:
            if t.startswith("."):
                continue
            readable = t[1:].replace("_", " ") if t.startswith("#") else next(
                (an.original(t) for _, an in (pile[i] for i in idx) if t in an.counts), t)
            if readable not in words:
                words.append(readable)
            if len(words) == 3:
                break
        terms = Counter({t: total[t] for t in common})
        similar = catalog.similar(_Profile(terms)) if terms else []
        if similar and similar[0][0] >= EXISTING_FOLDER:
            target = similar[0][1]
            existing = os.path.isdir(config.undated(target))  # a rule destination may not exist yet: created then
        else:
            where = base
            if where is None:
                where = os.path.dirname(similar[0][1]) if similar and similar[0][0] >= 0.15 else cfg.expand("{DOCS}")
            name = config.clean_name("_".join(w.title() for w in words[:2]) or "Group", is_dir=True)
            target, existing = os.path.join(where, name), os.path.isdir(os.path.join(where, name))
        groups.append(Group([pile[i][0] for i in idx], words, target, existing, terms))
    return groups


def apply(group: Group, cfg: config.Config, target: str | None = None, pin: bool = False) -> list[str]:
    """Move the files of a group (each move logged, so `desktidy undo` works). Returns the new paths. A dated
    folder (Bills/{YEAR}) takes each file's own date."""
    from . import naming
    from .deadlines import file_date
    from .service import move, record
    folder = target or group.target
    done = []
    for path in group.files:
        if not os.path.exists(path):
            continue
        where = config.dated(folder, file_date(path, ct.analyze(path, False))) if config.is_dated(folder) else folder
        action, final = move(path, where, naming.final_name(os.path.basename(path), None), False)
        record(action, path, final, f"grouped from the to-sort pile: about {group.label}")
        done.append(final)
    if pin and not config.is_dated(folder):
        folders.pin(folder)
    return done
