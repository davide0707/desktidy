# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""What macOS and Linux share (see system.py): a lock file for the single instance, API keys in a private file,
the `desktidy` command in ~/.local/bin, hidden files, terminals and the small helpers to run system tools."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys

KEYS_WHERE = "a private file in DeskTidy's data folder (keys.json, readable only by you)"
_held: dict[str, int] = {}  # lock name -> file descriptor kept open while the process lives


# ---------------------------------------------------------------- running tools
def run(argv: list[str], timeout: float = 20, **kw) -> subprocess.CompletedProcess | None:
    """Run a system tool quietly; None when it is missing or too slow."""
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, **kw)
    except (OSError, subprocess.TimeoutExpired):
        return None


def spawn(argv: list[str], cwd: str | None = None) -> bool:
    """Start a program and forget about it (own session, no terminal attached)."""
    try:
        subprocess.Popen(argv, cwd=cwd, **detached())
        return True
    except OSError:
        return False


def detached() -> dict:
    return {"start_new_session": True, "close_fds": True, "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def have(tool: str) -> str | None:
    return shutil.which(tool)


# ---------------------------------------------------------------- single instance
def _lock_path(name: str) -> str:
    from . import config
    folder = config.data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / (re.sub(r"[^A-Za-z0-9_.-]+", "_", name.split("\\")[-1]) + ".lock"))


def claim_single_instance(name: str) -> bool:
    """An exclusive lock on a file of the data folder, held until the process ends (released by the system even
    after a crash). The file holds the pid, for `desktidy stop`."""
    import fcntl
    fd = os.open(_lock_path(name), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _held[name] = fd
    return True


def instance_running(name: str) -> bool:
    import fcntl
    try:
        fd = os.open(_lock_path(name), os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)  # refused only while the service holds its lock
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def instance_pid(name: str) -> int | None:
    if not instance_running(name):
        return None
    try:
        with open(_lock_path(name), encoding="ascii") as f:
            return int(f.read().strip() or 0) or None
    except (OSError, ValueError):
        return None


def kill(pid: int, force: bool = False) -> bool:
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- files
def is_hidden(entry: os.DirEntry) -> bool:
    """Dot files, links, and on macOS the files Finder hides (UF_HIDDEN)."""
    if entry.name.startswith(".") or entry.is_symlink():
        return True
    return bool(getattr(entry.stat(follow_symlinks=False), "st_flags", 0) & getattr(stat, "UF_HIDDEN", 0))


def free_name(folder: str, name: str, sep: str = "_") -> str:
    """name, name_2, name_3... (before the extension) that does not exist yet in folder."""
    stem, ext = os.path.splitext(name)
    candidate, n = name, 2
    while os.path.lexists(os.path.join(folder, candidate)):
        candidate, n = f"{stem}{sep}{n}{ext}", n + 1
    return os.path.join(folder, candidate)


# ---------------------------------------------------------------- terminal
def enable_ansi() -> bool:
    return os.environ.get("TERM") != "dumb"


def clear_screen() -> None:
    print("\x1b[2J\x1b[H", end="", flush=True)


def editor_command() -> list[str] | None:
    """$VISUAL or $EDITOR, when DeskTidy runs in a terminal."""
    if not sys.stdin or not sys.stdin.isatty():
        return None
    for var in ("VISUAL", "EDITOR"):
        if os.environ.get(var):
            try:
                return shlex.split(os.environ[var])
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------- API keys
def _keys_file() -> str:
    from . import config
    return config.path("keys")


def api_key(env: str | None = "ANTHROPIC_API_KEY") -> str | None:
    """A key from keys.json (read again when it changes, so a new key works without restarting the service),
    falling back to the environment variable of the same name."""
    if not env:
        return None
    from . import config
    data = config.read_json_cached(_keys_file(), {})
    value = data.get(env) if isinstance(data, dict) else None
    return (str(value or "") or os.environ.get(env) or "").strip() or None


def set_api_key(key: str | None, env: str = "ANTHROPIC_API_KEY") -> None:
    from . import config
    file = _keys_file()
    data = config.read_json(file, {})
    data = data if isinstance(data, dict) else {}
    if key:
        data[env] = key
    else:
        data.pop(env, None)
    tmp = file + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, file)
    config._json_cache.pop(file, None)


# ---------------------------------------------------------------- the `desktidy` command
BIN = os.path.join("~", ".local", "bin")
MARK = "# added by DeskTidy"


def _bin() -> str:
    return os.path.expanduser(BIN)


def _on_path(folder: str) -> bool:
    return any(os.path.realpath(p) == os.path.realpath(folder) for p in os.environ.get("PATH", "").split(os.pathsep) if p)


def _shell_profile() -> str:
    """The startup file of the user's shell, where ~/.local/bin is added to PATH when it is missing."""
    shell = os.path.basename(os.environ.get("SHELL", ""))
    home = os.path.expanduser("~")
    if shell == "zsh":
        return os.path.join(home, ".zshrc")
    if shell == "bash":
        return os.path.join(home, ".bash_profile" if sys.platform == "darwin" else ".bashrc")
    if shell == "fish":
        return os.path.join(home, ".config", "fish", "conf.d", "desktidy.fish")
    return os.path.join(home, ".profile")


def install_command(argv: list[str]) -> bool:
    """~/.local/bin/desktidy: a link to the installed command (or a tiny script), and ~/.local/bin in PATH.
    Nothing to do when `desktidy` already works (pipx). True if something was added."""
    found = shutil.which("desktidy")
    if found and os.path.realpath(found) == os.path.realpath(argv[0]):
        return False
    folder = _bin()
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, "desktidy")
    if os.path.lexists(target):
        if not _ours(target):
            return False  # someone else's command: leave it
        os.remove(target)
    if len(argv) == 1:
        os.symlink(argv[0], target)
    else:
        with open(target, "w", encoding="utf-8") as f:
            f.write(f"#!/bin/sh\n{MARK}\nexec {shlex.join(argv)} \"$@\"\n")
        os.chmod(target, 0o755)
    if not _on_path(folder):
        profile = _shell_profile()
        line = (f"fish_add_path {shlex.quote(folder)}" if profile.endswith(".fish")
                else 'export PATH="$HOME/.local/bin:$PATH"')
        os.makedirs(os.path.dirname(profile), exist_ok=True)
        with open(profile, "a", encoding="utf-8") as f:
            f.write(f"\n{line}  {MARK}\n")
    return True


def _ours(path: str) -> bool:
    if os.path.islink(path):
        return "desktidy" in os.path.basename(os.path.realpath(path)).lower()
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return MARK in f.read(500)
    except OSError:
        return False


def uninstall_command() -> bool:
    removed = False
    target = os.path.join(_bin(), "desktidy")
    if os.path.lexists(target) and _ours(target):
        os.remove(target)
        removed = True
    profile = _shell_profile()
    try:
        with open(profile, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return removed
    kept = [ln for ln in lines if MARK not in ln]
    if len(kept) != len(lines):
        with open(profile, "w", encoding="utf-8") as f:
            f.writelines(kept)
        removed = True
    return removed


# ---------------------------------------------------------------- OCR helpers
def ocr_languages(available: set[str]) -> str:
    """Tesseract languages: the user's language (from LANG) and English, when installed."""
    codes = {"it": "ita", "en": "eng", "de": "deu", "fr": "fra", "es": "spa", "pt": "por", "nl": "nld", "pl": "pol",
             "ru": "rus", "sv": "swe", "da": "dan", "fi": "fin", "nb": "nor", "cs": "ces", "ro": "ron", "hu": "hun",
             "tr": "tur", "el": "ell", "uk": "ukr"}
    wanted = []
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        for part in os.environ.get(var, "").split(":"):
            code = codes.get(part[:2].lower())
            if code and code not in wanted:
                wanted.append(code)
    wanted.append("eng")
    chosen = [c for c in wanted if c in available]
    return "+".join(dict.fromkeys(chosen)) or "eng"
