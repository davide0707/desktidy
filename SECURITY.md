# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/davide0707/desktidy/security/advisories/new) instead.
You will get an answer within a week.

## What DeskTidy does with your data

- Everything runs on your computer. Settings, logs and the moves history live in DeskTidy's data folder
  (`%LOCALAPPDATA%\DeskTidy`, `~/Library/Application Support/DeskTidy`, `~/.local/share/desktidy`), created
  readable only by you on macOS and Linux.
- API keys (`GROQ_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`...) are stored in your Windows user environment, or
  on macOS and Linux in `keys.json` in the data folder with permissions `600` (only you can read it). They are never
  written to the logs and are shown masked.
- When the AI is enabled, only a short text excerpt (or a downscaled image when there is no text), the file name and a
  short list of folder names are sent to the AI service you chose (with Ollama, nothing leaves your computer).
  Photos and screenshots are never sent. Files matched by a `private` rule are sent only in the `all` mode ("Always
  AI"), which the user chooses explicitly; before the first one goes to a service on the internet DeskTidy names the
  service and asks.
- Organisation advice (`desktidy advice`, automatic only in the `ai-only` and `all` modes) sends folder names, file counts and types
  and two file names per folder (none from folders of `private` rules), never the content of a file.
- Text inside files is treated as data: the AI is instructed to ignore any instruction written in a file, and its
  answer can only pick a folder from the list DeskTidy sent.
- The search index (`index.db`), deadlines and learned rules are local files in the data folder; nothing is uploaded.
- The `desktidy:` link (notification buttons, right-click menu) accepts only a fixed list of actions; ids are checked
  against DeskTidy's own records, a drive must be a single letter and a memory card a short hex id, so a web page
  can't make DeskTidy open, move or delete an arbitrary path. The right-click menu, the link, the start at sign-in and
  the `desktidy` command are installed for the current user only (HKCU on Windows; `~/Library/LaunchAgents`,
  `~/.config/autostart`, `~/.local/share` and `~/.local/bin` on macOS and Linux): no administrator rights.
- `desktidy editor` listens on 127.0.0.1 only, while the command runs: the page needs a random token in its address,
  every API call must carry it in a header, and requests whose Host is not 127.0.0.1/localhost are refused.
- Once a week DeskTidy asks GitHub for the latest release number (anonymous, no data about you); turn it off with
  `"updates": {"check": false}`.
