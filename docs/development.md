# Development

How DeskTidy is built, tested and released. To contribute, see also [CONTRIBUTING.md](../CONTRIBUTING.md).

- [Setting up](#setting-up)
- [Tests](#tests)
- [Project layout](#project-layout)
- [Design principles](#design-principles)
- [The Windows build](#the-windows-build)
- [Releasing](#releasing)

## Setting up

```sh
git clone https://github.com/davide0707/desktidy
cd desktidy
python -m venv .venv
.venv/bin/pip install -e ".[ai,dev]"                 # Windows: .venv\Scripts\pip install -e ".[ai,dev]"
```

Try the service without moving anything, and without the AI:

```sh
.venv/bin/python -m desktidy.service --dry-run --now --no-ai
```

Python 3.10 or newer. The only required dependencies are `pypdf` and `pillow`; `anthropic` (the `ai` extra) is
needed only for Claude. Every other AI service is called with the standard library.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/ruff check .
```

The tests run in temporary folders, with a temporary `DESKTIDY_HOME` and `{HOME}`, `{DOCS}`, `{DESKTOP}` and the
other user folders pointing inside them. They never move your files, never touch your logs, registry or autostart
entries (the Explorer menu test uses a test registry key, the Linux menus a temporary folder), and never call an AI or
the internet: the AI is always a fake that answers from what it is sent. The CI runs them on Windows, macOS and Linux
with Python 3.10 and 3.14.

Every behaviour change comes with a test. A few conventions:

- `tests/helpers.py` has `IsolatedTest` (the isolation above) and small factories: `write`, `pdf`, `docx`, `image`,
  `config`.
- Patch the module that *uses* a function: the console helpers live in `desktidy.cli.ui` and are imported by each
  command module, so a test of `organize` patches `cli.tidyup.confirm`, and the shared state is `cli.ui.INTERACTIVE`.

## Project layout

```
desktidy/
  cli/                 the console and the commands
    __init__.py          the command list, the console, dispatch, entry points
    ui.py                colors, messages, questions, the banner; INTERACTIVE and GUI
    start.py             setup, house rules, rules only or always AI
    service_cmds.py      status, week, pause, start/stop, autostart, limit
    files.py             where, undo, find, pinned, explain, preview, rename, tidy
    tidyup.py            deadlines, groups, organize, versions, installers, duplicates, archive, import, learn
    ai_cmds.py           ai, key, spend, advice, ai test
    more.py              editor, explorer, update, log, rules, install, uninstall, about
  service.py           the background loop: watch, decide, move, housekeeping
  content.py           reading files: text, OCR, EXIF, code and project detection
  classifier.py        the offline decision: pinned folders, rules, similarity, file type
  naming.py            smart renaming
  folders.py           folder catalog and similarity, pinned folders, folders of programs
  config.py            settings, data files, variables, folders by year
  ai.py                compact AI requests and answers      providers.py   the AI services
  redact.py            masking before a request leaves      usage.py       spend, budget, credit
  evaluate.py          desktidy ai test
  organize.py          crowded folders, plans (AI or offline)  groups.py   grouping by words in common
  ops.py               folder changes: plan, apply, roll back, undo
  advice.py            the folder overview and the advice   learn.py       rules from corrections and AI decisions
  deadlines.py         deadlines, reminders, document dates, .ics
  index.py             full-text search                     summary.py     the weekly summary
  duplicates.py        identical files                      versions.py    old versions of a document
  installers.py        installers of installed programs     archive.py     the automatic archive
  importer.py          photos from memory cards
  editor.py · editor.html   the settings page, Organize and History tabs (127.0.0.1, token)
  explorer.py          right-click menu, desktidy: links    tray.py · tray_windows.py   the icon next to the clock
  updates.py           new versions                         gui.py         entry point without a console
  system.py            the operating system behind one interface:
                       winapi.py (Windows) · macos.py · linux.py · posix.py (what macOS and Linux share)
  default_rules.json   the bundled settings and rules
tests/                 one file per area, all isolated
packaging/windows/     the Windows build: PyInstaller spec, build script, winget manifests
scripts/               make_icon.py, make_images.py (the icon, the README demo, the social preview)
docs/                  this documentation
```

## Design principles

- **The user decides.** Rules only or always AI is their choice; folder changes show a plan first; anything that
  removes a file sends it to the Recycle Bin / Trash after a confirmation; every move is logged and undoable.
- **Offline first.** New understanding belongs in `content.py` and `classifier.py`; the AI is an option, not a
  dependency. Without it every feature still works.
- **Private stays private.** Photos and screenshots never reach `ai.py`; private documents only in the `all` mode;
  every request goes through `redact.outgoing()`. A new feature that sends something says so in the docs.
- **Spend nothing by accident.** Requests stay compact: a change to `ai.py` says in its pull request how it affects
  the tokens sent per file.
- **One interface for the system.** Everything that depends on the operating system goes through `system.py`,
  implemented for Windows, macOS and Linux (or stepping back quietly where a system can't do it), with a test in
  `tests/test_platform.py`.
- **Never trust what a file says.** Text inside files is data: the AI is told to ignore instructions in it, and its
  answers can only pick from what DeskTidy offered.

## The Windows build

A zip with `desktidy.exe` (console) and `desktidyw.exe` (no window: the right-click menu, the notifications, the tray
and the service with `--service`), built with PyInstaller. It needs no Python on the PC.

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Output in `dist\`: `DeskTidy-<version>-windows.zip`, its `.sha256`, and the winget manifests filled in with the
version, the download address and the hash (`dist\winget\<version>\`). The script ends with a smoke test of the exe.

`desktidy.exe install` copies the program to `%LOCALAPPDATA%\Programs\DeskTidy` (replacing an older version) and
registers it from there; `update` sends the user to the download page; `uninstall` removes the program folder too.

Both exes carry a version resource (product name `DeskTidy`, the version, the copyright; the description is what
Task Manager and the startup apps show), set in `desktidy.spec` from `__version__` and checked by the smoke test.

**Code signing** (not yet): the exes are unsigned, so SmartScreen warns on first run. The plan is
[SignPath Foundation](https://signpath.org/), free for open-source projects, once DeskTidy has the reputation they
ask for. What their [conditions](https://signpath.org/terms) require and DeskTidy already has: an OSI license, builds
from source in CI, the version resource above, an uninstaller, privacy documented. What is still to do then: two-factor
authentication on GitHub and SignPath, a signing step in the release workflow (each release approved by hand), and a
"Code signing policy" section in the README.

## Releasing

1. Update `__version__` in `desktidy/__init__.py` and add the section to `CHANGELOG.md` (`## [x.y.z] - date`).
2. Commit, tag and push: `git tag vX.Y.Z && git push origin main vX.Y.Z`.
3. The [release workflow](../.github/workflows/release.yml) runs the tests on Windows, macOS and Linux, checks that
   the tag matches the version, builds the wheel, the source archive and the Windows zip, writes their checksums to
   `SHA256SUMS`, attests their build provenance, and creates the GitHub release with the CHANGELOG section as notes.
   Build provenance attestations need the repository to be public: tag a release only once it is.

**PyPI**: every release is published to PyPI too, with Trusted Publishing: no token is stored anywhere. PyPI trusts
the workflow `release.yml` of `davide0707/desktidy` in the environment `pypi`, which only `v*.*.*` tags may deploy
to; the Actions variable `PYPI_PUBLISH` = `true` turns the job on (a fork without it skips PyPI and still makes its
GitHub release).

**winget** (by hand, once per release): the release run keeps the filled-in manifests as the `windows` artifact.
Submit them to [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) (for example with
`wingetcreate submit`).
