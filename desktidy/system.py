"""The operating system behind one small interface. Windows (winapi.py), macOS (macos.py) and Linux (linux.py)
each provide the same functions; macOS and Linux share what they have in common (posix.py). Single instance, files
in use, the Trash, notifications and dialogs, opening files, autostart at sign-in, the `desktidy` command, API keys,
the user folders, memory cards, installed programs, the screen size and OCR. Everything else in DeskTidy is plain,
portable Python.

Callers use `system.<function>` at call time, so a test can patch one function for every module.
"""

from __future__ import annotations

import sys

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
LINUX = not (WINDOWS or MACOS)  # Linux and the other Unix-like systems
FROZEN = bool(getattr(sys, "frozen", False))  # the Windows build (desktidy.exe + desktidyw.exe), not Python + pip


def program_home() -> str:
    """Where the Windows build lives once installed: %LOCALAPPDATA%\\Programs\\DeskTidy (no admin rights needed),
    never the folder the zip was extracted to (Downloads is tidied by DeskTidy itself)."""
    import os
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, "Programs", "DeskTidy")

if WINDOWS:
    from . import winapi as _os
elif MACOS:
    from . import macos as _os
else:
    from . import linux as _os
if not WINDOWS:
    from . import posix as _posix


def _get(name: str):
    """The platform's own function, else the one macOS and Linux share."""
    return getattr(_os, name) if WINDOWS or hasattr(_os, name) else getattr(_posix, name)


# ---------------------------------------------------------------- words for the user interface
NAME = "Windows" if WINDOWS else "macOS" if MACOS else "Linux"
MACHINE = "a Windows PC" if WINDOWS else "a Mac" if MACOS else "a Linux PC"   # in the AI instructions
TRASH = "Recycle Bin" if WINDOWS else "Trash"
FILE_MANAGER = "Explorer" if WINDOWS else "Finder" if MACOS else "the file manager"
TERMINAL = "Command Prompt" if WINDOWS else "Terminal" if MACOS else "terminal"
AUTOSTART = _get("AUTOSTART")         # where the autostart entry lives, for the messages
KEYS_WHERE = _get("KEYS_WHERE")       # where the API keys are kept, for the messages

# ---------------------------------------------------------------- processes and files
claim_single_instance = _get("claim_single_instance")   # (name) -> False if another process holds it
instance_running = _get("instance_running")             # (name) -> bool
instance_pid = _get("instance_pid")                     # (name) -> pid of the holder, or None
kill = _get("kill")                                     # (pid, force=False) -> bool
file_in_use = _get("file_in_use")                       # (path) -> True if another program has it open
is_hidden = _get("is_hidden")                           # (os.DirEntry) -> hidden, system file or link
recycle = _get("recycle")                               # (path) -> True once it is in the Trash
detached = _get("detached")                             # () -> Popen arguments: no window, own session

# ---------------------------------------------------------------- user interface
notify = _get("notify")               # (title, body, actions=[(label, "desktidy:...")], launch=None)
ask_yes_no = _get("ask_yes_no")       # (text, title) -> True / False / None (nobody can answer)
message = _get("message")             # (text, title, error=False)
enable_ansi = _get("enable_ansi")     # () -> colors in this terminal
open_path = _get("open_path")         # (file, folder or URL) with the default program
reveal = _get("reveal")               # (path) -> the file manager with the file selected
edit_file = _get("edit_file")         # (path) -> a text editor
new_terminal = _get("new_terminal")   # (argv, cwd) -> False when no terminal could be opened
clear_screen = _get("clear_screen")

# ---------------------------------------------------------------- installation
autostart_info = _get("autostart_info")         # () -> {"exists": bool | None, "enabled": bool}
autostart_install = _get("autostart_install")   # (argv, workdir, start_now) -> bool
autostart_enable = _get("autostart_enable")     # (on) -> bool
autostart_remove = _get("autostart_remove")     # () -> bool
autostart_start = _get("autostart_start")       # () -> True if the system started the service
autostart_end = _get("autostart_end")           # () -> ask the system to end the service
install_command = _get("install_command")       # (argv) -> True if the `desktidy` command was added
uninstall_command = _get("uninstall_command")   # () -> True if it was removed

# ---------------------------------------------------------------- data
data_home = _get("data_home")       # () -> the folder that holds DeskTidy's data folder
user_dirs = _get("user_dirs")       # () -> {"HOME", "DOCS", "DOWNLOADS", "DESKTOP", "PICTURES", "VIDEOS", "MUSIC"}
api_key = _get("api_key")           # (env name) -> the key or None
set_api_key = _get("set_api_key")   # (key or None, env name)

# ---------------------------------------------------------------- devices, programs, screen, OCR
removable_drives = _get("removable_drives")       # () -> [{"id", "name", "label", "serial", "root"}]
installed_programs = _get("installed_programs")   # () -> [{"name", "version", "publisher"}]
installer_product = _get("installer_product")     # (path) -> {"name", "version", "company"} or {}
INSTALLER_EXT = _get("INSTALLER_EXT")             # installer files of this system
screen_sizes = _get("screen_sizes")               # () -> {(width, height)} of the screens, in pixels
ocr = _get("ocr")                                 # (png path) -> recognised text ("" if none)
ocr_engine = _get("ocr_engine")                   # () -> name of the OCR engine, or None when missing


def mask(key: str | None) -> str:
    if not key:
        return "(none)"
    return key[:12] + "..." + key[-4:] if len(key) > 20 else "***"
