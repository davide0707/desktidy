# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""macOS: the tools every Mac has. Notifications and dialogs through osascript (terminal-notifier, if installed, makes
notifications clickable), the Trash through the `trash` command or Foundation, autostart with a launchd agent,
volumes in /Volumes, apps in /Applications, the screen through CoreGraphics and OCR with the Vision framework
(see system.py for the shared interface)."""

from __future__ import annotations

import ctypes
import hashlib
import os
import plistlib
import shlex
import subprocess
import sys
import tempfile

from .posix import editor_command, free_name, have, run, spawn

LABEL = "io.github.davide0707.desktidy"
AUTOSTART = f"a launchd agent (~/Library/LaunchAgents/{LABEL}.plist)"
PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"   # Homebrew tools for the agent too


def data_home() -> str:
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support")


def user_dirs() -> dict[str, str]:
    home = os.path.expanduser("~")
    names = {"DOCS": "Documents", "DOWNLOADS": "Downloads", "DESKTOP": "Desktop", "PICTURES": "Pictures",
             "VIDEOS": "Movies", "MUSIC": "Music"}
    return {"HOME": home, **{k: os.path.join(home, v) for k, v in names.items()}}


def _osascript(lines: list[str], *args: str, timeout: float = 60, language: str = "AppleScript"):
    argv = ["osascript", "-l", language]
    for line in lines:
        argv += ["-e", line]
    return run(argv + list(args), timeout=timeout)


# ---------------------------------------------------------------- files
def file_in_use(path: str) -> bool:
    """True if a program has the file open (lsof)."""
    r = run(["lsof", "-t", "--", path], timeout=15)
    return r is not None and r.returncode == 0 and bool(r.stdout.strip())


_TRASH_JXA = ['ObjC.import("Foundation");',
              "function run(argv) { return $.NSFileManager.defaultManager"
              ".trashItemAtURLResultingItemURLError($.NSURL.fileURLWithPath(argv[0]), null, null); }"]


def recycle(path: str) -> bool:
    """Move to the Trash ("Put Back" works): the `trash` command (macOS 15+, or Homebrew), else Foundation's
    trashItemAtURL through osascript, else a plain move into ~/.Trash."""
    path = os.path.abspath(path)
    tool = have("trash")
    if tool:
        run([tool, path], timeout=60)
    if os.path.lexists(path):
        _osascript(_TRASH_JXA, path, language="JavaScript")
    if os.path.lexists(path):
        try:
            os.rename(path, free_name(os.path.expanduser("~/.Trash"), os.path.basename(path), " "))
        except OSError:
            return False
    return not os.path.lexists(path)


# ---------------------------------------------------------------- notifications and dialogs
def notify(title: str, body: str, actions=(), launch: str | None = None) -> None:
    """A notification. With terminal-notifier (brew install terminal-notifier) a click runs the main action
    (launch, or the first button); osascript notifications have no buttons."""
    target = launch or next((url for _, url in actions), None)
    tool = have("terminal-notifier")
    if tool:
        argv = [tool, "-title", "DeskTidy", "-subtitle", title, "-message", body or " "]
        if target:
            argv += ["-execute", f"{shlex.quote(sys.executable)} -m desktidy.gui url {shlex.quote(target)}"]
        spawn(argv)
        return
    spawn(["osascript", "-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
           "-e", "end run", title, body])


def ask_yes_no(text: str, title: str) -> bool | None:
    r = _osascript(["on run argv",
                    'set r to display dialog (item 1 of argv) with title (item 2 of argv) buttons {"No", "Yes"} '
                    'default button "Yes" with icon note giving up after 3600',
                    'if gave up of r then return "timeout"',
                    "return button returned of r", "end run"], text, title, timeout=3700)
    answer = r.stdout.decode("utf-8", "ignore").strip() if r is not None and r.returncode == 0 else ""
    return {"Yes": True, "No": False}.get(answer)


def message(text: str, title: str, error: bool = False) -> None:
    _osascript(["on run argv", f"display alert (item 1 of argv) message (item 2 of argv) as "
                f"{'critical' if error else 'informational'} giving up after 600", "end run"], title, text, timeout=700)


def open_path(path: str) -> None:
    spawn(["open", path])


def reveal(path: str) -> None:
    spawn(["open", "-R", path] if os.path.exists(path) else ["open", os.path.dirname(path)])


def edit_file(path: str) -> None:
    editor = editor_command()
    if editor:
        subprocess.call([*editor, path])
    else:
        spawn(["open", "-t", path])


def new_terminal(argv: list[str], cwd: str) -> bool:
    """A Terminal window (or the app that opens .command files) running argv."""
    fd, script = tempfile.mkstemp(suffix=".command", prefix="desktidy_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f'#!/bin/sh\nrm -f "$0"\ncd {shlex.quote(cwd)} || exit 1\n{shlex.join(argv)}\n')
    os.chmod(script, 0o700)
    return spawn(["open", script])


# ---------------------------------------------------------------- autostart: a launchd agent
def _plist() -> str:
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", LABEL + ".plist")


def _parked() -> str:
    from . import config
    return str(config.data_dir() / "launchd-agent-off.plist")


def _domain() -> str:
    return f"gui/{os.getuid()}"


def agent(argv: list[str], workdir: str) -> dict:
    """The launchd agent: started at login, restarted after a crash (not after `desktidy stop`)."""
    return {"Label": LABEL, "ProgramArguments": list(argv), "WorkingDirectory": workdir, "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 60, "LimitLoadToSessionType": "Aqua",
            "EnvironmentVariables": {"PATH": PATH, "PYTHONIOENCODING": "utf-8"}}


def _load(plist: str) -> bool:
    r = run(["launchctl", "bootstrap", _domain(), plist], timeout=30)
    if r is None or r.returncode != 0:
        r = run(["launchctl", "load", "-w", plist], timeout=30)
    return r is not None and r.returncode == 0


def autostart_info() -> dict:
    if os.path.exists(_plist()):
        return {"exists": True, "enabled": True}
    return {"exists": True, "enabled": False} if os.path.exists(_parked()) else {"exists": False}


def autostart_install(argv: list[str], workdir: str, start_now: bool = True) -> bool:
    os.makedirs(os.path.dirname(_plist()), exist_ok=True)
    with open(_plist(), "wb") as f:
        plistlib.dump(agent(argv, workdir), f)
    if os.path.exists(_parked()):
        os.remove(_parked())
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], timeout=30)
    return _load(_plist())


def autostart_enable(on: bool) -> bool:
    """Off: the agent is set aside (it won't start at the next login; the running service goes on)."""
    src, dst = (_parked(), _plist()) if on else (_plist(), _parked())
    if not os.path.exists(src):
        return os.path.exists(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(src, dst)
    if on:
        _load(dst)
    return True


def autostart_remove() -> bool:
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], timeout=30)
    removed = False
    for p in (_plist(), _parked()):
        if os.path.exists(p):
            os.remove(p)
            removed = True
    return removed


def autostart_start() -> bool:
    if not os.path.exists(_plist()):
        return False
    r = run(["launchctl", "kickstart", f"{_domain()}/{LABEL}"], timeout=30)
    return r is not None and r.returncode == 0


def autostart_end() -> None:
    return None  # `desktidy stop` ends the service with a signal; launchd does not restart a clean exit


# ---------------------------------------------------------------- volumes
def removable_drives() -> list[dict]:
    """Cards, USB sticks and other volumes mounted in /Volumes (not the startup disk)."""
    found = []
    try:
        names = os.listdir("/Volumes")
    except OSError:
        return found
    for name in names:
        root = os.path.join("/Volumes", name)
        if name.startswith(".") or not os.path.ismount(root) or os.path.realpath(root) == "/":
            continue
        try:
            st = os.statvfs(root)
            size = st.f_blocks * st.f_frsize
        except OSError:
            continue
        serial = hashlib.blake2b(f"{name}|{size}".encode(), digest_size=4).hexdigest().upper()
        found.append({"id": serial, "name": name, "label": name, "serial": serial, "root": root})
    return found


# ---------------------------------------------------------------- apps and installers
INSTALLER_EXT = {".dmg", ".pkg"}


def installed_programs() -> list[dict]:
    """The apps in /Applications and ~/Applications, with the version from their Info.plist."""
    out = []
    for base in ("/Applications", "/Applications/Utilities", os.path.expanduser("~/Applications")):
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".app"):
                continue
            try:
                with open(os.path.join(base, name, "Contents", "Info.plist"), "rb") as f:
                    info = plistlib.load(f)
            except (OSError, ValueError, plistlib.InvalidFileException):
                info = {}
            version = info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or ""
            out.append({"name": name[:-4], "version": str(version), "publisher": str(info.get("CFBundleIdentifier", ""))})
    return out


def installer_product(path: str) -> dict:
    return {}  # a disk image must be mounted to be read: the file name is enough to recognise the app


# ---------------------------------------------------------------- screen and OCR
def screen_sizes() -> set[tuple[int, int]]:
    """Every active display in pixels (Retina included), from CoreGraphics."""
    sizes: set[tuple[int, int]] = set()
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                              ctypes.POINTER(ctypes.c_uint32)]
        cg.CGGetActiveDisplayList.restype = ctypes.c_int32
        cg.CGDisplayCopyDisplayMode.argtypes = [ctypes.c_uint32]
        cg.CGDisplayCopyDisplayMode.restype = ctypes.c_void_p
        for fn in (cg.CGDisplayModeGetPixelWidth, cg.CGDisplayModeGetPixelHeight):
            fn.argtypes, fn.restype = [ctypes.c_void_p], ctypes.c_size_t
        cg.CGDisplayModeRelease.argtypes, cg.CGDisplayModeRelease.restype = [ctypes.c_void_p], None
        ids, count = (ctypes.c_uint32 * 16)(), ctypes.c_uint32()
        if cg.CGGetActiveDisplayList(16, ids, ctypes.byref(count)) != 0:
            return sizes
        for i in range(min(count.value, 16)):
            mode = cg.CGDisplayCopyDisplayMode(ids[i])
            if not mode:
                continue
            w, h = cg.CGDisplayModeGetPixelWidth(mode), cg.CGDisplayModeGetPixelHeight(mode)
            cg.CGDisplayModeRelease(mode)
            if w and h:
                sizes |= {(w, h), (h, w)}
    except (OSError, AttributeError):
        pass
    return sizes


def ocr(png: str) -> str:
    """Text recognition with the Vision framework (macOS 10.15+): offline, nothing is sent."""
    from . import config
    script = str(config.PACKAGE_DIR / "ocr_macos.js")
    r = run(["osascript", "-l", "JavaScript", script, png], timeout=90)
    return r.stdout.decode("utf-8", "ignore") if r is not None and r.returncode == 0 else ""


def ocr_engine() -> str | None:
    return "macOS Vision"
