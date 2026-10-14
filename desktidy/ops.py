# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Changes to whole folders, applied from the organisation advice (`desktidy advice apply <n>`): merge, rename,
move, archive, create, pin, remove empty folders.

Safe by design:
  * a PLAN is shown first, nothing happens until it is confirmed
  * folders that must never move are refused: drive roots, the user folder, the watched folders, the to-sort
    folder, DeskTidy's data, folders whose name starts with "!"
  * if a step fails, the steps already done are rolled back
  * the rules, the pinned folders, the search index and the deadlines that pointed into a moved folder are updated
  * the whole change is journalled in folder_ops.json: `desktidy advice undo` reverts the latest one
Files are never deleted: merging two folders moves the files, a name already taken becomes name_v2.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime

from . import config, folders

AUTOMATIC = {"merge", "rename", "move", "archive", "create", "pin", "cleanup"}
DEFAULT_ARCHIVE = "{DOCS}/Archive"


@dataclass
class Plan:
    title: str
    steps: list[dict] = field(default_factory=list)   # {"op": "move"|"mkdir"|"rmdir"|"pin", ...}
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and not self.problems


# ---------------------------------------------------------------- safety
def protected(cfg: config.Config) -> list[str]:
    home = os.path.expanduser("~")
    out = [home, cfg.default_destination, str(config.data_dir())]
    out += [cfg.expand("{" + v + "}") for v in ("HOME", "DOCS", "DESKTOP", "DOWNLOADS", "PICTURES", "VIDEOS", "MUSIC")]
    out += [cfg.expand(w["path"]) for w in cfg["watched_folders"]]
    return [os.path.normcase(os.path.abspath(p)) for p in out]


def _refuse(path: str, cfg: config.Config) -> str | None:
    p = os.path.normcase(os.path.abspath(path))
    if not os.path.isdir(path):
        return f"{config.short(path)} does not exist"
    if os.path.splitdrive(p)[1] in ("\\", "/", "") or os.path.ismount(path):
        return f"{path} is a drive"
    if p in protected(cfg):
        return f"{config.short(path)} is a folder DeskTidy must not move"
    if config.inside(str(config.data_dir()), path):
        return f"{config.short(path)} holds DeskTidy's own data"
    if os.path.basename(path).startswith("!"):
        return f"{os.path.basename(path)} starts with ! (hands off)"
    if folders.app_owned(path):
        return f"{os.path.basename(path)} belongs to a program (settings, saves): moving it could break it"
    return None


def _free(path: str, is_dir: bool) -> str:
    from .service import free_name
    return free_name(os.path.dirname(path), os.path.basename(path), is_dir)


# ---------------------------------------------------------------- planning
def _merge_steps(src: str, dst: str, steps: list[dict]) -> None:
    """Move everything inside `src` into `dst`; subfolders with the same name are merged too."""
    for e in sorted(os.scandir(src), key=lambda e: e.name.lower()):
        target = os.path.join(dst, e.name)
        if e.is_dir(follow_symlinks=False) and os.path.isdir(target):
            _merge_steps(e.path, target, steps)
        else:
            if os.path.exists(target) or any(s.get("dst", "").lower() == target.lower() for s in steps):
                stem, ext = (e.name, "") if e.is_dir() else os.path.splitext(e.name)
                n = 2
                while os.path.exists(target) or any(s.get("dst", "").lower() == target.lower() for s in steps):
                    target = os.path.join(dst, f"{stem}_v{n}{ext}")
                    n += 1
            steps.append({"op": "move", "src": e.path, "dst": target})
    steps.append({"op": "rmdir", "path": src})


def plan(tip: dict, cfg: config.Config) -> Plan:
    """What applying a tip would do, step by step (nothing is changed)."""
    kind, paths = tip.get("kind", ""), list(tip.get("paths", []))
    p = Plan(tip.get("title", kind))
    if kind not in AUTOMATIC:
        p.problems.append(f"a '{kind}' tip needs your judgement: open the folders and do it by hand")
        return p
    needed = {"merge": 2, "move": 2, "rename": 1, "archive": 1, "create": 1, "pin": 1, "cleanup": 1}[kind]
    if len(paths) < needed:
        p.problems.append(f"the tip names {len(paths)} folder(s), {needed} needed")
        return p
    new_name = config.clean_name(tip.get("new_name", ""), is_dir=True) if tip.get("new_name") else ""
    if kind in ("rename", "create") and not new_name:
        p.problems.append("the tip gives no new folder name")
        return p
    if kind == "merge":
        dst = paths[0]
        if not os.path.isdir(dst):
            p.problems.append(f"{config.short(dst)} does not exist")
        for src in paths[1:]:
            if (why := _refuse(src, cfg)) is not None:
                p.problems.append(why)
            elif config.inside(dst, src) or config.inside(src, dst):
                p.problems.append(f"{os.path.basename(src)} and {os.path.basename(dst)} are inside each other")
            elif not p.problems:
                _merge_steps(src, dst, p.steps)
                p.steps.append({"op": "follow", "src": src, "dst": dst})  # rules and pinned folders follow
    elif kind == "move":
        dst = paths[0]
        if not os.path.isdir(dst):
            p.problems.append(f"{config.short(dst)} does not exist")
        for src in paths[1:]:
            if (why := _refuse(src, cfg)) is not None:
                p.problems.append(why)
            elif config.inside(dst, src):
                p.problems.append(f"{os.path.basename(src)} can't go inside itself")
            else:
                p.steps.append({"op": "move", "src": src, "dst": _free(os.path.join(dst, os.path.basename(src)), True)})
    elif kind == "rename":
        src = paths[0]
        target = os.path.join(os.path.dirname(src), new_name)
        if (why := _refuse(src, cfg)) is not None:
            p.problems.append(why)
        elif os.path.exists(target) and os.path.normcase(target) != os.path.normcase(src):
            p.problems.append(f"{new_name} already exists there: merge them instead")
        else:
            p.steps.append({"op": "move", "src": src, "dst": target})
    elif kind == "archive":
        try:
            root = cfg.folder(cfg.get("archive", {}).get("folder", DEFAULT_ARCHIVE))
        except OSError as ex:
            p.problems.append(str(ex))
            return p
        if not os.path.isdir(root):
            p.steps.append({"op": "mkdir", "path": root})
        for src in paths:
            if (why := _refuse(src, cfg)) is not None:
                p.problems.append(why)
            elif config.inside(root, src):
                p.problems.append(f"{os.path.basename(src)} holds the archive folder")
            else:
                p.steps.append({"op": "move", "src": src, "dst": _free(os.path.join(root, os.path.basename(src)), True)})
    elif kind == "create":
        target = os.path.join(paths[0], new_name)
        if not os.path.isdir(paths[0]):
            p.problems.append(f"{config.short(paths[0])} does not exist")
        elif os.path.exists(target):
            p.problems.append(f"{config.short(target)} already exists")
        else:
            p.steps += [{"op": "mkdir", "path": target}, {"op": "pin", "path": target}]
    elif kind == "pin":
        if not os.path.isdir(paths[0]):
            p.problems.append(f"{config.short(paths[0])} does not exist")
        else:
            p.steps.append({"op": "pin", "path": paths[0]})
    elif kind == "cleanup":
        for src in paths:
            if os.path.isdir(src) and not os.listdir(src) and _refuse(src, cfg) is None:
                p.steps.append({"op": "rmdir", "path": src})
        if not p.steps:
            p.problems.append("none of these folders is empty: nothing to clean up automatically")
    return p


def describe(step: dict) -> str:
    op = step["op"]
    if op == "follow":
        return f"update rules and pinned folders: {config.short(step['src'])} -> {config.short(step['dst'])}"
    if op == "move":
        same = os.path.dirname(step["src"]) == os.path.dirname(step["dst"])
        return (f"rename {config.short(step['src'])} -> {os.path.basename(step['dst'])}" if same
                else f"move   {config.short(step['src'])} -> {config.short(step['dst'])}")
    return {"mkdir": "create", "rmdir": "remove (empty)", "pin": "pin"}[op] + f" {config.short(step['path'])}"


# ---------------------------------------------------------------- doing and undoing
def _move(src: str, dst: str) -> None:
    if os.path.normcase(src) == os.path.normcase(dst):
        os.rename(src, dst)  # only the case of the name changes
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        raise OSError(f"{dst} already exists")
    shutil.move(src, dst)


def _do(step: dict) -> None:
    op = step["op"]
    if op == "move":
        _move(step["src"], step["dst"])
    elif op == "mkdir":
        os.makedirs(step["path"])
    elif op == "rmdir":
        os.rmdir(step["path"])          # only an empty folder: never deletes files
    elif op == "pin":
        step["was_pinned"] = any(os.path.normcase(v["path"]) == os.path.normcase(step["path"])
                                 for v in folders.load_pinned()["pinned"])
        folders.pin(step["path"])


def _undo(step: dict) -> None:
    op = step["op"]
    if op == "move":
        back = step["src"]
        if os.path.exists(back) and os.path.normcase(back) != os.path.normcase(step["dst"]):
            back = _free(back, os.path.isdir(step["dst"]))  # something new took the old name: name_v2
        _move(step["dst"], back)
        step["restored"] = back
    elif op == "mkdir":
        if os.path.isdir(step["path"]) and not os.listdir(step["path"]):
            os.rmdir(step["path"])
    elif op == "rmdir":
        os.makedirs(step["path"], exist_ok=True)
    elif op == "pin" and not step.get("was_pinned"):
        folders.unpin(step["path"])


def unexpand(cfg: config.Config, path: str) -> str:
    """An absolute path written with the variables of rules.json when possible: {DOCS}/Study rather than
    C:\\Users\\name\\Documents\\Study or /home/name/Documents/Study (so rules.json stays portable)."""
    best, best_len = path, 0
    for name in [*config.BUILTIN_VARIABLES, *cfg.get("variables", {})]:  # the most specific one wins
        value = cfg.expand("{" + name + "}").rstrip(os.sep)
        if "{" not in value and config.inside(path, value) and len(value) > best_len:
            best, best_len = "{" + name + "}" + path[len(value):], len(value)
    return best


def _relocate(path: str, moves: list[tuple[str, str]]) -> str | None:
    for src, dst in moves:
        if config.inside(path, src):
            return dst + path[len(src):]
    return None


def _follow(moves: list[tuple[str, str]], cfg: config.Config) -> list[dict]:
    """Point the rules, the candidate folders and the pinned folders at the new places; returns the changes."""
    changes: list[dict] = []

    def change(data):
        conf = config.Config(data, cfg.source)
        for i, r in enumerate(data.get("rules", [])):
            new = _relocate(conf.expand(r["destination"]), moves)
            if new:
                changes.append({"kind": "rule", "index": i, "old": r["destination"], "new": unexpand(conf, new)})
                r["destination"] = changes[-1]["new"]
        for i, entry in enumerate(data.get("ai", {}).get("candidate_folders", [])):
            raw = entry["path"] if isinstance(entry, dict) else entry
            new = _relocate(conf.expand(raw), moves)
            if new:
                changes.append({"kind": "candidate", "index": i, "old": raw, "new": unexpand(conf, new)})
                if isinstance(entry, dict):
                    entry["path"] = changes[-1]["new"]
                else:
                    data["ai"]["candidate_folders"][i] = changes[-1]["new"]

    if cfg.source and os.path.exists(cfg.source):
        config.update_config(change, cfg.source)
    d = folders.load_pinned()
    for v in d["pinned"]:
        new = _relocate(v["path"], moves)
        if new:
            changes.append({"kind": "pinned", "old": v["path"], "new": new})
            v["path"] = new
    if any(c["kind"] == "pinned" for c in changes):
        folders.save_pinned(d)
    return changes


def _revert(changes: list[dict], cfg: config.Config) -> None:
    def change(data):
        for c in changes:
            if c["kind"] == "rule" and c["index"] < len(data.get("rules", [])) \
                    and data["rules"][c["index"]]["destination"] == c["new"]:
                data["rules"][c["index"]]["destination"] = c["old"]
            elif c["kind"] == "candidate":
                entries = data.get("ai", {}).get("candidate_folders", [])
                if c["index"] < len(entries):
                    entry = entries[c["index"]]
                    if isinstance(entry, dict) and entry.get("path") == c["new"]:
                        entry["path"] = c["old"]
                    elif entry == c["new"]:
                        entries[c["index"]] = c["old"]
    if cfg.source and os.path.exists(cfg.source) and any(c["kind"] != "pinned" for c in changes):
        config.update_config(change, cfg.source)
    d = folders.load_pinned()
    for c in (c for c in changes if c["kind"] == "pinned"):
        for v in d["pinned"]:
            if os.path.normcase(v["path"]) == os.path.normcase(c["new"]):
                v["path"] = c["old"]
    folders.save_pinned(d)


def _relink(moves: list[tuple[str, str]]) -> None:
    """The search index and the deadlines follow the files (moved one by one, or with their folder)."""
    from . import deadlines, index
    for src, dst in moves:
        index.moved(src, dst)
        index.moved_folder(src, dst)
        deadlines.moved(src, dst)
        deadlines.moved_folder(src, dst)


def journal() -> list[dict]:
    data = config.read_json(config.path("ops"), [])
    return data if isinstance(data, list) else []


def apply(p: Plan, cfg: config.Config, tip: dict | None = None) -> dict:
    """Do the plan; on any error undo what was done and raise. Returns the journal entry."""
    if not p.ok:
        raise ValueError("; ".join(p.problems) or "nothing to do")
    done: list[dict] = []
    try:
        for step in p.steps:
            _do(step)
            done.append(step)
    except Exception:
        for step in reversed(done):
            try:
                _undo(step)
            except OSError:
                pass
        raise
    moves = [(s["src"], s["dst"]) for s in done if s["op"] in ("move", "follow")]
    changes = _follow(moves, cfg) if moves else []
    _relink(moves)
    entry = {"id": hashlib.blake2b(datetime.now().isoformat().encode(), digest_size=4).hexdigest(),
             "at": datetime.now().isoformat(timespec="seconds"), "title": p.title, "tip": tip or {},
             "steps": done, "changes": changes, "undone": False}
    config.write_json(config.path("ops"), (journal() + [entry])[-100:])
    return entry


def undo_last(cfg: config.Config) -> dict | None:
    """Revert the latest applied change that is not undone yet. An item that can't be put back (moved or deleted
    since) is skipped and listed in entry["skipped"]; the rest is reverted."""
    entries = journal()
    entry = next((e for e in reversed(entries) if not e.get("undone")), None)
    if not entry:
        return None
    skipped = []
    for step in reversed(entry["steps"]):
        try:
            _undo(step)
        except OSError:
            gone = step["op"] == "move" and not os.path.exists(step["dst"])
            skipped.append(f"{os.path.basename(step['dst'])} is no longer in {config.short(os.path.dirname(step['dst']))}"
                           " (moved or put back since)" if gone else describe(step))
    _revert(entry["changes"], cfg)
    _relink([(s["dst"], s.get("restored", s["src"])) for s in reversed(entry["steps"])
             if s["op"] == "follow" or s.get("restored")])
    entry["skipped"] = skipped
    entry["undone"] = datetime.now().isoformat(timespec="seconds")
    config.write_json(config.path("ops"), entries)
    return entry


def current_path(path: str) -> str:
    """Where a path recorded before some folder changes is now (moves.csv keeps the old paths)."""
    for entry in journal():
        if entry.get("undone"):
            continue
        for step in entry["steps"]:
            if step["op"] in ("move", "follow") and config.inside(path, step["src"]):
                path = step["dst"] + path[len(step["src"]):]
    return path
