# AI and privacy

DeskTidy reads your files on your computer. Whether it also asks an AI, and which one, is your choice, and you can
change it any time. This page says exactly what each choice means.

- [Rules only, or always AI](#rules-only-or-always-ai)
- [The services](#the-services)
- [What the AI sees, and what it never sees](#what-the-ai-sees-and-what-it-never-sees)
- [Masking](#masking)
- [Limits and spend](#limits-and-spend)
- [Testing a service](#testing-a-service)
- [Organisation advice](#organisation-advice)
- [Everything else that leaves your computer](#everything-else-that-leaves-your-computer)

## Rules only, or always AI

The setup asks the question; `desktidy ai <mode>` changes the answer.

| Mode | The AI reads | Files per day |
|---|---|---|
| `off` (`desktidy ai rules`) | nothing: the offline engine decides everything, nothing leaves your computer | 0 |
| `limited` | only the files the offline engine can't place | 10 |
| `moderate` | also the ones it places with low confidence | 30 |
| `ai-only` | every file except private ones; it also fixes names that don't match the content | 100 |
| `all` (`desktidy ai all`) | **always AI**: every file, bills, payslips and IDs included, and the AI names the files the rules would rename (`scan0001.pdf` → `Fattura_2231_Acme_Srl_2026-09-30.pdf`) | 100 |

When the AI is not available (no key, no internet, daily limit or budget reached) the offline engine takes over, so
nothing ever stops. Before private documents start going to a service on the internet, `desktidy ai all` names the
service and asks; with **Ollama** the AI runs on your computer and they never leave it.

## The services

`desktidy ai provider <name>`, then `desktidy key`:

| Service | Cost | Privacy | Reads images | Default model |
|---|---|---|---|---|
| `groq` *(default)* | **free** plan, about 1,000 requests a day, no card | prompts not used for training | no (text and OCR only) | `openai/gpt-oss-20b` |
| `gemini` | **free** tier on the Flash and Flash-Lite models | free tier: Google may use prompts to improve its products | yes | `gemini-3.5-flash-lite` |
| `mistral` | **free** Experiment plan (phone verification) | free plan: prompts may be used for training | yes | `mistral-small-latest` |
| `openrouter` | **free** `:free` models, 50 requests a day | free models: the host may log prompts | depends on the model | `google/gemma-4-31b-it:free` |
| `ollama` | **free**, runs on your computer ([ollama.com](https://ollama.com/download)) | nothing leaves your computer | yes | `gemma3:4b` |
| `claude` | paid, about $0.0003 per file with the Batch API | not used for training | yes | `claude-haiku-4-5` |
| `openai` | paid | not used for training by default | yes | `gpt-5-nano` |
| `custom` | any OpenAI-compatible server (LM Studio, vLLM...) | your server | set `ai.vision` | set `ai.model` |

Free plans and model names change often (checked in October 2026): `desktidy ai model <id>` switches model and
`desktidy key test` checks key and service for free. If a service refuses a feature (for example strict JSON),
DeskTidy steps down to a simpler request by itself. A `custom` or `ollama` service moved to another machine with
`ai.base_url` is treated as a service on the network, not as local.

API keys are kept in your Windows user environment, or on macOS and Linux in `keys.json` in DeskTidy's data folder,
readable only by you. They are never written to the logs and are shown masked.

## What the AI sees, and what it never sees

**Never sent, in any mode**: photos, screenshots and programs. They are recognised offline (camera data, screen
sizes, file types) and placed by your rules.

**Never sent unless you chose `all`**: files matched by a rule marked `private` (IDs, payslips, bills, CVs... in the
bundled rules).

**Sent for the other files**, one short request for up to 8 files:

- the file name, its kind (PDF, 2 pages...) and what DeskTidy recognised;
- about 1,200 characters of the text DeskTidy already read on your computer (OCR included), with its key terms;
- for a file with no text at all, a picture of it downscaled to 512 px, only to services that read images, and
  never for a private document while masking is on (a picture can't be masked);
- a short list of candidate folders (names only).

The file itself is never uploaded. The AI can only pick a folder from the list DeskTidy sent, and it is told to ignore
any instruction written inside a file.

`desktidy explain <file>` says for any file whether the AI would see it.

## Masking

Before anything goes to a service on the internet, DeskTidy replaces the numbers that identify you:

| In the text | Sent as | Checked by |
|---|---|---|
| `IT60 X054 2811 1010 0000 0123 456` | `[IBAN]` | the IBAN check digits (mod 97) |
| `4111 1111 1111 1111` | `[CARD]` | the Luhn check |
| `RSSMRA80A01H501U` | `[TAX_CODE]` | the codice fiscale check letter |
| `P.IVA 01234567897` | `[VAT_NO]` | the label and the check digit |
| `mario.rossi@example.com` | `[EMAIL]` | |
| `Tel. 333 123 4567`, `+39 02 1234 5678` | `[PHONE]` | a phone label, or `+`/`00` |

A number is masked only when its check digits say it really is one, so amounts, dates and invoice numbers reach the
AI and it still understands the document. **Names and street addresses are not masked**: they can't be told apart
from the rest of the text reliably. Masking is on by default (`"ai": {"redact": true}`) and is never needed with
Ollama, where nothing leaves your computer.

## Limits and spend

| Limit | Default | Change it |
|---|---|---|
| Files DeskTidy tidies per day, AI or not | unlimited | `desktidy limit 30` · `desktidy limit unlimited` |
| Files the AI looks at per day | 10 / 30 / 100 by mode | `desktidy ai max 50` · `ai max unlimited` · `ai max auto` |
| Total AI budget | $5 | `desktidy spend budget 10` |

When a limit is reached, the other files wait for the next day or go to the offline engine (one notification tells
you). With a paid service, `desktidy spend credit 4.85` tells DeskTidy your balance: it estimates what is left and
pauses the AI before the credit runs out. `desktidy spend` shows today, the last 7 days, the month and the total.

Every request is designed to be small:

| What | Effect |
|---|---|
| A short list of likely folders per file instead of the whole folder tree | the tree was ~80% of the tokens |
| Up to 8 files share one request, and files arriving close together wait up to 90 s for each other | instructions and folders paid once, fewer requests on free plans |
| A name check only for names the offline engine can't match with the content | no tokens spent on good names |
| An excerpt and key terms, never the whole file | small requests |
| A compact JSON answer: folder, name, summary, deadline and document date in one row | one request does it all |
| Claude's **Batch API** by default | **half price** (answers usually within minutes) |

Measured with Anthropic's token counter on the same three files, against the first design (the whole folder tree in
every request): **1,292 → 371 input tokens per file**, about **$0.00026 per file** with Claude Haiku 4.5 in batches.

## Testing a service

```sh
desktidy ai test --dry      # what would be sent: files, requests, size; nothing leaves your computer
desktidy ai test            # send 18 made-up documents and score the answers
```

The documents are invented (an Italian invoice, a bill, a payslip, lecture notes, a contract, a recipe, a flight
booking, a shopping list that fits no folder...), written to a temporary folder and deleted afterwards; your pinned
folders are not used and not shown. DeskTidy compares the answers with the right ones: the folder, the name, the date
of the document and the deadline. The spend is booked like any other request but not against the daily file limit.
Run it again after `desktidy ai provider <name>` to compare services.

## Organisation advice

In the `ai-only` and `all` modes, once DeskTidy has tidied enough files (30 by default), it asks the AI about once a
week how your folders could be organised better: merge, split, rename, move, archive, create or pin a folder.
`desktidy advice new` asks right away in any AI mode, and `advice apply 2` does it after a preview (folders of
programs, drives, your main folders and DeskTidy's data are refused; `advice undo` reverts it).

One small request: folder names, how many files each holds and of which types, the year of the latest change, two
file names per folder (none from private folders) and what DeskTidy saw recently. Never the content of a file.

`desktidy organize` with the AI reads, for each loose item, the name, the kind, a few key terms and the first words
of the text (about 60 tokens), with the same rules on what is never sent.

## Everything else that leaves your computer

- The AI service you chose, as described above, and nothing at all with *rules only* or Ollama.
- Once a week an anonymous request to GitHub for the latest version number (`"updates": {"check": false}` turns it
  off).

That's all. The search index, the deadlines, the learned rules, the logs and the history of moves are files in
DeskTidy's data folder. See also [SECURITY.md](../SECURITY.md).
