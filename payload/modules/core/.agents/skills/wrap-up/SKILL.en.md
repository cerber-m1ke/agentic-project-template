---
name: wrap-up
description: Session wrap-up and Knowledge harvesting. Use at the end of a work session, after finishing a task or stage, before switching topics, and when the human says "that's it for today", "wrap up", "save the context".
---

# Session wrap-up

The goal is to move into `Knowledge/` whatever will be useful in future sessions and cannot be derived
from Resources and git history. Write concisely, in the project's language; create new notes only via
`Toolbox/tb kb new`. Before creating any note, look for a similar one (`Toolbox/tb kb search …`) and
update it instead of creating a duplicate.

## Steps

1. **Gather material.** Go through the session: what was done, which decisions were made, what was
   postponed, what tripped you up, what you learned about entities. For changes in repository resources,
   check `git -C Resources/<name> status` and `git -C Resources/<name> log`.
2. **Active task** (`Toolbox/tb kb search --type task --status active --brief`). Update:
   - "Progress" — what is done and what comes next, with absolute dates;
   - "Decisions along the way" — decisions that apply only within the task;
   - "Takeaways for Knowledge" — what to move into other notes once the task is finished;
   - `status`: `active`, `blocked` (record the reason) or `done`; the `resources` field — affected resources;
   - `verified` — today's date.
   If the work happened without a task but will continue, suggest creating one:
   `Toolbox/tb kb new task <slug> --title "…" --description "…"`.
3. **Task finished (`done`).** Distribute the "Takeaways for Knowledge" across Decisions, Gotchas,
   Entities and Examples, and suggest that the human delete the task file — it stays in git history.
4. **Postponed items and ideas** → Plans: `Toolbox/tb kb new plan <slug> --title "…" --description "…"` (status `idea`).
   To come back to it soon or by a date → a reminder: `Toolbox/tb kb new reminder <slug> --title "…"`
   with links to the notes and `due` if the date is known.
5. **Pitfalls** → Gotchas: `Toolbox/tb kb new gotcha <slug> --title "…" --description "…"` — symptom, cause, workaround,
   how to check it still applies; versions go in `applies_to` (`node@22`).
6. **Decisions that will outlive the task** → propose an ADR: `Toolbox/tb kb new decision <slug> --title "…" --description "…"`
   with status `proposed`. Move it to `accepted` only with the human's consent.
7. **Entities.** Learned something new about a service, module or data store (relations, invariants,
   owners) — update its card in Entities or create one: `Toolbox/tb kb new entity <slug> --title "…" --description "…"`.
8. **Re-verified notes.** If you checked a note against Resources during the session and it is correct,
   set `verified` to today's date (`Toolbox/tb kb verify <path>`). Fix an outdated note in place. Offer the human to delete a dead one
   (the gotcha's cause is fixed, the decision is replaced, the example or entity is no longer needed):
   Knowledge stores only what is alive, earlier versions are in git history.
9. **Check and commit.** `Toolbox/tb kb lint`; fix all errors. Commit your Knowledge edits
   (skill `kb-commit`); corrections to this session's commits — `--amend`.
10. **Report to the human:** the commits, paths of the notes you created and changed, and what needs their
    decision (ADRs, note deletion, statuses).
11. **What else is nearby.** `Toolbox/tb kb nearby <the session's task>`; without a task —
    `Toolbox/tb kb nearby --query "<what was done: modules, files, topics>" --resource <resource>`.
    - Keep only what is really close: the same module or files, a shared cause, the same check. One
      shared word is not a reason.
    - Offer to take up the close items (at most three): what it is, why now is convenient, where to do it.
      In this session — if the work is small and the session's context is still free (no compaction,
      no long outputs, not many files read). Otherwise — in a new session with a ready short brief: the
      goal, note paths, resources, what this session already knows.
    - A reminder has been considered (taken up or declined) — with the human's consent delete it or move
      `due`, then commit.
    - Nothing close — say so in one line.

## Do not record

- what is visible from code, configs, resource READMEs or `git log`;
- a retelling of the session or a chronology without conclusions;
- temporary things — logs, drafts, exports (those belong in `Runtime/`);
- secrets, tokens, passwords, personal data.

Convert relative dates ("yesterday", "on Friday") to absolute ones; links between notes are relative
Markdown links. Knowledge rules — `Knowledge/README.md`.
