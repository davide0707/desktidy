# Changelog

All notable changes to DeskTidy are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/)
and the project uses [Semantic Versioning](https://semver.org/).

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

[1.2.0]: https://github.com/davide0707/desktidy/releases/tag/v1.2.0
[1.1.0]: https://github.com/davide0707/desktidy/releases/tag/v1.1.0
[1.0.0]: https://github.com/davide0707/desktidy/releases/tag/v1.0.0
