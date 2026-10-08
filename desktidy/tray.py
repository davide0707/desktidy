"""The DeskTidy icon in the notification area (system tray), next to the clock: state at a glance in the tooltip,
and a menu with the latest moves, upcoming deadlines, advice, search, pause and resume, settings.

Plain Win32 through ctypes (Shell_NotifyIcon + a hidden window + its message loop, on its own thread of the
background service): no extra library. Turn it off with "tray": false in rules.json.
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from datetime import date, datetime, timedelta

from . import APP_NAME, __version__, config

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0000
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_TRAY = 0x8000 + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
MF_STRING, MF_GRAYED, MF_POPUP, MF_SEPARATOR = 0x0, 0x1, 0x10, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
user32.LoadIconW.restype = wintypes.HICON
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.LPVOID]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


# ---------------------------------------------------------------- the menu (pure: testable)
def menu_model(running: bool = True) -> list:
    """[(label, action or None, enabled) | None (separator) | (label, [submenu])]. Actions are tuples."""
    from . import advice, deadlines, usage
    from .service import paused_until, read_moves
    paused, until = paused_until()
    state = "paused" + (f" until {until:%H:%M}" if until else "") if paused else ("running" if running else "stopped")
    moves = [m for m in read_moves() if m["action"] == "MOVED"]
    today = [m for m in moves if m["time"].startswith(date.today().isoformat())]
    ai_today = usage.read()["today_files"]
    model: list = [(f"{APP_NAME} {__version__} · {state}", None, False),
                   (f"Tidied today: {len(today)} · AI today: {ai_today}", None, False), None]
    recent = [(f"{os.path.basename(m['destination'])[:40]}  →  {os.path.basename(os.path.dirname(m['destination']))}",
               ("reveal", m["destination"]), True) for m in moves[-8:][::-1]]
    model.append(("Latest moves", recent + [None, ("All moves...", ("console", "where"), True)]) if recent
                 else ("Latest moves (none yet)", None, False))
    due = deadlines.upcoming()[:6]
    if due:
        items = [(f"{d['date'][8:10]}/{d['date'][5:7]}  {d['what'][:38]}" + (f"  {d['amount']}" if d.get("amount") else ""),
                  ("open", d["path"]) if d.get("path") else ("console", "deadlines"), True) for d in due]
        model.append((f"Deadlines ({len(due)})", items + [None, ("All deadlines...", ("console", "deadlines"), True)]))
    tips = advice.load().get("tips", [])
    model += [(f"Advice ({len(tips)} ideas)..." if tips else "Advice...", ("console", "advice"), True),
              ("Search files...", ("console", "find"), True), None]
    if paused:
        model.append(("Resume", ("resume",), True))
    else:
        model += [("Pause for 1 hour", ("pause", "1h"), True), ("Pause until tomorrow", ("pause", "tomorrow"), True)]
    model += [None, ("Open console", ("console", ""), True), ("Settings...", ("editor",), True), None,
              ("Stop DeskTidy", ("stop",), True)]
    return model


def run_action(action: tuple) -> None:
    from .explorer import open_console
    kind = action[0]
    if kind == "reveal":
        from .ops import current_path
        from .winapi import reveal
        reveal(current_path(action[1]))
    elif kind == "open":
        if os.path.exists(action[1]):
            os.startfile(action[1])
    elif kind == "console":
        open_console(*([action[1]] if action[1] else []))
    elif kind == "editor":
        open_console("editor")
    elif kind == "pause":
        until = (datetime.now() + timedelta(hours=1) if action[1] == "1h"
                 else datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=8))
        with open(config.path("pause"), "w", encoding="utf-8") as f:
            f.write("until=" + until.isoformat(timespec="seconds"))
    elif kind == "resume":
        try:
            os.remove(config.path("pause"))
        except OSError:
            pass
    elif kind == "stop":
        with open(config.path("stop"), "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat(timespec="seconds"))


# ---------------------------------------------------------------- the icon
class Tray:
    def __init__(self, tooltip: str = APP_NAME):
        self.hwnd = None
        self.icon = None
        self.tooltip = tooltip
        self.ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)  # kept alive: Windows calls it
        self._actions: dict[int, tuple] = {}
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")

    def _data(self, flags: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd, nid.uID, nid.uFlags, nid.uCallbackMessage = self.hwnd, 1, flags, WM_TRAY
        nid.hIcon = self.icon
        nid.szTip = self.tooltip[:127]
        return nid

    def _add(self) -> None:
        nid = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def update(self, tooltip: str) -> None:
        """New tooltip (any thread)."""
        self.tooltip = tooltip
        if self.hwnd:
            nid = self._data(NIF_TIP)
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _build(self, items: list, menu) -> None:
        for entry in items:
            if entry is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            elif isinstance(entry[1], list):
                sub = user32.CreatePopupMenu()
                self._build(entry[1], sub)
                user32.AppendMenuW(menu, MF_POPUP, sub, entry[0])
            else:
                label, action, enabled = entry
                n = len(self._actions) + 1
                if action:
                    self._actions[n] = action
                user32.AppendMenuW(menu, MF_STRING | (0 if enabled and action else MF_GRAYED), n, label)

    def _menu(self) -> None:
        from . import winapi
        self._actions = {}
        menu = user32.CreatePopupMenu()
        try:
            self._build(menu_model(winapi.instance_running(config.SERVICE_MUTEX)), menu)
        except Exception as ex:  # a broken data file must not break the menu
            user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, f"DeskTidy: {type(ex).__name__}")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        chosen = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, self.hwnd,
                                       None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if chosen in self._actions:
            try:
                run_action(self._actions[chosen])
            except Exception:
                pass

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY and (lparam & 0xFFFF) in (WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU):
            self._menu()
            return 0
        if msg == self._taskbar_created:  # Explorer restarted: add the icon again
            self._add()
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            nid = self._data(0)
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def loop(self) -> None:
        """Create the hidden window and the icon, then run the message loop (blocks: call it on its own thread)."""
        instance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = instance
        wc.lpszClassName = "DeskTidyTray"
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "DeskTidyTray", "DeskTidy", 0, 0, 0, 0, 0, None, None, instance, None)
        icon_file = str(config.PACKAGE_DIR / "icon.ico")
        self.icon = user32.LoadImageW(None, icon_file, 1, 0, 0, 0x10 | 0x40) if os.path.exists(icon_file) else None
        self.icon = self.icon or user32.LoadIconW(None, ctypes.c_void_p(32512))
        self._add()
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.hwnd = None

    def stop(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)


def start(tooltip: str = APP_NAME) -> Tray:
    tray = Tray(tooltip)
    threading.Thread(target=tray.loop, name="tray", daemon=True).start()
    tray.ready.wait(5)
    return tray
