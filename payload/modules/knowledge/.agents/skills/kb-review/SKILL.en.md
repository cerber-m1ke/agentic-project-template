---
name: kb-review
description: Knowledge review — stale notes, unharvested task takeaways, forgotten plans, duplicates, broken links. Use when the human asks, on a reminder (tb kb stale, a hook), after a major milestone, or every few weeks.
---

# Knowledge review

The goal is to keep `Knowledge/` clean: current, free of duplicates and noise. You prepare suggestions;
the human decides what to apply. Do not delete anything or change statuses without their confirmation.

## Collect

1. `Toolbox/tb kb lint` — schema errors, broken links, file names, the `AGENTS.md` budget
   (Windows PowerShell: `Toolbox\tb.cmd kb lint`).
2. `Toolbox/tb kb stale` — candidates for re-checking (`--days N` — a custom threshold).
3. `Toolbox/tb kb index` — the overall picture, to spot duplicates.

## Analyze

- **Stale** (from `stale`): check each note against Resources the same way as in `kb-lookup`
  (versions against `applies_to`, whether files and functions exist). Correct — update `verified`;
  wrong — fix it in place; dead (the cause is fixed, the decision is replaced) — delete it.
- **Retired statuses** (`superseded`, `resolved`, `outdated`, `dropped`; `lint` and `stale` show them): delete the note.
- **Finished tasks** (`done`, "harvest pending"): distribute "Takeaways for Knowledge" to Decisions,
  Gotchas, Entities, Examples and delete the task.
- **Stalled tasks** (`active`/`blocked` without updates): ask the human about their status.
- **Plans** `idea`/`ready`: are they still relevant — to `ready`, to a task, or delete (record an important reason in a decision).
- **Decisions** `proposed` for more than 30 days: accept or delete — the human decides.
- **Duplicates and overlaps:** merge into one note, fix the links.
- **Notes that duplicate the code,** resource READMEs or git history: cut them down to a link to the source
  plus the non-obvious parts, or delete them.

## Suggestions and applying

1. Show the human a list grouped by action: update `verified`, fix, change status, merge, delete,
   questions for the human. For each item — the path and a one-line reason.
2. Apply only what was confirmed. Deleted notes remain in git history.
3. `Toolbox/tb kb lint` — there must be no errors.
4. Report briefly and offer to commit via the skill `kb-commit`.
