# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""The file manager's right-click menu, for the current user only (no administrator rights):

  * on files: Tidy now · Explain · Hands off (adds or removes the "!")
    and on folders: Pin / unpin · Explain · Old versions here · Hands off
  * Windows: a "DeskTidy" submenu in Explorer (on Windows 11 under "Show more options", like every classic entry),
    and the desktidy: protocol used by the buttons of the notifications ("Open", "Undo", "Done", "Import"...)
  * Linux: scripts for Files (Nautilus), actions for Nemo and a service menu for Dolphin
  * macOS: none yet (use `desktidy explain <file>`, or drag the file into the console)

Installed by `desktidy install` or `desktidy explorer on`, removed by `desktidy explorer off` / `uninstall`.
Only a fixed list of actions is accepted from a desktidy: link, with ids checked against DeskTidy's own records:
a web page can't make DeskTidy open or move an arbitrary path.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

from . import config, system

CLASSES = "Software\\Classes"
MENU = "DeskTidy"
PROTOCOL = "desktidy"
CONSOLE_ACTIONS = {"where", "advice", "deadlines", "learn", "update", "console", "groups", "installers",
                   "versions", "find", "status", "spend", "week", "organize", "duplicates"}
ICON = config.PACKAGE_DIR / "icon.ico"
ICON_PNG = config.PACKAGE_DIR / "icon.png"
AVAILABLE = not system.MACOS


def _scripts() -> str:
    return os.path.dirname(sys.executable)


def gui_argv() -> list[str]:
    """A DeskTidy command without a console window (desktidyw)."""
    if system.WINDOWS:
        exe = os.path.join(_scripts(), "desktidyw.exe")
        if os.path.exists(exe):
            return [exe]
        pythonw = os.path.join(_scripts(), "pythonw.exe")
        return [pythonw if os.path.exists(pythonw) else sys.executable, "-m", "desktidy.gui"]
    return [sys.executable, "-m", "desktidy.gui"]


def gui_command() -> str:
    return " ".join(f'"{a}"' if a.endswith(".exe") or " " in a else a for a in gui_argv())


def console_command() -> list[str]:
    exe = os.path.join(_scripts(), "desktidy.exe" if system.WINDOWS else "desktidy")
    return [exe] if os.path.exists(exe) else [sys.executable, "-m", "desktidy"]


def service_command() -> list[str]:
    """The background service, without a window."""
    if system.FROZEN:  # the Windows build has no desktidy-service.exe: desktidyw.exe --service
        return [os.path.join(_scripts(), "desktidyw.exe"), "--service"]
    exe = os.path.join(_scripts(), "desktidy-service.exe" if system.WINDOWS else "desktidy-service")
    if os.path.exists(exe):
        return [exe]
    pythonw = os.path.join(_scripts(), "pythonw.exe")
    return [pythonw if system.WINDOWS and os.path.exists(pythonw) else sys.executable, "-m", "desktidy.service"]


def _console_line() -> str:
    return " ".join(f'"{p}"' if " " in p or p.endswith(".exe") else p for p in console_command())


# ---------------------------------------------------------------- Windows: Explorer menu and protocol (registry)
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
                      ("3organize", "Organize this folder...", f'{console} organize "%1" --pause'),
                      ("4versions", "Old versions here...", f'{console} versions "%1" --pause'),
                      ("5handsoff", "Hands off / allow (!)", f'{gui} handsoff "%1"')],
        # right-click on the empty space of an open folder, or of the Desktop
        "Directory\\Background": [("1organize", "Organize this folder...", f'{console} organize "%V" --pause')],
        "DesktopBackground": [("1organize", "Organize the Desktop...", f'{console} organize "%V" --pause')],
    }
    for target, items in menus.items():
        base = f"{target}\\shell\\{MENU}"
        keys[base] = {"MUIVerb": "DeskTidy", "SubCommands": "", "Icon": icon}
        for key, label, command in items:
            keys[f"{base}\\shell\\{key}"] = {"MUIVerb": label}
            keys[f"{base}\\shell\\{key}\\command"] = {"": command}
    return keys


# ---------------------------------------------------------------- Linux: Nautilus scripts, Nemo actions, Dolphin menu
ACTIONS = [  # (id, label, command, for files, for folders, in a terminal)
    ("tidy", "Tidy now", "tidy", True, False, False),
    ("explain", "Explain", "explain", True, True, True),
    ("pin", "Pin or unpin this folder", "pin-toggle", False, True, False),
    ("organize", "Organize this folder", "organize", False, True, True),
    ("versions", "Old versions here", "versions", False, True, True),
    ("handsoff", "Hands off or allow (!)", "handsoff", True, True, False),
]


def _action_argv(command: str, terminal: bool) -> list[str]:
    """desktidyw <command> <path>, or desktidyw terminal <command> <path> for the ones that show a report."""
    return gui_argv() + (["terminal", command] if terminal else [command])


def linux_menus(data: str | None = None) -> dict[str, str]:
    """{absolute path: content} of every file written in the user's data folder (~/.local/share)."""
    from .linux import desktop_exec
    data = data or os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    files: dict[str, str] = {}
    service = ("[Desktop Entry]\nType=Service\nMimeType=all/allfiles;inode/directory;\n"
               f"X-KDE-ServiceTypes=KonqPopupMenu/Plugin\nX-KDE-Submenu=DeskTidy\nIcon={ICON_PNG}\n"
               f"Actions={';'.join(a[0] for a in ACTIONS)}\n")
    for key, label, command, on_files, on_dirs, terminal in ACTIONS:
        argv = _action_argv(command, terminal)
        files[os.path.join(data, "nautilus", "scripts", "DeskTidy", label)] = (
            "#!/bin/sh\n# DeskTidy: script for Files (Nautilus)\n"
            f'for f in "$@"; do {shlex.join(argv)} "$(realpath -- "$f")"; done\n')
        kinds = "any;" if on_files and on_dirs else "dir;" if on_dirs else "nodirs;"
        files[os.path.join(data, "nemo", "actions", f"desktidy-{key}.nemo_action")] = (
            f"[Nemo Action]\nName=DeskTidy: {label}\nComment=DeskTidy\nExec={desktop_exec(argv)} %F\n"
            f"Icon-Name=edit-find\nSelection=s\nExtensions={kinds}\nQuote=double\n")
        service += f"\n[Desktop Action {key}]\nName={label}\nExec={desktop_exec(argv)} %f\n"
    for folder in (("kio", "servicemenus"), ("kservices5", "ServiceMenus")):  # KDE 6 and KDE 5
        files[os.path.join(data, *folder, "desktidy.desktop")] = service
    return files


# ---------------------------------------------------------------- install / uninstall
MENU_TARGETS = ("*", "Directory", "Directory\\Background", "DesktopBackground")


def install(root: str = CLASSES) -> None:
    if system.WINDOWS:
        from . import winapi
        for target in MENU_TARGETS:  # a clean menu: no item left over from an older version
            winapi.reg_delete_tree(f"{root}\\{target}\\shell\\{MENU}")
        for key, values in entries().items():
            winapi.reg_write(f"{root}\\{key}", values)
    elif system.LINUX:
        for path, text in linux_menus().items():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            os.chmod(path, 0o755)  # scripts and KDE 6 service menus must be executable
    else:
        raise OSError("there is no Finder menu on macOS yet")


def uninstall(root: str = CLASSES) -> bool:
    removed = False
    if system.WINDOWS:
        from . import winapi
        for key in (PROTOCOL, *(f"{target}\\shell\\{MENU}" for target in MENU_TARGETS)):
            removed |= winapi.reg_delete_tree(f"{root}\\{key}")
    elif system.LINUX:
        menus = linux_menus()
        for path in menus:
            if os.path.exists(path):
                os.remove(path)
                removed = True
        try:
            os.rmdir(os.path.dirname(next(p for p in menus if os.sep + "nautilus" + os.sep in p)))
        except (OSError, StopIteration):
            pass
    return removed


def installed(root: str = CLASSES) -> bool:
    if system.WINDOWS:
        from . import winapi
        return winapi.reg_read(f"{root}\\{PROTOCOL}\\shell\\open\\command") is not None
    return system.LINUX and any(os.path.exists(p) for p in linux_menus())


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
    if "card" in params and not re.fullmatch(r"[0-9A-F]{4,16}", params["card"]):
        return None
    return action, params


def open_console(*args: str) -> None:
    """A new terminal window running a DeskTidy command (it waits for Enter before closing). Without a terminal
    (a Linux desktop with none of the usual ones) the report is shown in a message instead."""
    command = console_command() + list(args) + (["--pause"] if args else [])
    if system.new_terminal(command, str(config.data_dir())):
        return
    r = subprocess.run(console_command() + list(args), capture_output=True, text=True, timeout=300,
                       stdin=subprocess.DEVNULL, env={**os.environ, "NO_COLOR": "1"})
    system.message((r.stdout or r.stderr or "").strip()[-3000:] or "Done", "DeskTidy")
