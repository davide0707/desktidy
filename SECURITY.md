# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/davide0707/desktidy/security/advisories/new) instead.
You will get an answer within a week.

## What DeskTidy does with your data

- Everything runs on your PC. Settings, logs and the moves history live in `%LOCALAPPDATA%\DeskTidy`.
- API keys are stored in your Windows user environment (`GROQ_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`...),
  never in a file, and are shown masked.
- When the AI is enabled, only a short text excerpt (or a downscaled image when there is no text), the file name and a
  short list of folder names are sent to the AI service you chose (with Ollama, nothing leaves your PC).
  Files matched by a `private` rule, photos and screenshots are never sent.
- Text inside files is treated as data: the AI is instructed to ignore any instruction written in a file, and its
  answer can only pick a folder from the list DeskTidy sent.
