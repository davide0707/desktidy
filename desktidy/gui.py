"""Entry point without a console window (desktidyw.exe): used by the Explorer menu, the notification buttons and
the tray icon. Same commands as `desktidy`; results are shown as notifications, errors in a message box."""

from .cli import main_gui


def main() -> None:
    main_gui()


if __name__ == "__main__":
    main()
