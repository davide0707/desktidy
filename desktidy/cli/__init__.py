# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""DeskTidy command line: an interactive console (menu) and one-shot commands.

  desktidy                 open the console
  desktidy <command> ...   run one command:  desktidy status · desktidy pause 30m · desktidy where invoice
  desktidy help            list every command

Here: the list of commands, the console, the dispatch and the entry points. The commands themselves are in
start, service_cmds, files, tidyup, ai_cmds and more; what they share (colors, questions, INTERACTIVE) in ui.
"""

from __future__ import annotations

import io
import re
import shlex
import subprocess
import sys
from contextlib import redirect_stdout

from .. import APP_NAME, __version__, config, folders, system
from . import ui
from .ai_cmds import (
    AI_ALIASES,
    _test_key,
    ai_test,
    apply_tip,
    choose_provider,
    cmd_advice,
    cmd_ai,
    cmd_key,
    cmd_spend,
    confirm_everything,
    print_tips,
    provider_table,
)
from .files import (
    UNDOABLE,
    _norm,
    cmd_explain,
    cmd_find,
    cmd_handsoff,
    cmd_pin_toggle,
    cmd_pinned,
    cmd_preview,
    cmd_rename,
    cmd_tidy,
    cmd_undo,
    cmd_where,
    find_moves,
    pin_folder,
    print_move,
    suggest,
    undo_ids,
    undo_move,
    unpin_folder,
)
from .more import (
    MENU_WHERE,
    cmd_about,
    cmd_editor,
    cmd_explorer,
    cmd_install,
    cmd_log,
    cmd_open,
    cmd_rules,
    cmd_terminal,
    cmd_uninstall,
    cmd_update,
    cmd_url,
    install_program,
)
from .service_cmds import (
    cmd_autostart,
    cmd_limit,
    cmd_pause,
    cmd_restart,
    cmd_resume,
    cmd_start,
    cmd_status,
    cmd_stop,
    cmd_week,
    parse_duration,
)
from .start import HOUSE_RULES, choose_engine, cmd_guide, cmd_setup
from .tidyup import (
    ORGANIZE_PLACES,
    _parse_date,
    cmd_archive,
    cmd_deadlines,
    cmd_duplicates,
    cmd_groups,
    cmd_import,
    cmd_installers,
    cmd_learn,
    cmd_organize,
    cmd_versions,
    organize_apply,
    organize_name,
    plan_organize,
    print_organize,
)
from .ui import (
    _LETTERS,
    LOGO,
    C,
    _notify_result,
    _pick,
    ago,
    ask,
    banner,
    bar,
    confirm,
    enable_colors,
    fail,
    hint,
    info,
    ok,
    prompt,
    resolve_folder,
    row,
    running,
    start_service,
    stop_service,
    summary_line,
    title,
    unquote,
    usd,
    wait_for,
    warn,
)

# ================================================================ dispatch
COMMANDS = [  # (number, name, function, description, aliases, section)
    (1, "setup", cmd_setup, "first-run setup: house rules, pinned folders, rules only or always AI", ["init"],
     "Start here"),
    (2, "guide", cmd_guide, "the house rules ('!' = hands off, pinned folders, undo...)", ["house-rules"], "Start here"),
    (3, "status", cmd_status, "service, limits, AI, deadlines and latest moves", ["s", "st"], "Service"),
    (4, "week", cmd_week, "your week: files tidied, duplicates, deadlines, AI  (week off)",
     ["settimana", "summary", "riepilogo"], "Service"),
    (5, "pause", cmd_pause, "pause  (pause 30m · pause 2h · pause 18:30)", [], "Service"),
    (6, "resume", cmd_resume, "end the pause", ["unpause"], "Service"),
    (7, "start", cmd_start, "start the service", ["run"], "Service"),
    (8, "stop", cmd_stop, "stop now, starts again at sign-in  (stop forever)", [], "Service"),
    (9, "restart", cmd_restart, "stop and start", [], "Service"),
    (10, "autostart", cmd_autostart, "start at sign-in  (on · off)", ["boot"], "Service"),
    (11, "limit", cmd_limit, "files tidied per day at most  (limit 30 · limit unlimited)", ["limits", "max"], "Service"),
    (12, "where", cmd_where, "where did my files go  (where invoice · where --all)", ["w"], "Files"),
    (13, "undo", cmd_undo, "put a file back where it was, with its old name", ["restore"], "Files"),
    (14, "find", cmd_find, "search by content  (find electricity bill september)", ["search", "cerca"], "Files"),
    (15, "pinned", cmd_pinned, "pinned folders  (pin recipes cooking · unpin 1)", ["pins"], "Files"),
    (16, "explain", cmd_explain, "what DeskTidy understands of a file  (explain x.pdf)", ["why", "analyze"], "Files"),
    (17, "preview", cmd_preview, "what it would do now, moving nothing  (preview --now)", ["dry-run"], "Files"),
    (18, "rename", cmd_rename, "smart renaming  (smart · generic · off)", [], "Files"),
    (19, "tidy", cmd_tidy, "tidy one file now  (tidy x.pdf, also from the right-click menu)", ["now"], "Files"),
    (20, "deadlines", cmd_deadlines, "bills and deadlines found in your documents  (deadlines done 1)",
     ["scadenze", "due"], "Tidy up"),
    (21, "groups", cmd_groups, "the to-sort pile, grouped into folders  (groups apply 1 --pin)", ["pile"], "Tidy up"),
    (22, "organize", cmd_organize, "loose files grouped into folders, by the AI or offline  (organize desktop)",
     ["organise", "riordina", "sort"], "Tidy up"),
    (23, "versions", cmd_versions, "old versions of the same document  (versions apply all)", ["versioni"], "Tidy up"),
    (24, "installers", cmd_installers, "setup files of programs already installed  (installers clean)",
     ["installer"], "Tidy up"),
    (25, "duplicates", cmd_duplicates, "the same file in two places: keep one  (duplicates clean)",
     ["doppioni", "dupes", "dup"], "Tidy up"),
    (26, "archive", cmd_archive, "archive what is untouched for months  (archive on · archive now)", ["archivio"],
     "Tidy up"),
    (27, "import", cmd_import, "photos from a memory card, sorted by date  (import E:)", ["photos"], "Tidy up"),
    (28, "learn", cmd_learn, "rules learned from your corrections  (learn accept 1)", ["learned"], "Tidy up"),
    (29, "ai", cmd_ai, "how much AI: off (rules only) · limited · moderate · ai-only · all (always AI)", ["mode"], "AI"),
    (30, "key", cmd_key, "API key of the chosen AI service  (key test · key remove)", ["apikey"], "AI"),
    (31, "spend", cmd_spend, "AI spend and balance  (spend credit 4.85 · spend web)", ["cost", "balance", "usage"], "AI"),
    (32, "advice", cmd_advice, "ideas to organise files and folders  (advice new · advice apply 2)", ["tips", "consigli"],
     "AI"),
    (33, "editor", cmd_editor, "all the settings in your browser", ["ui", "gui", "settings-ui"], "More"),
    (34, "explorer", cmd_explorer, "right-click menu and notification buttons  (on · off)", ["context-menu"], "More"),
    (35, "update", cmd_update, "check for a new version and update", ["upgrade"], "More"),
    (36, "log", cmd_log, "activity log  (log errors · log 100)", ["errors"], "More"),
    (37, "rules", cmd_rules, "edit rules.json  (rules check)", ["config", "settings"], "More"),
    (38, "open", cmd_open, "open the data folder", ["data"], "More"),
    (39, "install", cmd_install, "command, start at sign-in, right-click menu", [], "More"),
    (40, "uninstall", cmd_uninstall, "remove the start at sign-in, the command and the menu", [], "More"),
    (41, "about", cmd_about, "version and author", ["version", "info"], "More"),
]


HIDDEN = {"handsoff": cmd_handsoff, "pin-toggle": cmd_pin_toggle, "url": cmd_url,  # right-click menu and links
          "terminal": cmd_terminal}


def find_command(name: str):
    name = name.lower()
    if name == "pin":
        return lambda a: pin_folder(a) if a or ui.INTERACTIVE else cmd_pinned([])
    if name == "unpin":
        return unpin_folder
    if name == "errors":
        return lambda a: cmd_log(["errors", *a])
    if name in ("provider", "providers"):
        return lambda a: cmd_ai(["provider", *a])
    if name in HIDDEN:
        return HIDDEN[name]
    for number, cmd, func, _, aliases, _ in COMMANDS:
        if name in (str(number), cmd) or name in aliases:
            return func
    return None


def menu() -> None:
    section = None
    for number, name, _, text, _, sec in COMMANDS:
        if sec != section:
            section = sec
            print(f"\n  {C.R}{C.BOLD}{sec}{C.X} {C.GR}{'─' * (56 - len(sec))}{C.X}")
        print(f"   {C.W}{number:>2}){C.X} {C.G}{name:<11}{C.X}{text}")
    print(f"\n   {C.W}99){C.X} {C.G}{'exit':<11}{C.X}{C.GR}close the console{C.X}")


def cmd_help(args):
    title("Commands")
    print(f"  In the console type the {C.W}number{C.X} or the {C.W}name{C.X}; from a {system.TERMINAL}: "
          f"{C.W}desktidy <command>{C.X}")
    menu()
    print(f"""
  {C.BOLD}Examples{C.X}
    desktidy status                 desktidy where invoice
    desktidy pause 2h               desktidy undo invoice
    desktidy stop                   desktidy ai moderate
    desktidy autostart off          desktidy spend credit 4.85
    desktidy pin pasta recipes      desktidy explain {EXAMPLE}
    desktidy ai all                 desktidy advice new
    desktidy find bolletta luce     desktidy deadlines
    desktidy limit 30               desktidy ai max unlimited
    desktidy installers             desktidy editor

  {C.BOLD}Good to know{C.X}
    {C.GR}- Files and folders whose name starts with ! are never touched ("!draft.docx").
    - Photos and screenshots never go to the AI; private documents only with: desktidy ai all.
    - Every move and rename is logged: desktidy where · desktidy undo.{C.X}""")


EXAMPLE = (r'"C:\Users\me\Downloads\scan0001.pdf"' if system.WINDOWS else
           "~/Downloads/scan0001.pdf")


def split_line(line: str) -> list[str]:
    r"""Like the command line of this system: spaces separate, quotes keep together; on macOS and Linux a
    backslash escapes a space too (paths dragged into Terminal: My\ File.pdf)."""
    if not system.WINDOWS:
        try:
            return shlex.split(line)
        except ValueError:
            pass
    return [a.strip('"') for a in re.findall(r'"[^"]*"|\S+', line)]


def run(argv: list[str]) -> int:
    if "--pause" in argv:  # started in its own window (right-click menu, notification): keep it open at the end
        try:
            return run([a for a in argv if a != "--pause"])
        finally:
            try:
                input(f"\n  {C.GR}Press Enter to close{C.X} ")
            except (EOFError, KeyboardInterrupt):
                pass
    if not argv:
        return console()
    name, args = argv[0], argv[1:]
    if name.lower() in ("help", "-h", "--help", "/?", "?", "menu"):
        cmd_help(args)
        return 0
    if name.lower() in ("--version", "-v"):
        print(f"{APP_NAME} {__version__}")
        return 0
    func = find_command(name)
    if not func:
        fail(f"Unknown command: {name}.  Type  desktidy help  for the list")
        return 1
    try:
        result = func(args)
    except KeyboardInterrupt:
        print()
        return 130
    return result if isinstance(result, int) and not isinstance(result, bool) else 0


def console() -> int:
    ui.INTERACTIVE = True
    system.clear_screen()
    banner()
    menu()
    hint("\n  Type a number or a command (options too: 'pause 30m'). 'menu' shows this list again, '99' exits.")
    try:
        missing = folders.setup_missing(config.load_config())
    except Exception:
        missing = None
    if missing:
        print()
        warn(f"Setup not finished ({missing}): DeskTidy is only watching, nothing is moved yet.")
        if confirm("Run the setup now?", default_yes=True):
            cmd_setup([])
    while True:
        try:
            line = prompt().strip()
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print()
            return 0
        parts = split_line(line)
        if parts and parts[0].lower() == "desktidy":  # on-screen hints say "desktidy <command>"
            parts = parts[1:]
        if not parts:
            continue
        name = parts[0].lower()
        if name in ("99", "exit", "quit", "q"):
            hint("Bye!")
            return 0
        if name in ("menu", "m"):
            menu()
            continue
        if name in ("cls", "clear"):
            system.clear_screen()
            banner()
            continue
        if name in ("help", "?", "h"):
            cmd_help([])
            continue
        func = find_command(name)
        if not func:
            fail(f"Unknown command: {parts[0]}  (type 'menu' or 'help')")
            continue
        try:
            func(parts[1:])
        except KeyboardInterrupt:
            print()
            warn("interrupted")
        except Exception as ex:
            fail(f"{type(ex).__name__}: {ex}")


def main_gui() -> None:
    """desktidyw: commands from the right-click menu, the notification buttons and the tray, without a console.
    Nobody can type an answer, so nothing is asked; problems are shown in a message box."""
    ui.GUI = True
    sys.stdin = io.StringIO("")
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            run(sys.argv[1:])
    except Exception as ex:
        system.message(f"{type(ex).__name__}: {ex}", APP_NAME, error=True)
        return
    problems = [line.strip()[4:] for line in buffer.getvalue().splitlines() if line.strip().startswith("[-]")]
    if problems:
        system.message("\n".join(problems), APP_NAME, error=True)


def main() -> None:
    if not sys.stdout.isatty():
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    enable_colors()
    sys.exit(run(sys.argv[1:]))


__all__ = [  # everything stays reachable as desktidy.cli.<name>
    "AI_ALIASES",
    "C",
    "HOUSE_RULES",
    "LOGO",
    "MENU_WHERE",
    "ORGANIZE_PLACES",
    "UNDOABLE",
    "_LETTERS",
    "_norm",
    "_notify_result",
    "_parse_date",
    "_pick",
    "_test_key",
    "ago",
    "ai_test",
    "apply_tip",
    "ask",
    "banner",
    "bar",
    "choose_engine",
    "choose_provider",
    "cmd_about",
    "cmd_advice",
    "cmd_ai",
    "cmd_archive",
    "cmd_autostart",
    "cmd_deadlines",
    "cmd_duplicates",
    "cmd_editor",
    "cmd_explain",
    "cmd_explorer",
    "cmd_find",
    "cmd_groups",
    "cmd_guide",
    "cmd_handsoff",
    "cmd_import",
    "cmd_install",
    "cmd_installers",
    "cmd_key",
    "cmd_learn",
    "cmd_limit",
    "cmd_log",
    "cmd_open",
    "cmd_organize",
    "cmd_pause",
    "cmd_pin_toggle",
    "cmd_pinned",
    "cmd_preview",
    "cmd_rename",
    "cmd_restart",
    "cmd_resume",
    "cmd_rules",
    "cmd_setup",
    "cmd_spend",
    "cmd_start",
    "cmd_status",
    "cmd_stop",
    "cmd_terminal",
    "cmd_tidy",
    "cmd_undo",
    "cmd_uninstall",
    "cmd_update",
    "cmd_url",
    "cmd_versions",
    "cmd_week",
    "cmd_where",
    "confirm",
    "confirm_everything",
    "enable_colors",
    "fail",
    "find_moves",
    "hint",
    "info",
    "install_program",
    "ok",
    "organize_apply",
    "organize_name",
    "parse_duration",
    "pin_folder",
    "plan_organize",
    "print_move",
    "print_organize",
    "print_tips",
    "prompt",
    "provider_table",
    "resolve_folder",
    "row",
    "running",
    "start_service",
    "stop_service",
    "suggest",
    "summary_line",
    "title",
    "undo_ids",
    "undo_move",
    "unpin_folder",
    "unquote",
    "usd",
    "wait_for",
    "warn",
    "config",
    "folders",
    "subprocess",
    "system",
]
