"""Windows integration: single instance, files in use, Recycle Bin, notifications, user environment,
Task Scheduler and console colors. Everything here is a thin wrapper around a Windows API or tool."""

from __future__ import annotations

import base64
import ctypes
import os
import re
import subprocess
import winreg
from ctypes import wintypes

NO_WINDOW = 0x08000000
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                             wintypes.DWORD, wintypes.HANDLE]
_k32.OpenMutexW.restype = wintypes.HANDLE
_k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]


# ---------------------------------------------------------------- processes and files
def claim_single_instance(name: str) -> bool:
    """Create a named mutex; False if another process already owns it. The handle lives as long as the process."""
    _k32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def instance_running(name: str) -> bool:
    handle = _k32.OpenMutexW(0x00100000, False, name)  # SYNCHRONIZE
    if handle:
        _k32.CloseHandle(handle)
        return True
    return False


def file_in_use(path: str) -> bool:
    """True if another program has the file open (we ask for exclusive read access)."""
    handle = _k32.CreateFileW(path, 0x80000000, 0, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        return True
    _k32.CloseHandle(handle)
    return False


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def recycle(path: str) -> bool:
    """Send to the Recycle Bin silently (FO_DELETE + ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI)."""
    op = _SHFILEOPSTRUCTW(None, 3, path + "\0", None, 0x40 | 0x10 | 0x4 | 0x400, False, None, None)
    ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return not os.path.exists(path)


# ---------------------------------------------------------------- user interface
def notify(title: str, body: str) -> None:
    """Windows toast notification, sent through PowerShell (no extra dependency, no registration)."""
    def esc(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "''"))
    app = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType = WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>{esc(title)}</text>"
        f"<text>{esc(body)}</text></binding></visual></toast>');"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app}')"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($x))")
    try:
        subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                          "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode()],
                         creationflags=NO_WINDOW)
    except OSError:
        pass


def ask_yes_no(text: str, title: str) -> bool:
    """Topmost Yes/No message box (blocks the calling thread until answered)."""
    return ctypes.windll.user32.MessageBoxW(None, text, title, 0x4 | 0x20 | 0x10000 | 0x40000) == 6


def enable_ansi() -> bool:
    """Turn on ANSI colors in the Windows console. False when output is redirected."""
    try:
        handle = _k32.GetStdHandle(-11)
        mode = wintypes.DWORD()
        if not _k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(_k32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except OSError:
        return False


def open_path(path: str) -> None:
    os.startfile(path)


def reveal(path: str) -> None:
    """Open Explorer with the file selected (or its folder, if the file is gone)."""
    if os.path.exists(path):
        subprocess.Popen(f'explorer /select,"{path}"')
    else:
        subprocess.Popen(f'explorer "{os.path.dirname(path)}"')


# ---------------------------------------------------------------- user environment
def _broadcast_environment_change() -> None:
    result = wintypes.DWORD()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 0x2, 3000, ctypes.byref(result))


def get_user_env(name: str) -> tuple[str, int]:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            return winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return "", winreg.REG_EXPAND_SZ


def set_user_env(name: str, value: str | None, kind: int = winreg.REG_SZ) -> None:
    """Like setx: persistent user variable (None deletes it). New programs see it immediately."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        if value:
            winreg.SetValueEx(key, name, 0, kind, value)
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
    _broadcast_environment_change()


def api_key() -> str | None:
    """ANTHROPIC_API_KEY read from the user environment in the registry, so a new key works without restarting
    the service; falls back to the process environment."""
    try:
        value, _ = get_user_env("ANTHROPIC_API_KEY")
    except OSError:
        value = ""
    return (value or os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None


def set_api_key(key: str | None) -> None:
    set_user_env("ANTHROPIC_API_KEY", key)


def mask(key: str | None) -> str:
    if not key:
        return "(none)"
    return key[:12] + "..." + key[-4:] if len(key) > 20 else "***"


def path_entries() -> list[str]:
    value, _ = get_user_env("Path")
    return [p for p in value.split(";") if p.strip()]


def add_to_path(folder: str) -> bool:
    entries = path_entries()
    if any(os.path.normcase(p.rstrip("\\")) == os.path.normcase(folder.rstrip("\\")) for p in entries):
        return False
    _, kind = get_user_env("Path")
    set_user_env("Path", ";".join(entries + [folder]), kind or winreg.REG_EXPAND_SZ)
    return True


def remove_from_path(folder: str) -> bool:
    entries = path_entries()
    kept = [p for p in entries if os.path.normcase(p.rstrip("\\")) != os.path.normcase(folder.rstrip("\\"))]
    if len(kept) == len(entries):
        return False
    _, kind = get_user_env("Path")
    set_user_env("Path", ";".join(kept), kind or winreg.REG_EXPAND_SZ)
    return True


# ---------------------------------------------------------------- Task Scheduler
def task_info(name: str) -> dict:
    """{"exists", "enabled", "at_logon", "command"} read from the task XML (the same in every Windows language)."""
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", name, "/xml"], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return {"exists": None}
    if r.returncode != 0:
        return {"exists": False}
    raw = r.stdout
    xml = raw.decode("utf-16", "ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("mbcs", "ignore")
    settings = re.search(r"<Settings>(.*?)</Settings>", xml, re.S)
    disabled = settings and re.search(r"<Enabled>\s*false\s*</Enabled>", settings.group(1))
    command = re.search(r"<Command>(.*?)</Command>", xml)
    return {"exists": True, "enabled": not disabled, "at_logon": "<LogonTrigger>" in xml,
            "command": command.group(1).strip('"') if command else ""}


def schtasks(name: str, *args: str) -> bool:
    r = subprocess.run(["schtasks", *args, "/tn", name], capture_output=True, timeout=30)
    return r.returncode == 0


def register_logon_task(name: str, executable: str, workdir: str, start_now: bool = True) -> bool:
    """Run `executable` at every sign-in of the current user: normal priority, restarted if it crashes."""
    q = lambda s: "'" + s.replace("'", "''") + "'"  # noqa: E731 - PowerShell single-quoted string
    script = f"""
$ErrorActionPreference = 'Stop'
$user = "$env:USERDOMAIN\\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute {q(executable)} -WorkingDirectory {q(workdir)}
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -Priority 6
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive
Register-ScheduledTask -Force -TaskName {q(name)} -Description 'Keeps Downloads, Desktop and Documents tidy.' `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
{"Start-ScheduledTask -TaskName " + q(name) if start_now else ""}
"""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                        base64.b64encode(script.encode("utf-16-le")).decode()], capture_output=True, timeout=60)
    return r.returncode == 0
