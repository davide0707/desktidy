#!/bin/sh
# DeskTidy installer for macOS and Linux: creates a private Python environment, installs DeskTidy in it, adds the
# `desktidy` command and starts the service at every sign-in. Safe to run again (it updates the installation).
#   sh install.sh
set -eu
root=$(cd "$(dirname "$0")" && pwd)
venv="$root/.venv"
python="$venv/bin/python"

printf '\n  DeskTidy setup\n\n'

if [ ! -x "$python" ]; then
    base=""
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
            base=$candidate
            break
        fi
    done
    if [ -z "$base" ]; then
        echo "  [-] Python 3.10+ is required."
        echo "      macOS: https://www.python.org/downloads/ (or: brew install python)"
        echo "      Linux: sudo apt install python3 python3-venv   (Fedora: sudo dnf install python3)"
        exit 1
    fi
    echo "  [*] Creating the Python environment (.venv)..."
    if ! "$base" -m venv "$venv"; then
        echo "  [-] The environment could not be created. Debian / Ubuntu: sudo apt install python3-venv"
        exit 1
    fi
fi

echo "  [*] Installing DeskTidy and its libraries..."
"$python" -m pip install --disable-pip-version-check -q --upgrade pip
if ! "$python" -m pip install --disable-pip-version-check -q -e "$root[ai]"; then
    echo "  [-] Installation failed"
    exit 1
fi

if [ "$(uname -s)" = "Linux" ] && ! command -v tesseract >/dev/null 2>&1; then
    echo "  [!] Optional, to read scans and pictures (OCR): sudo apt install tesseract-ocr tesseract-ocr-ita"
    echo "      (Fedora: sudo dnf install tesseract tesseract-langpack-ita · Arch: sudo pacman -S tesseract-data-ita)"
fi

"$venv/bin/desktidy" install
printf '\n  Done. Open a NEW terminal window and type:  desktidy\n'
