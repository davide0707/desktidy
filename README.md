<p align="center">
  <img src="docs/demo.svg" alt="DeskTidy console: where did my invoice go, and how much did the AI cost" width="880">
</p>

<h1 align="center">DeskTidy</h1>

<p align="center">
  <b>Your files, sorted while you work.</b><br>
  DeskTidy watches Downloads, Desktop and Documents, understands what every new file is about,
  gives it a proper name and files it in the right folder. Offline first, with an AI of your choice (free ones included) only for the hard cases.
</p>

<p align="center">
  <a href="https://github.com/davide0707/desktidy/actions/workflows/ci.yml"><img src="https://github.com/davide0707/desktidy/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?logo=windows" alt="Windows 10 | 11">
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/AI-free%20or%20~%240.0003%20%2F%20file-8A2BE2" alt="AI: free or about $0.0003 per file">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license"></a>
</p>

---

`scan0001.pdf` lands in Downloads. Two minutes later it is `Documents\Personal\Bills\Invoice_2231_Northwind_Energy.pdf`,
you get a notification, and `desktidy where invoice` tells you where it went and why. No cloud drive, no subscription:
it reads the file **on your PC**, and only when it really can't decide it asks an AI: a free one (Groq, Gemini,
Mistral, OpenRouter, or Ollama on your own PC) or Claude / OpenAI for a fraction of a cent.

## Read me first: the house rules

DeskTidy moves files for you, so it plays by a few simple rules. The installer shows them and asks you to accept them
before anything is moved ([HOUSE_RULES.md](HOUSE_RULES.md)).

1. **A name starting with `!` is never touched.** `!draft.docx` or a folder called `!work in progress` stays exactly
   where it is. Remove the `!` to let DeskTidy handle it again.
2. **Pin at least 2 folders before it starts.** Pinned folders are the places you want things to go (e.g. `Study`,
   `Work`, `Recipes`). Until two are pinned DeskTidy only watches: `desktidy setup` walks you through it.
3. **It waits before acting.** Downloads after 2 minutes, Desktop and Documents after 10. Open files, unfinished
   downloads, Office lock files, hidden and system files are skipped.
4. **Nothing is lost.** Every move and rename is logged (`desktidy where`) and can be undone (`desktidy undo`).
   Identical duplicates go to the Recycle Bin, never deleted.
5. **Private stays private.** IDs, payslips, bills, CVs, photos and screenshots are never sent to the AI. The AI is
   optional, with a daily limit and a budget.
6. **You're in charge.** `desktidy pause 1h`, `desktidy stop`, `desktidy preview` (see what it would do).

## Highlights

- **Understands content, offline.** Text from PDF, Word, Excel, PowerPoint (old `.doc` too), LibreOffice, RTF, HTML,
  e-mails, notebooks and ebooks; the built-in **Windows OCR** for scans and pictures; photos (camera EXIF),
  screenshots, icons, source code pasted into a `.txt`, and project types inside folders and zip files
  (Python, web, STM32, KiCad, gerber, 3D printing...). Plurals, singulars and typos are handled: `calculs notes.txt`
  still goes to *Calculus*.
- **Smart renaming.** `scan0001.pdf`, `Document1.docx`, `download (3).pdf` or a name that has nothing to do with the
  content get a real name, taken from the document title. When the AI looks at a file whose name doesn't match its
  content, it fixes the name too, in the same request. The original name is always logged and `desktidy undo`
  brings it back.
- **Advice on how to organise.** Once DeskTidy has an overview of your files, the AI suggests better ways to organise
  them: folders to merge or split, clearer names, an archive, a pinned folder for what keeps landing in *To_Sort*
  (`desktidy advice`). Ideas only: nothing is changed for you.
- **Pinned folders.** Create `Recipes` on your Desktop and DeskTidy asks *"Pin it?"*. From then on recipes go there:
  by name, by content, or because they look like the files you already put inside.
- **Any AI, free ones included.** Pick the service: **Groq, Google Gemini, Mistral, OpenRouter** (free plans),
  **Ollama** (free, runs on your PC, nothing leaves it), **Claude** or **OpenAI** (paid), or any OpenAI-compatible
  server. Four levels: `off`, `limited`, `moderate`, `ai-only` (every file, with name checks and organisation advice).
- **Cheap by design.** A short list of likely folders instead of the whole tree, several files per request, short
  excerpts, and Claude's Batch API at half price. **Measured: ~5.7× cheaper than sending the folder tree with every
  file** (see below).
- **Always in control.** Pause, see where anything went, undo any move, preview what would happen. Everything from a
  Kali-style console or one-line commands.

## Quick start

1. Install [Python 3.10+](https://www.python.org/downloads/) (tick *Add python.exe to PATH*).
2. Download DeskTidy and run the installer:

   ```bat
   git clone https://github.com/davide0707/desktidy
   cd desktidy
   install.cmd
   ```

3. The setup starts by itself: read the house rules and pin at least 2 folders.
4. Open a **new** Command Prompt and type `desktidy`.
5. Adapt the destinations to your folders: `desktidy rules` (then `desktidy rules check`).
6. Optional, for the hard cases: `desktidy ai provider` to pick an AI service (free ones included), then `desktidy key`.

> Without an AI DeskTidy works fully offline. With a free plan it costs nothing; with Claude a month of downloads
> costs cents.

<details>
<summary>Prefer pipx?</summary>

```bat
pipx install "desktidy[ai] @ git+https://github.com/davide0707/desktidy"
desktidy install
```
</details>

## How it decides

```mermaid
flowchart LR
    A[New file in Downloads, Desktop or Documents] --> B{Ready?<br/>download complete,<br/>not open, no '!'}
    B -- yes --> C[Read it on the PC<br/>text, OCR, EXIF, project type]
    C --> D{Offline decision<br/>pinned · name · content<br/>similarity · file type}
    D -- confident --> F[Rename if needed<br/>and move]
    D -- unsure, and AI mode allows --> E[AI of your choice, free or paid:<br/>short folder list, files batched]
    E --> F
    F --> G[Notification + moves.csv<br/>desktidy where / undo]
```

1. **Pinned folders**: the name or the content talks about a folder you pinned.
2. **Name**: rule words, also in plural/singular form or with one typo.
3. **Content**: strong words (`content_words`), topics (`topics`, at least 2-3 must appear) and recognised kinds
   (`recognize`: `photo`, `screenshot`, `code_python`, `project_kicad`...). A *generic* rule such as "notes" gives way
   to a confident content match.
4. **Similarity** with the files already in each folder.
5. **File type** (`.stl`, `.py`, `.exe`...). Programs only ever go to the installers folder.

Run `desktidy explain <file>` to see exactly what DeskTidy understood and why it chose a folder.

## Smart renaming

| Before | After | Why |
|---|---|---|
| `scan0001.pdf` | `Invoice_2231_from_Northwind_Energy.pdf` | generic name, title from the first heading |
| `Document1.docx` | `Lab_report_RC_filters.docx` | generic name, title from the document properties |
| `holiday_photos_list.txt` (an electricity bill) | `Electricity_bill_September.txt` | the name didn't match the content |
| `Report_final.pdf` (a shopping list, no title) | `Weekly_shopping_list.pdf` | the AI found the name didn't match the content |
| `download (3).pdf` (no clear title) | `RC_Circuit_Resistance_Measurement.pdf` | name suggested by the AI in the same request |
| `!draft.docx`, `IMG_2034.jpg`, `my_thesis.pdf` | unchanged | `!` means hands off; photos and good names are kept |

`desktidy rename smart | generic | off` chooses how bold it is. In `smart` mode, every file the AI looks at also gets
its name checked: the AI keeps your name when it fits (even loosely) and replaces it only when it is misleading or
says nothing. Names that clearly match the content are never sent for checking, and an AI name must be meaningful
and really different to replace yours.

## AI: free or paid, your choice

DeskTidy asks an AI only about the files the offline engine can't place (or places with low confidence, in `moderate`
mode). Choose the service with `desktidy ai provider <name>`, then `desktidy key`:

| Service | Cost | Privacy | Reads images | Default model |
|---|---|---|---|---|
| `groq` *(default)* | **free** plan, about 1,000 requests a day, no card | prompts not used for training | no (text and OCR only) | `openai/gpt-oss-20b` |
| `gemini` | **free** tier on the Flash and Flash-Lite models | free tier: Google may use prompts to improve its products | yes | `gemini-3.5-flash-lite` |
| `mistral` | **free** Experiment plan (phone verification) | free plan: prompts may be used for training | yes | `mistral-small-latest` |
| `openrouter` | **free** `:free` models, 50 requests a day | free models: the host may log prompts | depends on the model | `google/gemma-4-31b-it:free` |
| `ollama` | **free**, runs on your PC ([ollama.com](https://ollama.com/download)) | nothing leaves your PC | yes | `gemma3:4b` |
| `claude` | paid, ~$0.0003 per file with the Batch API | not used for training | yes | `claude-haiku-4-5` |
| `openai` | paid | not used for training by default | yes | `gpt-5-nano` |
| `custom` | any OpenAI-compatible server (LM Studio, vLLM...) | your server | set `ai.vision` | set `ai.model` |

Free plans and model names change often (checked in October 2026): `desktidy ai model <id>` switches model, and
`desktidy key test` checks key and service for free. If a service refuses a feature (for example strict JSON),
DeskTidy steps down to a simpler request by itself and remembers it.

### Spending as little as possible

Every request is designed to be small, whatever the service:

| What | Effect |
|---|---|
| Short list of likely folders per file (offline candidates, similar folders, pinned, top areas) | the folder tree was ~80% of the tokens |
| Up to 8 files share one request, and files arriving close together wait up to 90 s for each other | instructions and folders paid once, fewer requests on free plans |
| Name check only for names the offline engine can't match with the content | no tokens spent on good names |
| ~1,200-character excerpt + key terms, from the text already read on the PC (OCR included) | the file itself is never uploaded |
| Images only when there is no text, downscaled to 512 px (never to text-only services) | ~260 tokens per image |
| Compact JSON answer with one-letter keys; a name is requested only when needed | few output tokens |
| **Batch API** by default with Claude | **half price** (answers usually within minutes) |

Measured with Anthropic's token counter on the same three files, against the previous design (whole folder tree in
every request): **1,292 → 371 input tokens per file**, plus the 50% batch discount: **~$0.0015 → ~$0.00026 per file
with Claude Haiku 4.5**.

Built-in brakes: a daily file limit, a total budget, an estimated credit (`desktidy spend credit 4.85`), and an
automatic pause when Anthropic reports the credit is exhausted. `desktidy spend` shows today, the last 7 days, the
month and the total.

> AI services do not let API keys read the prepaid balance, so DeskTidy computes the spend from the token counts
> returned with every answer, and estimates the remaining credit from the balance you type in.

**Never sent**: files matched by a `private` rule, photos, screenshots, programs. **Sent for the others**: the excerpt
above, the file name and the short folder list. API keys are stored in your Windows user environment
(`GROQ_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`...), never in a file.

### Advice on how to organise

In `ai-only` mode, once DeskTidy has tidied enough files to have an overview (30 by default), it asks the AI how your
files and folders could be organised better, about once a week, and tells you with a notification. `desktidy advice`
shows the ideas (merge, split, rename, archive, create or pin a folder, a naming convention), each with the folders
involved; `desktidy advice open 2` opens them in Explorer and `desktidy advice pin 2` pins one. `desktidy advice new`
asks right away in any AI mode. Nothing is moved or renamed for you.

One small request (~2,000 tokens for 100 folders): folder names, how many files each holds and of which types, the
year of the latest change, two file names per folder (none from private folders), and what DeskTidy saw recently
(files left in *To_Sort*, moves you undid). Never the content of a file. Even without an AI, `desktidy advice` lists
what it finds offline: a growing *To_Sort* pile, empty or very full folders, clutter in Downloads.
Settings in the `ai` section: `advice` (`auto` = ai-only mode, `on`, `off`), `advice_after_files`, `advice_every_days`,
`language` (empty = the language of your folder names).

## Commands

Type `desktidy` for the console (use the number or the name), or `desktidy <command>` from any Command Prompt.

| Command | What it does |
|---|---|
| `setup` · `guide` | first-run setup (house rules + pinned folders) · show the house rules |
| `status` | running or stopped, pause, autostart, AI mode and key, spend, latest moves |
| `pause [30m · 2h · 1h30m · 1d · 18:30]` / `resume` | pause for a while, or until you resume |
| `start` / `stop` / `stop forever` / `restart` | `stop` stops now and starts again at the next sign-in |
| `autostart on · off` | start at sign-in |
| `where [name] [--open · --all]` | where did a file go, and why |
| `undo [name · number]` | put a file back where it was, with its old name |
| `pinned` · `pin <folder> [words]` · `unpin <folder>` · `pinned suggest` | pinned folders |
| `explain <file> [--ai]` | what DeskTidy understands of a file and where it would put it |
| `preview [--now] [--ai]` | what it would do right now, moving nothing |
| `rename smart · generic · off` | how bold renaming is |
| `spend` · `spend credit <usd>` · `spend budget <usd>` · `spend web` | AI spend, balance, budget |
| `ai provider [name]` (or `provider`) | choose the AI service: groq, gemini, mistral, openrouter, ollama, claude, openai, custom |
| `ai off · limited · moderate · ai-only` · `ai max <n>` · `ai model <id>` · `ai delivery batch · instant` | how much AI, which model |
| `key` · `key test` · `key remove` | API key of the chosen service (hidden while you paste it, checked for free) |
| `advice` · `advice new` · `advice open <n>` · `advice pin <n>` | ideas to organise files and folders better |
| `log [errors · 100 · open]` · `rules [check]` · `open` | log, settings, data folder |
| `install` · `uninstall` · `about` | command and autostart, version |

## Configuration

Settings live in `%LOCALAPPDATA%\DeskTidy\rules.json` (created from [`default_rules.json`](desktidy/default_rules.json)
on the first run) and reload by themselves.

```jsonc
{
  "variables": { "DOCS": "%USERPROFILE%\\Documents", "INSTALLERS": "%USERPROFILE%\\Documents\\05_Software\\Installers" },
  "watched_folders": [ { "path": "{HOME}\\Downloads", "wait_seconds": 120, "include_folders": true } ],
  "default_destination": "{DOCS}\\00_Inbox\\To_Sort",
  "rename": { "mode": "smart" },
  "pinned_folders": { "min_required": 2, "ask": true, "ask_for_new_folders_in": ["{HOME}\\Desktop"] },
  "ai": { "provider": "groq", "mode": "limited", "model": "", "budget_usd": 5.0, "gather_seconds": 90,
          "advice": "auto", "user_context": "photographer; client shoots, invoices and contracts" },
  "rules": [
    {
      "name": "Study: maths",
      "name_words": ["calculus", "linear algebra"],            // in the file name
      "content_words": ["calculus"],                           // strong: one is enough
      "topics": ["derivative", "integral", "limit", "matrix"], // at least min_topics must appear
      "recognize": [],                                         // photo, screenshot, code_python, project_kicad...
      "destination": "{DOCS}\\01_Study\\Courses\\Maths",
      "private": false,                                        // true = never sent to the AI
      "generic": false                                         // true = a confident content match wins over the name
    }
  ]
}
```

Keywords work in any language; the bundled rules include English and Italian ones.

## Your data

Everything DeskTidy writes stays on your PC, in `%LOCALAPPDATA%\DeskTidy` (`desktidy open`):
`rules.json`, `moves.csv` (every move and rename, opens in Excel), `desktidy.log`, `ai_usage.json`, `pinned.json`.
None of it lives in the program folder, so updating DeskTidy never touches it. `desktidy uninstall` removes the
autostart and the command and leaves your files alone.

## FAQ

**Will it touch files I'm working on?** No. It waits until a download is complete and the file has been still for a
while, skips open files, Office lock files, hidden and system files, and anything whose name starts with `!`.

**What if it gets one wrong?** `desktidy undo <name>` restores it, with its original name, and DeskTidy leaves it alone
from then on.

**Does it need the internet?** No. The AI is optional and only used for the files the offline engine can't place;
with Ollama even the AI runs on your PC.

**Is there a free AI option?** Yes: Groq, Gemini, Mistral and OpenRouter have free plans, and Ollama is free and local.
`desktidy ai provider` lists them with their limits and privacy terms.

**macOS or Linux?** Not yet: it relies on Windows OCR, Task Scheduler and notifications. Contributions are welcome.

## Development

```bat
python -m venv .venv
.venv\Scripts\pip install -e ".[ai,dev]"
.venv\Scripts\python -m unittest discover -s tests -t .
.venv\Scripts\ruff check .
.venv\Scripts\desktidy-service --dry-run --now
```

The tests run in temporary folders: they never move your files or touch your logs, and never call the AI.

```
desktidy/
  cli.py          console, commands, setup      service.py      background loop, moves, AI batches
  classifier.py   offline decision engine       content.py      text, OCR, EXIF, code and project detection
  naming.py       smart renaming                folders.py      folder catalog, similarity, pinned folders
  ai.py           compact AI requests           providers.py    Claude, OpenAI, Gemini, Groq, Mistral, Ollama...
  usage.py        spend, budget, credit         advice.py       folder overview and organisation advice
  config.py       settings and data files       winapi.py       Task Scheduler, notifications, Recycle Bin
```

## Roadmap

- System tray icon with pause and recent moves
- Watch any folder, not just Downloads / Desktop / Documents
- Learn new rules from your `undo` corrections
- macOS and Linux support
- PyPI release

Ideas and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Di Filippo Davide

If DeskTidy saves you some clicks, a ⭐ helps other people find it.
