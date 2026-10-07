# Contributing to DeskTidy

Thanks for helping! Bug reports, ideas, new rules and pull requests are all welcome.

## Getting started

```bat
git clone https://github.com/davide0707/desktidy
cd desktidy
python -m venv .venv
.venv\Scripts\pip install -e ".[ai,dev]"
```

Run the checks before opening a pull request:

```bat
.venv\Scripts\python -m unittest discover -s tests -t .
.venv\Scripts\ruff check .
```

Tests use temporary folders and a temporary `DESKTIDY_HOME`, never call the AI and never touch your real files.
To try the service without moving anything: `.venv\Scripts\desktidy-service --dry-run --now`.

## Guidelines

- **Offline first.** New understanding belongs in `content.py` / `classifier.py`; the AI is the last resort.
- **Spend nothing by accident.** Any change to `ai.py` must keep requests compact; say in the pull request how it
  affects the tokens sent per file (`client.messages.count_tokens` is free).
- **Never surprise the user.** Moves must stay logged and undoable; files starting with `!`, open files and private
  files must stay untouched.
- **Keep it readable.** Small functions, clear names, a docstring where the *why* isn't obvious.
- Add or update a test for every behaviour change, and a line in `CHANGELOG.md`.

## Good first issues

- More bundled rules and keywords (other languages welcome).
- More file formats in `content.py`.
- A system tray icon.

## Reporting a bug

Open an issue with your Windows version, the output of `desktidy about` and `desktidy log errors`, and, if possible,
`desktidy explain <file>` for the file that went wrong. Please remove personal paths and names first.
