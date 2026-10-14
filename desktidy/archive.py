# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Automatic archive: what lies untouched for months on the Desktop or in the to-sort folder goes to
Archive/<year> (optionally compressed into a .zip), so the places you look at every day stay clean.

Off by default: `desktidy archive on`. Then once a day:
  * items (files and folders) not changed for archive.after_days (180) are moved to archive.folder/<year of the
    last change>; a folder counts as changed when anything inside it changed
  * never: names starting with "!", shortcuts, hidden and system files, pinned folders (or folders holding one),
    items DeskTidy itself placed there recently, the archive folder itself
  * archive.zip = true compresses each item into <name>.zip (checked before the original is removed)
Every item is logged: `desktidy where` finds it and `desktidy undo` brings it back (unzipping it if needed).
"""

from __future__ import annotations

import os
import shutil
import time
import zipfile
from datetime import datetime, timedelta

from . import config, folders, system

DEFAULT = {"enabled": False, "after_days": 180, "folder": "{DOCS}/Archive", "zip": False, "max_per_run": 200}
SKIP_EXT = {".lnk", ".url", ".desktop", ".webloc", ".ini", ".tmp", ".crdownload", ".part", ".download"}


def settings(cfg: dict) -> dict:
    s = {**DEFAULT, **cfg.get("archive", {})}
    if "sources" not in s:
        s["sources"] = ["{DESKTOP}", cfg.get("default_destination", "")]
    return s


def _latest_change(path: str, is_dir: bool) -> float:
    st = os.stat(path)
    t = st.st_mtime
    if is_dir:
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    t = max(t, os.stat(os.path.join(root, f)).st_mtime)
                except OSError:
                    pass
    return t


def candidates(cfg: config.Config, now: float | None = None) -> list[tuple[str, bool, float]]:
    """[(path, is_dir, latest change)] that would be archived now."""
    from .service import IGNORED_NAMES, read_moves
    s = settings(cfg)
    now = now or time.time()
    limit = now - s["after_days"] * 86400
    root = cfg.expand(s["folder"])
    first = (datetime.fromtimestamp(now) - timedelta(days=s["after_days"])).strftime("%Y-%m-%d")
    recent = {os.path.normcase(os.path.dirname(m["destination"])) + "|" + os.path.basename(m["destination"]).lower()
              for m in read_moves() if m["time"] >= first}
    pinned = folders.active_pinned()
    out = []
    for source in s["sources"]:
        base = cfg.expand(source) if source else ""
        try:
            entries = list(os.scandir(base)) if base else []
        except OSError:
            continue
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                if e.name.startswith(("!", ".", "~$")) or e.name.lower() in IGNORED_NAMES:
                    continue
                if not is_dir and os.path.splitext(e.name)[1].lower() in SKIP_EXT:
                    continue
                if system.is_hidden(e):
                    continue
                if is_dir and (folders.holds_pinned(e.path, pinned) or config.inside(root, e.path)
                               or config.inside(e.path, root)):
                    continue
                if os.path.normcase(os.path.dirname(e.path)) + "|" + e.name.lower() in recent:
                    continue  # DeskTidy put it there recently: it is not forgotten, it is new here
                latest = _latest_change(e.path, is_dir)
            except OSError:
                continue
            if latest < limit:
                out.append((e.path, is_dir, latest))
    return sorted(out, key=lambda x: x[2])[: s["max_per_run"]]


def _zip(path: str, is_dir: bool, target: str) -> None:
    tmp = target + ".desktidy_tmp"
    total = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        if is_dir:
            parent = os.path.dirname(path)
            for root, _, files in os.walk(path):
                for f in files:
                    full = os.path.join(root, f)
                    z.write(full, os.path.relpath(full, parent))
                    total += os.path.getsize(full)
        else:
            z.write(path, os.path.basename(path))
            total = os.path.getsize(path)
    with zipfile.ZipFile(tmp) as z:
        if z.testzip() is not None or sum(i.file_size for i in z.infolist()) != total:
            os.remove(tmp)
            raise OSError("the archive could not be verified")
    os.replace(tmp, target)


def archive_one(path: str, is_dir: bool, latest: float, cfg: config.Config) -> tuple[str, str]:
    """(action, final path). Moves (or zips) one item into the archive and logs it."""
    from .service import free_name, move, record
    s = settings(cfg)
    folder = os.path.join(cfg.folder(s["folder"]), str(datetime.fromtimestamp(latest).year))
    os.makedirs(folder, exist_ok=True)
    when = datetime.fromtimestamp(latest).strftime("%d %b %Y")
    if s["zip"]:
        target = free_name(folder, os.path.basename(path) + ".zip", False)
        _zip(path, is_dir, target)
        if is_dir:
            shutil.rmtree(path)
        else:
            os.remove(path)
        record("ARCHIVED_ZIP", path, target, f"untouched since {when}: archived and compressed")
        return "ARCHIVED_ZIP", target
    action, final = move(path, folder, os.path.basename(path), is_dir)
    if action == "DUPLICATE_TRASHED":  # an identical copy is already archived
        record(action, path, final, f"already in the archive: duplicate sent to the {system.TRASH}")
        return action, final
    record("ARCHIVED", path, final, f"untouched since {when}: archived")
    return "ARCHIVED", final


def run(cfg: config.Config, log=None) -> list[str]:
    """Archive what is due (only when archive.enabled). Returns one line per item."""
    if not settings(cfg)["enabled"]:
        return []
    lines = []
    for path, is_dir, latest in candidates(cfg):
        try:
            _, final = archive_one(path, is_dir, latest, cfg)
            lines.append(f"{os.path.basename(path)} -> {config.short(os.path.dirname(final))}")
        except OSError as ex:
            if log:
                log(f"ERROR archiving {path}: {ex!r}")
    if lines and log:
        log(f"ARCHIVED {len(lines)} item(s) untouched for {settings(cfg)['after_days']}+ days")
    return lines


def restore(archived: str, original: str) -> str:
    """Undo of an ARCHIVED_ZIP: extract next to the original place, then remove the .zip. Returns the path."""
    parent = os.path.dirname(original)
    os.makedirs(parent, exist_ok=True)
    with zipfile.ZipFile(archived) as z:
        names = z.namelist()
        top = names[0].replace("\\", "/").split("/")[0] if names else os.path.basename(original)
        target = original if not os.path.exists(original) else os.path.join(parent, "restored_" + top)
        if os.path.exists(target):
            raise OSError(f"{target} already exists")
        tmp = os.path.join(parent, ".desktidy_restore")
        z.extractall(tmp)
    shutil.move(os.path.join(tmp, top), target)
    shutil.rmtree(tmp, ignore_errors=True)
    os.remove(archived)
    return target
