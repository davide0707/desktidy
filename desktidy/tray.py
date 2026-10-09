"""The DeskTidy icon next to the clock: state at a glance in the tooltip, and a menu with the latest moves, upcoming
deadlines, advice, search, pause and resume, settings. Turn it off with "tray": false in rules.json.

The menu and its actions are plain Python (here); the icon itself is drawn by tray_windows.py (Win32, no extra
library). On macOS and Linux there is no tray icon yet: notifications, the console and `desktidy editor` do the job.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from . import APP_NAME, __version__, config, system


def menu_model(running: bool = True) -> list:
    """[(label, action or None, enabled) | None (separator) | (label, [submenu])]. Actions are tuples."""
    from . import advice, deadlines, usage
    from .service import paused_until, read_moves
    paused, until = paused_until()
    state = "paused" + (f" until {until:%H:%M}" if until else "") if paused else ("running" if running else "stopped")
    moves = [m for m in read_moves() if m["action"] == "MOVED"]
    today = [m for m in moves if m["time"].startswith(date.today().isoformat())]
    ai_today = usage.read()["today_files"]
    model: list = [(f"{APP_NAME} {__version__} · {state}", None, False),
                   (f"Tidied today: {len(today)} · AI today: {ai_today}", None, False), None]
    recent = [(f"{os.path.basename(m['destination'])[:40]}  →  {os.path.basename(os.path.dirname(m['destination']))}",
               ("reveal", m["destination"]), True) for m in moves[-8:][::-1]]
    model.append(("Latest moves", recent + [None, ("All moves...", ("console", "where"), True)]) if recent
                 else ("Latest moves (none yet)", None, False))
    due = deadlines.upcoming()[:6]
    if due:
        items = [(f"{d['date'][8:10]}/{d['date'][5:7]}  {d['what'][:38]}" + (f"  {d['amount']}" if d.get("amount") else ""),
                  ("open", d["path"]) if d.get("path") else ("console", "deadlines"), True) for d in due]
        model.append((f"Deadlines ({len(due)})", items + [None, ("All deadlines...", ("console", "deadlines"), True)]))
    tips = advice.load().get("tips", [])
    model += [(f"Advice ({len(tips)} ideas)..." if tips else "Advice...", ("console", "advice"), True),
              ("Search files...", ("console", "find"), True), None]
    if paused:
        model.append(("Resume", ("resume",), True))
    else:
        model += [("Pause for 1 hour", ("pause", "1h"), True), ("Pause until tomorrow", ("pause", "tomorrow"), True)]
    model += [None, ("Open console", ("console", ""), True), ("Settings...", ("editor",), True), None,
              ("Stop DeskTidy", ("stop",), True)]
    return model


def run_action(action: tuple) -> None:
    from .explorer import open_console
    kind = action[0]
    if kind == "reveal":
        from .ops import current_path
        system.reveal(current_path(action[1]))
    elif kind == "open":
        if os.path.exists(action[1]):
            system.open_path(action[1])
    elif kind == "console":
        open_console(*([action[1]] if action[1] else []))
    elif kind == "editor":
        open_console("editor")
    elif kind == "pause":
        until = (datetime.now() + timedelta(hours=1) if action[1] == "1h"
                 else datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=8))
        with open(config.path("pause"), "w", encoding="utf-8") as f:
            f.write("until=" + until.isoformat(timespec="seconds"))
    elif kind == "resume":
        try:
            os.remove(config.path("pause"))
        except OSError:
            pass
    elif kind == "stop":
        with open(config.path("stop"), "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat(timespec="seconds"))


def start(tooltip: str = APP_NAME):
    """Show the icon (on its own thread); None where there is no tray icon."""
    if not system.WINDOWS:
        return None
    from .tray_windows import Tray
    return Tray.start(tooltip)
