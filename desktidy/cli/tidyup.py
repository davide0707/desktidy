"""Tidy-up tools: deadlines, groups, organize, versions, installers, duplicates, archive, photo import, learning."""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime

from .. import APP_NAME, config, folders, system
from . import ui
from .ui import C, _pick, ago, ask, confirm, fail, hint, info, ok, resolve_folder, row, title, unquote, usd, warn


def _parse_date(text: str):
    from .. import deadlines
    for kind, rx in deadlines.DATES:
        m = rx.fullmatch(config.strip_accents(text.strip()).lower())
        if m:
            return deadlines._make(kind, m, date.today())
    return None


def cmd_deadlines(args):
    from .. import deadlines
    sub = args[0].lower() if args else ""
    if sub in ("done", "paid", "remove", "delete", "open", "undone"):
        key = args[1] if len(args) > 1 else ""
        item = deadlines.find(key)
        if not item:
            fail(f"Usage: desktidy deadlines {sub} <number>   (see: desktidy deadlines)")
            return
        if sub in ("done", "paid"):
            deadlines.update(item["id"], done=True)
            ok(f"Done: {item['what']} (no more reminders)")
        elif sub == "undone":
            deadlines.update(item["id"], done=False, notified=[])
            ok(f"Reminders back on for: {item['what']}")
        elif sub == "open":
            if item.get("path") and os.path.exists(item["path"]):
                system.open_path(item["path"])
            else:
                fail("The file is no longer where it was")
        else:
            deadlines.remove(item["id"])
            ok(f"Removed: {item['what']}")
        return
    if sub == "add":
        when = _parse_date(args[1]) if len(args) > 1 else None
        what = " ".join(args[2:]).strip()
        if not when or not what:
            fail('Usage: desktidy deadlines add 2026-10-30 Pay the rent   (also 30/10/2026 or "30 ottobre")')
            return
        item = deadlines.add(when, what)
        (ok if item else info)(f"Added: {what} on {when:%a %d %b %Y}" if item else "Already listed")
        return
    if sub in ("ics", "calendar", "calendario", "export"):
        words = [a for a in args[1:] if not a.startswith("--")]
        target = os.path.abspath(unquote(" ".join(words))) if words else os.path.join(str(config.data_dir()),
                                                                                         "deadlines.ics")
        if os.path.isdir(target):
            target = os.path.join(target, "deadlines.ics")
        try:
            count = deadlines.export_ics(target, config.load_config())
        except OSError as ex:
            fail(f"Could not write {target}: {ex}")
            return
        ok(f"{count} open deadline(s) written to {C.BOLD}{target}{C.X}")
        hint("  Import it in your calendar (Outlook: open the file · Google Calendar: Settings > Import). Importing "
             "again\n  updates the same events instead of adding copies.")
        if "--open" in args:
            system.open_path(target)
        return
    if sub == "scan":
        from .. import content as ct
        target = unquote(" ".join(args[1:]))
        if not os.path.isfile(target):
            fail("Usage: desktidy deadlines scan <file>")
            return
        an = ct.analyze(target, False, config.load_config())
        from .. import naming
        added = deadlines.add_for_file(target, an, naming.title(an) or "")
        for d in added:
            ok(f"{d['date']}: {d['what']}" + (f" · {d['amount']}" if d.get("amount") else ""))
        if not added:
            info("No deadline found in this file (or already listed)")
        return
    items = deadlines.upcoming()
    title("Deadlines")
    if not items:
        info("No upcoming deadlines. DeskTidy finds them in the documents it tidies (bills, enrolments, contracts).")
        hint('  Add one by hand: desktidy deadlines add 2026-10-30 "Pay the rent"')
        return
    for i, d in enumerate(items, 1):
        n = deadlines.days_left(d)
        color = C.R if n < 0 else C.Y if n <= 3 else C.G
        amount = f"  {C.BOLD}{d['amount']}{C.X}" if d.get("amount") else ""
        print(f"  {C.W}{i:>2}){C.X} {color}{date.fromisoformat(d['date']):%a %d %b %Y}{C.X} {C.GR}({deadlines.when_text(d)})"
              f"{C.X}  {d['what']}{amount}")
        if d.get("path"):
            print(f"      {C.GR}{config.short(d['path'])}{C.X}")
    hint("\n  desktidy deadlines done <n> · open <n> · remove <n> · add <date> <what> · scan <file> · "
         "ics [file] --open (to your calendar)")
    n = _pick("Number to open (Enter = none):", len(items))
    if n:
        cmd_deadlines(["open", str(n)])


def cmd_groups(args):
    from .. import groups
    cfg = config.load_config()
    found = groups.find(cfg)
    if args and args[0].lower() == "apply":
        n = args[1] if len(args) > 1 else ""
        if not (n.isdigit() and 1 <= int(n) <= len(found)):
            fail("Usage: desktidy groups apply <n> [--pin] [--to <folder>]   (see: desktidy groups)")
            return
        g = found[int(n) - 1]
        to = args[args.index("--to") + 1] if "--to" in args and args.index("--to") + 1 < len(args) else None
        target = resolve_folder(to) if to else g.target
        moved = groups.apply(g, cfg, target, pin="--pin" in args)
        ok(f"{len(moved)} file(s) moved to {C.BOLD}{config.short(target)}{C.X}" + (" (pinned)" if "--pin" in args else ""))
        info(f"Undo any of them: {C.W}desktidy undo <name>{C.X}")
        return
    title(f"Groups in {config.short(cfg.default_destination)}")
    if not found:
        info("No groups: the files waiting to be sorted have little in common (or there are fewer than 3).")
        return
    for i, g in enumerate(found, 1):
        where = f"{C.G}existing{C.X} {config.short(g.target)}" if g.existing else f"{C.Y}new{C.X} {config.short(g.target)}"
        print(f"\n  {C.W}{i}){C.X} {C.BOLD}{len(g.files)} files about {g.label}{C.X}\n      -> {where}")
        for f in g.files[:5]:
            print(f"      {C.GR}· {os.path.basename(f)}{C.X}")
        if len(g.files) > 5:
            print(f"      {C.GR}  ... and {len(g.files) - 5} more{C.X}")
    hint("\n  desktidy groups apply <n> [--pin] [--to <folder>]   (--pin: the next ones go there by themselves)")
    n = _pick("Number to apply now (Enter = none):", len(found))
    if n:
        pin = not found[n - 1].existing and confirm("Pin the folder, so the next ones go there by themselves?", True)
        cmd_groups(["apply", str(n)] + (["--pin"] if pin else []))


ORGANIZE_PLACES = {"desktop": "{DESKTOP}", "scrivania": "{DESKTOP}", "downloads": "{DOWNLOADS}",
                   "download": "{DOWNLOADS}", "documents": "{DOCS}", "documenti": "{DOCS}", "docs": "{DOCS}"}


def cmd_organize(args):
    """Loose files and folders grouped into folders by the AI: the crowded folders, a plan, apply, undo."""
    from .. import ops, organize
    cfg = config.load_config()
    words = [a for a in args if not a.startswith("--")]
    sub = words[0].lower() if words else ""
    if sub == "apply":
        return organize_apply(words[1] if len(words) > 1 else "", cfg, "--pin" in args, "--yes" in args)
    if sub == "undo":
        latest = next((e for e in reversed(ops.journal()) if not e.get("undone")), None)
        entry = organize.undo(cfg)
        if entry:
            back = sum(1 for s in entry["steps"] if s["op"] == "move" and s.get("restored"))
            ok(f"Undone: {C.BOLD}{entry['title']}{C.X} ({back} item(s) back where they were)")
            for s in entry.get("skipped", []):
                warn(f"could not put back: {s}")
            info("DeskTidy leaves them there until you change them")
        elif latest:
            fail(f"The latest folder change is not an organize: {C.BOLD}{latest['title']}{C.X}. "
                 f"Undo it first: {C.W}desktidy advice undo{C.X}")
        else:
            info("Nothing to undo")
        return
    if sub in ("plan", "show", "last"):
        return print_organize(organize.load())
    if not words:
        spots = organize.crowded(cfg)
        title("Crowded folders")
        if not spots:
            info(f"No folder holds {cfg.get('organize', {}).get('min_items', organize.MIN_ITEMS)}+ loose items: "
                 "all tidy. Organize one anyway: desktidy organize <folder>")
        for i, s in enumerate(spots, 1):
            print(f"  {C.W}{i:>2}){C.X} {C.BOLD}{organize_name(s.path, cfg)}{C.X}  {C.GR}{s.files} file(s)"
                  + (f", {s.folders} folder(s)" if s.folders else "") + f"   {config.short(s.path)}{C.X}")
        saved = organize.load()
        if any(not g.get("applied") for g in saved.get("groups", [])):
            hint(f"\n  A plan from {ago(saved.get('at'))} is waiting: desktidy organize plan")
        hint("\n  desktidy organize <n | folder> [--offline] · organize all · organize apply <n | all> [--pin] · "
             "organize undo")
        if spots and (ui.INTERACTIVE or sys.stdin.isatty()):
            n = ask("Number to organise, 'all' for every one (Enter = none):").lower()
            if n == "all" or (n.isdigit() and 1 <= int(n) <= len(spots)):
                plan_organize([s.path for s in spots[:organize.PLAN_SPOTS]] if n == "all" else [spots[int(n) - 1].path],
                              cfg, "--offline" in args)
        return
    if sub == "all":
        targets = [s.path for s in organize.crowded(cfg)][:organize.PLAN_SPOTS]
        if not targets:
            info("No crowded folders: all tidy")
            return
    elif sub.isdigit():
        spots = organize.crowded(cfg)
        if not 1 <= int(sub) <= len(spots):
            fail("No such number: see the list with  desktidy organize")
            return
        targets = [spots[int(sub) - 1].path]
    else:
        text = " ".join(words)
        targets = [cfg.expand(ORGANIZE_PLACES[text.lower()]) if text.lower() in ORGANIZE_PLACES
                   else cfg.default_destination if text.lower() in ("inbox", "to_sort", "to-sort", "pile")
                   else resolve_folder(text)]
        if not os.path.isdir(targets[0]):
            fail(f"{targets[0]} is not a folder")
            return
    plan_organize(targets, cfg, "--offline" in args)


def organize_name(path: str, cfg) -> str:
    if os.path.normcase(path) == os.path.normcase(cfg.default_destination):
        return "the to-sort pile"
    return os.path.basename(path.rstrip(os.sep)) or path


def plan_organize(targets: list[str], cfg, offline: bool = False) -> None:
    """A plan for the given folders, from the AI or (no AI, or --offline) from the offline engine; saved, shown."""
    from .. import ai, organize, providers, redact
    p = providers.current(cfg)
    key = None if offline else ai.ready(cfg, print, files=False)
    if not key and not offline:
        info("No AI now (desktidy ai): the offline engine groups the items with names and words in common")
    pinned = folders.active_pinned()
    count = sum(len(organize.loose(t, cfg, pinned)) for t in targets)
    if not count:
        info("Nothing loose to organise there")
        return
    if key:
        cost = organize.estimate(count, cfg)
        price = "free plan" if p.free or p.local else f"about {usd(cost, 3)}" if cost is not None else "price unknown"
        private = ("Photos and screenshots are never sent; private documents are (you chose Always AI)"
                   + (", with IBANs, tax codes and phone numbers masked" if redact.wanted(cfg) else "")
                   if config.ai_mode(cfg) == config.EVERYTHING else "Private files, photos and screenshots are never sent")
        if (ui.INTERACTIVE or sys.stdin.isatty()) and not confirm(
                f"Send {p.name} the names of {count} item(s) and a few words from each? {private}. ({price})", True):
            return
    results = []
    for t in targets:
        name = organize_name(t, cfg)
        r = organize.plan_folder(t, cfg, key, hint, lambda k, n, name=name: print(
            f"\r  {C.B}[*]{C.X} Reading {name}: {k}/{n} ", end="\n" if k == n else "", flush=True))
        if r["failed"]:
            warn(f"{organize_name(t, cfg)}: no usable answer from {p.name} (desktidy log errors)")
        results.append(r)
    data = organize.save(results, cfg, offline=key is None)
    print_organize(data)
    if data["groups"] and (ui.INTERACTIVE or sys.stdin.isatty()):
        n = ask("Number to apply, 'all' for the whole plan (Enter = none):").lower()
        if n == "all" or n.isdigit():
            organize_apply(n, cfg)


def print_organize(data: dict) -> None:
    title("Organize: the plan")
    groups = data.get("groups", [])
    if not data.get("folders"):
        info("No plan yet: desktidy organize <folder>")
        return
    source = " · ".join(x for x in (data.get("service", "the AI"), data.get("model", ""), ago(data.get("at"))) if x)
    hint(f"From {source}. Nothing has moved yet.")
    number = {id(g): i for i, g in enumerate(groups, 1)}
    for f in data["folders"]:
        mine = [g for g in groups if os.path.normcase(g["folder"]) == os.path.normcase(f["folder"])]
        print(f"\n  {C.BOLD}{C.W}{os.path.basename(f['folder'].rstrip(os.sep)) or f['folder']}{C.X}  "
              f"{C.GR}{config.short(f['folder'])}{C.X}")
        for g in mine:
            where = f"{C.Y}new{C.X} {config.short(g['target'])}" if g["new"] else \
                f"{C.G}existing{C.X} {config.short(g['target'])}"
            done = f"  {C.G}(done){C.X}" if g.get("applied") else ""
            print(f"  {C.W}{number[id(g)]:>2}){C.X} {C.BOLD}{g['title']}{C.X} {C.GR}({len(g['files'])}){C.X}"
                  f" -> {where}{done}")
            if g.get("why"):
                print(f"      {C.GR}{g['why']}{C.X}")
            names = [os.path.basename(x) for x in g["files"]]
            print(f"      {C.GR}· " + " · ".join(names[:4]) + (f" ... and {len(names) - 4} more" if len(names) > 4 else "")
                  + C.X)
        if not mine:
            info("no groups: the items have little in common")
        rest = [f"{f['left']} stay where they are" if f.get("left") else "",
                f"{f['private']} private (never sent)" if f.get("private") else "",
                f"{f['unreadable']} unreadable" if f.get("unreadable") else ""]
        if any(rest):
            hint("      " + " · ".join(x for x in rest if x))
    if groups:
        hint("\n  desktidy organize apply <n | all> [--pin]   (a preview first; --pin: the next files about them go there"
             " by themselves) · organize undo")


def organize_apply(n: str, cfg, pin: bool = False, yes: bool = False) -> None:
    """Show what applying groups of the plan would do, then do it (undoable with: desktidy organize undo)."""
    from .. import ops, organize
    groups = organize.load().get("groups", [])
    numbers = [i for i, g in enumerate(groups, 1) if not g.get("applied")] if n.lower() == "all" else \
        [int(n)] if n.isdigit() and 1 <= int(n) <= len(groups) else []
    if not numbers:
        fail("Usage: desktidy organize apply <n | all> [--pin]   (see: desktidy organize plan)")
        return
    chosen = [groups[i - 1] for i in numbers if not groups[i - 1].get("applied")]
    if not chosen:
        info("Already done")
        return
    interactive = ui.INTERACTIVE or sys.stdin.isatty()
    if not pin and not yes and interactive and any(g["new"] for g in chosen):
        pin = confirm("Pin the new folders, so the next files about them go there by themselves?", True)
    plan, notes = organize.steps(chosen, cfg, pin)
    title(plan.title)
    for p in plan.problems:
        fail(p)
    for note in notes:
        warn(note)
    if not plan.ok:
        hint("  Nothing was changed.")
        return
    for step in plan.steps[:30]:
        print(f"   {C.CY}·{C.X} {ops.describe(step)}")
    if len(plan.steps) > 30:
        print(f"   {C.GR}... and {len(plan.steps) - 30} more{C.X}")
    moves = sum(1 for s in plan.steps if s["op"] == "move")
    hint(f"\n  {moves} move(s). Files are never deleted; a name already taken becomes name_v2.")
    if not yes and not confirm("Do it?", default_yes=False):
        return
    try:
        organize.apply(numbers, cfg, pin)
    except Exception as ex:
        fail(f"Stopped and rolled back: {ex}")
        return
    ok(f"Done: {moves} item(s) moved")
    info(f"Changed your mind? {C.W}desktidy organize undo{C.X} (all of it) · {C.W}desktidy undo <name>{C.X} (one file)")


def cmd_versions(args):
    from .. import versions
    cfg = config.load_config()
    folder_args = [a for a in args if not a.startswith("--") and a.lower() not in ("apply", "all") and not a.isdigit()]
    folder = resolve_folder(" ".join(folder_args)) if folder_args else None
    found = versions.find(cfg, folder)
    if args and args[0].lower() == "apply":
        n = args[1] if len(args) > 1 else ""
        chosen = found if n == "all" else [found[int(n) - 1]] if n.isdigit() and 1 <= int(n) <= len(found) else []
        if not chosen:
            fail("Usage: desktidy versions apply <n>|all   (see: desktidy versions)")
            return
        moved = sum(len(versions.apply(f)) for f in chosen)
        ok(f"{moved} older version(s) moved into {versions.FOLDER} folders. Undo: desktidy undo <name>")
        return
    title("Old versions" + (f" in {config.short(folder)}" if folder else ""))
    if not found:
        info("No versions of the same document found.")
        return
    def changed(p: str) -> str:
        return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%d/%m/%Y %H:%M")
    for i, f in enumerate(found, 1):
        print(f"\n  {C.W}{i}){C.X} {C.BOLD}{os.path.basename(f.keep)}{C.X}  {C.GR}{config.short(f.folder)}{C.X}\n"
              f"      {C.G}stays{C.X}  {C.GR}last changed {changed(f.keep)} (the newest){C.X}")
        for o in f.older:
            print(f"      {C.Y}aside{C.X} {os.path.basename(o)}  {C.GR}last changed {changed(o)}{C.X}")
    hint(f"\n  The newest by date stays; the others go into {versions.FOLDER}. desktidy versions apply <n> | all")
    if ui.INTERACTIVE or sys.stdin.isatty():
        answer = ask("Number to tidy, 'all', or Enter = none:").lower()
        if answer == "all" or (answer.isdigit() and 1 <= int(answer) <= len(found)):
            cmd_versions(["apply", answer] + folder_args)


def cmd_installers(args):
    from .. import installers
    cfg = config.load_config()
    info("Comparing your installers with the installed programs...")
    found = installers.find(cfg)
    if not found:
        ok("No installers of programs that are already installed")
        return
    same = [c for c in found if c.same_version]
    older = [c for c in found if not c.same_version]
    title(f"Installers you may not need: {installers.human(sum(c.size for c in found))}")
    for label, group in (("Same version installed", same), ("A newer version is installed", older)):
        if not group:
            continue
        print(f"\n  {C.BOLD}{label}{C.X} {C.GR}({installers.human(sum(c.size for c in group))}){C.X}")
        for c in group:
            folder = config.short(os.path.dirname(c.path))
            print(f"   {C.CY}{installers.human(c.size):>9}{C.X}  {os.path.basename(c.path)}  {C.GR}{folder}{C.X}\n"
                  f"              {C.GR}installed: {c.installed} {c.installed_version}{C.X}")
    if not (args and args[0].lower() in ("clean", "remove", "delete")):
        hint(f"\n  Send them to the {system.TRASH}: desktidy installers clean   (you confirm each group)")
        return
    can_ask = ui.INTERACTIVE or sys.stdin.isatty()
    if not can_ask and "--yes" not in args:
        fail("Nothing recycled: confirm with  desktidy installers clean --yes  (same-version installers only)")
        return
    chosen = []
    if same and (not can_ask or confirm(f"Recycle the {len(same)} installer(s) of the same version?", True)):
        chosen += same
    if older and can_ask and confirm(f"Recycle the {len(older)} installer(s) older than the installed program?"):
        chosen += older
    files, size = installers.clean(chosen)
    ok(f"{files} installer(s) sent to the {system.TRASH}, {installers.human(size)} freed (restore them from there)")


def cmd_duplicates(args):
    """The same file in two or more of your folders: keep one, the others to the Recycle Bin."""
    from .. import duplicates, installers
    cfg = config.load_config()
    words = [a for a in args if not a.startswith("--")]
    sub = words[0].lower() if words else ""
    info("Looking for identical files in your folders (offline, nothing is changed)...")
    found = duplicates.find(cfg, lambda n: print(f"\r  {C.B}[*]{C.X} {n} files looked at ", end="", flush=True))
    print("\r" + " " * 40 + "\r", end="")
    if not found:
        ok("No duplicates: every file is there once")
        return
    wasted = sum(g.wasted for g in found)
    title(f"Duplicates: {len(found)} group(s), {installers.human(wasted)} to free")
    for i, g in enumerate(found[:30], 1):
        print(f"  {C.W}{i:>2}){C.X} {C.CY}{installers.human(g.keep.size):>9}{C.X} x{len(g.copies)}  "
              f"{C.BOLD}{os.path.basename(g.keep.path)}{C.X}\n      {C.G}keep{C.X}   {config.short(g.keep.path)}")
        for c in g.extra:
            print(f"      {C.GR}recycle {config.short(c.path)}{C.X}")
    if len(found) > 30:
        hint(f"  ... and {len(found) - 30} more group(s)")
    if sub not in ("clean", "remove", "delete"):
        hint(f"\n  Keep one copy, the others to the {system.TRASH}: desktidy duplicates clean [n]   (after a preview)")
        return
    n = words[1] if len(words) > 1 else ""
    if n and not (n.isdigit() and 1 <= int(n) <= len(found)):
        fail("Usage: desktidy duplicates clean [n]   (see: desktidy duplicates)")
        return
    chosen = [found[int(n) - 1]] if n else found
    copies = sum(len(g.extra) for g in chosen)
    if "--yes" not in args and not confirm(f"Send {copies} copy(ies) to the {system.TRASH} "
                                           f"({installers.human(sum(g.wasted for g in chosen))})?", False):
        hint("  Nothing was changed.")
        return
    files, size, notes = duplicates.clean(chosen)
    for note in notes:
        warn(note)
    ok(f"{files} copy(ies) sent to the {system.TRASH}, {installers.human(size)} freed (restore them from there)")


def cmd_archive(args):
    from .. import archive
    sub = args[0].lower() if args else ""
    value = args[1].lower() if len(args) > 1 else ""
    if sub in ("on", "off"):
        config.update_config(lambda d: d.setdefault("archive", {}).__setitem__("enabled", sub == "on"))
        ok("Automatic archive " + ("on: once a day" if sub == "on" else "off"))
        return
    if sub == "after" and value.isdigit():
        config.update_config(lambda d: d.setdefault("archive", {}).__setitem__("after_days", int(value)))
        ok(f"Items untouched for {value} days are archived")
        return
    if sub == "zip" and value in ("on", "off"):
        config.update_config(lambda d: d.setdefault("archive", {}).__setitem__("zip", value == "on"))
        ok("Archived items are " + ("compressed into .zip" if value == "on" else "moved as they are"))
        return
    cfg = config.load_config()
    s = archive.settings(cfg)
    items = archive.candidates(cfg)
    title("Archive")
    row("Automatic", (f"{C.G}on{C.X}" if s["enabled"] else f"{C.Y}off{C.X} (desktidy archive on)")
        + f" · after {s['after_days']} days · {'zip' if s['zip'] else 'as they are'}")
    row("Archive folder", config.short(cfg.expand(s["folder"])))
    row("Looks in", ", ".join(config.short(cfg.expand(x)) for x in s["sources"] if x))
    if not items:
        ok("Nothing to archive right now")
        return
    print(f"\n  {C.BOLD}{len(items)} item(s) untouched for {s['after_days']}+ days:{C.X}")
    for path, is_dir, latest in items[:15]:
        suffix = os.sep if is_dir else ""
        print(f"   {C.GR}{datetime.fromtimestamp(latest):%d/%m/%Y}{C.X}  {os.path.basename(path)}{suffix}")
    if sub == "now" or ((ui.INTERACTIVE or sys.stdin.isatty()) and confirm("Archive them now?")):
        done = 0
        for path, is_dir, latest in items:
            try:
                archive.archive_one(path, is_dir, latest, cfg)
                done += 1
            except OSError as ex:
                fail(f"{os.path.basename(path)}: {ex}")
        ok(f"{done} item(s) archived. Undo any of them: desktidy undo <name>")


def cmd_import(args):
    from .. import importer
    sub = args[0].lower() if args else ""
    if sub == "auto" and len(args) > 1 and args[1].lower() in ("on", "off"):
        config.update_config(lambda d: d.setdefault("import", {}).__setitem__("auto", args[1].lower() == "on"))
        ok("Photos are imported " + ("without asking" if args[1].lower() == "on" else "after you confirm"))
        return
    cfg = config.load_config()
    wanted = args[1] if sub == "--card" and len(args) > 1 else ""
    if system.WINDOWS and re.fullmatch(r"[a-z]:?\\?", sub):
        root = sub[0].upper() + ":\\"
        label = root
    elif sub and not wanted and os.path.isdir(os.path.expanduser(unquote(" ".join(args)))):
        root = os.path.abspath(os.path.expanduser(unquote(" ".join(args))))
        label = os.path.basename(root) or root
    else:
        cards = [c for c in importer.cards(cfg) if not wanted or c["serial"] == wanted]
        if not cards:
            info("No memory card or USB stick with a DCIM folder is plugged in.")
            hint(f"  Phones connected by cable are not a drive: copy from them with {system.FILE_MANAGER} or the "
                 "phone's app.")
            return
        card = cards[0]
        name = card["label"] or "card"
        root, label = card["root"], name if name == card["name"] else f"{name} ({card['name']})"
    info(f"Reading the photos on {label}...")
    new = importer.new_media(root, cfg)
    if not new:
        ok("Nothing new to import")
        return
    size = sum(m.size for m in new)
    first, last = new[0].taken, new[-1].taken
    title(f"{len(new)} new photos/videos on {label}")
    row("Taken", f"{first:%d %b %Y} - {last:%d %b %Y}")
    row("Size", f"{size / 1e9:.2f} GB" if size > 1e9 else f"{size / 1e6:.0f} MB")
    row("Into", f"{config.short(importer.target_for(new[0], cfg))} ...")
    if not ui.GUI and not confirm("Import them now? (they are copied: the card is not changed)", True):
        return
    if ui.GUI:
        system.notify(f"{APP_NAME}: importing {len(new)} photos/videos", f"From {label}. You can keep working.")
    s = importer.run(root, cfg, progress=None if ui.GUI else lambda n, m: print(f"\r  {C.GR}{n}/{len(new)}{C.X}", end=""))
    print("\r", end="")
    text = f"{s['copied']} imported, {s['skipped']} already there" + (f", {s['failed']} failed" if s["failed"] else "")
    ok(text)
    for f in s["folders"][:5]:
        print(f"   {C.GR}{config.short(f)}{C.X}")
    if ui.GUI:
        system.notify(f"{APP_NAME}: photos imported", text)


def cmd_learn(args):
    from .. import learn
    sub = args[0].lower() if args else ""
    if sub in ("accept", "add", "yes", "reject", "no") and len(args) > 1 and args[1].isdigit():
        p = (learn.accept if sub in ("accept", "add", "yes") else learn.reject)(int(args[1]))
        if not p:
            fail("No such proposal (see: desktidy learn)")
        elif sub in ("accept", "add", "yes"):
            ok(f"Rule added at the top of your rules: {C.BOLD}{p['rule']['name']}{C.X} -> {p['rule']['destination']}")
        else:
            ok("It won't be proposed again")
        return
    if sub in ("scan", "now"):
        info("Looking for files you moved yourself...")
        new = learn.scan(config.load_config())
        ok(f"{len(new)} new proposal(s)")
    d = learn.load()
    title("Learned from your corrections and from the AI")
    if d["corrections"]:
        print(f"  {C.GR}Latest corrections:{C.X}")
        for c in d["corrections"][-6:][::-1]:
            print(f"   {C.GR}{c['at'][:10]}{C.X}  {c['file']}  {C.GR}{os.path.basename(c['chosen'])}{C.X} -> "
                  f"{C.G}{os.path.basename(c['user'])}{C.X}")
    else:
        info("No corrections yet: when you move a file DeskTidy placed, it notices (every 30 minutes).")
    if not d["proposals"]:
        return
    print(f"\n  {C.BOLD}Proposed rules{C.X}")
    for i, p in enumerate(d["proposals"], 1):
        r = p["rule"]
        what = ", ".join(r.get("name_words", []) + r.get("topics", []))
        source = f"the AI placed {p.get('count', len(p['examples']))} like these there" if p.get("source") == "ai" \
            else "your corrections"
        private = f" {C.Y}(private){C.X}" if r.get("private") else ""
        print(f"   {C.W}{i}){C.X} files about {C.CY}{what}{C.X} -> {C.G}{r['destination']}{C.X}{private}\n"
              f"      {C.GR}from {source}: {', '.join(p['examples'][:3])}{C.X}")
    hint("\n  desktidy learn accept <n> · learn reject <n>   (a rule from the AI places the next ones offline: less AI)")
    n = _pick("Number to accept (Enter = later):", len(d["proposals"]))
    if n:
        cmd_learn(["accept", str(n)])
