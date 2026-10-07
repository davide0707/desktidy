# Changelog

All notable changes to DeskTidy are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/)
and the project uses [Semantic Versioning](https://semver.org/).

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

[1.0.0]: https://github.com/davide0707/desktidy/releases/tag/v1.0.0
