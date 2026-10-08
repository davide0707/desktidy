"""Data files, settings (rules.json) and the small helpers shared by the service, the CLI and the engines."""

from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_RULES = PACKAGE_DIR / "default_rules.json"
OCR_SCRIPT = PACKAGE_DIR / "ocr.ps1"

TASK_NAME = "DeskTidy"                      # Windows Task Scheduler entry
SERVICE_MUTEX = "Local\\DeskTidyService"    # exists while the background service runs

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
    "pause": "PAUSE",               # exists = paused (may contain "until=ISO-TIME")
    "stop": "STOP",                 # exists = the service stops at its next check
    "bin": "bin",                   # holds desktidy.cmd, added to PATH by "desktidy install"
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
    """%LOCALAPPDATA%\\DeskTidy, or DESKTIDY_HOME when set (tests, portable installs)."""
    home = os.environ.get("DESKTIDY_HOME")
    if not home:
        home = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "DeskTidy")
    return Path(home)


def path(name: str) -> str:
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
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
class Config(dict):
    """rules.json as a dict, plus {VARIABLE} expansion for paths."""

    def __init__(self, data: dict, source: str = ""):
        super().__init__(data)
        self.source = source
        self._vars = {k: os.path.expandvars(v) for k, v in data.get("variables", {}).items()}

    def expand(self, p: str) -> str:
        for _ in range(3):  # variables may use other variables: {YEAR} = {UNI}\...
            for k, v in self._vars.items():
                p = p.replace("{" + k + "}", v)
        return os.path.normpath(os.path.expandvars(p))

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


def daily_limit(cfg: dict) -> int:
    ai = cfg.get("ai", {})
    return ai["max_files_per_day"] if isinstance(ai.get("max_files_per_day"), int) else AI_MODES[ai_mode(cfg)][1]


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
    """C:\\Users\\me\\Documents\\x -> Documents\\x, C:\\Users\\me\\x -> ~\\x."""
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    if os.path.normcase(p).startswith(os.path.normcase(docs)):
        return "Documents" + p[len(docs):]
    if os.path.normcase(p).startswith(os.path.normcase(home)):
        return "~" + p[len(home):]
    return p


def inside(p: str, base: str) -> bool:
    p, base = os.path.normcase(os.path.abspath(p)), os.path.normcase(os.path.abspath(base))
    return p == base or p.startswith(base.rstrip("\\") + "\\")
