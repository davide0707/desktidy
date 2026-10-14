# Contributing to DeskTidy

Thanks for helping! Bug reports, ideas, rules in other languages and pull requests are all welcome.

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

The tests are isolated: temporary folders, no AI, no internet, never your real files, registry or autostart entries.
[docs/development.md](docs/development.md) explains the project layout, the conventions and how the Windows build and
the releases work.

## Guidelines

- **Never surprise the user.** Moves stay logged and undoable; files starting with `!`, open files and private files
  stay untouched; folder changes show a plan first; anything that removes a file sends it to the Recycle Bin / Trash
  after a confirmation.
- **Offline first.** New understanding belongs in `content.py` / `classifier.py`; the AI is an option.
- **Private stays private.** Nothing new is sent to an AI service without saying so in
  [docs/ai-and-privacy.md](docs/ai-and-privacy.md), and every request goes through `redact.outgoing()`.
- **Spend nothing by accident.** Keep AI requests compact; say in the pull request how a change to `ai.py` affects
  the tokens sent per file.
- **Keep it readable.** Small functions, clear names, a docstring where the *why* isn't obvious.
- **Test it.** Add or update a test for every behaviour change, and a line in `CHANGELOG.md`.

## Good first issues

- More bundled rules and keywords (other languages welcome) in `desktidy/default_rules.json`.
- More file formats in `content.py`.
- More deadline phrasings (other languages) in `deadlines.py`.
- Translations of the console and notifications.

## Reporting a bug

Open an issue with your system (Windows, macOS or Linux and its version, and the desktop on Linux), the output of
`desktidy about` and `desktidy log errors`, and, if possible, `desktidy explain <file>` for the file that went wrong.
Please remove personal paths and names first. Security problems: see [SECURITY.md](SECURITY.md).

## License of contributions

DeskTidy is licensed under the [GNU General Public License v3.0 or later](LICENSE). By contributing you agree that
your contributions are licensed under the same terms. New source files start with the license identifier and their
author:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) <year> <your name>
```
