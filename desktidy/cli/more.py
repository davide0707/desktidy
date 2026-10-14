# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""More: the settings editor, the right-click menu, updates, the log, rules.json, install and uninstall, about."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from .. import APP_NAME, REPO_URL, __author__, __license__, __version__, config, folders, system
from ..explorer import console_command, service_command
from ..service import move_id, read_moves
from . import ui
from .files import cmd_undo
from .start import cmd_setup
from .tidyup import cmd_import
from .ui import (
    C,
    _notify_result,
    banner,
    confirm,
    fail,
    hint,
    info,
    ok,
    row,
    running,
    start_service,
    stop_service,
    title,
    wait_for,
    warn,
)

MENU_WHERE = ("Windows 11: under 'Show more options'" if system.WINDOWS else
              "Files: Scripts > DeskTidy · Nemo and Dolphin: DeskTidy")


def cmd_explorer(args):
    from .. import explorer
    sub = args[0].lower() if args else ""
    if not explorer.AVAILABLE:
        info("There is no Finder menu yet: use  desktidy explain <file>  (you can drag the file into the window)")
        return
    if sub in ("on", "install"):
        explorer.install()
        ok(f"Right-click menu 'DeskTidy' added ({MENU_WHERE})" + (", notification buttons on" if system.WINDOWS else ""))
    elif sub in ("off", "remove", "uninstall"):
        ok("Removed" if explorer.uninstall() else "It was not installed")
    else:
        info(f"Right-click menu in {system.FILE_MANAGER}: "
             + (f"{C.G}on{C.X}" if explorer.installed() else f"{C.Y}off{C.X}"))
        hint("  desktidy explorer on | off")


def cmd_editor(args):
    from .. import editor
    info("Opening the settings in your browser (only this computer can reach it). Ctrl+C or 'Close editor' to finish.")
    editor.serve(open_browser="--no-browser" not in args, say=lambda m: hint("  " + m))
    ok("Editor closed")


def cmd_update(args):
    from .. import updates
    info(f"Checking GitHub for a new version (you have {__version__})...")
    release = updates.latest()
    if release is None:
        warn("Could not reach GitHub, or no release published yet")
        return
    if not updates.newer(release["version"]):
        ok(f"You have the latest version ({__version__})")
        return
    title(f"DeskTidy {release['version']} is available")
    for line in release["notes"].splitlines()[:25]:
        print(f"  {C.GR}{line}{C.X}")
    kind, commands = updates.install_kind()
    if not commands:  # the Windows build: a new zip, then desktidy.exe install (it replaces the old version)
        info(f"Download DeskTidy {release['version']} from {release['url']}, extract it and run desktidy.exe install")
        if (ui.INTERACTIVE or sys.stdin.isatty()) and confirm("Open the download page?", True):
            system.open_path(release["url"])
        return
    hint(f"\n  Installed with {kind}: " + "  &&  ".join(" ".join(c) for c in commands))
    if (ui.INTERACTIVE or sys.stdin.isatty()) and confirm("Update now?", True):
        was_running = running()
        if was_running:
            stop_service()
        if updates.run_update(lambda m: hint("  " + m)):
            ok(f"Updated. Open a new {system.TERMINAL} window to use the new version")
        else:
            fail(f"The update failed: see above, or download it from {release['url']}")
        if was_running:
            start_service()


def cmd_url(args):
    """desktidy: links (notification buttons, right-click menu). Only a fixed list of actions with checked ids."""
    from .. import deadlines, explorer
    parsed = explorer.parse_url(args[0] if args else "")
    if not parsed:
        fail("Unknown DeskTidy link")
        return
    action, p = parsed
    if action in explorer.CONSOLE_ACTIONS:
        explorer.open_console(*([] if action == "console" else [action]))
    elif action == "undo":
        cmd_undo([p.get("ids", "").replace(",", " ")])
    elif action == "open":
        from ..ops import current_path
        m = next((m for m in read_moves() if move_id(m) == p.get("id")), None)
        if m:
            system.reveal(current_path(m["destination"]))
    elif action in ("deadline-done", "deadline-open"):
        item = deadlines.find(p.get("id", ""))
        if not item:
            return
        if action == "deadline-done":
            deadlines.update(item["id"], done=True)
            _notify_result(APP_NAME, f"Done: {item['what']}. No more reminders.")
        elif item.get("path") and os.path.exists(item["path"]):
            system.open_path(item["path"])
        else:
            explorer.open_console("deadlines")
    elif action == "import":
        cmd_import(["--card", p["card"]] if p.get("card") else [p.get("drive", "") + ":"])


def cmd_terminal(args):
    """A DeskTidy command in a new terminal window (Linux file manager menus)."""
    from .. import explorer
    if args:
        explorer.open_console(*args)


# ================================================================ commands: more
def cmd_log(args):
    if "open" in args:
        system.open_path(config.path("log"))
        return
    n = next((int(a) for a in args if a.isdigit()), 25)
    errors_only = "errors" in args
    try:
        with open(config.path("log"), encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        info("No log yet")
        return
    if errors_only:
        problem = re.compile(r"ERROR|AI paused|AI unavailable|AI: (?:error|API key|access denied|credit|no "
                             r"(?:connection|API key|usable)|rate limited)")
        lines = [ln for ln in lines if problem.search(ln)]
    title("Recent problems" if errors_only else f"Last {n} log lines")
    for ln in lines[-n:]:
        color = (C.R if "ERROR" in ln else C.G if "MOVED" in ln else C.Y if "DUPLICATE" in ln or "PINNED" in ln
                 else C.CY if " AI" in ln else C.GR)
        print(f"  {color}{ln}{C.X}")
    if errors_only and not lines:
        ok("No problems")


def cmd_rules(args):
    if args and args[0].lower() in ("check", "test"):
        try:
            cfg = config.load_config()
        except ValueError as ex:
            fail(f"rules.json is not valid JSON: {ex}")
            return
        from .. import editor
        errors, warnings = editor.validate(dict(cfg))  # the same checks as saving in the editor
        for e in errors:
            fail(e)
        for w in warnings:
            warn(w)
        if not errors:
            ok(f"rules.json is valid: {len(cfg['rules'])} rules, {len(cfg['watched_folders'])} watched folders")
        return
    config.load_config()  # creates rules.json on the first run
    info(f"Opening {config.path('rules')}. Changes apply at the next pass; then: {C.W}desktidy rules check{C.X}")
    system.edit_file(config.path("rules"))


def cmd_open(args):
    system.open_path(str(config.data_dir()))


def install_program() -> str | None:
    """The Windows build, run from wherever the zip was extracted: copy it to its own folder (replacing an older
    version) and return the desktidy.exe to run there; None when it already runs from there."""
    here, target = os.path.dirname(sys.executable), system.program_home()
    if os.path.normcase(os.path.abspath(here)) == os.path.normcase(os.path.abspath(target)):
        return None
    if running():
        stop_service()
    info(f"Copying DeskTidy to {target}...")
    fresh, old = target + ".new", target + ".old"
    for leftover in (fresh, old):
        shutil.rmtree(leftover, ignore_errors=True)
    shutil.copytree(here, fresh)
    if os.path.exists(target):
        os.replace(target, old)  # fails if a file of the old version is still open: nothing is lost then
    os.replace(fresh, target)
    shutil.rmtree(old, ignore_errors=True)
    return os.path.join(target, "desktidy.exe")


def cmd_install(args):
    title("Install")
    if system.FROZEN:
        try:
            exe = install_program()
        except OSError as ex:
            fail(f"Could not copy the program: {ex}. Close DeskTidy (desktidy stop) and try again")
            return 1
        if exe:  # the copy registers itself: autostart, command and menu point to the installed program
            return subprocess.run([exe, "install", *args]).returncode
    if system.install_command(console_command()):
        ok(f"'desktidy' command added: it works in NEW {system.TERMINAL} windows")
    else:
        info("The 'desktidy' command is already available")
    config.load_config()
    ok(f"Settings: {config.path('rules')}")
    from .. import explorer
    if explorer.AVAILABLE:
        try:
            explorer.install()
            ok(f"Right-click menu in {system.FILE_MANAGER} (DeskTidy: {MENU_WHERE})"
               + (" and the buttons of the notifications" if system.WINDOWS else ""))
        except OSError as ex:
            warn(f"Right-click menu not installed ({ex}): desktidy explorer on")
    if system.autostart_install(service_command(), str(config.data_dir()), start_now=not running()):
        ok(f"Starts at every sign-in ({system.AUTOSTART})")
    else:
        fail("Could not register the start at sign-in")
    if not running() and not wait_for(running, 60, "starting"):
        warn("The service did not start yet: desktidy status")
    if folders.setup_missing(config.load_config()) and sys.stdin.isatty():
        cmd_setup([])
    else:
        info(f"Optional AI: {C.W}desktidy ai provider{C.X} (free options included); without it DeskTidy works offline")


def cmd_uninstall(args):
    title("Uninstall")
    info("Removes autostart and the command. Your files, rules and logs stay where they are.")
    if (ui.INTERACTIVE or sys.stdin.isatty()) and not confirm("Continue?"):
        return
    if running():
        (ok if stop_service() else fail)("Service stopped")
    if system.autostart_info().get("exists"):
        (ok if system.autostart_remove() else fail)("Start at sign-in removed")
    if system.uninstall_command():
        ok("'desktidy' command removed")
    from .. import explorer
    if explorer.uninstall():
        ok("Right-click menu" + (" and desktidy: links" if system.WINDOWS else "") + " removed")
    program = os.path.dirname(sys.executable)
    if system.FROZEN and os.path.normcase(program) == os.path.normcase(system.program_home()) and all(
            os.path.exists(os.path.join(program, x)) for x in ("desktidy.exe", "desktidyw.exe", "_internal")):
        # the program can't delete itself while it runs: a hidden command does it a few seconds after it exits
        subprocess.Popen(["cmd", "/c", f'timeout /t 3 /nobreak >nul & rmdir /s /q "{program}"'],
                         cwd=os.path.dirname(program), **system.detached())
        ok(f"The program folder is removed in a few seconds ({program})")
        info(f"To delete your settings and logs too: remove {config.data_dir()}")
    else:
        info(f"To delete everything: remove {config.data_dir()} and the program folder")


def cmd_about(args):
    banner()
    print()
    row("Version", __version__)
    row("Author", __author__)
    row("Project", REPO_URL)
    row("License", f"{__license__}: free software, with NO WARRANTY (see LICENSE)")
    row("Program", os.path.dirname(sys.executable) + " (Windows build)" if system.FROZEN else
        str(config.PACKAGE_DIR.parent))
    row("Data", str(config.data_dir()))
    row("System", f"{system.NAME} ({sys.platform})")
    row("Python", sys.version.split()[0])
