"""DeskTidy command line: an interactive console (menu) and one-shot commands.

  desktidy                 open the console
  desktidy <command> ...   run one command:  desktidy status · desktidy pause 30m · desktidy where invoice
  desktidy help            list every command
"""

from __future__ import annotations

import getpass
import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta

from . import APP_NAME, REPO_URL, __author__, __version__, config, folders, system, usage
from .explorer import console_command, service_command
from .service import move_id, paused_until, read_moves, record, tidied_today

INTERACTIVE = False  # True inside the console: commands ask for what is missing
GUI = False          # True when started without a console (right-click menu, notification buttons, tray)
UNDOABLE = ("MOVED", "ARCHIVED", "ARCHIVED_ZIP")


# ================================================================ look and feel
class C:
    R = G = Y = B = M = CY = W = GR = BOLD = X = ""


def enable_colors() -> None:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty() or not system.enable_ansi():
        return
    C.R, C.G, C.Y, C.B, C.M, C.CY = "\x1b[91m", "\x1b[92m", "\x1b[93m", "\x1b[94m", "\x1b[95m", "\x1b[96m"
    C.W, C.GR, C.BOLD, C.X = "\x1b[97m", "\x1b[90m", "\x1b[1m", "\x1b[0m"


def ok(msg: str) -> None:
    print(f"  {C.G}[+]{C.X} {msg}")


def fail(msg: str) -> None:
    print(f"  {C.R}[-]{C.X} {msg}")


def warn(msg: str) -> None:
    print(f"  {C.Y}[!]{C.X} {msg}")


def info(msg: str) -> None:
    print(f"  {C.B}[*]{C.X} {msg}")


def hint(msg: str) -> None:
    print(f"  {C.GR}{msg}{C.X}")


def row(label: str, value: str, mark: str | None = None) -> None:
    mark = mark or f"{C.B}[*]{C.X}"
    print(f"  {mark} {label} {C.GR}{'.' * max(2, 20 - len(label))}{C.X} {value}")


def title(text: str) -> None:
    print(f"\n  {C.BOLD}{C.W}{text}{C.X}\n  {C.GR}{'─' * len(text)}{C.X}")


def ask(question: str, default: str = "") -> str:
    try:
        answer = input(f"  {C.CY}[?]{C.X} {question} ").strip()
    except EOFError:
        return default
    return answer or default


def confirm(question: str, default_yes: bool = False) -> bool:
    answer = ask(f"{question} [{'Y/n' if default_yes else 'y/N'}]", "y" if default_yes else "n").lower()
    return answer in ("y", "yes", "s", "si")


def usd(x: float, digits: int = 4) -> str:
    return f"${x:,.{digits}f}"


def ago(iso: str | None) -> str:
    try:
        s = (datetime.now() - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return "?"
    if s < 90:
        return f"{int(s)}s ago"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)}h {int(s % 3600 // 60)}m ago"
    return f"{int(s // 86400)} days ago"


def unquote(s: str) -> str:
    return s.strip().strip('"').strip("'").strip()


def bar(fraction: float, width: int = 20) -> str:
    full = max(0, min(width, round(fraction * width)))
    color = C.G if fraction < 0.6 else C.Y if fraction < 0.9 else C.R
    return f"{color}{'█' * full}{C.GR}{'░' * (width - full)}{C.X}"


_LETTERS = {
    "D": ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "S": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "K": ["██╗  ██╗", "██║ ██╔╝", "█████╔╝ ", "██╔═██╗ ", "██║  ██╗", "╚═╝  ╚═╝"],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "I": ["██╗", "██║", "██║", "██║", "██║", "╚═╝"],
    "Y": ["██╗   ██╗", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚██╔╝  ", "   ██║   ", "   ╚═╝   "],
}
LOGO = ["".join(_LETTERS[ch][i] for ch in "DESKTIDY") for i in range(6)]


def banner() -> None:
    print()
    for color, line in zip([C.CY, C.CY, C.B, C.B, C.M, C.M], LOGO):
        print(f" {C.BOLD}{color}{line}{C.X}")
    print(f" {C.GR}{'─' * 64}{C.X}")
    print(f"   {C.BOLD}{C.W}{APP_NAME}{C.X} {C.GR}v{__version__}{C.X}  {C.GR}::{C.X}  your files, sorted while you work")
    print(f"   {C.GR}by{C.X} {C.G}{__author__}{C.X}  {C.GR}·  {REPO_URL.replace('https://', '')}{C.X}")
    print(f" {C.GR}{'─' * 64}{C.X}")
    print("   " + summary_line())


def summary_line() -> str:
    running = system.instance_running(config.SERVICE_MUTEX)
    paused, until = paused_until()
    if running and paused:
        state = f"{C.Y}● PAUSED{C.X}" + (f" until {until:%H:%M}" if until else "")
    elif running:
        state = f"{C.G}● RUNNING{C.X}"
    else:
        state = f"{C.R}● STOPPED{C.X}"
    from . import providers
    try:
        cfg = config.load_config()
        mode, p = config.ai_mode(cfg), providers.current(cfg)
        service = f" {C.GR}({p.id}){C.X}"
        key = f" {C.Y}(no key){C.X}" if mode != "off" and p.key_env and not system.api_key(p.key_env) else ""
    except Exception:
        mode, service, key = "?", "", ""
    return (f"{state}   {C.GR}|{C.X}   AI: {C.CY}{mode}{C.X}{service}{key}   {C.GR}|{C.X}   "
            f"AI spend: {usd(usage.read()['total_usd'], 2)}")


def prompt() -> str:
    running = system.instance_running(config.SERVICE_MUTEX)
    paused, _ = paused_until()
    state = (f"{C.Y}paused" if paused else f"{C.G}running") if running else f"{C.R}stopped"
    try:
        user = getpass.getuser().lower()
    except (OSError, KeyError, ImportError):
        user = "user"
    print(f"\n{C.G}┌──({C.X}{C.BOLD}{C.B}{user}@desktidy{C.X}{C.G})-[{C.X}{C.BOLD}{state}{C.X}{C.G}]{C.X}")
    return input(f"{C.G}└─{C.X}{C.BOLD}{C.B}${C.X} ").replace("\ufeff", "").replace("ï»¿", "")


# ================================================================ service control
def wait_for(condition, seconds: float, message: str = "") -> bool:
    if message:
        print(f"  {C.B}[*]{C.X} {message}", end="", flush=True)
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            if message:
                print()
            return True
        if message:
            print(".", end="", flush=True)
        time.sleep(0.5)
    if message:
        print()
    return condition()


def running() -> bool:
    return system.instance_running(config.SERVICE_MUTEX)


def start_service() -> bool:
    try:
        os.remove(config.path("stop"))
    except OSError:
        pass
    if not system.autostart_start():  # autostart off or not installed: start it directly, without a window
        subprocess.Popen(service_command(), cwd=str(config.data_dir()), **system.detached())
    return wait_for(running, 60, "starting")


def stop_service() -> bool:
    """Ask nicely (STOP file: the current work finishes), then ask the system, then end the process."""
    with open(config.path("stop"), "w", encoding="utf-8") as f:
        f.write(datetime.now().isoformat(timespec="seconds"))
    stopped = wait_for(lambda: not running(), 20, "waiting for the current work to finish")
    if not stopped:
        system.autostart_end()
        stopped = wait_for(lambda: not running(), 5)
    if not stopped:
        pid = system.instance_pid(config.SERVICE_MUTEX) or (config.read_json(config.path("state"), {}) or {}).get("pid")
        if pid:
            system.kill(pid)
            stopped = wait_for(lambda: not running(), 5) or (system.kill(pid, force=True) and
                                                             wait_for(lambda: not running(), 5))
    try:
        os.remove(config.path("stop"))
    except OSError:
        pass
    return stopped


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
    ("Private stays private.",
     "IDs, payslips, bills, CVs, photos and screenshots are never sent to the AI. The AI is optional,\n"
     "      with a daily limit and a budget."),
    ("You're in charge.", "desktidy pause 1h · desktidy stop · desktidy preview (see what it would do)."),
]


def cmd_guide(args):
    title("House rules")
    for i, (head, text) in enumerate(HOUSE_RULES, 1):
        print(f"   {C.W}{i}.{C.X} {C.BOLD}{C.G}{head}{C.X}\n      {C.GR}{text}{C.X}")


def cmd_setup(args):
    """First-run setup: accept the house rules, pin enough folders, optionally choose an AI service."""
    global INTERACTIVE
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
        if not (INTERACTIVE or sys.stdin.isatty()):
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
    can_ask = (INTERACTIVE or sys.stdin.isatty()) and "--accept" not in args
    if can_ask and "limits" not in cfg:
        answer = ask("At most how many files a day should DeskTidy tidy? (a number, Enter = unlimited):")
        cmd_limit([answer or "unlimited"])
    if can_ask and confirm("Use an AI for the files DeskTidy can't place by itself? (free options available)"):
        title("Choose the AI service")
        ids = provider_table(cfg)
        choice = ask("Number or name (Enter = groq, free):").lower() or "groq"
        pid = ids[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(ids) else choice
        was, INTERACTIVE = INTERACTIVE, True  # so choose_provider offers to paste the key
        try:
            choose_provider(pid)
        finally:
            INTERACTIVE = was
    if not running():
        hint(f"  The service is not running: {C.W}desktidy start{C.X}")


# ================================================================ commands: service
def cmd_status(args):
    title("Status")
    state = config.read_json(config.path("state"), {}) or {}
    paused, until = paused_until()
    task = system.autostart_info()
    if running():
        detail = f" {C.GR}(last pass {ago(state.get('last_pass'))}){C.X}" if state.get("last_pass") else ""
        row("Service", f"{C.G}{C.BOLD}RUNNING{C.X}{detail}", f"{C.G}[+]{C.X}")
    else:
        row("Service", f"{C.R}{C.BOLD}STOPPED{C.X}   start it with: {C.W}desktidy start{C.X}", f"{C.R}[-]{C.X}")
    if paused:
        row("Paused", f"{C.Y}yes{C.X}, " + (f"until {until:%H:%M on %d %b}" if until else "until: desktidy resume"),
            f"{C.Y}[!]{C.X}")
    if task.get("exists") is False:
        row("Autostart", f"{C.Y}not installed{C.X} (desktidy install)", f"{C.Y}[!]{C.X}")
    elif task.get("exists"):
        row("Autostart", f"{C.G}on{C.X} (at sign-in)" if task["enabled"] else f"{C.Y}off{C.X} (desktidy autostart on)")
    try:
        cfg = config.load_config()
    except Exception as ex:
        fail(f"rules.json is not valid: {ex}  ->  desktidy rules")
        return
    if missing := folders.setup_missing(cfg):
        row("Setup", f"{C.Y}not finished{C.X} ({missing}): only watching -> {C.W}desktidy setup{C.X}", f"{C.Y}[!]{C.X}")
    watched =", ".join(f"{os.path.basename(cfg.expand(w['path']))} ({w.get('wait_seconds', 120) // 60} min)"
                        for w in cfg["watched_folders"])
    row("Watching", watched)
    from . import providers
    mode, p = config.ai_mode(cfg), providers.current(cfg)
    row("AI", f"{C.CY}{mode}{C.X} - {config.AI_MODES[mode][0]}" + (
        "" if mode == "off" else f" {C.GR}(AI files: {config.limit_text(config.daily_limit(cfg))}){C.X}"))
    if mode != "off":
        row("AI service", f"{p.name} · {config.ai_model(cfg)} · {config.ai_delivery(cfg)}"
                          + (f" · {C.G}free{C.X}" if p.free else ""))
        key = system.api_key(p.key_env)
        if key:
            row("API key", system.mask(key))
        elif p.key_env:
            row("API key", f"{C.Y}none{C.X} - the AI can't work: desktidy key", f"{C.Y}[!]{C.X}")
    u = usage.read()
    row("AI spend", f"today {usd(u['today_usd'])} ({u['today_files']} files) · total {usd(u['total_usd'])} · "
                    f"budget {usd(cfg.ai.get('budget_usd', 5.0), 2)}")
    if state.get("ai_pending"):
        row("Waiting for AI", f"{state['ai_pending']} file(s) {C.GR}(gathered to share one request, or in a "
                              f"batch: usually a few minutes){C.X}")
    if u.get("warning"):
        row("AI problem", f"{C.Y}{u['warning']['text']}{C.X} {C.GR}({ago(u['warning']['at'])}){C.X}", f"{C.Y}[!]{C.X}")
    elif mode != "off" and key and (block := usage.block_reason(cfg, u)):
        row("AI paused", f"{C.Y}{block}{C.X}", f"{C.Y}[!]{C.X}")
    row("Renaming", f"{config.rename_mode(cfg)} - {config.RENAME_MODES[config.rename_mode(cfg)]}")
    if cfg.get("analysis", {}).get("ocr", True):
        engine = system.ocr_engine()
        if engine:
            row("Reading scans", f"{engine} {C.GR}(OCR, on this computer){C.X}")
        else:
            row("Reading scans", f"{C.Y}no OCR{C.X}: sudo apt install tesseract-ocr tesseract-ocr-ita  "
                                 f"{C.GR}(or dnf / pacman: tesseract){C.X}", f"{C.Y}[!]{C.X}")
    from . import advice
    tips = advice.load()
    if tips.get("tips"):
        row("Advice", f"{len(tips['tips'])} idea(s) to organise your files, {ago(tips.get('at'))}  "
                      f"->  {C.W}desktidy advice{C.X}")
    elif advice.enabled(cfg):
        row("Advice", f"after {cfg.ai.get('advice_after_files', 30)} tidied files "
                      f"({advice.moved_count()} so far), or now: {C.W}desktidy advice new{C.X}")
    pinned = folders.load_pinned()["pinned"]
    row("Pinned folders", f"{len(pinned)}" + (f"  ({', '.join(os.path.basename(p['path']) for p in pinned[:5])})"
                                              if pinned else "  (desktidy pinned)"))
    moves = read_moves()
    today = [m for m in moves if m["time"].startswith(date.today().isoformat())]
    limit = config.tidy_limit(cfg)
    row("Tidied today", f"{len(today)}" + (f" of {limit} (daily limit: desktidy limit)" if limit is not None
                                           else f"  {C.GR}(no daily limit){C.X}"))
    from . import deadlines, index, learn
    soon = deadlines.upcoming(past_days=3)[:3]
    if soon:
        row("Deadlines", " · ".join(f"{d['what'][:28]} {deadlines.when_text(d)}" for d in soon)
            + f"  {C.GR}(desktidy deadlines){C.X}", f"{C.Y}[!]{C.X}" if deadlines.days_left(soon[0]) <= 1 else None)
    proposals = learn.load()["proposals"]
    if proposals:
        row("Learned", f"{len(proposals)} rule(s) from your corrections to review -> {C.W}desktidy learn{C.X}")
    stats = index.stats()
    row("Search index", f"{stats['files']} files ({stats['bytes'] / 1e6:.1f} MB)  {C.GR}(desktidy find <words>){C.X}")
    if state.get("last_error"):
        row("Last error", f"{C.R}{state['last_error']}{C.X}  (desktidy log errors)", f"{C.R}[-]{C.X}")
    if moves:
        print(f"\n  {C.GR}Latest:{C.X}")
        for m in moves[-3:][::-1]:
            print_move(m)


def parse_duration(text: str) -> datetime | None:
    """'30m', '2h', '1h30m', '1d', '45' (minutes), '18:30' -> end time; None if not understood."""
    t = text.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(?:until)?(\d{1,2})[:.](\d{2})", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return None
        end = datetime.now().replace(hour=h, minute=mi, second=0, microsecond=0)
        return end if end > datetime.now() else end + timedelta(days=1)
    if re.fullmatch(r"\d+", t):
        return datetime.now() + timedelta(minutes=int(t))
    parts = re.findall(r"(\d+)([a-z]+)", t)
    units = {"s": 1, "sec": 1, "m": 60, "min": 60, "mins": 60, "h": 3600, "hr": 3600, "hour": 3600,
             "hours": 3600, "d": 86400, "day": 86400, "days": 86400}
    if not parts or "".join(n + u for n, u in parts) != t or any(u not in units for _, u in parts):
        return None
    return datetime.now() + timedelta(seconds=sum(int(n) * units[u] for n, u in parts))


def cmd_pause(args):
    text = " ".join(args)
    if not text and INTERACTIVE:
        text = ask("For how long? (30m, 2h, 1d, 18:30 - Enter = until you resume):")
    if text:
        until = parse_duration(text)
        if not until:
            fail(f"can't understand '{text}'. Examples: 30m  2h  1h30m  1d  18:30")
            return
        with open(config.path("pause"), "w", encoding="utf-8") as f:
            f.write("until=" + until.isoformat(timespec="seconds"))
        when = f"{until:%H:%M}" + (f" on {until:%d %b}" if until.date() != date.today() else "")
        ok(f"Paused until {C.BOLD}{when}{C.X}. It resumes by itself (or now with {C.W}desktidy resume{C.X})")
    else:
        open(config.path("pause"), "w").close()
        ok(f"Paused until you type: {C.W}desktidy resume{C.X}")
    if not running():
        warn("the service is stopped anyway")


def cmd_resume(args):
    if os.path.exists(config.path("pause")):
        os.remove(config.path("pause"))
        ok("Resumed: tidying again within 30 seconds")
    else:
        info("It wasn't paused")
    if not running():
        warn(f"the service is stopped: {C.W}desktidy start{C.X}")


def cmd_start(args):
    if running():
        info("Already running")
    elif start_service():
        ok("Started")
        if paused_until()[0]:
            warn(f"it is paused: {C.W}desktidy resume{C.X} to let it work")
    else:
        fail(f"It did not start. See: {C.W}desktidy log errors{C.X}")


def cmd_stop(args):
    forever = bool(args) and args[0].lower() in ("forever", "--forever", "always")
    if not running():
        info("Already stopped")
    elif stop_service():
        ok("Stopped")
    else:
        fail("Could not stop it")
        return
    task = system.autostart_info()
    if forever and task.get("enabled"):
        if system.autostart_enable(False):
            ok("Autostart off: it won't start again at the next sign-in")
    elif task.get("exists") and task.get("enabled"):
        info(f"It starts again at the next sign-in. Earlier: {C.W}desktidy start{C.X} · "
             f"never again: {C.W}desktidy stop forever{C.X}")
    else:
        info(f"It won't start by itself (autostart is off). To start it: {C.W}desktidy start{C.X}")


def cmd_restart(args):
    if running() and not stop_service():
        fail("Could not stop it")
        return
    cmd_start(args)


def cmd_autostart(args):
    task = system.autostart_info()
    choice = args[0].lower() if args else ""
    if not choice:
        state = ("not installed" if task.get("exists") is False else
                 f"{C.G}on{C.X}" if task.get("enabled") else f"{C.Y}off{C.X}")
        info(f"Start at sign-in: {state}")
        if not INTERACTIVE:
            hint("Change it with: desktidy autostart on | off")
            return
        choice = ask("Turn it on or off? (Enter = leave it):").lower()
        if not choice:
            return
    if choice in ("on", "yes", "1", "true"):
        if task.get("exists") is False:
            cmd_install([])
        elif system.autostart_enable(True):
            ok("Autostart on: it starts at every sign-in")
        else:
            fail("Could not turn it on")
    elif choice in ("off", "no", "0", "false"):
        if task.get("exists") is False:
            info("Not installed: it doesn't start by itself anyway")
        elif system.autostart_enable(False):
            ok("Autostart off: it won't start at the next sign-in")
            if running():
                info(f"It is still running now (to stop it: {C.W}desktidy stop{C.X})")
        else:
            fail("Could not turn it off")
    else:
        fail("Type on or off")


# ================================================================ commands: files
def print_move(m: dict, number: int | None = None) -> None:
    from . import index, ops
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
    if not text and INTERACTIVE:
        text = ask("File name (or part of it) - Enter = latest moves:")
    found = find_moves(text)[:15]
    title(f"Where did '{text}' go?" if text else "Latest moves")
    if not found:
        warn(f"Nothing called '{text}' in the log. Try a shorter part of the name." if text else "Nothing moved yet")
        return
    from .ops import current_path
    for i, m in enumerate(found, 1):
        print_move(m, i)
    if "--open" in args:
        system.reveal(current_path(found[0]["destination"]))
    elif INTERACTIVE:
        n = ask(f"Number to show in {system.FILE_MANAGER} (Enter = none):")
        if n.isdigit() and 1 <= int(n) <= len(found):
            system.reveal(current_path(found[int(n) - 1]["destination"]))
    else:
        hint(f"\n  Show the first in {system.FILE_MANAGER}: desktidy where {text or '<name>'} --open"
             "   ·   whole log: desktidy where --all")


def undo_move(m: dict) -> str:
    """Put one logged move (or archived item) back where it was, with its old name. Returns the restored path."""
    from . import archive
    from .ops import current_path
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
    st = os.stat(target)
    kept = config.read_json(config.path("kept"), []) or []
    kept.append({"path": target, "size": st.st_size, "mtime": st.st_mtime})
    config.write_json(config.path("kept"), kept[-500:])
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
    from .ops import current_path
    text = " ".join(args)
    ids = re.findall(r"#?([0-9a-f]{8})\b", text.lower())
    if ids and re.fullmatch(r"[#0-9a-f,\s]+", text.lower()):
        restored, problems = undo_ids(ids)
        for p in restored:
            ok(f"Restored {C.BOLD}{os.path.basename(p)}{C.X} to {config.short(os.path.dirname(p))}")
        for p in problems:
            fail(p)
        if GUI and restored:
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
        if not INTERACTIVE and not sys.stdin.isatty():
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


def resolve_folder(text: str) -> str:
    """A folder path: absolute (~ too), or a name looked up on the Desktop, in Documents and in the current folder."""
    text = os.path.expanduser(unquote(text))
    if os.path.isabs(text):
        return os.path.normpath(text)
    desktop, docs = config.BUILTIN_VARIABLES["DESKTOP"], config.BUILTIN_VARIABLES["DOCS"]
    for base in (desktop, docs, os.getcwd()):
        candidate = os.path.join(base, text)
        if os.path.isdir(candidate):
            return os.path.normpath(candidate)
    return os.path.normpath(os.path.join(desktop, text))  # if it doesn't exist: on the Desktop


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
    if INTERACTIVE:
        choice = ask("a) add   r) remove   s) suggestions   (Enter = back):").lower()
        {"a": lambda: pin_folder([]), "r": lambda: unpin_folder([]), "s": suggest}.get(choice, lambda: None)()


def pin_folder(args):
    if not args:
        if not INTERACTIVE:
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
        if INTERACTIVE and not confirm(f"{config.short(target)} doesn't exist. Create it?", default_yes=True):
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
    text = " ".join(args) if args else (ask("Number or name of the folder to unpin:") if INTERACTIVE else "")
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
        if not INTERACTIVE and not sys.stdin.isatty():
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
    if not target and INTERACTIVE:
        target = unquote(ask("File or folder to explain (you can drag it here):"))
    if not target:
        fail("Usage: desktidy explain <file or folder>   (add --ai to ask Claude too)")
        return
    if not os.path.exists(target):
        fail(f"Not found: {target}")
        return
    from . import classifier, naming
    from . import content as ct
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
        row("Offline decision", f"{C.G}{config.short(d.dest)}{C.X}  {C.GR}({d.reason}; {d.strength}){C.X}", f"{C.G}[+]{C.X}")
    else:
        row("Offline decision", f"{C.Y}none{C.X} -> {config.short(cfg.default_destination)}", f"{C.Y}[!]{C.X}")
    new_name = naming.final_name(an.name, plan.new_stem or plan.fallback, is_dir)
    row("New name", f"{C.BOLD}{new_name}{C.X}  {C.GR}({plan.reason}){C.X}" if plan.reason else new_name)
    if d.private or an.is_private:
        row("AI", "never: private file, it stays on this PC")
    elif classifier.wants_ai(d, an, cfg):
        check = " and would check that the name fits the content" if naming.ai_may_check(an, plan, cfg) else ""
        row("AI", f"would be asked (mode {config.ai_mode(cfg)}){check}")
    else:
        row("AI", f"not needed (mode {config.ai_mode(cfg)})")
    if use_ai:
        from . import ai, providers
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
    from .service import Options, Service
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
        if not INTERACTIVE:
            return
        choice = ask("New mode (Enter = keep):").lower()
        if not choice:
            return
    if choice not in config.RENAME_MODES:
        fail("Choose: smart, generic or off")
        return
    config.update_config(lambda d: d.setdefault("rename", {}).__setitem__("mode", choice))
    ok(f"Renaming: {C.BOLD}{choice}{C.X} - {config.RENAME_MODES[choice]}")


# ================================================================ commands: AI
def cmd_spend(args):
    sub = args[0].lower() if args else ""
    if sub in ("credit", "balance", "topup"):
        value = args[1] if len(args) > 1 else (ask(f"Balance right now in USD (see {config.BILLING_URL}):")
                                               if INTERACTIVE else "")
        try:
            amount = float(value.replace("$", "").replace(",", "."))
        except ValueError:
            fail("Write the balance in dollars, e.g.  desktidy spend credit 4.85")
            return
        usage.set_credit(amount)
        ok(f"Credit saved: {usd(amount, 2)}. From now on the remainder is estimated automatically.")
        cfg = config.load_config()
        if cfg.ai.get("budget_usd", 5.0) <= usage.read()["total_usd"] + 0.05:
            warn("the spending budget is already reached: raise it with  desktidy spend budget <usd>")
        return
    if sub == "budget":
        value = args[1] if len(args) > 1 else (ask("New total budget in USD:") if INTERACTIVE else "")
        try:
            budget = round(float(value.replace("$", "").replace(",", ".")), 2)
        except ValueError:
            fail("Write a number, e.g.  desktidy spend budget 10")
            return
        config.update_config(lambda d: d.setdefault("ai", {}).__setitem__("budget_usd", budget))
        ok(f"Budget: {usd(budget, 2)} (the AI stops by itself when the total spend reaches it)")
        return
    if sub in ("web", "console", "billing"):
        info(f"Opening {config.BILLING_URL}")
        system.open_path(config.BILLING_URL)
        return

    cfg = config.load_config()
    u = usage.read()
    from . import providers
    p, model, price = providers.current(cfg), config.ai_model(cfg), providers.prices(cfg)
    title("AI spend")
    if price is None:
        cost = f'{C.Y}price unknown{C.X} (set "price_per_million" in rules.json)'
    elif not any(price):
        cost = f"{C.G}free plan{C.X}"
    else:
        cost = f"${price[0]:g} in / ${price[1]:g} out per million tokens" + ("; batch = half" if p.batch else "")
    row("Model", f"{p.name} · {model}  {C.GR}({cost}{C.GR}){C.X}")
    today = date.today()
    row("Today", f"{usd(u['today_usd'])}   {u['today_files']} files   "
                 f"{C.GR}(limit {config.limit_text(config.daily_limit(cfg))}){C.X}")
    f7, s7 = usage.between(u, (today - timedelta(days=6)).isoformat())
    row("Last 7 days", f"{usd(s7)}   {f7} files")
    fm, sm = usage.between(u, today.replace(day=1).isoformat())
    row("This month", f"{usd(sm)}   {fm} files")
    avg = u["total_usd"] / u["total_files"] if u["total_files"] else 0
    row("Total", f"{C.BOLD}{usd(u['total_usd'])}{C.X}   {u['total_files']} files"
                 + (f"   {C.GR}(avg {usd(avg)} per file){C.X}" if avg else ""))
    budget = cfg.ai.get("budget_usd", 5.0)
    fraction = u["total_usd"] / budget if budget else 1
    row("Budget", f"{bar(fraction)} {fraction:.0%} of {usd(budget, 2)}")
    left = usage.credit_left(u)
    if left is None:
        row("Credit", f"not set  {C.GR}->{C.X} check it ({C.W}desktidy spend web{C.X}) and type it: "
                      f"{C.W}desktidy spend credit 4.85{C.X}")
    else:
        c = u["credit"]
        files = f"  {C.GR}(~{int(left / avg):,} files){C.X}" if avg and left > 0 else ""
        color = C.G if left > 1 else C.Y if left > 0.2 else C.R
        row("Credit", f"{usd(c['usd'], 2)} on {c['at'][:10]}  ->  about {color}{C.BOLD}{usd(left, 2)}{C.X} left{files}")
    if u.get("warning"):
        warn(u["warning"]["text"])
    elif config.ai_mode(cfg) != "off" and (block := usage.block_reason(cfg, u)):
        warn(f"AI paused: {block}")
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    values = [u["days"].get(d, {"files": 0, "usd": 0.0}) for d in days]
    top = max((v["usd"] for v in values), default=0) or 1
    print(f"\n  {C.GR}Last 7 days:{C.X}")
    for d, v in zip(days, values):
        length = round(v["usd"] / top * 30)
        print(f"   {d[8:10]}/{d[5:7]} {C.CY}{'█' * length}{C.X}{'▏' if not length else ''} "
              f"{C.GR}{usd(v['usd'])} · {v['files']} files{C.X}")
    hint("\n  Exact figures from the token counts of every answer. Anthropic does not expose the prepaid balance to\n"
         "  API keys: check it with  desktidy spend web  and type it with  desktidy spend credit <usd>.")
    if INTERACTIVE:
        value = ask("Balance you see NOW in the Anthropic console, in USD (Enter = skip, 'web' = open it):")
        if value.lower() == "web":
            system.open_path(config.BILLING_URL)
            value = ask("Balance in USD (Enter = skip):")
        if value:
            cmd_spend(["credit", value])


AI_ALIASES = {
    "off": "off", "none": "off", "no": "off", "disable": "off", "0": "off",
    "limited": "limited", "limit": "limited", "low": "limited", "1": "limited",
    "moderate": "moderate", "medium": "moderate", "2": "moderate",
    "ai-only": "ai-only", "aionly": "ai-only", "only": "ai-only", "always": "ai-only", "all": "ai-only", "3": "ai-only",
}


def provider_table(cfg) -> list:
    """Print the AI services, numbered; returns their ids in the same order."""
    from . import providers
    current = providers.provider_id(cfg)
    ids = list(providers.PROVIDERS)
    for i, pid in enumerate(ids, 1):
        p = providers.PROVIDERS[pid]
        mark = f"{C.G}●{C.X}" if pid == current else f"{C.GR}○{C.X}"
        if p.free:
            cost = f"{C.G}FREE{C.X} - {p.free}"
        else:
            cost = "your own server: usually free" if p.local else f"{C.Y}paid{C.X}"
        if not p.key_env or p.local:
            key_state = ""
        else:
            key_state = f"  {C.GR}·{C.X} {C.G}key set{C.X}" if system.api_key(p.key_env) else f"  {C.GR}· no key{C.X}"
        print(f"   {mark} {C.W}{i}){C.X} {C.BOLD}{pid:<11}{C.X}{p.name}{key_state}\n"
              f"        {cost}\n        {C.GR}model {p.model or '(set one)'} · {p.privacy}"
              f"{' · reads images' if p.vision else ' · text only'}{C.X}")
    return ids


def choose_provider(pid: str) -> bool:
    from . import providers
    pid = pid.lower()
    if pid not in providers.PROVIDERS:
        fail(f"Unknown service '{pid}'. Choose: {', '.join(providers.PROVIDERS)}")
        return False

    def change(d):
        ai = d.setdefault("ai", {})
        ai["provider"] = pid
        for k in ("model", "base_url", "vision", "price_per_million"):
            ai.pop(k, None)  # the new service's defaults apply
    config.update_config(change)
    p = providers.PROVIDERS[pid]
    ok(f"AI service: {C.BOLD}{p.name}{C.X} (model {p.model or 'to be set'})" + (f" - {C.G}free{C.X}" if p.free else ""))
    if p.privacy:
        info(p.privacy)
    if pid == "ollama":
        info("Install Ollama from ollama.com, then:  ollama pull " + p.model)
    elif pid == "custom":
        info('Set the server in rules.json: "ai": {"base_url": "http://localhost:1234/v1", "model": "..."}')
    if p.key_env and not system.api_key(p.key_env):
        warn(f"no {p.name} key yet: {C.W}desktidy key{C.X}  (get one at {p.key_url})")
        if INTERACTIVE and confirm("Paste the key now?", default_yes=True):
            cmd_key([])
    return True


def cmd_ai(args):
    from . import providers
    cfg = config.load_config()
    current = config.ai_mode(cfg)
    sub = args[0].lower() if args else ""
    raw = args[1] if len(args) > 1 else ""
    value = raw.lower()
    if sub in ("provider", "service", "providers", "services"):
        if raw:
            choose_provider(raw)
            return
        title("AI services")
        ids = provider_table(cfg)
        hint("\n  Free and private: groq (cloud, not used for training) or ollama (on this PC).\n"
             "  Switch with: desktidy ai provider <name>   then: desktidy key")
        if INTERACTIVE:
            choice = ask("Number or name (Enter = keep):").lower()
            if choice:
                choose_provider(ids[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(ids) else choice)
        return
    if sub == "max":
        limit = config.parse_limit(value)
        if value == "auto":
            config.update_config(lambda d: d["ai"].pop("max_files_per_day", None))
            ok(f"AI daily limit: the mode's default ({config.AI_MODES[current][1]} files)")
        elif limit == config.UNLIMITED:
            config.update_config(lambda d: d["ai"].__setitem__("max_files_per_day", config.UNLIMITED))
            ok("The AI may look at any number of files a day (no limit)")
            hint("  The budget still applies: desktidy spend budget <usd>")
        elif isinstance(limit, int):
            config.update_config(lambda d: d["ai"].__setitem__("max_files_per_day", limit))
            ok(f"The AI will look at {limit} files a day at most")
        else:
            fail("Examples:  desktidy ai max 50   ·   desktidy ai max unlimited   ·   desktidy ai max auto")
        return
    if sub == "model":
        if not raw:
            fail("Example: desktidy ai model haiku   (Claude: haiku, sonnet, opus; other services: the model id)")
            return
        model = providers.CLAUDE_MODELS.get(value, raw) if providers.provider_id(cfg) == "claude" else raw
        config.update_config(lambda d: d["ai"].__setitem__("model", model))
        price = providers.prices(config.load_config())
        if price is None:
            ok(f"Model: {model}")
            warn('unknown price: add  "price_per_million": [input, output]  to the ai section of rules.json')
        elif any(price):
            ok(f"Model: {model} (${price[0]:g} / ${price[1]:g} per million tokens)")
        else:
            ok(f"Model: {model} (free plan)")
        return
    if sub == "confidence":
        if value not in ("high", "medium"):
            fail("Type high (only sure answers, recommended) or medium")
            return
        config.update_config(lambda d: d["ai"].__setitem__("min_confidence", value))
        ok(f"AI answers accepted with confidence: {value}" + (" or high" if value == "medium" else ""))
        return
    if sub == "delivery":
        if value not in ("batch", "instant"):
            fail("Type batch (half price, answer in minutes - Claude only) or instant (answer in seconds)")
            return
        config.update_config(lambda d: d["ai"].__setitem__("delivery", value))
        note = "" if providers.current(cfg).batch else " (applies to Claude; the other services always answer at once)"
        ok(f"AI delivery: {value}{note}")
        return
    if not sub:
        p = providers.current(cfg)
        title(f"How much to use the AI ({p.name})")
        for i, (mode, (text, limit)) in enumerate(config.AI_MODES.items()):
            mark = f"{C.G}●{C.X}" if mode == current else f"{C.GR}○{C.X}"
            per_day = f" {C.GR}(max {limit}/day){C.X}" if limit else ""
            print(f"   {mark} {C.W}{i}){C.X} {C.BOLD}{mode:<9}{C.X} {text}{per_day}")
        hint(f"\n  Service {p.id} · model {config.ai_model(cfg)} · delivery {config.ai_delivery(cfg)} · "
             f"min confidence {cfg.ai.get('min_confidence', 'high')}\n"
             "  More: desktidy ai provider (Claude, OpenAI, Gemini, Groq, Mistral, OpenRouter, Ollama)\n"
             "        ai max <n|unlimited>\n"
             "        ai model <name>  ·  ai delivery batch|instant  ·  ai confidence high|medium")
        if not INTERACTIVE:
            return
        sub = ask("New mode (0-3 or name, Enter = keep):").lower()
        if not sub:
            return
    mode = AI_ALIASES.get(sub)
    if not mode:
        fail(f"Unknown mode '{sub}'. Choose: off, limited, moderate, ai-only  (or: ai provider)")
        return

    def change(d):
        d.setdefault("ai", {})["mode"] = mode
        d["ai"].pop("max_files_per_day", None)  # the new mode's limit applies
    config.update_config(change)
    text, limit = config.AI_MODES[mode]
    ok(f"AI: {C.BOLD}{mode}{C.X} - {text}" + (f" (max {limit} files/day)" if limit else ""))
    info("Applies from the next pass (within 30 seconds), no restart needed")
    p = providers.current(cfg)
    if mode != "off" and p.key_env and not system.api_key(p.key_env):
        warn(f"no {p.name} key yet: {C.W}desktidy key{C.X}")


def cmd_key(args):
    from . import providers
    cfg = config.load_config()
    p = providers.current(cfg)
    if not p.key_env:
        info(f"{p.name} needs no API key." + (" Make sure Ollama is running." if p.id == "ollama" else ""))
        _test_key(None, cfg)
        return
    sub = args[0] if args else ""
    current = system.api_key(p.key_env)
    if sub.lower() in ("remove", "delete", "clear"):
        system.set_api_key(None, p.key_env)
        ok(f"{p.name} key removed")
        return
    if sub.lower() in ("test", "check"):
        if not current:
            fail(f"No {p.name} key set")
            return
        _test_key(current, cfg)
        return
    new = sub
    if not new:
        info(f"{p.name} key ({p.key_env}): {system.mask(current)}  {C.GR}(kept in {system.KEYS_WHERE}){C.X}")
        if not INTERACTIVE and not sys.stdin.isatty():
            hint("Usage: desktidy key <NEW-KEY>   ·   desktidy key test   ·   desktidy key remove\n"
                 "  (for another service first: desktidy ai provider <name>)")
            return
        if p.key_url:
            info(f"Get one at {p.key_url} (it stays hidden while you paste it)")
        try:
            new = getpass.getpass(f"  {C.CY}[?]{C.X} Paste the new {p.name} key (Enter = cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not new:
            return
    looks_wrong = p.id == "claude" and not new.startswith("sk-ant-")
    if looks_wrong and not confirm("Claude keys start with 'sk-ant-'. Save it anyway?"):
        return
    if _test_key(new, cfg) is False and not confirm("The key was rejected. Save it anyway?"):
        return
    system.set_api_key(new, p.key_env)
    usage.clear_warning()
    ok(f"{p.name} key saved ({system.mask(new)}). The service uses it right away, no restart needed.")


def _test_key(key: str | None, cfg) -> bool | None:
    from . import ai, providers
    p = providers.current(cfg)
    if not ai.available(cfg):
        warn("the anthropic library is not installed: pip install anthropic")
        return None
    info(f"Checking with {p.name} (free)...")
    valid, message = ai.check_key(key, cfg)
    (ok if valid else fail if valid is False else warn)(message)
    return valid


def print_tips(data: dict) -> None:
    from .ops import AUTOMATIC
    for i, t in enumerate(data.get("tips", []), 1):
        auto = f"  {C.G}(advice apply {i}){C.X}" if t["kind"] in AUTOMATIC and t.get("paths") else ""
        print(f"\n   {C.W}{i}){C.X} {C.CY}[{t['kind']}]{C.X} {C.BOLD}{t['title']}{C.X}{auto}")
        if t.get("detail"):
            print(f"      {t['detail']}")
        for p in t.get("paths", [])[:4]:
            print(f"      {C.GR}-> {config.short(p)}{C.X}")
        if t.get("new_name"):
            print(f"      {C.GR}new name: {t['new_name']}{C.X}")


def cmd_advice(args):
    """Tips to organise files and folders better: from the AI (automatic in ai-only mode) plus offline findings."""
    from . import advice
    sub = args[0].lower() if args else ""
    cfg = config.load_config()
    if sub in ("new", "now", "refresh", "ask"):
        from . import ai, providers
        p = providers.current(cfg)
        key = ai.ready(cfg, print, files=False)
        if not key:
            fail("The AI is not available: choose a service and a key first (desktidy ai provider · desktidy key)")
            return
        price = "free plan" if p.free or p.local else "about $0.005"
        if (INTERACTIVE or sys.stdin.isatty()) and not confirm(
                f"Send {p.name} the names of your folders and a few file names (never the content)? ({price})", True):
            return
        info("Looking at your folders...")
        result = advice.generate(cfg, lambda m: hint(m), key)
        if not result:
            fail("No usable answer (desktidy log errors)")
            return
        data = result
    elif sub in ("open", "show") and len(args) > 1 or sub.isdigit():
        n = args[1] if len(args) > 1 else sub
        tips = advice.load().get("tips", [])
        tip = tips[int(n) - 1] if n.isdigit() and 1 <= int(n) <= len(tips) else None
        if not tip or not tip["paths"]:
            fail(f"Tip {n} has no folder to open")
            return
        system.open_path(tip["paths"][0])
        return
    elif sub == "pin":
        tips = advice.load().get("tips", [])
        n = args[1] if len(args) > 1 else ""
        tip = tips[int(n) - 1] if n.isdigit() and 1 <= int(n) <= len(tips) else None
        if not tip or not tip["paths"]:
            fail("Usage: desktidy advice pin <tip number>   (pins the first folder of that tip)")
            return
        folders.pin(tip["paths"][0])
        ok(f"Pinned {C.BOLD}{os.path.basename(tip['paths'][0])}{C.X}")
        return
    elif sub == "apply":
        return apply_tip(args[1] if len(args) > 1 else "", cfg, "--yes" in args)
    elif sub == "undo":
        from . import ops
        entry = ops.undo_last(cfg)
        if entry:
            ok(f"Undone: {C.BOLD}{entry['title']}{C.X} ({len(entry['steps'])} step(s) reverted, rules and pinned "
               "folders restored)")
        else:
            info("No applied tip to undo")
        return
    else:
        data = advice.load()
    title("Organisation advice")
    if data.get("tips"):
        hint(f"From {data.get('service', 'the AI')} · {data.get('model', '')} · {ago(data.get('at'))}. "
             "Nothing is changed for you: these are ideas.")
        print_tips(data)
    elif sub not in ("new", "now", "refresh", "ask"):
        if advice.enabled(cfg):
            need = cfg.ai.get("advice_after_files", 30)
            info(f"No AI advice yet: it comes by itself once DeskTidy has an overview of your files "
                 f"({advice.moved_count()}/{need} files tidied). Ask now: {C.W}desktidy advice new{C.X}")
        else:
            info(f"No AI advice yet. Ask now: {C.W}desktidy advice new{C.X}  (automatic in mode ai-only)")
    findings = advice.overview(cfg).findings
    if findings:
        print(f"\n  {C.GR}Seen on this PC (offline, now):{C.X}")
        for f in findings:
            warn(f)
    hint("\n  desktidy advice new · advice apply <n> (do it, after a preview) · advice undo · advice open <n> "
         f"({system.FILE_MANAGER}) · advice pin <n>")
    if INTERACTIVE and data.get("tips"):
        n = ask(f"Number to open in {system.FILE_MANAGER}, 'a' + number to apply it (Enter = back):")
        n = n.lower().replace(" ", "")
        if n.isdigit():
            cmd_advice(["open", n])
        elif n.startswith("a") and n[1:].isdigit():
            apply_tip(n[1:], cfg)


def apply_tip(n: str, cfg, yes: bool = False) -> None:
    """Show what a tip would do, then do it (undoable with: desktidy advice undo)."""
    from . import advice, ops
    tips = advice.load().get("tips", [])
    if not (n.isdigit() and 1 <= int(n) <= len(tips)):
        fail("Usage: desktidy advice apply <tip number>   (see: desktidy advice)")
        return
    tip = tips[int(n) - 1]
    plan = ops.plan(tip, cfg)
    title(f"Apply: {tip['title']}")
    for p in plan.problems:
        fail(p)
    if not plan.ok:
        hint("  Nothing was changed.")
        return
    moves = [s for s in plan.steps if s["op"] == "move"]
    for step in plan.steps[:25]:
        print(f"   {C.CY}·{C.X} {ops.describe(step)}")
    if len(plan.steps) > 25:
        print(f"   {C.GR}... and {len(plan.steps) - 25} more{C.X}")
    hint(f"\n  {len(moves)} move(s). Files are never deleted; rules and pinned folders follow the folders.")
    if not yes and not confirm("Do it?", default_yes=False):
        return
    try:
        entry = ops.apply(plan, cfg, tip)
    except Exception as ex:
        fail(f"Stopped and rolled back: {ex}")
        return
    updated = f", {len(entry['changes'])} setting(s) updated" if entry["changes"] else ""
    ok(f"Done: {len(entry['steps'])} step(s){updated}")
    info(f"Changed your mind? {C.W}desktidy advice undo{C.X}")


# ================================================================ commands: find and tidy up
def _pick(prompt: str, count: int) -> int | None:
    """A number between 1 and count typed by the user (only when someone can answer)."""
    if not (INTERACTIVE or sys.stdin.isatty()) or not count:
        return None
    n = ask(prompt)
    return int(n) if n.isdigit() and 1 <= int(n) <= count else None


def cmd_find(args):
    """Search by content: desktidy find electricity bill september."""
    from . import index
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
    if not text and (INTERACTIVE or sys.stdin.isatty()):
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


def _parse_date(text: str):
    from . import deadlines
    for kind, rx in deadlines.DATES:
        m = rx.fullmatch(config.strip_accents(text.strip()).lower())
        if m:
            return deadlines._make(kind, m, date.today())
    return None


def cmd_deadlines(args):
    from . import deadlines
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
    if sub == "scan":
        from . import content as ct
        target = unquote(" ".join(args[1:]))
        if not os.path.isfile(target):
            fail("Usage: desktidy deadlines scan <file>")
            return
        an = ct.analyze(target, False, config.load_config())
        from . import naming
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
    hint("\n  desktidy deadlines done <n> · open <n> · remove <n> · add <date> <what> · scan <file>")
    n = _pick("Number to open (Enter = none):", len(items))
    if n:
        cmd_deadlines(["open", str(n)])


def cmd_groups(args):
    from . import groups
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


def cmd_versions(args):
    from . import versions
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
    if INTERACTIVE or sys.stdin.isatty():
        answer = ask("Number to tidy, 'all', or Enter = none:").lower()
        if answer == "all" or (answer.isdigit() and 1 <= int(answer) <= len(found)):
            cmd_versions(["apply", answer] + folder_args)


def cmd_installers(args):
    from . import installers
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
    can_ask = INTERACTIVE or sys.stdin.isatty()
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


def cmd_archive(args):
    from . import archive
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
    if sub == "now" or ((INTERACTIVE or sys.stdin.isatty()) and confirm("Archive them now?")):
        done = 0
        for path, is_dir, latest in items:
            try:
                archive.archive_one(path, is_dir, latest, cfg)
                done += 1
            except OSError as ex:
                fail(f"{os.path.basename(path)}: {ex}")
        ok(f"{done} item(s) archived. Undo any of them: desktidy undo <name>")


def cmd_import(args):
    from . import importer
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
    if not GUI and not confirm("Import them now? (they are copied: the card is not changed)", True):
        return
    if GUI:
        system.notify(f"{APP_NAME}: importing {len(new)} photos/videos", f"From {label}. You can keep working.")
    s = importer.run(root, cfg, progress=None if GUI else lambda n, m: print(f"\r  {C.GR}{n}/{len(new)}{C.X}", end=""))
    print("\r", end="")
    text = f"{s['copied']} imported, {s['skipped']} already there" + (f", {s['failed']} failed" if s["failed"] else "")
    ok(text)
    for f in s["folders"][:5]:
        print(f"   {C.GR}{config.short(f)}{C.X}")
    if GUI:
        system.notify(f"{APP_NAME}: photos imported", text)


def cmd_learn(args):
    from . import learn
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
    title("Learned from your corrections")
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
        print(f"   {C.W}{i}){C.X} files about {C.CY}{what}{C.X} -> {C.G}{r['destination']}{C.X}\n"
              f"      {C.GR}from: {', '.join(p['examples'][:3])}{C.X}")
    hint("\n  desktidy learn accept <n> · learn reject <n>")
    n = _pick("Number to accept (Enter = later):", len(d["proposals"]))
    if n:
        cmd_learn(["accept", str(n)])


def cmd_limit(args):
    """How many files DeskTidy may tidy per day (AI or not)."""
    cfg = config.load_config()
    text = args[0] if args else ""
    if not text:
        limit = config.tidy_limit(cfg)
        title("Daily limit")
        row("Files tidied per day", f"{tidied_today()} today, " + (f"at most {limit}" if limit is not None else "no limit"))
        row("Files the AI looks at", f"{usage.read()['today_files']} today, at most "
                                     f"{config.limit_text(config.daily_limit(cfg))} (desktidy ai max)")
        hint("\n  desktidy limit 30 · desktidy limit unlimited · desktidy ai max 50 | unlimited")
        if INTERACTIVE:
            text = ask("New limit (a number or 'unlimited', Enter = keep):")
        if not text:
            return
    value = config.parse_limit(text)
    if value is None or value == 0:
        fail("Type a number of files (1 or more) or 'unlimited'. To stop for a while: desktidy pause")
        return
    config.update_config(lambda d: d.setdefault("limits", {}).__setitem__("files_per_day", value))
    if value == config.UNLIMITED:
        ok("No daily limit: DeskTidy tidies every file that is ready")
    else:
        ok(f"At most {C.BOLD}{value}{C.X} files a day; the others wait for the next day ({tidied_today()} tidied today)")


MENU_WHERE = ("Windows 11: under 'Show more options'" if system.WINDOWS else
              "Files: Scripts > DeskTidy · Nemo and Dolphin: DeskTidy")


def cmd_explorer(args):
    from . import explorer
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
    from . import editor
    info("Opening the settings in your browser (only this computer can reach it). Ctrl+C or 'Close editor' to finish.")
    editor.serve(open_browser="--no-browser" not in args, say=lambda m: hint("  " + m))
    ok("Editor closed")


def cmd_update(args):
    from . import updates
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
    hint(f"\n  Installed with {kind}: " + "  &&  ".join(" ".join(c) for c in commands))
    if (INTERACTIVE or sys.stdin.isatty()) and confirm("Update now?", True):
        was_running = running()
        if was_running:
            stop_service()
        if updates.run_update(lambda m: hint("  " + m)):
            ok(f"Updated. Open a new {system.TERMINAL} window to use the new version")
        else:
            fail(f"The update failed: see above, or download it from {release['url']}")
        if was_running:
            start_service()


def _notify_result(title_text: str, body: str, ids: list[str] | None = None) -> None:
    if GUI:
        buttons = [("Open", f"desktidy:open?id={ids[-1]}"), ("Undo", f"desktidy:undo?ids={ids[-1]}")] if ids else []
        system.notify(title_text, body, buttons)


def cmd_tidy(args):
    """Tidy one file or folder now (right-click menu), with the AI if the mode allows it."""
    from . import classifier, naming
    from . import content as ct
    from .service import Options, Service
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
        from . import ai
        key = ai.ready(cfg, hint)
        if key:
            item = ai.item_for(target, is_dir, base, an, d, plan, cfg)
            lines = svc.finish_item(item, (ai.ask([item], cfg, key, hint) or {}).get(1), cfg)
    if lines is None:
        lines = svc.finish(cfg, target, is_dir, base, d.dest, d.reason, plan.new_stem or plan.fallback, plan.reason,
                           an=an)
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


def cmd_url(args):
    """desktidy: links (notification buttons, right-click menu). Only a fixed list of actions with checked ids."""
    from . import deadlines, explorer
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
        from .ops import current_path
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
    from . import explorer
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
        missing = [cfg.expand(w["path"]) for w in cfg["watched_folders"] if not os.path.isdir(cfg.expand(w["path"]))]
        ok(f"rules.json is valid: {len(cfg['rules'])} rules, {len(cfg['watched_folders'])} watched folders")
        for m in missing:
            warn(f"watched folder not found: {m}")
        return
    config.load_config()  # creates rules.json on the first run
    info(f"Opening {config.path('rules')}. Changes apply at the next pass; then: {C.W}desktidy rules check{C.X}")
    system.edit_file(config.path("rules"))


def cmd_open(args):
    system.open_path(str(config.data_dir()))


def cmd_install(args):
    title("Install")
    if system.install_command(console_command()):
        ok(f"'desktidy' command added: it works in NEW {system.TERMINAL} windows")
    else:
        info("The 'desktidy' command is already available")
    config.load_config()
    ok(f"Settings: {config.path('rules')}")
    from . import explorer
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
    if (INTERACTIVE or sys.stdin.isatty()) and not confirm("Continue?"):
        return
    if running():
        (ok if stop_service() else fail)("Service stopped")
    if system.autostart_info().get("exists"):
        (ok if system.autostart_remove() else fail)("Start at sign-in removed")
    if system.uninstall_command():
        ok("'desktidy' command removed")
    from . import explorer
    if explorer.uninstall():
        ok("Right-click menu" + (" and desktidy: links" if system.WINDOWS else "") + " removed")
    info(f"To delete everything: remove {config.data_dir()} and the program folder")


def cmd_about(args):
    banner()
    print()
    row("Version", __version__)
    row("Author", __author__)
    row("Project", REPO_URL)
    row("License", "MIT")
    row("Program", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    row("Data", str(config.data_dir()))
    row("System", f"{system.NAME} ({sys.platform})")
    row("Python", sys.version.split()[0])


# ================================================================ dispatch
COMMANDS = [  # (number, name, function, description, aliases, section)
    (1, "setup", cmd_setup, "first-run setup: house rules, pinned folders, daily limit", ["init"], "Start here"),
    (2, "guide", cmd_guide, "the house rules ('!' = hands off, pinned folders, undo...)", ["house-rules"], "Start here"),
    (3, "status", cmd_status, "service, limits, AI, deadlines and latest moves", ["s", "st"], "Service"),
    (4, "pause", cmd_pause, "pause  (pause 30m · pause 2h · pause 18:30)", [], "Service"),
    (5, "resume", cmd_resume, "end the pause", ["unpause"], "Service"),
    (6, "start", cmd_start, "start the service", ["run"], "Service"),
    (7, "stop", cmd_stop, "stop now, starts again at sign-in  (stop forever)", [], "Service"),
    (8, "restart", cmd_restart, "stop and start", [], "Service"),
    (9, "autostart", cmd_autostart, "start at sign-in  (on · off)", ["boot"], "Service"),
    (10, "limit", cmd_limit, "files tidied per day at most  (limit 30 · limit unlimited)", ["limits", "max"], "Service"),
    (11, "where", cmd_where, "where did my files go  (where invoice · where --all)", ["w"], "Files"),
    (12, "undo", cmd_undo, "put a file back where it was, with its old name", ["restore"], "Files"),
    (13, "find", cmd_find, "search by content  (find electricity bill september)", ["search", "cerca"], "Files"),
    (14, "pinned", cmd_pinned, "pinned folders  (pin recipes cooking · unpin 1)", ["pins"], "Files"),
    (15, "explain", cmd_explain, "what DeskTidy understands of a file  (explain x.pdf)", ["why", "analyze"], "Files"),
    (16, "preview", cmd_preview, "what it would do now, moving nothing  (preview --now)", ["dry-run"], "Files"),
    (17, "rename", cmd_rename, "smart renaming  (smart · generic · off)", [], "Files"),
    (18, "tidy", cmd_tidy, "tidy one file now  (tidy x.pdf, also from the right-click menu)", ["now"], "Files"),
    (19, "deadlines", cmd_deadlines, "bills and deadlines found in your documents  (deadlines done 1)",
     ["scadenze", "due"], "Tidy up"),
    (20, "groups", cmd_groups, "the to-sort pile, grouped into folders  (groups apply 1 --pin)", ["pile"], "Tidy up"),
    (21, "versions", cmd_versions, "old versions of the same document  (versions apply all)", ["versioni"], "Tidy up"),
    (22, "installers", cmd_installers, "setup files of programs already installed  (installers clean)",
     ["installer"], "Tidy up"),
    (23, "archive", cmd_archive, "archive what is untouched for months  (archive on · archive now)", ["archivio"],
     "Tidy up"),
    (24, "import", cmd_import, "photos from a memory card, sorted by date  (import E:)", ["photos"], "Tidy up"),
    (25, "learn", cmd_learn, "rules learned from your corrections  (learn accept 1)", ["learned"], "Tidy up"),
    (26, "ai", cmd_ai, "how much AI: off · limited · moderate · ai-only  (ai max 50 | unlimited)", ["mode"], "AI"),
    (27, "key", cmd_key, "API key of the chosen AI service  (key test · key remove)", ["apikey"], "AI"),
    (28, "spend", cmd_spend, "AI spend and balance  (spend credit 4.85 · spend web)", ["cost", "balance", "usage"], "AI"),
    (29, "advice", cmd_advice, "ideas to organise files and folders  (advice new · advice apply 2)", ["tips", "consigli"],
     "AI"),
    (30, "editor", cmd_editor, "all the settings in your browser", ["ui", "gui", "settings-ui"], "More"),
    (31, "explorer", cmd_explorer, "right-click menu and notification buttons  (on · off)", ["context-menu"], "More"),
    (32, "update", cmd_update, "check for a new version and update", ["upgrade"], "More"),
    (33, "log", cmd_log, "activity log  (log errors · log 100)", ["errors"], "More"),
    (34, "rules", cmd_rules, "edit rules.json  (rules check)", ["config", "settings"], "More"),
    (35, "open", cmd_open, "open the data folder", ["data"], "More"),
    (36, "install", cmd_install, "command, start at sign-in, right-click menu", [], "More"),
    (37, "uninstall", cmd_uninstall, "remove the start at sign-in, the command and the menu", [], "More"),
    (38, "about", cmd_about, "version and author", ["version", "info"], "More"),
]
HIDDEN = {"handsoff": cmd_handsoff, "pin-toggle": cmd_pin_toggle, "url": cmd_url,  # right-click menu and links
          "terminal": cmd_terminal}


def find_command(name: str):
    name = name.lower()
    if name == "pin":
        return lambda a: pin_folder(a) if a or INTERACTIVE else cmd_pinned([])
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
    desktidy ai ai-only             desktidy advice new
    desktidy find bolletta luce     desktidy deadlines
    desktidy limit 30               desktidy ai max unlimited
    desktidy installers             desktidy editor

  {C.BOLD}Good to know{C.X}
    {C.GR}- Files and folders whose name starts with ! are never touched ("!draft.docx").
    - Private files (IDs, payslips, invoices, photos, screenshots) are never sent to the AI.
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
        func(args)
    except KeyboardInterrupt:
        print()
        return 130
    return 0


def console() -> int:
    global INTERACTIVE
    INTERACTIVE = True
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
    global GUI
    GUI = True
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
