# Changelog

All notable changes to DeskTidy are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/)
and the project uses [Semantic Versioning](https://semver.org/).

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

[1.1.0]: https://github.com/davide0707/desktidy/releases/tag/v1.1.0
[1.0.0]: https://github.com/davide0707/desktidy/releases/tag/v1.0.0
