<p align="center">
  <img src="https://raw.githubusercontent.com/davide0707/desktidy/main/docs/demo.svg" alt="The DeskTidy console: where did my invoice go, and how much did the AI cost" width="880">
</p>

<h1 align="center">DeskTidy</h1>

<p align="center">
  <b>Your files, sorted while you work.</b><br>
  DeskTidy watches your Downloads, Desktop and Documents, understands what every new file is about, gives it a
  proper name and puts it in the right folder. Every move can be undone. Windows, macOS and Linux.
</p>

<p align="center">
  <a href="https://github.com/davide0707/desktidy/releases/latest"><img src="https://img.shields.io/github/v/release/davide0707/desktidy?label=release" alt="Latest release"></a>
  <a href="https://github.com/davide0707/desktidy/actions/workflows/ci.yml"><img src="https://github.com/davide0707/desktidy/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows" alt="Windows 10 | 11">
  <img src="https://img.shields.io/badge/macOS-11%2B-000000?logo=apple" alt="macOS 11+">
  <img src="https://img.shields.io/badge/Linux-GNOME%20%7C%20KDE%20%7C%20more-FCC624?logo=linux&logoColor=black" alt="Linux">
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <a href="https://github.com/davide0707/desktidy/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPLv3-blue" alt="GPLv3 license"></a>
</p>

---

`scan0001.pdf` lands in your Downloads. Two minutes later it is in `Documents/04_Personal/Bills_and_Receipts`:
DeskTidy read it, recognised an invoice and filed it, and with the AI on it also renamed it
`Fattura_2231_Acme_Srl_2026-09-30.pdf`, after its number, issuer and date. You get a notification with **Open** and
**Undo**, a reminder before the payment is due, and `desktidy find acme september` finds it later by what it says.

No cloud drive, no subscription, no account. DeskTidy reads your files **on your computer**. Whether it also asks an AI
is **your choice**: rules only (nothing leaves your PC), or always AI, free (Groq, Gemini, Mistral, OpenRouter, or
Ollama running on your own computer) or paid (Claude, OpenAI) for a fraction of a cent per file.

## What it does

**Understands and names your files**
- Reads PDF, Word, Excel, PowerPoint, LibreOffice, RTF, HTML, e-mails, ebooks, notebooks and code; scans and pictures
  with the **OCR built into your system**; photos by their camera data; screenshots, icons, projects (Python, web,
  STM32, KiCad, 3D printing...) inside folders and zip files.
- Gives `scan0001.pdf`, `Document1.docx` or a misleading name a real one, from the document itself or from the AI:
  `Fattura_2231_Acme_Srl_2026-09-30.pdf`.

**Files them where you want**
- Your folders, your rules: *pinned folders* attract the files about them, rules in plain words (`invoice`,
  `fattura`, `calculus`...) decide the rest, and folders by year (`Bills/{YEAR}`) are filled in from each document's
  date.
- It learns: move a file it misplaced and it notices; when the AI keeps putting similar files in the same folder,
  it proposes a rule so the next ones are placed offline.

**Tidies up what is already there**
- `desktidy organize`: 50 loose files on your Desktop? It groups them into folders (the thesis, the trip, the bills),
  shows you the plan, and does it only when you say so.
- Duplicates across your folders, old versions of a document, installers of programs you already have, an archive
  for what you haven't touched in months, photos from memory cards sorted by date.

**Remembers for you**
- Search by content: `desktidy find bolletta luce settembre`, OCR text included, all local.
- Deadlines found in bills and forms ("pay by 30/10/2026", "scadenza 15 novembre"), with reminders and an `.ics`
  file for your calendar. A short summary of your week, once a week.

**Never surprises you**
- Every move and rename is logged and undoable, one file or a whole plan at a time. Nothing is ever deleted:
  duplicates go to the Recycle Bin / Trash.
- [Six house rules](https://github.com/davide0707/desktidy/blob/main/docs/house-rules.md) you accept at setup: names starting with `!` are never touched; nothing
  moves until you have pinned two folders; open and unfinished files are skipped; nothing is lost; private stays
  private unless you choose otherwise; you're in charge (pause, stop, preview, daily limit).
- Folders of programs (game saves, settings) are never reorganised.

**Part of your desktop**
- Right-click menu in Explorer, Files, Nemo and Dolphin; notifications with buttons; an icon next to the clock on
  Windows; and every setting, the organize plan and the history of moves in a page of your browser.

## Rules only, or always AI: you choose

The setup asks how DeskTidy should understand your files, and you can change it any time:

| | What happens | What leaves your computer |
|---|---|---|
| **Rules only** (`desktidy ai rules`) | the offline engine reads, names and files everything | nothing |
| **Always AI** (`desktidy ai all`) | the AI reads every file and names it; the rules are the fallback | an excerpt of each file, with IBANs, tax codes, cards, e-mails and phone numbers masked; photos and screenshots never |

Three levels in between use the AI only for the files the rules can't place. With **Ollama** the AI runs on your own
computer, so even *Always AI* sends nothing anywhere. `desktidy ai test` shows how well a service does on 18 made-up
documents before you trust it with yours. Details: [AI and privacy](https://github.com/davide0707/desktidy/blob/main/docs/ai-and-privacy.md).

## Install

**Windows, without Python**: download `DeskTidy-<version>-windows.zip` from the
[latest release](https://github.com/davide0707/desktidy/releases/latest), extract it anywhere, open a terminal in
that folder and run:

```bat
desktidy.exe install
```

It copies itself to `%LOCALAPPDATA%\Programs\DeskTidy` (no administrator rights), adds the `desktidy` command, the
start at sign-in and the right-click menu, then starts the setup.

> The exe is not code-signed yet, so the first time Windows may say *Windows protected your PC*: click
> **More info** → **Run anyway**. To be sure the zip is the one built here, compare its SHA-256 with `SHA256SUMS` in
> the release, or [verify its attestation](https://github.com/davide0707/desktidy#contributing).

**Windows, macOS and Linux, with Python 3.10+** and [pipx](https://pipx.pypa.io/):

```sh
pipx install "desktidy[ai]"
desktidy install
```

`[ai]` adds the library for Claude; the other AI services need nothing more. The latest development version, straight
from GitHub: `pipx install git+https://github.com/davide0707/desktidy` (for Claude add
`pipx inject desktidy anthropic`).

<details><summary>Getting pipx, or installing from the source</summary>

| Windows | macOS | Linux |
|---|---|---|
| `py -m pip install --user pipx` then `py -m pipx ensurepath` | `brew install pipx` then `pipx ensurepath` | `sudo apt install pipx` (Fedora: `dnf`, Arch: `python-pipx`) then `pipx ensurepath` |

From the source:

```sh
git clone https://github.com/davide0707/desktidy
cd desktidy
install.cmd          # Windows (or double-click it)
sh install.sh        # macOS and Linux
```
</details>

> **macOS** asks whether Python may read Downloads, Desktop and Documents the first time: click **Allow**.
> **Linux**: for scans and pictures install Tesseract, e.g. `sudo apt install tesseract-ocr tesseract-ocr-ita`.

### The first minute

`desktidy install` ends with the setup:

1. **The house rules**: read them and accept them.
2. **Pin at least two folders**: the places where files should end up (`Study`, `Work`, `Recipes`...).
3. **A daily limit**, or unlimited.
4. **Rules only or always AI**; for the AI, pick a service (`groq` is free) and paste its key.

Then open a new terminal and type `desktidy` for the console, or just let it work in the background.

## Everyday use

```sh
desktidy status                  # running? what did it do today?
desktidy where invoice           # where did a file go, and why
desktidy undo invoice            # put it back, with its old name
desktidy find electricity bill   # search by content
desktidy organize desktop        # group the loose files of the Desktop (a plan first)
desktidy deadlines               # bills and deadlines found in your documents
desktidy editor                  # every setting in your browser
```

All the commands: [command reference](https://github.com/davide0707/desktidy/blob/main/docs/commands.md).

## Documentation

| | |
|---|---|
| [User guide](https://github.com/davide0707/desktidy/blob/main/docs/guide.md) | how DeskTidy decides, renaming, organize, the tidy-up tools, search, deadlines, the desktop integration, FAQ |
| [AI and privacy](https://github.com/davide0707/desktidy/blob/main/docs/ai-and-privacy.md) | the modes, the services and their costs, what is sent and what never is, masking, the AI test |
| [Commands](https://github.com/davide0707/desktidy/blob/main/docs/commands.md) | every command and option |
| [Configuration](https://github.com/davide0707/desktidy/blob/main/docs/configuration.md) | `rules.json`, rules, variables, folders by year, where your data lives |
| [House rules](https://github.com/davide0707/desktidy/blob/main/docs/house-rules.md) | the six promises DeskTidy keeps |
| [Development](https://github.com/davide0707/desktidy/blob/main/docs/development.md) | the code, the tests, building the Windows version, releasing |

## Contributing

Bug reports, ideas, rules in other languages and pull requests are welcome: see [CONTRIBUTING.md](https://github.com/davide0707/desktidy/blob/main/CONTRIBUTING.md)
and the [code of conduct](https://github.com/davide0707/desktidy/blob/main/CODE_OF_CONDUCT.md). Questions and ideas to talk over: the
[Discussions](https://github.com/davide0707/desktidy/discussions). Security problems: please follow
[SECURITY.md](https://github.com/davide0707/desktidy/blob/main/SECURITY.md).

Every release lists the SHA-256 of its files in `SHA256SUMS` and carries a GitHub build provenance attestation:
`gh attestation verify DeskTidy-1.4.1-windows.zip -R davide0707/desktidy` proves a download was built here, from this
source.

## License

DeskTidy is free software: you can redistribute it and/or modify it under the terms of the
[GNU General Public License](https://github.com/davide0707/desktidy/blob/main/LICENSE) as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version. It is distributed in the hope that it will be useful, but **without any
warranty**.

Copyright © 2026 Di Filippo Davide
