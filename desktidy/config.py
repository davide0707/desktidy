"""Data files, settings (rules.json) and the small helpers shared by the service, the CLI and the engines."""

from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from pathlib import Path

from . import system

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_RULES = PACKAGE_DIR / "default_rules.json"

SERVICE_MUTEX = "Local\\DeskTidyService"    # held while the background service runs (a lock file on macOS/Linux)

_FILES = {
    "rules": "rules.json",          # your settings and rules
    "moves": "moves.csv",           # every move and rename (desktidy where / undo)
    "log": "desktidy.log",
    "usage": "ai_usage.json",       # AI spend per day and model, declared credit
    "pinned": "pinned.json",        # pinned folders
    "state": "state.json",          # written by the service on every pass
    "jobs": "ai_jobs.json",         # AI batches waiting for an answer
    "kept": "kept.json",            # files restored by undo: left alone until they change
    "setup": "setup.json",          # when the house rules were accepted
    "advice": "advice.json",        # the latest organisation tips (desktidy advice)
    "ops": "folder_ops.json",       # folder changes applied from the advice, to undo them
    "deadlines": "deadlines.json",  # payment and submission deadlines found in documents
    "learned": "learned.json",      # your corrections and the rules learned from them
    "imports": "imports.json",      # photos already imported from memory cards
    "updates": "updates.json",      # the latest version seen on GitHub
    "pause": "PAUSE",               # exists = paused (may contain "until=ISO-TIME")
    "stop": "STOP",                 # exists = the service stops at its next check
    "bin": "bin",                   # Windows: holds desktidy.cmd, added to PATH by "desktidy install"
    "keys": "keys.json",            # macOS/Linux: API keys, readable only by you (Windows: user environment)
}

AI_MODES = {  # mode: (what it does, files per day)
    "off": ("never: the offline engine decides everything", 0),
    "limited": ("only for files the offline engine cannot place", 10),
    "moderate": ("also for files placed with low confidence", 30),
    "ai-only": ("every file except private ones, fixes names that don't match the content, "
                "and suggests a better organisation over time", 100),
}
MODELS = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
PRICES = {  # USD per million tokens (input, output) of the paid models; free plans cost nothing
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.0),
}
RENAME_MODES = {
    "smart": "generic names and names that don't match the content",
    "generic": "only generic names (scan0001, Document1, download (3)...)",
    "off": "never rename",
}
BILLING_URL = "https://platform.claude.com/settings/billing"
KEYS_URL = "https://platform.claude.com/settings/keys"


# ---------------------------------------------------------------- data files
def data_dir() -> Path:
    """Where DeskTidy keeps its data, or DESKTIDY_HOME when set (tests, portable installs):
    Windows %LOCALAPPDATA%\\DeskTidy, macOS ~/Library/Application Support/DeskTidy, Linux ~/.local/share/desktidy."""
    home = os.environ.get("DESKTIDY_HOME")
    if not home:
        home = os.path.join(system.data_home(), "desktidy" if system.LINUX else "DeskTidy")
    return Path(home)


def path(name: str) -> str:
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)  # private: moves, logs and keys are yours only
    return str(folder / _FILES[name])


def read_json(file: str, default=None):
    try:
        with open(file, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


_json_cache: dict = {}


def read_json_cached(file: str, default=None):
    """Like read_json, but parsed again only when the file changes: for the files read at every pass.
    The result is shared, so callers must not modify it."""
    try:
        st = os.stat(file)
    except OSError:
        _json_cache.pop(file, None)
        return default
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _json_cache.get(file)
    if hit and hit[0] == stamp:
        return hit[1]
    value = read_json(file, default)
    _json_cache[file] = (stamp, value)
    return value


def write_json(file: str, data, indent: int | None = 1) -> None:
    """Atomic write: readers see either the old or the new file, never half of it."""
    tmp = file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
    os.replace(tmp, file)
    _json_cache.pop(file, None)


# ---------------------------------------------------------------- settings
# The user folders, always defined (rules.json may redefine them): {HOME}, {DOCS}, {DOWNLOADS}, {DESKTOP},
# {PICTURES}, {VIDEOS}, {MUSIC}. They are the real places on every system: Documents moved to OneDrive on Windows,
# Movies on macOS, Documenti or Scaricati on an Italian Linux desktop.
BUILTIN_VARIABLES = dict(system.user_dirs())


def expandvars(s: str) -> str:
    """%VAR%, $VAR and ${VAR} on every system, and ~ at the start. Where %USERPROFILE% does not exist (macOS,
    Linux: a rules.json written on Windows) it is the home folder."""
    def windows_var(m):
        value = os.environ.get(m.group(1))
        if value is None and m.group(1).upper() == "USERPROFILE":
            value = BUILTIN_VARIABLES.get("HOME")
        return m.group(0) if value is None else value
    s = re.sub(r"%([A-Za-z_][A-Za-z0-9_]*)%", windows_var, s)
    return os.path.expanduser(os.path.expandvars(s))


def native(p: str) -> str:
    """A path written with \\ or / in rules.json, with the separators of this system."""
    if os.sep == "/":
        p = p.replace("\\", "/")
    return os.path.normpath(p)


class Config(dict):
    """rules.json as a dict, plus {VARIABLE} expansion for paths."""

    def __init__(self, data: dict, source: str = ""):
        super().__init__(data)
        self.source = source
        merged = {**BUILTIN_VARIABLES, **data.get("variables", {})}
        self._vars = {k: expandvars(str(v)) for k, v in merged.items()}

    def expand(self, p: str) -> str:
        for _ in range(3):  # variables may use other variables: {YEAR} = {UNI}/...
            for k, v in self._vars.items():
                p = p.replace("{" + k + "}", v)
        return native(expandvars(p))

    def folder(self, p: str) -> str:
        """expand() for a folder DeskTidy is about to create or fill: refuses unknown {VARIABLES}, so a typo never
        creates a folder literally called "{DOCS}"."""
        path = self.expand(p)
        if "{" in path or not os.path.isabs(path):
            raise OSError(f"unknown variable or relative path in '{p}' (see the variables in rules.json)")
        return path

    @property
    def installer_dir(self) -> str | None:
        return os.path.normcase(self.expand("{INSTALLERS}")) if "INSTALLERS" in self._vars else None

    @property
    def default_destination(self) -> str:
        return self.expand(self["default_destination"])

    @property
    def ai(self) -> dict:
        return self.get("ai", {})


def load_config(file: str | None = None) -> Config:
    file = file or path("rules")
    if not os.path.exists(file) and file == path("rules"):
        shutil.copyfile(DEFAULT_RULES, file)  # first run: start from the bundled rules
    with open(file, encoding="utf-8") as f:
        return Config(json.load(f), file)


def update_config(change, file: str | None = None):
    """Apply change(data) to rules.json, keeping the previous version as rules.json.bak."""
    file = file or path("rules")
    with open(file, encoding="utf-8") as f:
        data = json.load(f)
    result = change(data)
    shutil.copyfile(file, file + ".bak")
    write_json(file, data, indent=2)
    return result


def ai_mode(cfg: dict) -> str:
    mode = cfg.get("ai", {}).get("mode", "off")
    return mode if mode in AI_MODES else "off"


UNLIMITED = "unlimited"
UNLIMITED_WORDS = {"unlimited", "illimitato", "illimitati", "none", "no-limit", "nolimit", "inf", "infinite", "∞"}


def parse_limit(text) -> int | str | None:
    """'30' -> 30, 'unlimited' (or 'illimitati', 'none'...) -> "unlimited", anything else -> None."""
    t = str(text).strip().lower()
    if t in UNLIMITED_WORDS:
        return UNLIMITED
    return int(t) if t.isdigit() else None


def _limit(value, default: int | None) -> int | None:
    if value == UNLIMITED:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def daily_limit(cfg: dict) -> int | None:
    """Files the AI may look at per day: ai.max_files_per_day (a number or "unlimited"), else the mode's default.
    None means no limit."""
    ai = cfg.get("ai", {})
    return _limit(ai.get("max_files_per_day"), AI_MODES[ai_mode(cfg)][1])


def tidy_limit(cfg: dict) -> int | None:
    """Files DeskTidy may tidy per day, AI or not: limits.files_per_day (a number or "unlimited", the default).
    None means no limit."""
    return _limit(cfg.get("limits", {}).get("files_per_day", UNLIMITED), None)


def limit_text(limit: int | None) -> str:
    return "unlimited" if limit is None else f"{limit}/day"


def ai_model(cfg: dict) -> str:
    from .providers import model
    return model(cfg)


def ai_delivery(cfg: dict) -> str:
    """batch = half price, answer usually within minutes (Claude only); instant = answer in seconds."""
    from .providers import current
    if not current(cfg).batch:
        return "instant"
    return "instant" if cfg.get("ai", {}).get("delivery") == "instant" else "batch"


def pinned_minimum(cfg: dict) -> int:
    """Pinned folders required before anything is moved (2 by default; 0 disables the first-run setup)."""
    return int(cfg.get("pinned_folders", {}).get("min_required", 2))


def rename_mode(cfg: dict) -> str:
    mode = cfg.get("rename", {}).get("mode", "smart")
    return mode if mode in RENAME_MODES else "smart"


# ---------------------------------------------------------------- names and paths
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def clean_name(name: str, is_dir: bool = False) -> str:
    """Safe, tidy file name: "Analisi Matematica (1).PDF" -> "Analisi_Matematica.pdf"."""
    stem, ext = (name, "") if is_dir else os.path.splitext(name)
    stem = strip_accents(stem)
    stem = re.sub(r"\s*\(\d+\)$", "", stem)            # "file (1)" -> "file"
    stem = re.sub(r"[^A-Za-z0-9.\-]+", "_", stem)       # letters, digits, dot, dash only
    stem = re.sub(r"_+", "_", stem).strip("_. ") or "file"
    return stem + ext.lower()


def short(p: str) -> str:
    """For the screen: C:\\Users\\me\\Documents\\x -> Documents\\x, /home/me/x -> ~/x."""
    home = os.path.expanduser("~")
    docs = system.user_dirs()["DOCS"]
    for base, name in ((docs, os.path.basename(docs)), (home, "~")):
        if inside(p, base):
            return name + p[len(base.rstrip(os.sep)):]
    return p


def inside(p: str, base: str) -> bool:
    p, base = os.path.normcase(os.path.abspath(p)), os.path.normcase(os.path.abspath(base))
    return p == base or p.startswith(base.rstrip(os.sep) + os.sep)
