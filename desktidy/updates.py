"""New versions: once a week DeskTidy asks GitHub for the latest release (one anonymous request, nothing about you
is sent) and shows a notification when there is a newer one. `desktidy update` checks now and updates the way
DeskTidy was installed: git clone (git pull + pip), pipx or pip. Turn the weekly check off with
"updates": {"check": false} in rules.json.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from . import REPO_URL, __version__, config

API = REPO_URL.replace("https://github.com/", "https://api.github.com/repos/") + "/releases/latest"


def parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def newer(latest: str, current: str = __version__) -> bool:
    return bool(latest) and parse(latest) > parse(current)


def latest(timeout: float = 10) -> dict | None:
    """{"version", "url", "notes", "published"} of the latest GitHub release, or None (offline, no release)."""
    request = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"DeskTidy/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag:
        return None
    return {"version": tag.lstrip("vV"), "url": data.get("html_url", REPO_URL + "/releases"),
            "notes": str(data.get("body") or "")[:2000], "published": data.get("published_at", "")}


def due(cfg: dict) -> bool:
    if not cfg.get("updates", {}).get("check", True):
        return False
    seen = config.read_json(config.path("updates"), {}) or {}
    try:
        return datetime.now() - datetime.fromisoformat(seen.get("checked", "")) > timedelta(days=7)
    except ValueError:
        return True


def check(notify=None) -> dict | None:
    """Ask GitHub, remember the answer, and notify once per new version. Returns the release if it is newer."""
    seen = config.read_json(config.path("updates"), {}) or {}
    release = latest()
    seen["checked"] = datetime.now().isoformat(timespec="seconds")
    if release:
        seen["latest"] = release["version"]
        seen["url"] = release["url"]
    config.write_json(config.path("updates"), seen)
    if not release or not newer(release["version"]):
        return None
    if notify and seen.get("notified") != release["version"]:
        notify(f"DeskTidy {release['version']} is available", f"You have {__version__}. Update: desktidy update",
               [("What's new", "desktidy:update")])
        seen["notified"] = release["version"]
        config.write_json(config.path("updates"), seen)
    return release


def install_kind() -> tuple[str, list[list[str]]]:
    """How DeskTidy was installed, and the commands that update it."""
    program = config.PACKAGE_DIR.parent
    if (program / ".git").exists():
        return "git clone", [["git", "-C", str(program), "pull", "--ff-only"],
                             [sys.executable, "-m", "pip", "install", "-q", "-e", str(program)]]
    if "pipx" in sys.prefix.lower():
        return "pipx", [["pipx", "upgrade", "desktidy"]]
    return "pip", [[sys.executable, "-m", "pip", "install", "-q", "--upgrade", "desktidy"]]


def run_update(say=print) -> bool:
    kind, commands = install_kind()
    for cmd in commands:
        say("$ " + " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            say((r.stderr or r.stdout).strip()[-600:])
            return False
    return True
