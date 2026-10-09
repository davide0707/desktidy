"""Linux (and the other Unix-like desktops): the freedesktop.org standards wherever there is one. User folders from
user-dirs.dirs, the Trash specification, notifications (notify-send, with buttons), XDG autostart (or a systemd user
service without a desktop), removable media mounted by udisks, dpkg/rpm packages, Tesseract OCR. Every tool is
optional: when one is missing the feature steps back quietly (see system.py for the shared interface)."""

from __future__ import annotations

import getpass
import glob
import hashlib
import io
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
from datetime import datetime
from functools import lru_cache
from urllib.parse import quote

from .posix import editor_command, have, ocr_languages, run, spawn

AUTOSTART = "the autostart of your desktop (~/.config/autostart)"
SERVICE = "desktidy.service"


def _config_home() -> str:
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def data_home() -> str:
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def icon_png() -> str:
    from . import config
    return str(config.PACKAGE_DIR / "icon.png")


# ---------------------------------------------------------------- user folders
_XDG_DIRS = {"DOCS": ("XDG_DOCUMENTS_DIR", "Documents"), "DOWNLOADS": ("XDG_DOWNLOAD_DIR", "Downloads"),
             "DESKTOP": ("XDG_DESKTOP_DIR", "Desktop"), "PICTURES": ("XDG_PICTURES_DIR", "Pictures"),
             "VIDEOS": ("XDG_VIDEOS_DIR", "Videos"), "MUSIC": ("XDG_MUSIC_DIR", "Music")}


def parse_user_dirs(text: str, home: str) -> dict[str, str]:
    """XDG_DOCUMENTS_DIR="$HOME/Documenti" -> {"XDG_DOCUMENTS_DIR": "/home/me/Documenti"} (user-dirs.dirs)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r'\s*(XDG_\w+_DIR)\s*=\s*"(.*)"\s*$', line)
        if m:
            value = m.group(2).replace('\\"', '"')
            value = home + value[5:] if value.startswith("$HOME") else value
            out[m.group(1)] = os.path.normpath(value)
    return out


@lru_cache(maxsize=1)
def user_dirs() -> dict[str, str]:
    """The user folders in the language of the desktop (Documenti, Scaricati, Scrivania...). A folder set to $HOME
    itself (that is, disabled) falls back to the English name: DeskTidy never watches the whole home folder."""
    home = os.path.expanduser("~")
    try:
        with open(os.path.join(_config_home(), "user-dirs.dirs"), encoding="utf-8") as f:
            found = parse_user_dirs(f.read(), home)
    except OSError:
        found = {}
    dirs = {"HOME": home}
    for key, (var, name) in _XDG_DIRS.items():
        value = found.get(var, "")
        dirs[key] = value if value and os.path.normpath(value) != os.path.normpath(home) else os.path.join(home, name)
    return dirs


# ---------------------------------------------------------------- files
def file_in_use(path: str) -> bool:
    """True if a process of this user has the file open (every /proc/<pid>/fd is compared by device and inode)."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    key, me = (st.st_dev, st.st_ino), str(os.getpid())
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit() and p != me]
    except OSError:
        return False
    for pid in pids:
        folder = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(folder)
        except OSError:
            continue  # another user's process, or gone
        for fd in fds:
            try:
                s = os.stat(f"{folder}/{fd}")
            except OSError:
                continue
            if (s.st_dev, s.st_ino) == key:
                return True
    return False


def _mount_point(path: str) -> str:
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def trash_dir(path: str) -> tuple[str, str | None]:
    """(trash folder, top folder for relative paths): the home trash for files on the same disk as the home folder,
    otherwise $topdir/.Trash/$uid or $topdir/.Trash-$uid on that disk (freedesktop.org Trash specification)."""
    home_data = data_home()
    os.makedirs(home_data, exist_ok=True)
    home_trash = os.path.join(home_data, "Trash")
    try:
        if os.lstat(path).st_dev == os.stat(home_data).st_dev:
            return home_trash, None
    except OSError:
        return home_trash, None
    top, uid = _mount_point(os.path.dirname(os.path.abspath(path))), os.getuid()
    shared = os.path.join(top, ".Trash")
    try:
        st = os.lstat(shared)
        if stat.S_ISDIR(st.st_mode) and st.st_mode & stat.S_ISVTX:
            mine = os.path.join(shared, str(uid))
            os.makedirs(mine, mode=0o700, exist_ok=True)
            return mine, top
    except OSError:
        pass
    mine = os.path.join(top, f".Trash-{uid}")
    try:
        os.makedirs(mine, mode=0o700, exist_ok=True)
        return mine, top
    except OSError:
        return home_trash, None  # a read-only disk: the item is copied into the home trash


def recycle(path: str) -> bool:
    """Move to the Trash, restorable from the file manager (Trash specification: files/ + info/*.trashinfo)."""
    path = os.path.abspath(path)
    trash, top = trash_dir(path)
    files, info = os.path.join(trash, "files"), os.path.join(trash, "info")
    os.makedirs(files, mode=0o700, exist_ok=True)
    os.makedirs(info, mode=0o700, exist_ok=True)
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    n = 1
    while True:
        candidate = name if n == 1 else f"{stem}.{n}{ext}"
        record = os.path.join(info, candidate + ".trashinfo")
        try:
            fd = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # reserves the name
        except FileExistsError:
            n += 1
            continue
        if os.path.lexists(os.path.join(files, candidate)):
            os.close(fd)
            os.remove(record)
            n += 1
            continue
        break
    original = os.path.relpath(path, top) if top else path
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"[Trash Info]\nPath={quote(original, safe='/')}\nDeletionDate={datetime.now():%Y-%m-%dT%H:%M:%S}\n")
    try:
        shutil.move(path, os.path.join(files, candidate))
    except OSError:
        os.remove(record)
        return False
    return not os.path.lexists(path)


# ---------------------------------------------------------------- notifications and dialogs
def _gvariant(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def notify(title: str, body: str, actions=(), launch: str | None = None) -> None:
    """A desktop notification. With notify-send 0.7.10+ the buttons work too: a small shell waits for the click
    (at most two hours) and runs the matching desktidy: action; otherwise a plain notification."""
    actions = list(actions)[:4]
    send = have("notify-send")
    if not send:
        if have("gdbus"):
            spawn(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications", "--object-path",
                   "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.Notify",
                   "'DeskTidy'", "0", _gvariant(icon_png()), _gvariant(title), _gvariant(body), "[]", "{}", "10000"])
        return
    plain = [send, "--app-name=DeskTidy", f"--icon={icon_png()}", title, body]
    if not actions and not launch:
        spawn(plain)
        return
    buttons = [f"--action={i}={label}" for i, (label, _) in enumerate(actions)]
    if launch:
        buttons.append("--action=default=Open")
    ask = [send, "--app-name=DeskTidy", f"--icon={icon_png()}", *buttons, title, body]
    if have("timeout"):
        ask = ["timeout", "7200", *ask]
    cases = "".join(f"  {i}) u={shlex.quote(url)} ;;\n" for i, (_, url) in enumerate(actions))
    if launch:
        cases += f"  default) u={shlex.quote(launch)} ;;\n"
    script = (f"a=$({shlex.join(ask)}); s=$?\n"
              f"if [ $s -ne 0 ] && [ $s -ne 124 ]; then exec {shlex.join(plain)}; fi\n"
              f'case "$a" in\n{cases}  *) exit 0 ;;\nesac\n'
              f'exec {shlex.quote(sys.executable)} -m desktidy.gui url "$u"\n')
    spawn(["sh", "-c", script])


def _markup(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def ask_yes_no(text: str, title: str) -> bool | None:
    """Yes/No dialog with zenity or kdialog (blocks the calling thread); None when neither is installed."""
    if have("zenity"):
        r = run(["zenity", "--question", "--title", title, "--text", _markup(text), "--width=440"], timeout=3600)
    elif have("kdialog"):
        r = run(["kdialog", "--title", title, "--yesno", text], timeout=3600)
    else:
        return None
    if r is None or r.returncode not in (0, 1):
        return None
    return r.returncode == 0


def message(text: str, title: str, error: bool = False) -> None:
    if have("zenity"):
        run(["zenity", "--error" if error else "--info", "--title", title, "--text", _markup(text), "--width=440"],
            timeout=3600)
    elif have("kdialog"):
        run(["kdialog", "--title", title, "--error" if error else "--msgbox", text], timeout=3600)
    else:
        notify(title, text)


def open_path(path: str) -> None:
    for tool in (["xdg-open"], ["gio", "open"]):
        if have(tool[0]) and spawn([*tool, path]):
            return


def reveal(path: str) -> None:
    """The file manager with the file selected (org.freedesktop.FileManager1), or its folder."""
    if os.path.exists(path):
        uri = "file://" + quote(os.path.abspath(path))
        if have("gdbus"):
            r = run(["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1", "--object-path",
                     "/org/freedesktop/FileManager1", "--method", "org.freedesktop.FileManager1.ShowItems",
                     f"[{_gvariant(uri)}]", "''"], timeout=10)
            if r is not None and r.returncode == 0:
                return
        if have("dbus-send"):
            r = run(["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
                     "--type=method_call", "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
                     f"array:string:{uri}", "string:"], timeout=10)
            if r is not None and r.returncode == 0:
                return
    open_path(os.path.dirname(path) if not os.path.isdir(path) else path)


def edit_file(path: str) -> None:
    editor = editor_command()
    if editor:
        subprocess.call([*editor, path])
    else:
        open_path(path)


_TERMINALS = [  # (program, arguments before the command; "str" = the command as one string)
    ("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("ptyxis", ["--"]), ("konsole", ["-e"]),
    ("xfce4-terminal", ["-x"]), ("mate-terminal", ["-x"]), ("tilix", ["-e", "str"]), ("kitty", []),
    ("alacritty", ["-e"]), ("foot", []), ("wezterm", ["start", "--"]), ("lxterminal", ["-e", "str"]),
    ("terminator", ["-x"]), ("xterm", ["-e"])]


def terminal_command(argv: list[str]) -> list[str] | None:
    """argv in a new terminal window: $TERMINAL, then the desktop's own terminal, then the usual ones."""
    if os.environ.get("TERMINAL") and have(os.environ["TERMINAL"]):
        return [os.environ["TERMINAL"], "-e", *argv]
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    order = sorted(_TERMINALS, key=lambda t: 0 if ("kde" in desktop and t[0] == "konsole")
                   or ("xfce" in desktop and t[0] == "xfce4-terminal") else 1)
    for program, before in order:
        if have(program):
            if "str" in before:
                return [program, *[b for b in before if b != "str"], shlex.join(argv)]
            return [program, *before, *argv]
    return None


def new_terminal(argv: list[str], cwd: str) -> bool:
    command = terminal_command(argv)
    return bool(command) and spawn(command, cwd=cwd)


# ---------------------------------------------------------------- autostart: XDG autostart, or systemd without a desktop
def desktop_exec(argv: list[str]) -> str:
    """The Exec= line of a .desktop file (quoting and escaping of the Desktop Entry specification)."""
    out = []
    for a in argv:
        a = a.replace("%", "%%")
        if not a or re.search(r"[\s\"'\\><~|&;$*?#()`]", a):
            a = '"' + re.sub(r'(["`$\\])', r"\\\1", a) + '"'
        out.append(a.replace("\\", "\\\\"))
    return " ".join(out)


def _autostart_file() -> str:
    return os.path.join(_config_home(), "autostart", "desktidy.desktop")


def _unit_file() -> str:
    return os.path.join(_config_home(), "systemd", "user", SERVICE)


def _desktop_session() -> bool:
    return any(os.environ.get(v) for v in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP"))


def _systemd() -> bool:
    r = run(["systemctl", "--user", "show-environment"], timeout=10) if have("systemctl") else None
    return r is not None and r.returncode == 0


def _backend() -> str:
    if os.path.exists(_unit_file()):
        return "systemd"
    if os.path.exists(_autostart_file()) or _desktop_session() or not _systemd():
        return "xdg"
    return "systemd"


def _systemctl(*args: str) -> bool:
    r = run(["systemctl", "--user", *args], timeout=30)
    return r is not None and r.returncode == 0


def autostart_entry(argv: list[str], workdir: str, enabled: bool = True) -> str:
    return ("[Desktop Entry]\nType=Application\nName=DeskTidy\n"
            "Comment=Keeps Downloads, Desktop and Documents tidy\n"
            f"Exec={desktop_exec(argv)}\nPath={workdir}\nIcon={icon_png()}\nTerminal=false\n"
            f"X-GNOME-Autostart-enabled={'true' if enabled else 'false'}\nX-GNOME-Autostart-Delay=10\n"
            f"Hidden={'false' if enabled else 'true'}\n")


def autostart_info() -> dict:
    if os.path.exists(_unit_file()):
        r = run(["systemctl", "--user", "is-enabled", SERVICE], timeout=10)
        return {"exists": True, "enabled": bool(r and r.stdout.strip() == b"enabled"), "kind": "systemd"}
    try:
        with open(_autostart_file(), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {"exists": False}
    hidden = re.search(r"^Hidden\s*=\s*true\s*$", text, re.M | re.I)
    off = re.search(r"^X-GNOME-Autostart-enabled\s*=\s*false\s*$", text, re.M | re.I)
    return {"exists": True, "enabled": not (hidden or off), "kind": "xdg"}


def autostart_install(argv: list[str], workdir: str, start_now: bool = True) -> bool:
    if _backend() == "systemd":
        os.makedirs(os.path.dirname(_unit_file()), exist_ok=True)
        with open(_unit_file(), "w", encoding="utf-8") as f:
            f.write("[Unit]\nDescription=DeskTidy: keeps Downloads, Desktop and Documents tidy\n\n"
                    f"[Service]\nExecStart={shlex.join(argv)}\nWorkingDirectory={workdir}\n"
                    "Restart=on-failure\nRestartSec=60\nNice=5\n\n[Install]\nWantedBy=default.target\n")
        _systemctl("daemon-reload")
        return _systemctl("enable", *(["--now"] if start_now else []), SERVICE)
    os.makedirs(os.path.dirname(_autostart_file()), exist_ok=True)
    with open(_autostart_file(), "w", encoding="utf-8") as f:
        f.write(autostart_entry(argv, workdir))
    return spawn(argv, cwd=workdir) if start_now else True


def autostart_enable(on: bool) -> bool:
    if os.path.exists(_unit_file()):
        return _systemctl("enable" if on else "disable", SERVICE)
    try:
        with open(_autostart_file(), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    text = re.sub(r"^Hidden\s*=.*$", f"Hidden={'false' if on else 'true'}", text, flags=re.M)
    text = re.sub(r"^X-GNOME-Autostart-enabled\s*=.*$", f"X-GNOME-Autostart-enabled={'true' if on else 'false'}",
                  text, flags=re.M)
    with open(_autostart_file(), "w", encoding="utf-8") as f:
        f.write(text)
    return True


def autostart_remove() -> bool:
    removed = False
    if os.path.exists(_unit_file()):
        _systemctl("disable", SERVICE)
        os.remove(_unit_file())
        _systemctl("daemon-reload")
        removed = True
    if os.path.exists(_autostart_file()):
        os.remove(_autostart_file())
        removed = True
    return removed


def autostart_start() -> bool:
    return os.path.exists(_unit_file()) and _systemctl("start", SERVICE)


def autostart_end() -> None:
    if os.path.exists(_unit_file()):
        _systemctl("stop", SERVICE)


# ---------------------------------------------------------------- removable media
def _unescape_mount(s: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def serial_of(uuid: str, fallback: str = "") -> str:
    """A short id for a card: its file system UUID ("1A2B-3C4D" -> "1A2B3C4D"), else a hash of the fallback."""
    hexa = re.sub(r"[^0-9A-Fa-f]", "", uuid).upper()
    if len(hexa) >= 4:
        return hexa[:16]
    return hashlib.blake2b((uuid + fallback).encode(), digest_size=4).hexdigest().upper()


def removable_drives() -> list[dict]:
    """Memory cards and USB sticks mounted by the desktop (udisks: /media/<user>, /run/media/<user>)."""
    try:
        with open("/proc/self/mounts", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    uuids = {}
    try:
        for u in os.listdir("/dev/disk/by-uuid"):
            uuids[os.path.realpath(os.path.join("/dev/disk/by-uuid", u))] = u
    except OSError:
        pass
    user = getpass.getuser()
    bases = (f"/media/{user}/", f"/run/media/{user}/", "/media/")
    found = []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        device, root = parts[0], _unescape_mount(parts[1])
        if not root.startswith(bases) or not os.path.isdir(root):
            continue
        label = os.path.basename(root)
        serial = serial_of(uuids.get(os.path.realpath(device), ""), device + root)
        found.append({"id": serial, "name": label, "label": label, "serial": serial, "root": root})
    return found


# ---------------------------------------------------------------- installed packages and installers
INSTALLER_EXT = {".deb", ".rpm"}


def installed_programs() -> list[dict]:
    """Packages installed with dpkg (Debian, Ubuntu, Mint...) or rpm (Fedora, openSUSE...), and Flatpak apps."""
    out = []
    if have("dpkg-query"):
        r = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\n"], timeout=60)
        out += _rows(r)
    if have("rpm"):
        r = run(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}\t%{VENDOR}\n"], timeout=60)
        out += _rows(r)
    if have("flatpak"):
        r = run(["flatpak", "list", "--app", "--columns=name,version,origin"], timeout=30)
        out += _rows(r)
    return out


def _rows(r) -> list[dict]:
    rows = []
    for line in (r.stdout.decode("utf-8", "ignore").splitlines() if r is not None and r.returncode == 0 else []):
        cells = line.split("\t") + ["", ""]
        if cells[0].strip():
            rows.append({"name": cells[0].strip(), "version": cells[1].strip(), "publisher": cells[2].strip()})
    return rows


def deb_control(path: str) -> dict:
    """Package, Version and Maintainer from a .deb (an ar archive holding control.tar.*), without dpkg."""
    with open(path, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            return {}
        while True:
            header = f.read(60)
            if len(header) < 60:
                return {}
            name, size = header[:16].decode("ascii", "ignore").strip().rstrip("/"), int(header[48:58].strip() or 0)
            if not name.startswith("control.tar"):
                f.seek(size + size % 2, 1)
                continue
            try:
                with tarfile.open(fileobj=io.BytesIO(f.read(size)), mode="r:*") as t:
                    member = next((m for m in t.getmembers() if m.name.lstrip("./") == "control"), None)
                    text = t.extractfile(member).read().decode("utf-8", "ignore") if member else ""
            except (tarfile.TarError, OSError, ValueError, AttributeError):
                return {}
            fields = dict(re.findall(r"^(Package|Version|Maintainer):\s*(.+)$", text, re.M))
            return {"name": fields.get("Package", ""), "version": fields.get("Version", ""),
                    "company": fields.get("Maintainer", "")}


def installer_product(path: str) -> dict:
    if path.lower().endswith(".deb"):
        try:
            product = deb_control(path)
        except OSError:
            product = {}
        if not product and have("dpkg-deb"):
            r = run(["dpkg-deb", "-f", path, "Package", "Version", "Maintainer"], timeout=20)
            text = r.stdout.decode("utf-8", "ignore") if r is not None and r.returncode == 0 else ""
            fields = dict(re.findall(r"^(Package|Version|Maintainer):\s*(.+)$", text, re.M))
            product = {"name": fields.get("Package", ""), "version": fields.get("Version", ""),
                       "company": fields.get("Maintainer", "")} if fields else {}
        return product
    if path.lower().endswith(".rpm") and have("rpm"):
        r = run(["rpm", "-qp", "--qf", "%{NAME}\t%{VERSION}\t%{VENDOR}", path], timeout=20)
        rows = _rows(r)
        if rows:
            return {"name": rows[0]["name"], "version": rows[0]["version"], "company": rows[0]["publisher"]}
    return {}


# ---------------------------------------------------------------- screen and OCR
def screen_sizes() -> set[tuple[int, int]]:
    """The preferred mode of every connected screen (/sys/class/drm), in pixels."""
    sizes: set[tuple[int, int]] = set()
    for connector in glob.glob("/sys/class/drm/card*-*"):
        try:
            with open(os.path.join(connector, "status"), encoding="ascii") as f:
                if f.read().strip() != "connected":
                    continue
            with open(os.path.join(connector, "modes"), encoding="ascii") as f:
                first = f.readline().strip()
        except OSError:
            continue
        m = re.match(r"(\d+)x(\d+)", first)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            sizes |= {(w, h), (h, w)}
    return sizes


@lru_cache(maxsize=1)
def _tesseract() -> tuple[str, str] | None:
    exe = have("tesseract")
    if not exe:
        return None
    r = run([exe, "--list-langs"], timeout=20)
    langs = set(r.stdout.decode("utf-8", "ignore").split()[1:]) if r is not None and r.returncode == 0 else set()
    return exe, ocr_languages(langs)


def ocr(png: str) -> str:
    """Text recognition with Tesseract, when installed (sudo apt install tesseract-ocr tesseract-ocr-ita)."""
    engine = _tesseract()
    if not engine:
        return ""
    r = run([engine[0], png, "stdout", "-l", engine[1]], timeout=90, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    return r.stdout.decode("utf-8", "ignore") if r is not None and r.returncode == 0 else ""


def ocr_engine() -> str | None:
    engine = _tesseract()
    return f"Tesseract ({engine[1]})" if engine else None
