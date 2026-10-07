"""DeskTidy command line: an interactive console (menu) and one-shot commands.

  desktidy                 open the console
  desktidy <command> ...   run one command:  desktidy status · desktidy pause 30m · desktidy where invoice
  desktidy help            list every command
"""

from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

from . import APP_NAME, REPO_URL, __author__, __version__, config, folders, usage, winapi
from .service import paused_until, read_moves, record

INTERACTIVE = False  # True inside the console: commands ask for what is missing


# ================================================================ look and feel
class C:
    R = G = Y = B = M = CY = W = GR = BOLD = X = ""


def enable_colors() -> None:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty() or not winapi.enable_ansi():
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
    running = winapi.instance_running(config.SERVICE_MUTEX)
    paused, until = paused_until()
    if running and paused:
        state = f"{C.Y}● PAUSED{C.X}" + (f" until {until:%H:%M}" if until else "")
    elif running:
        state = f"{C.G}● RUNNING{C.X}"
    else:
        state = f"{C.R}● STOPPED{C.X}"
    try:
        mode = config.ai_mode(config.load_config())
    except Exception:
        mode = "?"
    key = "" if winapi.api_key() else f" {C.Y}(no key){C.X}"
    return (f"{state}   {C.GR}|{C.X}   AI: {C.CY}{mode}{C.X}{key}   {C.GR}|{C.X}   "
            f"AI spend: {usd(usage.read()['total_usd'], 2)}")


def prompt() -> str:
    running = winapi.instance_running(config.SERVICE_MUTEX)
    paused, _ = paused_until()
    state = (f"{C.Y}paused" if paused else f"{C.G}running") if running else f"{C.R}stopped"
    user = os.environ.get("USERNAME", "user").lower()
    print(f"\n{C.G}┌──({C.X}{C.BOLD}{C.B}{user}@desktidy{C.X}{C.G})-[{C.X}{C.BOLD}{state}{C.X}{C.G}]{C.X}")
    return input(f"{C.G}└─{C.X}{C.BOLD}{C.B}${C.X} ").replace("\ufeff", "").replace("ï»¿", "")


# ================================================================ service control
def scripts_dir() -> str:
    return os.path.dirname(sys.executable)


def service_exe() -> str:
    exe = os.path.join(scripts_dir(), "desktidy-service.exe")
    return exe if os.path.exists(exe) else os.path.join(scripts_dir(), "pythonw.exe")


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
    return winapi.instance_running(config.SERVICE_MUTEX)


def start_service() -> bool:
    try:
        os.remove(config.path("stop"))
    except OSError:
        pass
    task = winapi.task_info(config.TASK_NAME)
    if task.get("exists") and task.get("enabled"):
        winapi.schtasks(config.TASK_NAME, "/run")
    else:  # autostart disabled or not installed: start it directly, without a window
        exe = service_exe()
        args = [exe] if exe.endswith("desktidy-service.exe") else [exe, "-m", "desktidy.service"]
        subprocess.Popen(args, cwd=str(config.data_dir()), close_fds=True,
                         creationflags=winapi.DETACHED | winapi.NO_WINDOW)
    return wait_for(running, 60, "starting")


def stop_service() -> bool:
    with open(config.path("stop"), "w", encoding="utf-8") as f:
        f.write(datetime.now().isoformat(timespec="seconds"))
    stopped = wait_for(lambda: not running(), 20, "waiting for the current work to finish")
    if not stopped:
        winapi.schtasks(config.TASK_NAME, "/end")
        stopped = wait_for(lambda: not running(), 5)
    if not stopped:
        pid = (config.read_json(config.path("state"), {}) or {}).get("pid")
        if pid:
            subprocess.run(["taskkill", "/pid", str(pid), "/f"], capture_output=True)
            stopped = wait_for(lambda: not running(), 5)
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
     "      Identical duplicates go to the Recycle Bin, never deleted."),
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
    """First-run setup: accept the house rules, pin enough folders, optionally set the AI key."""
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
    if can_ask and not winapi.api_key() and confirm("Use Claude AI for the files DeskTidy can't place by itself? "
                                                    "(needs an API key)"):
        cmd_key([])
    if not running():
        hint(f"  The service is not running: {C.W}desktidy start{C.X}")


# ================================================================ commands: service
def cmd_status(args):
    title("Status")
    state = config.read_json(config.path("state"), {}) or {}
    paused, until = paused_until()
    task = winapi.task_info(config.TASK_NAME)
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
    mode = config.ai_mode(cfg)
    row("AI", f"{C.CY}{mode}{C.X} - {config.AI_MODES[mode][0]}" + (
        "" if mode == "off" else f" {C.GR}(max {config.daily_limit(cfg)}/day, {config.ai_model(cfg)}, "
                                 f"{config.ai_delivery(cfg)}){C.X}"))
    key = winapi.api_key()
    if key:
        row("API key", winapi.mask(key))
    elif mode != "off":
        row("API key", f"{C.Y}none{C.X} - the AI can't work: desktidy key", f"{C.Y}[!]{C.X}")
    u = usage.read()
    row("AI spend", f"today {usd(u['today_usd'])} ({u['today_files']} files) · total {usd(u['total_usd'])} · "
                    f"budget {usd(cfg.ai.get('budget_usd', 5.0), 2)}")
    if state.get("ai_pending"):
        row("Waiting for AI", f"{state['ai_pending']} file(s) {C.GR}(batch: usually a few minutes){C.X}")
    if u.get("warning"):
        row("AI problem", f"{C.Y}{u['warning']['text']}{C.X} {C.GR}({ago(u['warning']['at'])}){C.X}", f"{C.Y}[!]{C.X}")
    elif mode != "off" and key and (block := usage.block_reason(cfg, u)):
        row("AI paused", f"{C.Y}{block}{C.X}", f"{C.Y}[!]{C.X}")
    row("Renaming", f"{config.rename_mode(cfg)} - {config.RENAME_MODES[config.rename_mode(cfg)]}")
    pinned = folders.load_pinned()["pinned"]
    row("Pinned folders", f"{len(pinned)}" + (f"  ({', '.join(os.path.basename(p['path']) for p in pinned[:5])})"
                                              if pinned else "  (desktidy pinned)"))
    moves = read_moves()
    today = [m for m in moves if m["time"].startswith(date.today().isoformat())]
    row("Tidied today", str(len(today)))
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
    task = winapi.task_info(config.TASK_NAME)
    if forever and task.get("enabled"):
        if winapi.schtasks(config.TASK_NAME, "/change", "/disable"):
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
    task = winapi.task_info(config.TASK_NAME)
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
        elif winapi.schtasks(config.TASK_NAME, "/change", "/enable"):
            ok("Autostart on: it starts at every sign-in")
        else:
            fail("Could not turn it on")
    elif choice in ("off", "no", "0", "false"):
        if task.get("exists") is False:
            info("Not installed: it doesn't start by itself anyway")
        elif winapi.schtasks(config.TASK_NAME, "/change", "/disable"):
            ok("Autostart off: it won't start at the next sign-in")
            if running():
                info(f"It is still running now (to stop it: {C.W}desktidy stop{C.X})")
        else:
            fail("Could not turn it off")
    else:
        fail("Type on or off")


# ================================================================ commands: files
def print_move(m: dict, number: int | None = None) -> None:
    name = os.path.basename(m["source"])
    when = f"{m['time'][8:10]}/{m['time'][5:7]} {m['time'][11:16]}"
    n = f"{C.W}{number:>3}{C.X} " if number is not None else "    "
    if m["action"] == "DUPLICATE_TRASHED":
        where = f"{C.Y}Recycle Bin{C.X} (duplicate of {config.short(m['destination'])})"
    elif m["action"] == "UNDONE":
        where = f"{C.CY}restored{C.X} to {config.short(m['destination'])}"
    else:
        where = f"{C.G}{config.short(os.path.dirname(m['destination']))}{C.X}"
        if os.path.basename(m["destination"]) != config.clean_name(name):
            where += f"\\{C.BOLD}{os.path.basename(m['destination'])}{C.X}"
    print(f"  {n}{C.GR}{when}{C.X}  {C.BOLD}{name}{C.X}\n        -> {where}\n        {C.GR}why: {m['reason']}{C.X}")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", config.strip_accents(s).lower())  # "Report 1" == "report_1"


def find_moves(text: str, actions=("MOVED", "DUPLICATE_TRASHED", "UNDONE")) -> list[dict]:
    moves = [m for m in read_moves() if m["action"] in actions]
    if text:
        q = _norm(text)
        moves = [m for m in moves
                 if q in _norm(os.path.basename(m["source"])) or q in _norm(os.path.basename(m["destination"]))]
    return moves[::-1]


def cmd_where(args):
    if "--all" in args:
        winapi.open_path(config.path("moves"))
        return
    text = " ".join(a for a in args if not a.startswith("--"))
    if not text and INTERACTIVE:
        text = ask("File name (or part of it) - Enter = latest moves:")
    found = find_moves(text)[:15]
    title(f"Where did '{text}' go?" if text else "Latest moves")
    if not found:
        warn(f"Nothing called '{text}' in the log. Try a shorter part of the name." if text else "Nothing moved yet")
        return
    for i, m in enumerate(found, 1):
        print_move(m, i)
    if "--open" in args:
        winapi.reveal(found[0]["destination"])
    elif INTERACTIVE:
        n = ask("Number to show in Explorer (Enter = none):")
        if n.isdigit() and 1 <= int(n) <= len(found):
            winapi.reveal(found[int(n) - 1]["destination"])
    else:
        hint(f"\n  Show the first in Explorer: desktidy where {text or '<name>'} --open"
             "   ·   whole log: desktidy where --all")


def cmd_undo(args):
    text = " ".join(args)
    candidates = [m for m in find_moves("", ("MOVED",)) if os.path.exists(m["destination"])]
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
    src, dst = choice["source"], choice["destination"]
    target = src if not os.path.exists(src) else os.path.join(os.path.dirname(src),
                                                               "restored_" + os.path.basename(src))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(dst, target)
    record("UNDONE", dst, target, "restored by desktidy undo")
    st = os.stat(target)
    kept = config.read_json(config.path("kept"), []) or []
    kept.append({"path": target, "size": st.st_size, "mtime": st.st_mtime})
    config.write_json(config.path("kept"), kept[-500:])
    ok(f"Restored {C.BOLD}{os.path.basename(target)}{C.X} to {config.short(os.path.dirname(target))}")
    info("DeskTidy will leave it there until you change it")


def resolve_folder(text: str) -> str:
    """A folder path: absolute, or a name looked up on the Desktop, in Documents and in the current folder."""
    text = unquote(text)
    if os.path.isabs(text):
        return os.path.normpath(text)
    home = os.path.expanduser("~")
    for base in (os.path.join(home, "Desktop"), os.path.join(home, "Documents"), os.getcwd()):
        candidate = os.path.join(base, text)
        if os.path.isdir(candidate):
            return os.path.normpath(candidate)
    return os.path.normpath(os.path.join(home, "Desktop", text))  # if it doesn't exist: on the Desktop


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
    info("Analysing on this PC (nothing is sent)...")
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
        row("AI", f"would be asked (mode {config.ai_mode(cfg)})")
    else:
        row("AI", f"not needed (mode {config.ai_mode(cfg)})")
    if use_ai:
        from . import ai
        key = ai.ready(cfg, print)
        if not key:
            fail("The AI is not available (desktidy status)")
            return
        if not confirm("Really ask Claude? (about $0.001)", default_yes=True):
            return
        item = ai.item_for(target, is_dir, os.path.dirname(target), an, d, plan, cfg)
        answer = (ai.ask([item], cfg, key, lambda m: hint(m)) or {}).get(1)
        if answer:
            row("Claude", f"{C.G}{config.short(answer.folder) if answer.folder else 'none fits'}{C.X} "
                          f"{C.GR}({answer.confidence}: {answer.why}){C.X}", f"{C.G}[+]{C.X}")
            if answer.name:
                row("Claude's name", answer.name)


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
        winapi.open_path(config.BILLING_URL)
        return

    cfg = config.load_config()
    u = usage.read()
    model = config.ai_model(cfg)
    price_in, price_out = config.PRICES.get(model, (0, 0))
    title("AI spend")
    row("Model", f"{model}  {C.GR}(${price_in:g} in / ${price_out:g} out per million tokens; batch = half){C.X}")
    today = date.today()
    row("Today", f"{usd(u['today_usd'])}   {u['today_files']} files   {C.GR}(limit {config.daily_limit(cfg)}/day){C.X}")
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
            winapi.open_path(config.BILLING_URL)
            value = ask("Balance in USD (Enter = skip):")
        if value:
            cmd_spend(["credit", value])


AI_ALIASES = {
    "off": "off", "none": "off", "no": "off", "disable": "off", "0": "off",
    "limited": "limited", "limit": "limited", "low": "limited", "1": "limited",
    "moderate": "moderate", "medium": "moderate", "2": "moderate",
    "ai-only": "ai-only", "aionly": "ai-only", "only": "ai-only", "always": "ai-only", "all": "ai-only", "3": "ai-only",
}


def cmd_ai(args):
    cfg = config.load_config()
    current = config.ai_mode(cfg)
    sub = args[0].lower() if args else ""
    value = args[1].lower() if len(args) > 1 else ""
    if sub == "max":
        if value == "auto":
            config.update_config(lambda d: d["ai"].pop("max_files_per_day", None))
            ok(f"Daily limit: the mode's default ({config.AI_MODES[current][1]} files)")
        elif value.isdigit():
            config.update_config(lambda d: d["ai"].__setitem__("max_files_per_day", int(value)))
            ok(f"Claude will look at {value} files a day at most")
        else:
            fail("Examples:  desktidy ai max 20   ·   desktidy ai max auto")
        return
    if sub == "model":
        model = config.MODELS.get(value, value if value in config.PRICES else None)
        if not model:
            fail("Models: haiku (cheapest, recommended), sonnet, opus")
            return
        config.update_config(lambda d: d["ai"].__setitem__("model", model))
        ok(f"Model: {model} (${config.PRICES[model][0]:g} / ${config.PRICES[model][1]:g} per million tokens)")
        if model != "claude-haiku-4-5":
            warn("costs more than haiku, which is plenty to pick a folder")
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
            fail("Type batch (half price, answer in minutes - recommended) or instant (full price, seconds)")
            return
        config.update_config(lambda d: d["ai"].__setitem__("delivery", value))
        ok(f"AI delivery: {value}")
        return
    if not sub:
        title("How much to use the AI (Claude)")
        for i, (mode, (text, limit)) in enumerate(config.AI_MODES.items()):
            mark = f"{C.G}●{C.X}" if mode == current else f"{C.GR}○{C.X}"
            per_day = f" {C.GR}(max {limit}/day){C.X}" if limit else ""
            print(f"   {mark} {C.W}{i}){C.X} {C.BOLD}{mode:<9}{C.X} {text}{per_day}")
        hint(f"\n  Model {config.ai_model(cfg)} · delivery {config.ai_delivery(cfg)} · min confidence "
             f"{cfg.ai.get('min_confidence', 'high')}\n"
             "  More: desktidy ai max <n>  ·  ai model haiku|sonnet|opus  ·  ai delivery batch|instant  ·  "
             "ai confidence high|medium")
        if not INTERACTIVE:
            return
        sub = ask("New mode (0-3 or name, Enter = keep):").lower()
        if not sub:
            return
    mode = AI_ALIASES.get(sub)
    if not mode:
        fail(f"Unknown mode '{sub}'. Choose: off, limited, moderate, ai-only")
        return

    def change(d):
        d.setdefault("ai", {})["mode"] = mode
        d["ai"].pop("max_files_per_day", None)  # the new mode's limit applies
    config.update_config(change)
    text, limit = config.AI_MODES[mode]
    ok(f"AI: {C.BOLD}{mode}{C.X} - {text}" + (f" (max {limit} files/day)" if limit else ""))
    info("Applies from the next pass (within 30 seconds), no restart needed")
    if mode != "off" and not winapi.api_key():
        warn(f"no API key yet: {C.W}desktidy key{C.X}")


def cmd_key(args):
    sub = args[0] if args else ""
    current = winapi.api_key()
    if sub.lower() in ("remove", "delete", "clear"):
        winapi.set_api_key(None)
        ok("Key removed: the AI won't be used until you set a new one")
        return
    if sub.lower() in ("test", "check"):
        if not current:
            fail("No key set")
            return
        _test_key(current)
        return
    new = sub
    if not new:
        info(f"Current key: {winapi.mask(current)}")
        if not INTERACTIVE and not sys.stdin.isatty():
            hint("Usage: desktidy key <NEW-KEY>   ·   desktidy key test   ·   desktidy key remove")
            return
        info(f"Create one at {config.KEYS_URL} (it stays hidden while you paste it)")
        try:
            new = getpass.getpass(f"  {C.CY}[?]{C.X} Paste the new key (Enter = cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not new:
            return
    if not new.startswith("sk-ant-") and not confirm("Keys usually start with 'sk-ant-'. Save it anyway?"):
        return
    if _test_key(new) is False and not confirm("The key was rejected. Save it anyway?"):
        return
    winapi.set_api_key(new)
    usage.clear_warning()
    ok(f"Key saved ({winapi.mask(new)}). The service uses it right away, no restart needed.")


def _test_key(key: str) -> bool | None:
    try:
        from . import ai
    except ImportError:
        warn("the anthropic library is not installed: can't verify the key")
        return None
    info("Checking the key with Anthropic (free)...")
    valid, message = ai.check_key(key)
    (ok if valid else fail if valid is False else warn)(message)
    return valid


# ================================================================ commands: more
def cmd_log(args):
    if "open" in args:
        winapi.open_path(config.path("log"))
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
    subprocess.Popen(["notepad.exe", config.path("rules")])


def cmd_open(args):
    subprocess.Popen(f'explorer "{config.data_dir()}"')


def cmd_install(args):
    title("Install")
    bin_dir = config.path("bin")
    os.makedirs(bin_dir, exist_ok=True)
    exe = os.path.join(scripts_dir(), "desktidy.exe")
    launcher = f'"{exe}" %*' if os.path.exists(exe) else f'"{sys.executable}" -m desktidy %*'
    with open(os.path.join(bin_dir, "desktidy.cmd"), "w", encoding="ascii", newline="\r\n") as f:
        f.write(f"@echo off\n{launcher}\n")
    if winapi.add_to_path(bin_dir):
        ok("'desktidy' command added: it works in NEW Command Prompt windows")
    else:
        info("The 'desktidy' command is already available")
    config.load_config()
    ok(f"Settings: {config.path('rules')}")
    if winapi.register_logon_task(config.TASK_NAME, service_exe(), str(config.data_dir()), start_now=not running()):
        ok("Starts at every sign-in (Task Scheduler: DeskTidy)")
    else:
        fail("Could not register the startup task")
    if not running() and not wait_for(running, 60, "starting"):
        warn("The service did not start yet: desktidy status")
    if folders.setup_missing(config.load_config()) and sys.stdin.isatty():
        cmd_setup([])
    elif not winapi.api_key():
        info(f"Optional AI: {C.W}desktidy key{C.X}  (without a key DeskTidy works offline)")


def cmd_uninstall(args):
    title("Uninstall")
    info("Removes autostart and the command. Your files, rules and logs stay where they are.")
    if (INTERACTIVE or sys.stdin.isatty()) and not confirm("Continue?"):
        return
    if running():
        (ok if stop_service() else fail)("Service stopped")
    if winapi.task_info(config.TASK_NAME).get("exists"):
        (ok if winapi.schtasks(config.TASK_NAME, "/delete", "/f") else fail)("Startup task removed")
    if winapi.remove_from_path(config.path("bin")):
        ok("'desktidy' command removed")
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
    row("Python", sys.version.split()[0])


# ================================================================ dispatch
COMMANDS = [  # (number, name, function, description, aliases, section)
    (1, "setup", cmd_setup, "first-run setup: house rules + at least 2 pinned folders", ["init"], "Start here"),
    (2, "guide", cmd_guide, "the house rules ('!' = hands off, pinned folders, undo...)", ["house-rules"], "Start here"),
    (3, "status", cmd_status, "service, AI, spend and latest moves", ["s", "st"], "Service"),
    (4, "pause", cmd_pause, "pause  (pause 30m · pause 2h · pause 18:30)", [], "Service"),
    (5, "resume", cmd_resume, "end the pause", ["unpause"], "Service"),
    (6, "start", cmd_start, "start the service", ["run"], "Service"),
    (7, "stop", cmd_stop, "stop now, starts again at sign-in  (stop forever)", [], "Service"),
    (8, "restart", cmd_restart, "stop and start", [], "Service"),
    (9, "autostart", cmd_autostart, "start at sign-in  (on · off)", ["boot"], "Service"),
    (10, "where", cmd_where, "where did my files go  (where invoice · where --all)", ["find", "w"], "Files"),
    (11, "undo", cmd_undo, "put a file back where it was, with its old name", ["restore"], "Files"),
    (12, "pinned", cmd_pinned, "pinned folders  (pin recipes cooking · unpin 1)", ["pins"], "Files"),
    (13, "explain", cmd_explain, "what DeskTidy understands of a file  (explain x.pdf)", ["why", "analyze"], "Files"),
    (14, "preview", cmd_preview, "what it would do now, moving nothing  (preview --now)", ["dry-run"], "Files"),
    (15, "rename", cmd_rename, "smart renaming  (smart · generic · off)", [], "Files"),
    (16, "spend", cmd_spend, "AI spend and balance  (spend credit 4.85 · spend web)", ["cost", "balance", "usage"], "AI"),
    (17, "ai", cmd_ai, "how much AI: off · limited · moderate · ai-only", ["mode"], "AI"),
    (18, "key", cmd_key, "set the Claude API key  (key test · key remove)", ["apikey"], "AI"),
    (19, "log", cmd_log, "activity log  (log errors · log 100)", ["errors"], "More"),
    (20, "rules", cmd_rules, "edit rules.json  (rules check)", ["config", "settings"], "More"),
    (21, "open", cmd_open, "open the data folder", ["data"], "More"),
    (22, "install", cmd_install, "add the command and start at sign-in", [], "More"),
    (23, "uninstall", cmd_uninstall, "remove autostart and the command", [], "More"),
    (24, "about", cmd_about, "version and author", ["version", "info"], "More"),
]


def find_command(name: str):
    name = name.lower()
    if name == "pin":
        return lambda a: pin_folder(a) if a or INTERACTIVE else cmd_pinned([])
    if name == "unpin":
        return unpin_folder
    if name == "errors":
        return lambda a: cmd_log(["errors", *a])
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
    print(f"  In the console type the {C.W}number{C.X} or the {C.W}name{C.X}; from cmd: {C.W}desktidy <command>{C.X}")
    menu()
    print(f"""
  {C.BOLD}Examples{C.X}
    desktidy status                 desktidy where invoice
    desktidy pause 2h               desktidy undo invoice
    desktidy stop                   desktidy ai moderate
    desktidy autostart off          desktidy spend credit 4.85
    desktidy pin pasta recipes      desktidy explain "C:\\Users\\me\\Downloads\\scan0001.pdf"

  {C.BOLD}Good to know{C.X}
    {C.GR}- Files and folders whose name starts with ! are never touched ("!draft.docx").
    - Private files (IDs, payslips, invoices, photos, screenshots) are never sent to the AI.
    - Every move and rename is logged: desktidy where · desktidy undo.{C.X}""")


def split_line(line: str) -> list[str]:
    """Like the Windows command line: spaces separate, quotes keep together."""
    return [a.strip('"') for a in re.findall(r'"[^"]*"|\S+', line)]


def run(argv: list[str]) -> int:
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
    os.system("cls")
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
            os.system("cls")
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


def main() -> None:
    if not sys.stdout.isatty():
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    enable_colors()
    sys.exit(run(sys.argv[1:]))
