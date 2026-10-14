# Commands

Type `desktidy` for the console (a numbered menu: type a number or a command), or `desktidy <command>` from any
terminal. `desktidy help` lists everything. Commands that change your files show what they would do and ask first;
in scripts, `--yes` confirms in advance (`organize apply`, `advice apply`, `duplicates clean`, `installers clean`,
`ai test`).

- [Start here](#start-here) · [Service](#service) · [Files](#files) · [Tidy up](#tidy-up) · [AI](#ai) · [More](#more)

## Start here

| Command | What it does |
|---|---|
| `setup` | first-run setup: the house rules, at least two pinned folders, a daily limit, rules only or always AI |
| `guide` | the [house rules](house-rules.md) |

## Service

DeskTidy works in the background, started at sign-in.

| Command | What it does |
|---|---|
| `status` | running or stopped, pause, limits, AI, OCR, deadlines, search index, the latest moves |
| `week` | the last 7 days: files tidied and renamed, duplicates, deadlines, the to-sort pile, the AI |
| `week off` · `week on` · `week day friday` | the weekly notification (on, Monday by default) |
| `pause` · `pause 30m` · `pause 2h` · `pause 1h30m` · `pause 1d` · `pause 18:30` | pause until you resume, for a while, or until a time |
| `resume` | end the pause |
| `start` · `stop` · `stop forever` · `restart` | the background service (`stop` lasts until the next sign-in) |
| `autostart on` · `autostart off` | start at sign-in |
| `limit 30` · `limit unlimited` | files tidied per day at most, with or without the AI |

## Files

| Command | What it does |
|---|---|
| `where invoice` · `where --all` · `where invoice --open` | where did a file go, and why (`--open` shows it in the file manager) |
| `undo` · `undo invoice` · `undo 2` · `undo #1a2b3c4d` | put a file back where it was, with its old name |
| `find electricity bill september` · `find ... --open` | search your documents by content (OCR included) |
| `find --rebuild` · `find --rebuild --ocr` | index the documents already in your folders now |
| `pinned` · `pin recipes cooking pasta` · `unpin recipes` · `pinned suggest` | pinned folders (a new name is created on the Desktop) |
| `explain report.pdf` · `explain report.pdf --ai` | what DeskTidy understands of a file, where it would go and why (`--ai`: ask the AI too, never for private files unless you chose always AI) |
| `preview` · `preview --now` · `preview --ai` | what it would do now, moving nothing (`--now`: ignore the waiting times) |
| `rename smart` · `rename generic` · `rename off` | how bold renaming is |
| `tidy report.pdf` | tidy one file or folder now |

## Tidy up

| Command | What it does |
|---|---|
| `deadlines` | bills and deadlines found in your documents |
| `deadlines done 2` · `deadlines open 2` · `deadlines remove 2` · `deadlines undone 2` | paid or submitted, open the document, forget it, remind again |
| `deadlines add 2026-10-30 Pay the rent` | add one by hand (also `30/10/2026` or `"30 ottobre"`) |
| `deadlines scan bill.pdf` | look for deadlines in one file |
| `deadlines ics` · `deadlines ics calendar.ics --open` | the open deadlines as a calendar file, with the same reminders |
| `groups` · `groups apply 1 --pin` · `groups apply 1 --to Projects` | the to-sort pile, grouped into folders |
| `organize` | the crowded folders among yours |
| `organize desktop` · `organize 2` · `organize C:\Users\me\Stuff` · `organize all` | a plan: loose items grouped into folders (`--offline`: without the AI) |
| `organize plan` · `organize apply 2` · `organize apply all --pin` · `organize undo` | the saved plan, do one group or all after a preview, put everything back |
| `versions` · `versions Documents\Thesis` · `versions apply 1` · `versions apply all` | old versions of the same document, set aside in `_old_versions` |
| `installers` · `installers clean` | setup files of programs that are already installed, to the Recycle Bin / Trash |
| `duplicates` · `duplicates clean` · `duplicates clean 3` | the same file in two places: one stays, the others to the Recycle Bin / Trash |
| `archive` · `archive on` · `archive off` · `archive now` · `archive after 120` · `archive zip on` | items untouched for months, moved to `Archive/<year>` |
| `import E:` · `import /Volumes/CARD` · `import auto on` | photos and videos copied from a memory card, sorted by date |
| `learn` · `learn accept 1` · `learn reject 1` | rules learned from your corrections and from the AI |

## AI

See [AI and privacy](ai-and-privacy.md) for the modes, the services and what each one sees.

| Command | What it does |
|---|---|
| `ai` | the current mode, service and model |
| `ai rules` · `ai limited` · `ai moderate` · `ai ai-only` · `ai all` | how much AI: rules only, ..., always AI (`ai all` names the service and asks before private documents go to the internet) |
| `ai provider` · `ai provider groq` | choose the service: `groq`, `gemini`, `mistral`, `openrouter`, `ollama`, `claude`, `openai`, `custom` |
| `ai model <id>` · `ai max 50` · `ai max unlimited` · `ai max auto` | the model, and how many files the AI looks at per day |
| `ai delivery batch` · `ai delivery instant` · `ai confidence high` · `ai confidence medium` | Claude's half-price batches, and which answers are accepted |
| `ai test` · `ai test --dry` | how well the service sorts and names 18 made-up documents (`--dry`: what would be sent, nothing is) |
| `key` · `key test` · `key remove` | the API key of the service |
| `spend` · `spend credit 4.85` · `spend budget 10` · `spend web` | what the AI cost, the remaining credit, the total budget |
| `advice` · `advice new` · `advice apply 2` · `advice undo` · `advice open 2` · `advice pin 2` | ideas to organise your folders, applied after a preview |

## More

| Command | What it does |
|---|---|
| `editor` | every setting in your browser, plus the *Organize* and *History* tabs |
| `explorer on` · `explorer off` | the right-click menu and the notification buttons |
| `update` | check for a new version and install it (the Windows build: the download page) |
| `log` · `log 100` · `log errors` · `log open` | the activity log |
| `rules` · `rules check` | open `rules.json`, or check it |
| `open` | the data folder |
| `install` · `uninstall` | the command, the start at sign-in and the right-click menu |
| `about` | version, author, license, folders |

Every command has short or translated aliases (`s` for `status`, `cerca` for `find`, `scadenze` for `deadlines`,
`riordina` for `organize`, `doppioni` for `duplicates`...): `desktidy help` lists them.
