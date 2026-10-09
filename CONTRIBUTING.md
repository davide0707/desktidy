# Contributing to DeskTidy

Thanks for helping! Bug reports, ideas, new rules and pull requests are all welcome.

## Getting started

```sh
git clone https://github.com/davide0707/desktidy
cd desktidy
python -m venv .venv
.venv/bin/pip install -e ".[ai,dev]"          # Windows: .venv\Scripts\pip install -e ".[ai,dev]"
```

Run the checks before opening a pull request (Windows: `.venv\Scripts\...`):

```sh
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/ruff check .
```

Tests use temporary folders, a temporary `DESKTIDY_HOME` and `{HOME}`, `{DOCS}` and the other user folders pointing
inside them; they never call the AI or the internet and never touch your real files, registry or autostart entries
(the Explorer menu test uses a test registry key, the Linux menus and autostart tests a temporary folder). The CI runs
them on Windows, macOS and Linux. To try the service without moving anything:
`.venv/bin/python -m desktidy.service --dry-run --now`.

## Where the system-specific code lives

Everything that depends on the operating system goes through `desktidy/system.py`, one small interface implemented
by `winapi.py` (Windows), `macos.py` and `linux.py`, with what macOS and Linux share in `posix.py`. The rest of
DeskTidy is plain Python: a new feature that needs the system adds one function to the interface, implemented for all
three (or stepping back quietly where the system can't do it), and a test in `tests/test_platform.py`.

## Guidelines

- **Offline first.** New understanding belongs in `content.py` / `classifier.py`; the AI is the last resort.
- **Spend nothing by accident.** Any change to `ai.py` must keep requests compact; say in the pull request how it
  affects the tokens sent per file (`client.messages.count_tokens` is free).
- **Never surprise the user.** Moves must stay logged and undoable; files starting with `!`, open files and private
  files must stay untouched.
- **Keep it readable.** Small functions, clear names, a docstring where the *why* isn't obvious.
- **Never act behind the user's back.** Folder changes show a plan first and can be undone; anything that deletes
  goes to the Recycle Bin / Trash after a confirmation.
- Add or update a test for every behaviour change, and a line in `CHANGELOG.md`.

## Good first issues

- More bundled rules and keywords (other languages welcome).
- More file formats in `content.py`.
- More deadline phrasings (other languages) in `deadlines.py`.
- Translations of the console and notifications.

## Reporting a bug

Open an issue with your system (Windows, macOS or Linux and its version, and the desktop on Linux), the output of
`desktidy about` and `desktidy log errors`, and, if possible, `desktidy explain <file>` for the file that went wrong.
Please remove personal paths and names first.

## Releasing

1. Update `__version__` in `desktidy/__init__.py` and add the section to `CHANGELOG.md` (`## [x.y.z] - date`).
2. Commit, then tag and push: `git tag vX.Y.Z && git push origin main vX.Y.Z`.
3. The [release workflow](.github/workflows/release.yml) runs the tests on Windows, macOS and Linux, checks that the
   tag matches the version, builds the package, publishes it to PyPI and creates the GitHub release with the
   CHANGELOG section as notes.

One-time setup on [pypi.org](https://pypi.org/manage/account/publishing/): add a *pending publisher* for project
`desktidy`, owner `davide0707`, repository `desktidy`, workflow `release.yml`, environment `pypi`. No token is stored
anywhere (Trusted Publishing).
