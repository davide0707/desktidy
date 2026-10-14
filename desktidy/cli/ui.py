# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""How the console looks and asks: colors, messages, questions, the banner, and what the commands share
(starting and stopping the service, a folder typed by the user). INTERACTIVE and GUI live here: one state
for every module (cli.ui.INTERACTIVE)."""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
import time
from datetime import datetime

from .. import APP_NAME, REPO_URL, __author__, __version__, config, system, usage
from ..explorer import service_command
from ..service import paused_until

INTERACTIVE = False  # True inside the console: commands ask for what is missing


GUI = False          # True when started without a console (right-click menu, notification buttons, tray)


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
    from .. import providers
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


# ================================================================ commands: find and tidy up
def _pick(prompt: str, count: int) -> int | None:
    """A number between 1 and count typed by the user (only when someone can answer)."""
    if not (INTERACTIVE or sys.stdin.isatty()) or not count:
        return None
    n = ask(prompt)
    return int(n) if n.isdigit() and 1 <= int(n) <= count else None


def _notify_result(title_text: str, body: str, ids: list[str] | None = None) -> None:
    if GUI:
        buttons = [("Open", f"desktidy:open?id={ids[-1]}"), ("Undo", f"desktidy:undo?ids={ids[-1]}")] if ids else []
        system.notify(title_text, body, buttons)
