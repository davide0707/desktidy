"""Explorer integration, for the current user only (no administrator rights):

  * right-click menu "DeskTidy" on files: Tidy now · Explain · Hands off (adds or removes the "!")
    and on folders: Pin / unpin · Explain · Old versions here · Hands off
    (on Windows 11 it is under "Show more options", like every classic menu entry)
  * the desktidy: protocol, used by the buttons of the notifications ("Open", "Undo", "Done", "Import"...)

Installed by `desktidy install` or `desktidy explorer on`, removed by `desktidy explorer off` / `uninstall`.
Only a fixed list of actions is accepted from a desktidy: link, with ids checked against DeskTidy's own records:
a web page can't make DeskTidy open or move an arbitrary path.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

from . import config, winapi

CLASSES = "Software\\Classes"
MENU = "DeskTidy"
PROTOCOL = "desktidy"
CONSOLE_ACTIONS = {"where", "advice", "deadlines", "learn", "update", "console", "groups", "installers",
                   "versions", "find", "status", "spend"}
ICON = config.PACKAGE_DIR / "icon.ico"


def _scripts() -> str:
    return os.path.dirname(sys.executable)


def gui_command() -> str:
    """Runs a DeskTidy command without a console window."""
    exe = os.path.join(_scripts(), "desktidyw.exe")
    if os.path.exists(exe):
        return f'"{exe}"'
    pythonw = os.path.join(_scripts(), "pythonw.exe")
    return f'"{pythonw if os.path.exists(pythonw) else sys.executable}" -m desktidy.gui'


def console_command() -> list[str]:
    exe = os.path.join(_scripts(), "desktidy.exe")
    return [exe] if os.path.exists(exe) else [sys.executable, "-m", "desktidy"]


def _console_line() -> str:
    return " ".join(f'"{p}"' if " " in p or p.endswith(".exe") else p for p in console_command())


def entries() -> dict[str, dict[str, str]]:
    """Every registry key written (relative to Software\\Classes) and its values."""
    gui, console, icon = gui_command(), _console_line(), str(ICON)
    keys: dict[str, dict[str, str]] = {
        PROTOCOL: {"": "URL:DeskTidy", "URL Protocol": ""},
        f"{PROTOCOL}\\DefaultIcon": {"": icon},
        f"{PROTOCOL}\\shell\\open\\command": {"": f'{gui} url "%1"'},
    }
    menus = {
        "*": [("1tidy", "Tidy now", f'{gui} tidy "%1"'),
              ("2explain", "Explain...", f'{console} explain "%1" --pause'),
              ("3handsoff", "Hands off / allow (!)", f'{gui} handsoff "%1"')],
        "Directory": [("1pin", "Pin / unpin this folder", f'{gui} pin-toggle "%1"'),
                      ("2explain", "Explain...", f'{console} explain "%1" --pause'),
                      ("3versions", "Old versions here...", f'{console} versions "%1" --pause'),
                      ("4handsoff", "Hands off / allow (!)", f'{gui} handsoff "%1"')],
    }
    for target, items in menus.items():
        base = f"{target}\\shell\\{MENU}"
        keys[base] = {"MUIVerb": "DeskTidy", "SubCommands": "", "Icon": icon}
        for key, label, command in items:
            keys[f"{base}\\shell\\{key}"] = {"MUIVerb": label}
            keys[f"{base}\\shell\\{key}\\command"] = {"": command}
    return keys


def install(root: str = CLASSES) -> None:
    for key, values in entries().items():
        winapi.reg_write(f"{root}\\{key}", values)


def uninstall(root: str = CLASSES) -> bool:
    removed = False
    for key in (PROTOCOL, f"*\\shell\\{MENU}", f"Directory\\shell\\{MENU}"):
        removed |= winapi.reg_delete_tree(f"{root}\\{key}")
    return removed


def installed(root: str = CLASSES) -> bool:
    return winapi.reg_read(f"{root}\\{PROTOCOL}\\shell\\open\\command") is not None


# ---------------------------------------------------------------- desktidy: links
def parse_url(url: str) -> tuple[str, dict[str, str]] | None:
    """'desktidy:undo?ids=1a2b3c4d' -> ('undo', {'ids': '1a2b3c4d'}); None for anything unexpected."""
    url = url.strip().strip('"')
    if not url.lower().startswith(PROTOCOL + ":"):
        return None
    parts = urlsplit(url)
    action = (parts.netloc or parts.path).strip("/").lower()
    params = {k: v[0] for k, v in parse_qs(parts.query).items()}
    allowed = CONSOLE_ACTIONS | {"undo", "open", "deadline-done", "deadline-open", "import"}
    if action not in allowed:
        return None
    if "id" in params and not re.fullmatch(r"[0-9a-f]{8}", params["id"]):
        return None
    if "ids" in params and not re.fullmatch(r"[0-9a-f]{8}(?:,[0-9a-f]{8}){0,19}", params["ids"]):
        return None
    if "drive" in params and not re.fullmatch(r"[A-Za-z]", params["drive"]):
        return None
    return action, params


def open_console(*args: str) -> None:
    """A new console window running a DeskTidy command (it waits for Enter before closing)."""
    command = console_command() + list(args) + (["--pause"] if args else [])
    subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=str(config.data_dir()))
