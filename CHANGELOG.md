# Changelog

All notable changes to DeskTidy are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/)
and the project uses [Semantic Versioning](https://semver.org/).

## [1.4.0] - 2026-10-14

DeskTidy is now free software under the **GNU General Public License v3.0 or later** (it was MIT).

### Added
- **Rules only or always AI: you choose.** The setup asks how DeskTidy should understand your files: with its rules
  alone (`desktidy ai rules`, nothing leaves your computer) or always with the AI (`desktidy ai all`). The new `all`
  mode sends every file to the AI, bills, payslips and IDs included, and the AI names the files the rules would
  rename (`scan0001.pdf` becomes `Fattura_2231_Acme_Srl_2026-09-30.pdf`); photos, screenshots and programs stay
  offline. Before private documents go to a service on the internet DeskTidy names it and asks; with Ollama they
  never leave the computer. The existing modes are unchanged: `ai-only` still keeps private files offline.
- **Masking**: IBANs, card numbers, Italian tax codes, VAT numbers, e-mails and phone numbers are replaced before
  anything goes to an AI service on the internet (checked by their check digits, so amounts and dates stay).
  `"ai": {"redact": true}` by default; names and addresses are not masked.
- **`desktidy organize`**: the crowded folders among yours (Desktop, Downloads, Documents, the to-sort pile, the
  pinned folders), and for any of them a plan that groups the loose items into folders, new ones or folders you
  already have: by the AI, or offline (`--offline`, or when there is no AI). `organize apply <n | all>` after a
  preview, `organize undo` puts everything back. Also from the right-click menu (folders, the empty space of a
  folder, the Desktop) and from the browser.
- **Folders by year**: `{YEAR}` and `{MONTH}` in a destination, filled in from the date of each document (read by the
  AI, found in its text, or the day it was last changed).
- **`desktidy duplicates`**: identical files across your folders; one copy stays, the others go to the Recycle Bin /
  Trash after you confirm. Hard links, files only in the cloud, code projects and the folders of programs are never
  touched.
- **`desktidy deadlines ics`**: the deadlines as a calendar file (Outlook, Google Calendar, Apple Calendar) with the
  same reminders.
- **`desktidy week`** and a weekly summary notification: files tidied, duplicates, deadlines of the week, the AI.
- **Rules learned from the AI**: five files the AI put in the same folder and you left there become a proposed rule,
  so the next ones are placed offline.
- **`desktidy ai test`**: 18 made-up documents sent to the chosen service and scored (folder, name, document date,
  deadline); `--dry` shows what would be sent without sending it.
- **Organize and History tabs** in `desktidy editor`: the plan with a preview, do it, undo; the latest moves, each
  with *Undo*.
- **The Windows build**: a zip with `desktidy.exe` and `desktidyw.exe` that needs no Python; `desktidy.exe install`
  copies it to `%LOCALAPPDATA%\Programs\DeskTidy`. Built and attached to every GitHub release; winget manifests.
- Documentation in `docs/`: user guide, AI and privacy, commands, configuration, development.

### Changed
- License: GPL-3.0-or-later, with an SPDX header in every source file.
- AI names for invoices, bills, receipts and other dated documents: the kind, the number, who issued it and the
  document date.
- House rule 5 is now "Private stays private, unless you choose otherwise".
- `desktidy ai always` and `ai all` now choose the new `all` mode (they meant `ai-only` before); `ai rules` = `off`.
- `advice undo` (and `organize undo`) goes on when an item can't be put back because it was moved or deleted in the
  meantime, and lists it; an item whose old name was taken comes back as `name_v2`.
- `desktidy rules check` runs the same checks as saving in the editor.
- The console code is split into the `desktidy.cli` package (no change for users).
- The GitHub release no longer depends on PyPI: publishing there is optional (`PYPI_PUBLISH`).

### Fixed
- The folders of programs inside Documents (game saves, settings, code snippets) are never organised, moved by the
  advice or deduplicated.
- `explain --ai` never sends a private file to the AI unless you chose always AI.
- A local AI service (Ollama, custom) moved to another machine with `ai.base_url` is no longer treated as local.
- An unknown `{VARIABLE}` in a rule destination never creates a folder with that name: the file stays and the log
  says why.
- Rules learned from corrections into a private folder are private too.
- Deadline reminders say "in N days" from the day they are computed for, not always from today.
- A watched folder with `wait_seconds: 0` no longer skips a file whose time is a few microseconds in the future
  (Windows).
- The AI batch tests are skipped, not failed, when the optional `anthropic` package is not installed.

## [1.3.0] - 2026-10-09

### Added
- **macOS and Linux**, with the same engine, commands and tools as on Windows. Everything that depends on the system
  goes through one small interface (`system.py`) implemented for Windows, macOS and Linux:
  - start at sign-in: a launchd agent on macOS (restarted after a crash, not after `desktidy stop`), the desktop's
    autostart on Linux, or a systemd user service where there is no desktop;
  - OCR: the Vision framework on macOS, Tesseract on Linux (when installed);
  - the Trash: `trash` / Foundation on macOS (*Put Back* works), the freedesktop.org Trash specification on Linux;
  - notifications: osascript (clickable with terminal-notifier) on macOS, `notify-send` with working buttons on Linux;
    "Pin it?" dialogs with osascript, zenity or kdialog;
  - right-click menu on Linux: Files (Nautilus) scripts, Nemo actions and a Dolphin service menu;
  - installers already installed: `.dmg` / `.pkg` against `/Applications` on macOS, `.deb` / `.rpm` against dpkg,
    rpm and Flatpak on Linux (the `.deb` control file is read without dpkg);
  - memory cards in `/Volumes` and `/media`; files in use found with `lsof` and `/proc`; API keys in a `keys.json`
    readable only by you; the `desktidy` command in `~/.local/bin`; `sh install.sh` for source installs.
- **The real user folders** as built-in variables on every system: `{DOWNLOADS}`, `{DESKTOP}`, `{PICTURES}`,
  `{VIDEOS}` and `{MUSIC}` next to `{HOME}` and `{DOCS}` (Windows known folders, so Documents moved to OneDrive is
  found; `user-dirs.dirs` on Linux, so `Documenti` and `Scaricati` are found).
- `desktidy status` shows the OCR engine; `desktidy about` the system.
- The CI runs the tests on Windows, macOS and Linux.

### Changed
- Paths in `rules.json` may be written with `/` or `\` on every system, and `%USERPROFILE%` works on macOS and Linux
  too: a `rules.json` written on Windows keeps working. The bundled rules use `/` and the new variables.
- Programs for every system (`.dmg`, `.pkg`, `.deb`, `.rpm`, `.AppImage`...) only go to the installers folder.
- Shortcuts and launchers (`.desktop`, `.webloc`) and system files of macOS and Linux (`.DS_Store`, `.directory`) are
  never tidied; on macOS and Linux dot files count as hidden.
- A move to another disk is detected by the disk itself (also on macOS and Linux), and an unexpected "different
  device" error falls back to the checked copy.
- `desktidy stop` asks the service to finish with a signal as well (launchd, systemd and logout stop it cleanly).
- Mount points and every user folder are refused by `advice apply`, like drive roots.

## [1.2.0] - 2026-10-09

### Added
- **Daily limits you choose**: `desktidy limit 30 | unlimited` (files tidied per day, AI or not; the others wait for
  the next day) and `desktidy ai max 50 | unlimited | auto` (files the AI looks at). Asked during the setup.
- **Search by content**: `desktidy find <words>`. A local full-text index (SQLite FTS5) of every tidied document,
  OCR text included, kept up to date in the background; accents, plurals and singulars don't matter.
- **Deadlines**: payment and submission dates (and amounts) found offline in Italian and English documents, with
  reminders 7 days, 1 day and on the day (`desktidy deadlines`). The AI adds the date only when the patterns miss it.
- **One-line summaries** from the AI, in the same request (shown by `where` and `find`).
- **Applying the advice**: `desktidy advice apply <n>` merges, renames, moves, archives, creates or pins folders after
  showing a step-by-step plan; protected folders are refused, a failed step rolls everything back, rules, pinned
  folders, index and deadlines follow the moved folders, and `desktidy advice undo` reverts it.
- **Learning from corrections**: files you move yourself after DeskTidy placed them become proposed rules
  (`desktidy learn`, `learn accept <n>`).
- **The to-sort pile, grouped** (`desktidy groups`), **old versions** of a document set aside (`desktidy versions`),
  **installers of installed programs** found by product name and version (`desktidy installers`), an opt-in
  **automatic archive** (`desktidy archive`), **photo import** from memory cards sorted by date (`desktidy import`).
- **Explorer right-click menu** (Tidy now, Explain, Hands off, Pin / unpin, Old versions here) and **notifications
  with buttons** (Open, Undo, Done, Import, Review) through a checked `desktidy:` link. `desktidy explorer on | off`.
- **Tray icon** next to the clock: today's work, latest moves, deadlines, advice, search, pause, settings.
- **Settings in the browser**: `desktidy editor` (local, token-protected, validated before saving).
- **Updates**: a weekly anonymous check of the latest GitHub release and `desktidy update`; a release workflow that
  publishes to PyPI with Trusted Publishing (`pipx install desktidy`).
- `desktidyw.exe`: the same commands without a console window (used by Explorer, notifications and the tray).
- `{HOME}` and `{DOCS}` are always defined; folders DeskTidy creates are refused if they contain an unknown variable.

### Changed
- Moves have a short id (`#1a2b3c4d`): `desktidy undo <id>`, and `undo` also restores archived (and zipped) items.
- `where` follows folders moved by applied advice and shows the AI summary.
- Less work per AI file: the analysis is no longer deep-copied when a batch is saved.
- The console menu is reorganised: Service, Files, Tidy up, AI, More.

### Fixed
- Error responses of the AI services are closed properly (no leaked connections).

## [1.1.0] - 2026-10-08

### Added
- The AI checks file names: every file it looks at in `smart` rename mode is marked `name?` when the offline
  engine can't match its name with the content, and the AI replaces the name only when it is misleading or says
  nothing. Names that clearly fit are never sent for checking; an AI name must be meaningful and really different.
- Generic-named pictures and scans without readable text get a name from the AI when it sees the image.
- Organisation advice (`desktidy advice`): in `ai-only` mode, once DeskTidy has an overview of your files, the AI
  suggests better ways to organise files and folders, about once a week, with a notification. `advice new` asks at
  any time, `advice open <n>` and `advice pin <n>` act on a tip. Offline findings (growing To_Sort pile, empty or
  very full folders, clutter) are shown even without an AI.

### Changed
- Files for the AI that arrive close together wait up to `ai.gather_seconds` (90) to share one request: fewer
  requests on free plans, instructions and folder list paid once.
- Less work at every pass: the pinned folders and the files restored by `undo` are parsed again only when they
  change, and a folder still being written is no longer walked to the end.

### Fixed
- With the AI enabled, the background service failed at every pass that had a file for the AI
  (`'Logger' object is not callable`); a test now runs a full pass against a fake AI service.
- A file can no longer be taken for a duplicate of itself.

## [1.0.0] - 2026-10-07

First public release.

### Added
- Background service that tidies Downloads, Desktop and Documents, started at sign-in by Task Scheduler.
- Offline content engine: PDF, Office (new and old formats), LibreOffice, RTF, HTML, e-mail, notebooks, epub, text
  and code; Windows OCR for scans and images; photo, screenshot, icon and code detection; project detection inside
  folders and zip files; plural/singular and typo-tolerant matching.
- Smart renaming of generic or mismatched names from the document title, with an AI-suggested name as a fallback.
- Pinned folders with a learned context and a *"Pin it?"* prompt for new Desktop folders.
- First-run setup: house rules to accept and at least 2 pinned folders before anything is moved.
- Optional AI with four modes (`off`, `limited`, `moderate`, `ai-only`) and a choice of services: Groq, Google
  Gemini, Mistral, OpenRouter (free plans), Ollama (free, local), Claude and OpenAI (paid) or any
  OpenAI-compatible server. Designed for cost: per-file folder shortlists, several files per request, short
  excerpts, compact answers, Claude's Batch API at half price, and an automatic fallback when a service
  refuses a request feature.
- Spend tracking per day and model, budget, declared credit with an estimated remainder, automatic pause when the
  credit is exhausted.
- Kali-style console and one-shot commands: `setup`, `guide`, `status`, `pause`, `resume`, `start`, `stop`,
  `restart`, `autostart`, `where`, `undo`, `pinned`, `pin`, `unpin`, `explain`, `preview`, `rename`, `spend`, `ai`,
  `key`, `log`, `rules`, `open`, `install`, `uninstall`, `about`.
- Test suite (no network, temporary folders only) and GitHub Actions CI.

[1.4.0]: https://github.com/davide0707/desktidy/releases/tag/v1.4.0
[1.3.0]: https://github.com/davide0707/desktidy/tree/2920375e89c8a9222904580d72d2abfcc067de9e
[1.2.0]: https://github.com/davide0707/desktidy/tree/8a2f8f8bef25f6f6b46a067d1c6539ad15a1e9e9
[1.1.0]: https://github.com/davide0707/desktidy/tree/cd73bbd009b0e470d65a7d7195d18a9b5088949f
[1.0.0]: https://github.com/davide0707/desktidy/tree/fa5940fca8c042c838ca5d1cb344819be88711df
