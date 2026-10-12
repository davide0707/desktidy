"""Duplicates across your folders: the same file, byte for byte, in two or more places (the photo copied twice, the
PDF downloaded again, the backup of a backup).

  desktidy duplicates                 the groups found, most space first (offline, nothing is changed)
  desktidy duplicates clean [n]       keep one copy per group (or of group n), the others to the Recycle Bin

Where: your folders (Desktop, Downloads, Documents, Pictures, Videos, Music) and the pinned folders, never the
system or the programs. Which copy stays: the one in the best place (a pinned folder, a destination of your rules,
Documents) rather than Downloads, the Desktop or the to-sort pile, and a clean name rather than "x (1)" or
"copy of x"; then the oldest.

Safe by design:
  * identical means identical: same size, same first and last 64 KB, then the same BLAKE2 hash of the whole file
  * never compared: hard links (one file with two names), links, names starting with "!", hidden and system
    files, code projects and their dependency folders (node_modules, venv...), the folders of programs (game
    saves, settings: folders.app_owned), DeskTidy's data, and files that are only in the cloud (OneDrive,
    iCloud: reading them would download them)
  * just before a copy goes, its size and time are checked again: a file changed since the scan is left alone
  * the copies go to the Recycle Bin / Trash, never deleted; each one is in moves.csv (desktidy where)
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field

from . import config, folders, system

MIN_SIZE = 512 * 1024          # smaller files are not worth it (duplicates.min_size_kb)
PART = 64 * 1024               # the first and last bytes compared before the whole file
CHUNK = 1024 * 1024
MAX_FILES = 300_000            # files looked at in one scan
CLOUD_ONLY = 0x1000 | 0x40000 | 0x400000   # Windows: OFFLINE, RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS
DATALESS = 0x40000000          # macOS: SF_DATALESS (iCloud "optimised storage")
COPY_NAME = re.compile(r"(?:\s*\(\d+\)|[ _-](?:copy|copia|kopie|copie)(?:\s*\d+)?|_v\d+)$|^(?:copy of|copia di)\s", re.I)


@dataclass
class Copy:
    path: str
    size: int
    mtime_ns: int


@dataclass
class Group:
    copies: list[Copy]                       # the one to keep first
    digest: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def keep(self) -> Copy:
        return self.copies[0]

    @property
    def extra(self) -> list[Copy]:
        return self.copies[1:]

    @property
    def wasted(self) -> int:
        return sum(c.size for c in self.extra)


def roots(cfg: config.Config) -> list[str]:
    """Your folders, without the ones inside another root (so nothing is looked at twice)."""
    found = [cfg.expand("{" + v + "}") for v in ("DESKTOP", "DOWNLOADS", "DOCS", "PICTURES", "VIDEOS", "MUSIC")]
    found += [p.path for p in folders.active_pinned()]
    found = [os.path.normpath(p) for p in dict.fromkeys(found) if "{" not in p and os.path.isdir(p)]
    return [p for p in found if not any(q != p and config.inside(p, q) for q in found)]


def cloud_only(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & CLOUD_ONLY) or bool(getattr(st, "st_flags", 0) & DATALESS)


def _files(cfg: config.Config, min_size: int, progress=None):
    """(path, stat) of the files worth comparing, under the roots."""
    data = str(config.data_dir())
    count = 0
    stack = list(reversed(roots(cfg)))  # links are never followed (and on Windows is_hidden skips junctions): no loops
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as found:
                entries = list(found)
        except OSError:
            continue
        names = {e.name.lower() for e in entries}
        if names & folders.PROJECT_MARKERS:
            continue  # a code project: its files belong together, copies included
        for e in entries:
            name = e.name.lower()
            try:
                if name.startswith(("!", ".", "~$", "$")) or system.is_hidden(e):
                    continue
                if e.is_dir(follow_symlinks=False):
                    if name in folders.DONT_DESCEND or config.inside(e.path, data) or folders.app_owned(e.path):
                        continue  # a program's folder: its identical files are on purpose
                    stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    if st.st_size < min_size or cloud_only(st):
                        continue
                    count += 1
                    if progress and count % 500 == 0:
                        progress(count)
                    yield e.path, st
                    if count >= MAX_FILES:
                        return
            except OSError:
                continue


def _digest(path: str, part: bool) -> str | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            if part:
                h.update(f.read(PART))
                size = os.fstat(f.fileno()).st_size
                if size > 2 * PART:
                    f.seek(size - PART)
                    h.update(f.read(PART))
            else:
                while block := f.read(CHUNK):
                    h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def _score(path: str, cfg: config.Config, good: list[str], inboxes: list[str]) -> tuple:
    """Higher is a better copy to keep: a good place, a clean name, then the oldest (sorted after)."""
    place = 2 if any(config.inside(path, g) for g in good) else -2 if any(config.inside(path, i) for i in inboxes) \
        else 1 if config.inside(path, cfg.expand("{DOCS}")) else 0
    stem = os.path.splitext(os.path.basename(path))[0]
    return place, 0 if COPY_NAME.search(stem) else 1


def find(cfg: config.Config, progress=None) -> list[Group]:
    """The duplicate groups, most wasted space first. Offline; only reads."""
    min_size = int(cfg.get("duplicates", {}).get("min_size_kb", MIN_SIZE // 1024)) * 1024
    by_size: dict[int, list[Copy]] = {}
    for path, st in _files(cfg, min_size, progress):
        by_size.setdefault(st.st_size, []).append(Copy(path, st.st_size, st.st_mtime_ns))
    rule_dests = sorted({cfg.expand(r["destination"]) for r in cfg["rules"]})
    good = [p.path for p in folders.active_pinned()] + [u for u in map(config.undated, rule_dests) if "{" not in u]
    inboxes = [cfg.default_destination, cfg.expand("{DOWNLOADS}"), cfg.expand("{DESKTOP}")]
    groups = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        for _, part in _split(_one_per_file(same_size), lambda c: _digest(c.path, part=True)):
            for digest, whole in _split(part, lambda c: _digest(c.path, part=False)):
                whole.sort(key=lambda c: (_score(c.path, cfg, good, inboxes), -c.mtime_ns), reverse=True)
                groups.append(Group(whole, digest))
    groups.sort(key=lambda g: (-g.wasted, g.keep.path.lower()))
    return groups


def _one_per_file(copies: list[Copy]) -> list[Copy]:
    """Hard links are one file with several names, not copies: only the first name stays. A full os.stat is
    needed (the one of a directory listing has no file id on Windows), so it is done only for same-size files."""
    seen: set = set()
    out = []
    for c in copies:
        try:
            st = os.stat(c.path)
        except OSError:
            continue
        key = (st.st_dev, st.st_ino)
        if st.st_ino and key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _split(copies: list[Copy], key) -> list[tuple[str, list[Copy]]]:
    """(key, copies) for the keys shared by 2 or more copies (a copy that can't be read is left out)."""
    out: dict[str, list[Copy]] = {}
    for c in copies:
        k = key(c)
        if k is not None:
            out.setdefault(k, []).append(c)
    return [(k, g) for k, g in out.items() if len(g) > 1]


def _unchanged(c: Copy) -> bool:
    try:
        st = os.stat(c.path)
    except OSError:
        return False
    return st.st_size == c.size and st.st_mtime_ns == c.mtime_ns


def clean(groups: list[Group]) -> tuple[int, int, list[str]]:
    """Recycle the extra copies; returns (files, bytes, notes). A group whose copy to keep is gone or changed is
    left alone, and so is a copy that changed or is open in a program."""
    from .service import record
    files = size = 0
    notes: list[str] = []
    for g in groups:
        if not _unchanged(g.keep) or _digest(g.keep.path, part=False) != g.digest:
            notes.append(f"{os.path.basename(g.keep.path)}: changed since the scan, left alone")
            continue
        for c in g.extra:
            if not _unchanged(c) or _digest(c.path, part=False) != g.digest:
                notes.append(f"{c.path}: changed since the scan, left alone")
            elif system.file_in_use(c.path):
                notes.append(f"{c.path}: open in a program, left alone")
            elif system.recycle(c.path):
                record("RECYCLED", c.path, g.keep.path, f"duplicate of {g.keep.path}")
                files, size = files + 1, size + c.size
            else:
                notes.append(f"{c.path}: could not be sent to the {system.TRASH}")
    return files, size, notes
