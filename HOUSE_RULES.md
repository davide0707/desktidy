# DeskTidy house rules

Read these before DeskTidy moves anything. The setup (`desktidy setup`, started by the installer) shows them again
and asks you to accept them. You can read them any time with `desktidy guide`.

1. **A name starting with `!` is never touched.**
   `!draft.docx` or a folder called `!work in progress` stays exactly where it is, in Downloads, on the Desktop or
   in Documents. Remove the `!` to let DeskTidy handle it again.

2. **Pin at least 2 folders before it starts.**
   Pinned folders are the places where you want things to end up, for example `Study`, `Work` or `Recipes`.
   New files that talk about them (by name or by content) go there. Until two folders are pinned, DeskTidy only
   watches and moves nothing. Pin with `desktidy pin <folder>`, with `desktidy setup`, or by answering *Yes* when
   DeskTidy asks *"Pin it?"* about a folder you just created on the Desktop.

3. **It waits before acting.**
   Downloads are handled 2 minutes after they finish, the Desktop and Documents after 10 minutes. Open files,
   unfinished downloads, Office lock files (`~$...`), hidden and system files and shortcuts are always skipped.

4. **Nothing is lost.**
   Every move and rename is written to `moves.csv`: `desktidy where <name>` finds any file, `desktidy undo <name>`
   puts it back with its original name. A file identical to one already in the destination goes to the Recycle Bin,
   never deleted. Different files with the same name become `name_v2`, `name_v3`...

5. **Private stays private.**
   Files matched by a `private` rule (IDs, payslips, bills, CVs...), photos and screenshots are never sent to the AI.
   The AI is optional (free services included: `desktidy ai provider`), used only when the offline
   engine is unsure, with a daily limit and a total budget.

6. **You're in charge.**
   `desktidy pause 1h` · `desktidy stop` · `desktidy preview` shows what would happen without moving anything ·
   `desktidy rules` edits every destination.
