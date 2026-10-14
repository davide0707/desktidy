## What and why

<!-- What does this change and which problem does it solve? Link the issue if there is one. -->

## Checklist

- [ ] `python -m unittest discover -s tests -t .` passes
- [ ] `ruff check .` passes
- [ ] Tests added or updated for the new behaviour
- [ ] `CHANGELOG.md` and, if needed, the documentation in `docs/` updated
- [ ] Moves stay logged and undoable; nothing is deleted
- [ ] Privacy: nothing new leaves the computer, or `docs/ai-and-privacy.md` says what and why
- [ ] If `ai.py` changed: the effect on the tokens sent per file is described
- [ ] New source files start with `# SPDX-License-Identifier: GPL-3.0-or-later`
