# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Entry point without a console window (desktidyw): used by the right-click menu, the notification buttons and
the tray icon. Same commands as `desktidy`; results are shown as notifications, errors in a message box.
`desktidyw --service [options]` runs the background service (the Windows build has no desktidy-service.exe)."""

import sys


def main() -> None:
    if sys.argv[1:2] == ["--service"]:
        from .service import main as service
        service(sys.argv[2:])
        return
    from .cli import main_gui
    main_gui()


if __name__ == "__main__":
    main()
