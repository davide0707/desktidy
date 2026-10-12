"""The background service: status, the week, pause and resume, start and stop, autostart, the daily limit."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta

from .. import config, folders, system, usage
from ..service import paused_until, read_moves, tidied_today
from . import ui
from .files import print_move
from .ui import C, ago, ask, fail, hint, info, ok, row, running, start_service, stop_service, title, usd, warn


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
    from .. import providers
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
    from .. import advice
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
    from .. import deadlines, index, learn
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


def cmd_week(args):
    """The last 7 days at a glance (also the weekly notification): week · week off|on · week day friday."""
    from .. import summary
    sub = args[0].lower() if args else ""
    if sub in ("off", "on"):
        config.update_config(lambda d: d.setdefault("summary", {}).__setitem__("weekly", sub == "on"))
        ok("Weekly summary " + ("on" if sub == "on" else "off"))
        return
    if sub == "day":
        day = config.strip_accents(args[1]).lower() if len(args) > 1 else ""
        if day not in summary.WEEKDAYS:
            fail("Usage: desktidy week day monday   (any day, in English or Italian)")
            return
        config.update_config(lambda d: d.setdefault("summary", {}).__setitem__("day", day))
        ok(f"The weekly summary comes on {day.title()}")
        return
    cfg = config.load_config()
    s = summary.week(cfg)
    title(f"Your week: {s['from']} - {s['to']}")
    row("Tidied", f"{s['tidied']} file(s)" + (f", {s['renamed']} renamed" if s["renamed"] else "")
        + (f", {s['by_ai']} placed by the AI" if s["by_ai"] else ""))
    if s["places"]:
        row("Most went to", ", ".join(f"{name} ({n})" for name, n in s["places"]))
    if s["duplicates"] or s["installers"]:
        row(f"To the {system.TRASH}", f"{s['duplicates']} duplicate(s), {s['installers']} installer(s)")
    if s["undone"]:
        row("Undone by you", str(s["undone"]))
    row("To sort", f"{s['pile']} file(s) in {config.short(cfg.default_destination)}" if s["pile"] else "nothing")
    row("AI", f"{s['ai_files']} file(s), {usd(s['ai_usd'], 2)}" if s["ai_files"] else "not used")
    if s["deadlines"]:
        print(f"\n  {C.BOLD}Deadlines this week{C.X}")
        for d in s["deadlines"]:
            print(f"   {C.Y}{d['date']}{C.X}  {d['what']}" + (f"  {C.BOLD}{d['amount']}{C.X}" if d["amount"] else ""))
    state = summary.settings(cfg)
    day = next(k for k, v in summary.WEEKDAYS.items() if v == state["day"]).title()
    hint(f"\n  The weekly notification is {'on, on ' + day if state['weekly'] else 'off'}: desktidy week off · "
         "week on · week day friday")


def cmd_pause(args):
    text = " ".join(args)
    if not text and ui.INTERACTIVE:
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
    from .more import cmd_install  # here, not at the top: more imports this module (through start)
    task = system.autostart_info()
    choice = args[0].lower() if args else ""
    if not choice:
        state = ("not installed" if task.get("exists") is False else
                 f"{C.G}on{C.X}" if task.get("enabled") else f"{C.Y}off{C.X}")
        info(f"Start at sign-in: {state}")
        if not ui.INTERACTIVE:
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
        if ui.INTERACTIVE:
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
