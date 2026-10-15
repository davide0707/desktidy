# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
# PyInstaller spec of the Windows build: one folder, DeskTidy\, with desktidy.exe (console) and desktidyw.exe
# (no window) sharing the same libraries. Built by build.ps1; nothing else is needed on the PC (no Python).
import os
import re

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

HERE = os.path.abspath(SPECPATH)  # noqa: F821 - defined by PyInstaller
ROOT = os.path.dirname(os.path.dirname(HERE))
ICON = os.path.join(ROOT, "desktidy", "icon.ico")
DATA = collect_data_files("desktidy")                 # rules, editor page, icons, OCR scripts
HIDDEN = collect_submodules("desktidy")               # modules imported inside functions
with open(os.path.join(ROOT, "desktidy", "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'^__version__ = "([^"]+)"', f.read(), re.M).group(1)


def version_info(name, description):
    """The Details tab of the exe's Properties: Task Manager and the startup apps show the description, and code
    signing (SignPath) requires the product name and version on every signed file."""
    numbers = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3]) + (0,)
    strings = {"CompanyName": "Di Filippo Davide", "FileDescription": description, "FileVersion": VERSION,
               "InternalName": name, "LegalCopyright": "Copyright (C) 2026 Di Filippo Davide. GPL-3.0-or-later.",
               "OriginalFilename": f"{name}.exe", "ProductName": "DeskTidy", "ProductVersion": VERSION}
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[StringFileInfo([StringTable("040904B0", [StringStruct(k, v) for k, v in strings.items()])]),
              VarFileInfo([VarStruct("Translation", [0x0409, 1200])])])


def analysis(script):
    return Analysis([os.path.join(HERE, script)], pathex=[ROOT], datas=DATA, hiddenimports=HIDDEN,  # noqa: F821
                    excludes=["tkinter", "unittest", "pydoc", "test"], noarchive=False)


# run_*.py, not desktidy.py: a script named like the package would hide it ("desktidy is not a package")
console, windowed = analysis("run_desktidy.py"), analysis("run_desktidyw.py")
exes = []
for a, name, has_console, description in ((console, "desktidy", True, "DeskTidy console"),
                                           (windowed, "desktidyw", False, "DeskTidy")):
    exes.append(EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name=name, console=has_console,  # noqa: F821
                    icon=ICON, upx=False, version=version_info(name, description)))

COLLECT(exes[0], console.binaries, console.datas, exes[1], windowed.binaries, windowed.datas,  # noqa: F821
        name="DeskTidy", upx=False)
