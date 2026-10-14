# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Files: where did they go, undo, search, pinned folders, explain, preview, renaming, tidy one file now."""

from __future__ import annotations

import os
import re
import shutil
import sys

from .. import APP_NAME, config, folders, system
from ..service import keep, move_id, read_moves, record
from . import ui
from .ui import C, _notify_result, _pick, ask, confirm, fail, hint, info, ok, resolve_folder, row, title, unquote, warn

UNDOABLE = ("MOVED", "ARCHIVED", "ARCHIVED_ZIP")


# ================================================================ commands: files
def print_move(m: dict, number: int | None = None) -> None:
    from .. import index, ops
    name = os.path.basename(m["source"])
    when = f"{m['time'][8:10]}/{m['time'][5:7]} {m['time'][11:16]}"
    n = f"{C.W}{number:>3}{C.X} " if number is not None else "    "
    about = ""
    if m["action"] == "DUPLICATE_TRASHED":
        where = f"{C.Y}{system.TRASH}{C.X} (duplicate of {config.short(m['destination'])})"
    elif m["action"] == "UNDONE":
        where = f"{C.CY}restored{C.X} to {config.short(m['destination'])}"
    elif m["action"] == "RECYCLED":
        where = f"{C.Y}{system.TRASH}{C.X}"
    else:
        dest = ops.current_path(m["destination"])
        label = {"ARCHIVED": "archived in ", "ARCHIVED_ZIP": "archived (zip) in "}.get(m["action"], "")
        where = f"{label}{C.G}{config.short(os.path.dirname(dest))}{C.X}"
        if os.path.basename(dest) != config.clean_name(name):
            where += f"{os.sep}{C.BOLD}{os.path.basename(dest)}{C.X}"
        about = index.summary_of(dest)
    print(f"  {n}{C.GR}{when}{C.X}  {C.BOLD}{name}{C.X}  {C.GR}#{move_id(m)}{C.X}\n        -> {where}"
          + (f"\n        {C.CY}about: {about}{C.X}" if about else "") + f"\n        {C.GR}why: {m['reason']}{C.X}")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", config.strip_accents(s).lower())  # "Report 1" == "report_1"


def find_moves(text: str, actions=("MOVED", "DUPLICATE_TRASHED", "UNDONE", "ARCHIVED", "ARCHIVED_ZIP",
                                   "RECYCLED")) -> list[dict]:
    moves = [m for m in read_moves() if m["action"] in actions]
    if text:
        q = _norm(text)
        moves = [m for m in moves
                 if q in _norm(os.path.basename(m["source"])) or q in _norm(os.path.basename(m["destination"]))]
    return moves[::-1]


def cmd_where(args):
    if "--all" in args:
        system.open_path(config.path("moves"))
        return
    text = " ".join(a for a in args if not a.startswith("--"))
    if not text and ui.INTERACTIVE:
        text = ask("File name (or part of it) - Enter = latest moves:")
    found = find_moves(text)[:15]
    title(f"Where did '{text}' go?" if text else "Latest moves")
    if not found:
        warn(f"Nothing called '{text}' in the log. Try a shorter part of the name." if text else "Nothing moved yet")
        return
    from ..ops import current_path
    for i, m in enumerate(found, 1):
        print_move(m, i)
    if "--open" in args:
        system.reveal(current_path(found[0]["destination"]))
    elif ui.INTERACTIVE:
        n = ask(f"Number to show in {system.FILE_MANAGER} (Enter = none):")
        if n.isdigit() and 1 <= int(n) <= len(found):
            system.reveal(current_path(found[int(n) - 1]["destination"]))
    else:
        hint(f"\n  Show the first in {system.FILE_MANAGER}: desktidy where {text or '<name>'} --open"
             "   ·   whole log: desktidy where --all")


def undo_move(m: dict) -> str:
    """Put one logged move (or archived item) back where it was, with its old name. Returns the restored path."""
    from .. import archive
    from ..ops import current_path
    src, dst = m["source"], current_path(m["destination"])
    if not os.path.exists(dst):
        raise FileNotFoundError(f"{os.path.basename(dst)} is no longer in {config.short(os.path.dirname(dst))}")
    target = src if not os.path.exists(src) else os.path.join(os.path.dirname(src), "restored_" + os.path.basename(src))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if m["action"] == "ARCHIVED_ZIP":
        target = archive.restore(dst, src)
    else:
        shutil.move(dst, target)
    record("UNDONE", dst, target, "restored by desktidy undo")
    keep(target)
    return target


def undo_ids(ids: list[str]) -> tuple[list[str], list[str]]:
    """(restored paths, problems) for moves given by their #id (notification buttons, `desktidy undo 1a2b3c4d`)."""
    wanted = {i.lower() for i in ids}
    rows = [m for m in read_moves() if m["action"] in UNDOABLE and move_id(m) in wanted]
    restored, problems = [], []
    for m in rows:
        try:
            restored.append(undo_move(m))
        except OSError as ex:
            problems.append(str(ex))
    if len(rows) < len(wanted):
        problems.append(f"{len(wanted) - len(rows)} move(s) not found")
    return restored, problems


def cmd_undo(args):
    from ..ops import current_path
    text = " ".join(args)
    ids = re.findall(r"#?([0-9a-f]{8})\b", text.lower())
    if ids and re.fullmatch(r"[#0-9a-f,\s]+", text.lower()):
        restored, problems = undo_ids(ids)
        for p in restored:
            ok(f"Restored {C.BOLD}{os.path.basename(p)}{C.X} to {config.short(os.path.dirname(p))}")
        for p in problems:
            fail(p)
        if ui.GUI and restored:
            names = "\n".join(os.path.basename(p) for p in restored[:4])
            system.notify(f"{APP_NAME}: {len(restored)} item(s) put back",
                          names + "\nDeskTidy leaves them there until you change them.")
        return
    candidates = [m for m in find_moves("", UNDOABLE) if os.path.exists(current_path(m["destination"]))]
    if not candidates:
        info("Nothing to undo")
        return
    if text.isdigit():
        index = int(text) - 1
        choice = candidates[index] if 0 <= index < len(candidates) else None
    elif text:
        q = _norm(text)
        choice = next((m for m in candidates
                       if q in _norm(os.path.basename(m["source"]) + os.path.basename(m["destination"]))), None)
    else:
        title("Undo a move")
        for i, m in enumerate(candidates[:10], 1):
            print_move(m, i)
        if not ui.INTERACTIVE and not sys.stdin.isatty():
            hint("\n  Undo one with: desktidy undo <number or name>")
            return
        n = ask("Number to restore (Enter = cancel):")
        choice = candidates[int(n) - 1] if n.isdigit() and 1 <= int(n) <= len(candidates[:10]) else None
    if not choice:
        if text:
            fail(f"No move matching '{text}' can be undone")
        return
    target = undo_move(choice)
    ok(f"Restored {C.BOLD}{os.path.basename(target)}{C.X} to {config.short(os.path.dirname(target))}")
    info("DeskTidy will leave it there until you change it")


def cmd_pinned(args):
    sub = args[0].lower() if args else ""
    if sub in ("add", "pin", "+"):
        return pin_folder(args[1:])
    if sub in ("remove", "unpin", "rm", "-"):
        return unpin_folder(args[1:])
    if sub in ("suggest", "suggestions", "new"):
        return suggest()
    d = folders.load_pinned()
    title("Pinned folders")
    hint("A pinned folder collects the new files about it: by name, by content, or because they look like the\n"
         "  files it already holds (its context, learned automatically).\n")
    if not d["pinned"]:
        info("No pinned folders yet")
    for i, v in enumerate(d["pinned"], 1):
        exists = os.path.isdir(v["path"])
        print(f"   {C.W}{i}){C.X} {C.BOLD}{os.path.basename(v['path'])}{C.X}  {C.GR}{config.short(v['path'])}{C.X}"
              + ("" if exists else f"  {C.R}(missing){C.X}"))
        if v.get("words"):
            print(f"      extra words: {', '.join(v['words'])}")
        if exists and (learned := folders.context_words(v["path"])):
            print(f"      {C.GR}learned context: {', '.join(learned)}{C.X}")
    try:
        new = folders.suggestions(config.load_config(), include_seen=True, wait=False)
    except Exception:
        new = []
    if new:
        print()
        warn(f"{len(new)} new folder(s) could be pinned: {', '.join(os.path.basename(p) for p in new[:5])}"
             f"  ->  {C.W}desktidy pinned suggest{C.X}")
    hint("\n  desktidy pin <folder> [extra words]   ·   desktidy unpin <n|folder>   ·   desktidy pinned suggest")
    if ui.INTERACTIVE:
        choice = ask("a) add   r) remove   s) suggestions   (Enter = back):").lower()
        {"a": lambda: pin_folder([]), "r": lambda: unpin_folder([]), "s": suggest}.get(choice, lambda: None)()


def pin_folder(args):
    if not args:
        if not ui.INTERACTIVE:
            fail("Usage: desktidy pin <folder> [extra words]   e.g.  desktidy pin pasta recipes")
            return
        text = ask("Folder to pin (a name on the Desktop or a full path; you can drag it here):")
        if not text:
            return
        words = ask("Extra words about it, comma separated (Enter = none):")
        args = [text] + [w.strip() for w in words.split(",") if w.strip()]
    target = resolve_folder(args[0])
    try:
        cfg = config.load_config()
        if any(os.path.normcase(target) == os.path.normcase(cfg.expand(w["path"])) for w in cfg["watched_folders"]):
            fail("A watched folder (Downloads, Desktop, Documents) can't be pinned")
            return
    except Exception:
        pass
    if not os.path.isdir(target):
        if ui.INTERACTIVE and not confirm(f"{config.short(target)} doesn't exist. Create it?", default_yes=True):
            return
        os.makedirs(target, exist_ok=True)
        ok(f"Created {target}")
    entry = folders.pin(target, args[1:])
    ok(f"Pinned {C.BOLD}{os.path.basename(target)}{C.X} ({config.short(target)})")
    info(f"New files with '{os.path.basename(target)}' in the name or about it will go there"
         + (f", and files about: {', '.join(entry['words'])}" if entry["words"] else ""))


def unpin_folder(args):
    d = folders.load_pinned()
    if not d["pinned"]:
        info("No pinned folders")
        return
    text = " ".join(args) if args else (ask("Number or name of the folder to unpin:") if ui.INTERACTIVE else "")
    if not text:
        fail("Usage: desktidy unpin <number|folder>")
        return
    if text.isdigit() and 1 <= int(text) <= len(d["pinned"]):
        target = d["pinned"][int(text) - 1]["path"]
    else:
        name = unquote(text).lower()
        matches = [v["path"] for v in d["pinned"] if os.path.basename(v["path"]).lower() == name
                   or os.path.normcase(v["path"]) == os.path.normcase(resolve_folder(text))]
        if not matches:
            fail(f"'{text}' is not pinned")
            return
        target = matches[0]
    folders.unpin(target)
    ok(f"{os.path.basename(target)} is no longer pinned (the folder and its files stay where they are)")


def suggest():
    try:
        new = folders.suggestions(config.load_config(), include_seen=True, wait=False)
    except Exception:
        new = []
    if not new:
        info("No new folders to pin (DeskTidy looks on the Desktop)")
        return
    for p in new:
        if not ui.INTERACTIVE and not sys.stdin.isatty():
            info(f'Could be pinned: {p}  ->  desktidy pin "{p}"')
            continue
        answer = ask(f"Pin {C.BOLD}{os.path.basename(p)}{C.X} ({config.short(p)})? [y/n/Enter = skip]").lower()
        if answer in ("y", "yes"):
            folders.pin(p)
            ok(f"Pinned {os.path.basename(p)}")
        elif answer in ("n", "no"):
            folders.never_ask(p)
            info("It won't be suggested again")


def cmd_explain(args):
    use_ai = "--ai" in args
    target = unquote(" ".join(a for a in args if a != "--ai"))
    if not target and ui.INTERACTIVE:
        target = unquote(ask("File or folder to explain (you can drag it here):"))
    if not target:
        fail("Usage: desktidy explain <file or folder>   (add --ai to ask Claude too)")
        return
    if not os.path.exists(target):
        fail(f"Not found: {target}")
        return
    from .. import classifier, naming
    from .. import content as ct
    cfg = config.load_config()
    is_dir = os.path.isdir(target)
    info("Analysing on this computer (nothing is sent)...")
    an = ct.analyze(target, is_dir, cfg)
    d = classifier.decide(target, is_dir, cfg, an)
    plan = naming.plan(an, cfg)
    title(os.path.basename(target))
    row("Kind", an.describe())
    if an.tags:
        row("Recognised", ", ".join(sorted(an.tags)), f"{C.G}[+]{C.X}")
    if an.info.get("error"):
        row("Reading", f"{C.Y}{an.info['error']}{C.X}", f"{C.Y}[!]{C.X}")
    if keys := an.keywords(10):
        row("Key terms", ", ".join(f"{an.original(w)} ({n})" for w, n in keys))
    if (t := naming.title(an)) and not is_dir:
        row("Title", t)
    if d.candidates:
        print(f"  {C.B}[*]{C.X} Candidate folders (points):")
        for points, dest, why in sorted(d.candidates, reverse=True)[:5]:
            print(f"      {C.CY}{points:5.1f}{C.X}  {config.short(dest)}\n             {C.GR}{why}{C.X}")
    if d.dest:
        shown = d.dest
        if config.is_dated(d.dest):  # Bills/{YEAR}: the folder of this file's date
            from ..deadlines import file_date
            shown = config.dated(d.dest, file_date(target, an))
        row("Offline decision", f"{C.G}{config.short(shown)}{C.X}  {C.GR}({d.reason}; {d.strength}){C.X}", f"{C.G}[+]{C.X}")
    else:
        row("Offline decision", f"{C.Y}none{C.X} -> {config.short(cfg.default_destination)}", f"{C.Y}[!]{C.X}")
    new_name = naming.final_name(an.name, plan.new_stem or plan.fallback, is_dir)
    row("New name", f"{C.BOLD}{new_name}{C.X}  {C.GR}({plan.reason}){C.X}" if plan.reason else new_name)
    shareable = not an.is_private and (not d.private or config.ai_mode(cfg) == config.EVERYTHING)
    if an.is_private:
        row("AI", "never: photos and screenshots stay on this PC")
    elif not shareable:
        row("AI", "not sent: private file, it stays on this PC (only with: desktidy ai all)")
    elif classifier.wants_ai(d, an, cfg):
        check = " and would check that the name fits the content" if naming.ai_may_check(an, plan, cfg) else ""
        private = ", private: you chose Always AI" if d.private else ""
        row("AI", f"would be asked (mode {config.ai_mode(cfg)}{private}){check}")
    else:
        row("AI", f"not needed (mode {config.ai_mode(cfg)})")
    if use_ai and not shareable:
        fail("Not sent to the AI: it is private (house rule 5)")
        return
    if use_ai:
        from .. import ai, providers
        p = providers.current(cfg)
        key = ai.ready(cfg, print)
        if not key:
            fail("The AI is not available (desktidy status)")
            return
        price = "free plan" if p.free else "about $0.001"
        if not confirm(f"Really ask {p.name}? ({price})", default_yes=True):
            return
        item = ai.item_for(target, is_dir, os.path.dirname(target), an, d, plan, cfg)
        answer = (ai.ask([item], cfg, key, lambda m: hint(m)) or {}).get(1)
        if answer:
            row(p.name, f"{C.G}{config.short(answer.folder) if answer.folder else 'none fits'}{C.X} "
                        f"{C.GR}({answer.confidence}: {answer.why}){C.X}", f"{C.G}[+]{C.X}")
            if ai.name_for(item, answer):
                row("Suggested name", answer.name + ("" if item.ask_name else
                                                     f"  {C.GR}(the current name doesn't match the content){C.X}"))
            elif item.check_name:
                row("Name", f"{C.G}fits the content{C.X}, kept")
        else:
            warn("No usable answer (desktidy log errors)")


def cmd_preview(args):
    from ..service import Options, Service
    use_ai = "--ai" in args
    title("Preview: what DeskTidy would do now (nothing is moved" + (")" if use_ai else ", no AI)"))
    if "--now" not in args:
        hint("Only items that are ready (Downloads after 2 min, Desktop/Documents after 10). Add --now to see all.")
    lines: list[str] = []
    opts = Options(dry_run=True, once=True, no_ai=not use_ai, now="--now" in args, say=lines.append)
    Service(opts).tick(config.load_config())
    if not lines:
        ok("Nothing to tidy right now")
    for line in lines:
        print(f"  {C.W}{line}{C.X}")


def cmd_rename(args):
    choice = args[0].lower() if args else ""
    current = config.rename_mode(config.load_config())
    if not choice:
        title("Smart renaming")
        for mode, text in config.RENAME_MODES.items():
            mark = f"{C.G}●{C.X}" if mode == current else f"{C.GR}○{C.X}"
            print(f"   {mark} {C.BOLD}{mode:<8}{C.X} {text}")
        hint("\n  The new name comes from the document title (offline). The original name stays in the log;\n"
             "  desktidy undo restores it. Names starting with ! are never touched.")
        if not ui.INTERACTIVE:
            return
        choice = ask("New mode (Enter = keep):").lower()
        if not choice:
            return
    if choice not in config.RENAME_MODES:
        fail("Choose: smart, generic or off")
        return
    config.update_config(lambda d: d.setdefault("rename", {}).__setitem__("mode", choice))
    ok(f"Renaming: {C.BOLD}{choice}{C.X} - {config.RENAME_MODES[choice]}")


def cmd_find(args):
    """Search by content: desktidy find electricity bill september."""
    from .. import index
    if args and args[0].lower() in ("--rebuild", "rebuild", "--index", "index"):
        cfg = config.load_config()
        info("Indexing the documents in your folders (offline" + (", with OCR: slower" if "--ocr" in args else "")
             + ")...")
        count = [0]

        def progress(_):
            count[0] += 1
            if count[0] % 25 == 0:
                print(f"\r  {C.GR}{count[0]} files{C.X}", end="", flush=True)
        result = index.refresh(cfg, limit=1_000_000, ocr="--ocr" in args, progress=progress)
        print("\r", end="")
        ok(f"{result['added']} added, {result['removed']} removed · {index.stats()['files']} files in the index")
        return
    text = " ".join(a for a in args if not a.startswith("--"))
    if not text and (ui.INTERACTIVE or sys.stdin.isatty()):
        text = ask("What are you looking for? (words from the content, the title or the name):")
    if not text:
        fail("Usage: desktidy find <words>   e.g.  desktidy find electricity bill september")
        return
    hits = index.search(text, 15)
    title(f"Files about '{text}'")
    if not hits:
        stats = index.stats()
        warn(f"Nothing found among {stats['files']} indexed files.")
        hint(f"  Fewer or other words? Existing files are indexed once a day, or now: {C.W}desktidy find --rebuild{C.X}")
        return
    for i, h in enumerate(hits, 1):
        folder = config.short(os.path.dirname(h.path))
        print(f"  {C.W}{i:>2}){C.X} {C.BOLD}{os.path.basename(h.path)}{C.X}  {C.GR}{folder}{C.X}")
        if h.summary or h.title:
            print(f"      {C.CY}{h.summary or h.title}{C.X}")
        if h.snippet:
            snippet = h.snippet.replace(index.MARK[0], C.Y or "*").replace(index.MARK[1], C.GR or "*")
            print(f"      {C.GR}{snippet}{C.X}")
    if "--open" in args:
        system.open_path(hits[0].path)
        return
    n = _pick("Number to open (Enter = none):", len(hits))
    if n:
        system.open_path(hits[n - 1].path)


def cmd_tidy(args):
    """Tidy one file or folder now (right-click menu), with the AI if the mode allows it."""
    from .. import classifier, naming
    from .. import content as ct
    from ..service import Options, Service
    target = os.path.abspath(unquote(" ".join(args)))
    if not os.path.exists(target):
        fail(f"Not found: {target}")
        return
    if os.path.basename(target).startswith("!"):
        fail(f"{os.path.basename(target)} starts with ! (hands off): remove the ! first")
        return
    is_dir = os.path.isdir(target)
    if is_dir and folders.holds_pinned(target):
        fail("A pinned folder (or a folder holding one) is never moved")
        return
    cfg = config.load_config()
    an = ct.analyze(target, is_dir, cfg)
    d = classifier.decide(target, is_dir, cfg, an)
    plan = naming.plan(an, cfg)
    svc = Service(Options(once=True))
    base = os.path.dirname(target)
    lines = None
    if classifier.wants_ai(d, an, cfg):
        from .. import ai
        key = ai.ready(cfg, hint)
        if key:
            item = ai.item_for(target, is_dir, base, an, d, plan, cfg)
            lines = svc.finish_item(item, (ai.ask([item], cfg, key, hint) or {}).get(1), cfg)
    if lines is None:
        lines = svc.finish(cfg, target, is_dir, base, d.dest, d.reason, plan.new_stem or plan.fallback, plan.reason,
                           an=an)
    if not lines and target in svc.errors:  # not moved because of a problem (an unknown variable in a rule...)
        fail(f"{os.path.basename(target)} was not moved: {svc.state.get('last_error', svc.errors[target])}")
        _notify_result(APP_NAME, f"{os.path.basename(target)} was not moved: see desktidy log errors")
        return
    if not lines:
        ok(f"{os.path.basename(target)} is already in the right place")
        _notify_result(APP_NAME, f"{os.path.basename(target)} is already in the right place")
        return
    ok(lines[0])
    _notify_result(f"{APP_NAME}: tidied", lines[0], svc.ids)


def cmd_handsoff(args):
    """Add or remove the "!" that tells DeskTidy to leave an item alone."""
    target = os.path.abspath(unquote(" ".join(args)))
    if not os.path.exists(target):
        fail(f"Not found: {target}")
        return
    name = os.path.basename(target)
    new = name[1:] if name.startswith("!") else "!" + name
    renamed = os.path.join(os.path.dirname(target), new)
    if os.path.exists(renamed):
        fail(f"{new} already exists there")
        return
    os.rename(target, renamed)
    record("RENAMED", target, renamed, "hands off (!)" if new.startswith("!") else "DeskTidy may tidy it again")
    text = f"{new}: DeskTidy leaves it alone" if new.startswith("!") else f"{new}: DeskTidy may tidy it again"
    ok(text)
    _notify_result(APP_NAME, text)


def cmd_pin_toggle(args):
    target = os.path.abspath(unquote(" ".join(args)))
    if not os.path.isdir(target):
        fail(f"Not a folder: {target}")
        return
    if any(os.path.normcase(v["path"]) == os.path.normcase(target) for v in folders.load_pinned()["pinned"]):
        folders.unpin(target)
        text = f"{os.path.basename(target)} is no longer pinned"
    else:
        folders.pin(target)
        text = f"{os.path.basename(target)} pinned: new files about it will go there"
    ok(text)
    _notify_result(APP_NAME, text)
