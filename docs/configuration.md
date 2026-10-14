# Configuration

Every setting lives in `rules.json`, in DeskTidy's data folder. It is created from
[`default_rules.json`](../desktidy/default_rules.json) on the first run and reloaded by itself when it changes.

- `desktidy editor` edits it in your browser, with validation before saving (the previous file is kept as
  `rules.json.bak`);
- `desktidy rules` opens the file, `desktidy rules check` checks it.

- [Your data](#your-data)
- [rules.json at a glance](#rulesjson-at-a-glance)
- [Rules](#rules)
- [Variables and folders by year](#variables-and-folders-by-year)
- [All the settings](#all-the-settings)

## Your data

Everything DeskTidy writes stays on your computer, in its data folder (`desktidy open`):

| Windows | macOS | Linux |
|---|---|---|
| `%LOCALAPPDATA%\DeskTidy` | `~/Library/Application Support/DeskTidy` | `~/.local/share/desktidy` |

| File | What it holds |
|---|---|
| `rules.json` | your settings and rules |
| `moves.csv` | every move and rename (opens in Excel or LibreOffice): `desktidy where`, `desktidy undo` |
| `desktidy.log` | the activity log: `desktidy log` |
| `index.db` | the search index: `desktidy find` |
| `deadlines.json` | the deadlines found in your documents |
| `learned.json` | your corrections, the AI decisions you kept, the proposed rules |
| `pinned.json` | the pinned folders |
| `folder_ops.json` | the folder changes applied by `organize` and `advice`, to undo them |
| `organize.json` · `advice.json` | the latest organize plan · the latest advice |
| `ai_usage.json` | AI spend per day and model, the declared credit |
| `kept.json` | files you put back: DeskTidy leaves them alone |
| `keys.json` | macOS and Linux: the API keys, readable only by you (Windows: your user environment) |
| `state.json` · `setup.json` · `summary.json` · `imports.json` · `updates.json` · `ai_jobs.json` | small state files: the service, the accepted house rules, the last weekly summary, the cards already imported, the latest version seen, AI batches waiting for an answer |

Nothing lives in the program folder, so updating DeskTidy never touches your data. `desktidy uninstall` leaves the data
folder where it is; delete it to remove everything. Set `DESKTIDY_HOME` to use another folder (portable installs,
tests).

## rules.json at a glance

```jsonc
{
  "variables": { "STUDY": "{DOCS}/01_Study", "INSTALLERS": "{DOCS}/05_Software/Installers" },
  "watched_folders": [
    { "path": "{DOWNLOADS}", "wait_seconds": 120, "include_folders": true },
    { "path": "{DESKTOP}", "wait_seconds": 600, "include_folders": false }
  ],
  "default_destination": "{DOCS}/00_Inbox/To_Sort",       // the to-sort pile
  "limits": { "files_per_day": "unlimited" },              // or a number
  "rename": { "mode": "smart" },                           // smart | generic | off
  "ai": { "provider": "groq", "mode": "limited", "redact": true, "budget_usd": 5.0,
          "user_context": "photographer; client shoots, invoices and contracts" },
  "deadlines": { "enabled": true, "remind_days": [7, 1, 0] },
  "summary": { "weekly": true, "day": "monday" },
  "rules": [
    {
      "name": "Bills, invoices and receipts",
      "name_words": ["invoice", "fattura", "bill", "bolletta"],  // in the file name
      "content_words": ["invoice", "fattura"],                    // strong: one is enough
      "topics": ["vat", "iva", "amount due", "due date"],         // at least min_topics must appear
      "min_topics": 3,
      "destination": "{DOCS}/04_Personal/Bills_and_Receipts/{YEAR}",
      "private": true                                             // sent to the AI only in the "all" mode
    }
  ]
}
```

## Rules

Rules are checked from the top: the first that matches wins. Pinned folders come before every rule.

| Field | Meaning |
|---|---|
| `name` | a label, shown in the logs and in `desktidy explain` |
| `name_words` | words in the file name (plural, singular and one typo tolerated) |
| `content_words` | strong words in the content: one is enough |
| `topics` · `min_topics` | words about the subject: at least `min_topics` must appear (2 or 3 by length if missing) |
| `recognize` | kinds DeskTidy recognises by itself: `photo`, `screenshot`, `icon`, `scan`, `code_python`, `project_web`, `project_kicad`, `gerber`, `print_3d`, `font`, `installer`, `photo_folder`... |
| `extensions` | file types, e.g. `[".stl", ".3mf"]` (empty = any) |
| `type` | `file` (default), `folder` or `both` |
| `destination` | where matching items go; variables allowed, `{YEAR}` and `{MONTH}` too |
| `private` | never sent to the AI, except in the `all` mode you chose; also excluded from the advice |
| `generic` | a broad rule ("notes"): a confident content match elsewhere wins over its name words |

Words work in any language; the bundled rules include English and Italian ones. Learned rules (`desktidy learn
accept`) are added at the top with the same fields.

## Variables and folders by year

`{HOME}`, `{DOCS}`, `{DOWNLOADS}`, `{DESKTOP}`, `{PICTURES}`, `{VIDEOS}` and `{MUSIC}` always exist and point to your
real folders on every system (Documents moved to OneDrive, `Movies` on macOS, `Documenti` or `Scaricati` on an Italian
Linux desktop). You can add your own in `variables` and use them in other variables.

`{YEAR}` and `{MONTH}` in a destination are filled in from the date of each document: the one the AI read, else the
one in its text, else the day the file was last changed. `{DOCS}/Bills/{YEAR}/{MONTH}` files a bill of 3 November
2025 in `Bills/2025/11`. A variable you define called `YEAR` wins over the date.

Write paths with `/`: a `rules.json` written on Windows with `\` and `%USERPROFILE%` works on macOS and Linux too. A
path with an unknown `{VARIABLE}` is refused (and reported by `rules check`) instead of creating a folder with that
name.

## All the settings

| Setting | Default | Meaning |
|---|---|---|
| `watched_folders[].path` | Downloads, Desktop, Documents | the folders DeskTidy watches |
| `watched_folders[].wait_seconds` | 120 / 600 / 600 | how long an item must be still before it is tidied |
| `watched_folders[].include_folders` | Downloads only | whether whole folders are tidied too |
| `watched_folders[].ignore` | `[]` | names to leave alone in that folder |
| `default_destination` | `{DOCS}/00_Inbox/To_Sort` | where items the rules can't place go |
| `interval_seconds` | 30 | how often the folders are looked at |
| `analysis.ocr` · `analysis.similarity` | `true` · `true` | read scans and pictures with OCR; compare with the files already in each folder |
| `rename.mode` | `smart` | `smart`, `generic` (only names that say nothing) or `off` |
| `pinned_folders.min_required` | 2 | pinned folders needed before anything is moved |
| `pinned_folders.ask` · `ask_for_new_folders_in` | `true` · Desktop | ask "Pin it?" for new folders there |
| `limits.files_per_day` | `unlimited` | files tidied per day, AI or not |
| `ai.mode` | `limited` | `off`, `limited`, `moderate`, `ai-only`, `all` (see [AI and privacy](ai-and-privacy.md)) |
| `ai.provider` · `ai.model` · `ai.base_url` | `groq` · the service's default | the service |
| `ai.redact` | `true` | mask IBANs, cards, tax codes, VAT numbers, e-mails and phones before sending |
| `ai.max_files_per_day` | by mode | files the AI looks at per day (a number or `unlimited`) |
| `ai.budget_usd` · `ai.credit_reserve_usd` | 5.0 · 0.10 | the AI stops at the budget, or before the declared credit runs out |
| `ai.delivery` | `batch` | `batch` (Claude, half price, minutes) or `instant` |
| `ai.min_confidence` | `high` | accept only sure answers, or `medium` too |
| `ai.gather_seconds` | 90 | files arriving together wait this long to share one request |
| `ai.advice` · `advice_after_files` · `advice_every_days` | `auto` · 30 · 7 | the organisation advice |
| `ai.language` · `ai.user_context` | empty | the language of names and advice; one line about you that helps the AI |
| `ai.candidate_folders` | your main areas | the folders (and how deep) offered to the AI |
| `search.enabled` · `search.index_private` | `true` · `true` | the search index, and whether private files are indexed (locally) |
| `deadlines.enabled` · `deadlines.remind_days` | `true` · `[7, 1, 0]` | deadline reminders |
| `summary.weekly` · `summary.day` | `true` · `monday` | the weekly summary |
| `organize.min_items` | 10 | loose items that make a folder crowded |
| `duplicates.min_size_kb` | 512 | smaller files are not compared |
| `groups.min_files` | 3 | files needed to propose a group of the to-sort pile |
| `learn.min_examples` · `learn.min_ai_examples` | 2 · 5 | corrections, or AI decisions, before a rule is proposed |
| `archive.enabled` · `after_days` · `folder` · `zip` · `sources` | off · 180 · `{DOCS}/Archive` · `false` · Desktop and to-sort | the automatic archive |
| `import.enabled` · `auto` · `photos` · `videos` · `pattern` · `delete_after` | on · off · `{PICTURES}` · `{VIDEOS}` · `{year}/{year}-{month}` · off | photos from memory cards |
| `tray` | `true` | the icon next to the clock (Windows) |
| `updates.check` | `true` | the weekly check for a new version on GitHub |
