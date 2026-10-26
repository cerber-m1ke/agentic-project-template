# Reminders

What is worth considering soon: notes, plans and tasks it is time to come back to. A reminder retells
nothing — it links to the notes and explains why and when to return to them. Type `reminder`, lifetime —
until it is considered.

## When to create

- A plan or task should be taken up as soon as a session gets close: the same resource, module, topic.
- A decision, pitfall or card needs another look after an event: a release, an upgrade, a pilot.
- The human asks "remind me when…".

## When not to create

- Something urgent — tell the human right away.
- You just need to write down an idea — that is a plan in Plans, without a reminder.
- Re-checking by age — `Toolbox/tb kb stale` shows that anyway.

## When a reminder surfaces

- **Start and course of a session.** The `kb-suggest` hook shows reminders that overlap the request;
  `kb-lookup` mentions them in its answer. Search finds a reminder by the words of the notes it links
  to as well.
- **End of a session.** `wrap-up` runs `Toolbox/tb kb nearby <task>`: reminders, plans and tasks close
  to the work done (a shared resource or module, links, tags, words). The Agent offers to take up the
  close ones — in this session or in a new one.
- **Due date.** With `due` the reminder appears in `Toolbox/tb kb stale` on that day; without `due` —
  14 days after `verified`.

## Status and deletion

There is no status. Once considered, delete the reminder and decide on the linked notes: into a task,
fix, delete or keep. Postponed — move `due` or `verified` (`Toolbox/tb kb verify`).

## Name and creation

The file name says what to consider: `adopt-followups-after-pilot.md`.

`Toolbox/tb kb new reminder adopt-followups-after-pilot --title "adopt follow-ups after the pilot"`

## Example (fragment)

```markdown
title: "adopt follow-ups after the pilot"
description: "Take the adopt follow-up plan once the pilot on the second project is over"
due: 2026-11-15
## What to consider
- [adopt follow-ups](../Plans/adopt-followups.md)
## Why and when
The pilot will show which items of the plan are still needed.
```
