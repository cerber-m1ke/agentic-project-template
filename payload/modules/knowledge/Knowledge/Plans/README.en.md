# Plans

Ideas, postponed work and things discovered along the way — so that nothing gets lost and tech debt
does not pile up silently. A very fluid area: the Agent reminds about plans, reviews keep it tidy.
Type `plan`, lifetime — until it becomes a task or is dropped.

## When to create

- Something worth doing, but not now, came up in a session (usually during `wrap-up`).
- An improvement idea came up or tech debt was noticed.

## When not to create

- Work has already started — that is a task in Tasks.
- It is urgent — tell the human right away instead of deferring it to a plan.
- A similar plan already exists — extend it.

## Statuses

- `idea` — written down, not worked out.
- `ready` — it is clear what to do and why; can be picked up.

There are no plans in progress or completed — such a plan is deleted:

- Picked up: `Toolbox/tb kb new task <slug>`, move the plan's content into the task, delete the plan.
  A small item done right away without a task — delete the plan.
- Rejected — delete the plan. If the reason matters, so the idea is not proposed again, record it as
  a decision in Decisions or under "Non-obvious details" of an entity card.

`kb-review` brings plans in `idea` and `ready` older than 60 days up for discussion with the human.

## Name and creation

The file name states the gist of the idea: `cache-kb-index.md`, `migrate-ci-to-actions.md`.

`Toolbox/tb kb new plan cache-kb-index --title "Cache the Knowledge index"`

## Example (excerpt)

```markdown
title: "Cache the Knowledge index"
description: "Search will slow down after ~2000 notes — cache in Runtime/cache/"
## Why
The prompt-submit hook runs a search on every prompt.
```
