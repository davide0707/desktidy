# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Installers you no longer need: setup files of programs that are already installed, in the same or a newer
version (.exe and .msi on Windows, .dmg and .pkg on macOS, .deb and .rpm on Linux). Often hundreds of MB each.

  desktidy installers          what could go, and how much space it frees
  desktidy installers clean    send them to the Trash (after you confirm; restore them from there)

How: the product name and version are read from the installer itself when the system allows it (the version
resource of an .exe, the MSI Property table, the control file of a .deb, rpm) and from its file name, and compared
with the installed programs (Windows "Installed apps", the apps in /Applications, dpkg / rpm / Flatpak packages).
An installer newer than the installed program is kept (it may be the update you have not run yet), and so is
anything downloaded in the last 7 days.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from . import config, content, system

MIN_BYTES = 1_000_000
RECENT_DAYS = 7
NOISE = {"setup", "installer", "install", "x64", "x86", "win64", "win32", "amd64", "arm64", "bit", "user", "system",
         "windows", "win", "release", "latest", "stable", "full", "offline", "online", "web", "msi", "exe",
         "portable", "the", "for", "and", "inc", "llc", "ltd", "corporation", "corp", "gmbh", "software",
         "technologies", "foundation", "pbc", "by", "version", "edition", "update", "package", "en", "us", "it",
         "multilingual", "lang", "machine", "wide", "linux", "deb", "rpm", "dmg", "pkg", "darwin", "mac", "macos",
         "osx", "universal", "intel", "aarch64", "noarch", "current", "el8", "el9", "el10"}
VERSION = re.compile(r"(?<![\d.])(\d+(?:\.\d+){1,3})(?![\d.])")


MATCH = 0.6                  # similarity of two product names needed to call them the same program


@dataclass
class Candidate:
    path: str
    size: int
    product: str
    installed: str
    installed_version: str
    installer_version: str
    same_version: bool          # False: the installed program is newer than this installer

    @property
    def status(self) -> str:
        return "same version installed" if self.same_version else "a newer version is installed"


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9+]+", content.split_camel(config.strip_accents(text)).lower())
    return [w for w in words if len(w) >= 2 and w not in NOISE and not re.fullmatch(r"[a-z]?\d[\w]*", w)]


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", config.strip_accents(text).lower())


def _version(text: str) -> tuple[int, ...]:
    m = VERSION.search(text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def similarity(installer_names: list[str], program: str) -> float:
    """0-1: how surely an installer (its product name and file name) is for this installed program.
    Word overlap (Jaccard, with at least one shared word of 4+ letters) or, for long names written without
    spaces ("GitHubDesktopSetup" / "GitHub Desktop"), one name starting with the other."""
    theirs, letters = set(tokens(program)), _letters(program)
    best = 0.0
    for name in installer_names:
        mine = set(tokens(name))
        shared = mine & theirs
        if shared and any(len(w) >= 4 for w in shared):
            best = max(best, len(shared) / len(mine | theirs))
        squash = _letters(name)
        short, long_ = sorted((squash, letters), key=len)
        if len(short) >= 6 and long_.startswith(short):
            best = max(best, 0.9)
    return best


def _installer_like(path: str, product: dict, in_installers_folder: bool) -> bool:
    if not path.lower().endswith(".exe") or in_installers_folder:
        return True  # .msi, .dmg, .pkg, .deb, .rpm are installers by nature
    text = (os.path.basename(path) + " " + product.get("name", "")).lower()
    return bool(re.search(r"setup|install", text))


def find(cfg: config.Config, programs: list[dict] | None = None) -> list[Candidate]:
    """Installers whose program is installed in the same or a newer version."""
    programs = system.installed_programs() if programs is None else programs
    roots = [(cfg.expand(w["path"]), False) for w in cfg["watched_folders"]]
    if cfg.installer_dir:
        roots.insert(0, (cfg.expand("{INSTALLERS}"), True))
    roots += [(cfg.expand(p), True) for p in cfg.get("installers", {}).get("folders", [])]
    recent = time.time() - RECENT_DAYS * 86400
    out, seen = [], set()
    for root, is_installers in roots:
        for folder, subdirs, files in os.walk(root):
            depth = os.path.relpath(folder, root).count(os.sep) + (folder != root)
            subdirs[:] = [d for d in subdirs if not d.startswith(("!", ".")) and depth < 3] if is_installers else []
            for f in files:
                path = os.path.join(folder, f)
                ext = os.path.splitext(f)[1].lower()
                if ext not in system.INSTALLER_EXT or f.startswith("!") or os.path.normcase(path) in seen:
                    continue
                seen.add(os.path.normcase(path))
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if st.st_size < MIN_BYTES or st.st_mtime > recent:
                    continue
                try:
                    product = system.installer_product(path)
                except OSError:
                    product = {}
                if not _installer_like(path, product, is_installers):
                    continue
                names = [n for n in (product.get("name", ""), os.path.splitext(f)[0]) if n]
                mine = _version(product.get("version", "")) or _version(f)
                scored = [(similarity(names, p["name"]), _version(p["version"])[:2] == mine[:2], p) for p in programs]
                score, _, match = max(scored, key=lambda x: (x[0], x[1]), default=(0, False, None))
                if score < MATCH:
                    continue
                theirs = _version(match["version"])
                if mine and theirs and mine > theirs:
                    continue  # newer than what is installed: maybe the update still to run
                same = not (mine and theirs) or mine[:3] == theirs[:3]
                out.append(Candidate(path, st.st_size, product.get("name") or f, match["name"], match["version"],
                                     ".".join(map(str, mine)), same))
    return sorted(out, key=lambda c: -c.size)


def clean(candidates: list[Candidate]) -> tuple[int, int]:
    """Send them to the Trash, logging each one. Returns (files, bytes)."""
    from .service import record
    files = size = 0
    for c in candidates:
        if os.path.exists(c.path) and not system.file_in_use(c.path) and system.recycle(c.path):
            record("RECYCLED", c.path, system.TRASH, f"installer of {c.installed} {c.installed_version} (installed)")
            files, size = files + 1, size + c.size
    return files, size


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
