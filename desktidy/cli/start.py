"""Start here: the house rules and the first-run setup (pinned folders, daily limit, rules only or always AI)."""

from __future__ import annotations

import os
import sys
from datetime import datetime

from .. import config, folders, system
from . import ui
from .ai_cmds import choose_provider, cmd_ai, provider_table
from .service_cmds import cmd_limit
from .ui import C, ask, confirm, hint, info, ok, resolve_folder, running, title, unquote, warn

# ================================================================ commands: start here
HOUSE_RULES = [
    ("A name starting with ! is never touched.",
     '"!draft.docx" or a folder called "!work in progress" stays where it is. Remove the ! to let DeskTidy handle it.'),
    ("Pin at least 2 folders before it starts.",
     "Pinned folders are the places you want things to go (e.g. Study, Work, Recipes). Until enough are pinned,\n"
     "      DeskTidy only watches. Pin with: desktidy pin <folder>, or answer Yes to \"Pin it?\"."),
    ("It waits before acting.",
     "Downloads after 2 minutes, Desktop and Documents after 10. Open files, unfinished downloads,\n"
     "      Office lock files, hidden and system files are skipped."),
    ("Nothing is lost.",
     "Every move and rename is logged (desktidy where) and can be undone (desktidy undo).\n"
     f"      Identical duplicates go to the {system.TRASH}, never deleted."),
    ("Private stays private, unless you choose otherwise.",
     "IDs, payslips, bills and CVs go to the AI only if you choose \"Always AI\" (desktidy ai all); with\n"
     "      Ollama the AI runs on this PC. Photos and screenshots never. The AI is optional, with a daily limit."),
    ("You're in charge.", "desktidy pause 1h · desktidy stop · desktidy preview (see what it would do)."),
]


def cmd_guide(args):
    title("House rules")
    for i, (head, text) in enumerate(HOUSE_RULES, 1):
        print(f"   {C.W}{i}.{C.X} {C.BOLD}{C.G}{head}{C.X}\n      {C.GR}{text}{C.X}")


def cmd_setup(args):
    """First-run setup: accept the house rules, pin enough folders, choose the rules alone or always the AI."""
    cfg = config.load_config()
    needed = config.pinned_minimum(cfg)
    title("Setup")
    cmd_guide([])
    print()
    accepted = (config.read_json(config.path("setup"), {}) or {}).get("rules_accepted")
    if not accepted:
        if "--accept" not in args and not confirm("Have you read the house rules? Accept them and continue?", True):
            warn("Setup paused: DeskTidy only watches until you accept them (desktidy setup)")
            return
        config.write_json(config.path("setup"), {"rules_accepted": datetime.now().isoformat(timespec="seconds")})
        ok("House rules accepted")
    while len(folders.active_pinned()) < needed:
        have = len(folders.active_pinned())
        print()
        info(f"Pinned folders: {C.BOLD}{have}/{needed}{C.X}. Pin the places where files should end up "
             "(e.g. Study, Work, Recipes).")
        new = folders.suggestions(cfg, include_seen=True, wait=False)
        for i, p in enumerate(new[:9], 1):
            print(f"   {C.W}{i}){C.X} {os.path.basename(p)}  {C.GR}{config.short(p)}{C.X}")
        if not (ui.INTERACTIVE or sys.stdin.isatty()):
            hint("  Pin them with: desktidy pin <folder>   (a name creates it on the Desktop)")
            return
        answer = unquote(ask(("Number above, " if new else "") + "a name to create on the Desktop, or a full path "
                             "(Enter = later):"))
        if not answer:
            warn(f"Setup paused at {have}/{needed}: DeskTidy only watches until it is finished (desktidy setup)")
            return
        target = new[int(answer) - 1] if answer.isdigit() and 1 <= int(answer) <= len(new[:9]) else resolve_folder(answer)
        words = ask(f"Extra words about '{os.path.basename(target)}', comma separated (Enter = none):")
        os.makedirs(target, exist_ok=True)
        folders.pin(target, [w.strip() for w in words.split(",") if w.strip()])
        ok(f"Pinned {C.BOLD}{os.path.basename(target)}{C.X}  {C.GR}{config.short(target)}{C.X}")
    ok(f"{C.BOLD}Setup complete{C.X}: DeskTidy starts tidying at its next pass (within 30 seconds)")
    can_ask = (ui.INTERACTIVE or sys.stdin.isatty()) and "--accept" not in args
    if can_ask and "limits" not in cfg:
        answer = ask("At most how many files a day should DeskTidy tidy? (a number, Enter = unlimited):")
        cmd_limit([answer or "unlimited"])
    if can_ask:
        choose_engine(cfg)
    if not running():
        hint(f"  The service is not running: {C.W}desktidy start{C.X}")


def choose_engine(cfg) -> None:
    """The big choice of the setup: the rules alone (offline) or always the AI."""
    title("How should DeskTidy understand your files?")
    print(f"   {C.W}1){C.X} {C.BOLD}Rules only{C.X}  offline: nothing leaves this PC, free. Clear names and known kinds\n"
          "      are placed well; scans and bills get plainer names.")
    print(f"   {C.W}2){C.X} {C.BOLD}Always AI{C.X}   the AI reads every file, bills and private documents too, and names\n"
          "      them well (Fattura_2231_Acme_Srl_2026-10-12). Free services available; with Ollama it runs on this PC.")
    hint("   Change it any time: desktidy ai rules · desktidy ai all  (in between: desktidy ai)")
    answer = ask("1 or 2 (Enter = keep the current setting):").lower()
    if answer in ("1", "rules", "regole"):
        cmd_ai(["off"])
    elif answer in ("2", "ai", "all"):
        title("Choose the AI service")
        ids = provider_table(cfg)
        choice = ask("Number or name (Enter = groq, free):").lower() or "groq"
        pid = ids[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(ids) else choice
        was, ui.INTERACTIVE = ui.INTERACTIVE, True  # so choose_provider offers to paste the key
        try:
            choose_provider(pid)
        finally:
            ui.INTERACTIVE = was
        cmd_ai(["all"])
