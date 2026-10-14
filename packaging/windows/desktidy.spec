# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
# PyInstaller spec of the Windows build: one folder, DeskTidy\, with desktidy.exe (console) and desktidyw.exe
# (no window) sharing the same libraries. Built by build.ps1; nothing else is needed on the PC (no Python).
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = os.path.abspath(SPECPATH)  # noqa: F821 - defined by PyInstaller
ROOT = os.path.dirname(os.path.dirname(HERE))
ICON = os.path.join(ROOT, "desktidy", "icon.ico")
DATA = collect_data_files("desktidy")                 # rules, editor page, icons, OCR scripts
HIDDEN = collect_submodules("desktidy")               # modules imported inside functions


def analysis(script):
    return Analysis([os.path.join(HERE, script)], pathex=[ROOT], datas=DATA, hiddenimports=HIDDEN,  # noqa: F821
                    excludes=["tkinter", "unittest", "pydoc", "test"], noarchive=False)


# run_*.py, not desktidy.py: a script named like the package would hide it ("desktidy is not a package")
console, windowed = analysis("run_desktidy.py"), analysis("run_desktidyw.py")
exes = []
for a, name, has_console in ((console, "desktidy", True), (windowed, "desktidyw", False)):
    exes.append(EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name=name, console=has_console,  # noqa: F821
                    icon=ICON, upx=False))

COLLECT(exes[0], console.binaries, console.datas, exes[1], windowed.binaries, windowed.datas,  # noqa: F821
        name="DeskTidy", upx=False)
