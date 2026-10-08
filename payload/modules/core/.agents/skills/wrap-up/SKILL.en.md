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
5. **Pitfalls** → Gotchas: `Toolbox/tb kb new gotcha <slug> --title "…" --description "…"` — symptom, cause, workaround,
   how to check it still applies; versions go in `applies_to` (`node@22`).
6. **Decisions that will outlive the task** → propose an ADR: `Toolbox/tb kb new decision <slug> --title "…" --description "…"`
   with status `proposed`. Move it to `accepted` only with the human's consent.
7. **Entities.** Learned something new about a service, module or data store (relations, invariants,
   owners) — update its card in Entities or create one: `Toolbox/tb kb new entity <slug> --title "…" --description "…"`.
8. **Re-verified notes.** If you checked a note against Resources during the session and it is correct,
   set `verified` to today's date. Fix an outdated note or change its status (`resolved`, `outdated`,
   `deprecated`, `superseded` with `superseded_by`).
9. **Check.** `Toolbox/tb kb lint`; fix all errors.
10. **Report to the human:** paths of the notes you created and changed, and what needs their decision
    (ADRs, task deletion, statuses). Offer to commit via the `kb-commit` skill. Do not commit yourself.

## Do not record

- what is visible from code, configs, resource READMEs or `git log`;
- a retelling of the session or a chronology without conclusions;
- temporary things — logs, drafts, exports (those belong in `Runtime/`);
- secrets, tokens, passwords, personal data.

Convert relative dates ("yesterday", "on Friday") to absolute ones; links between notes are relative
Markdown links. Knowledge rules — `Knowledge/README.md`.
