# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""desktidyw.exe of the Windows build: no console window. The right-click menu, the notification buttons, the tray,
and the background service (desktidyw.exe --service, registered by desktidy.exe install)."""

from desktidy.gui import main

if __name__ == "__main__":
    main()
