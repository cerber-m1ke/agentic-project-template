# Tasks

The specification of a current task: goal, details, decisions along the way, progress and takeaways
for Knowledge. With it, work continues in a new session, with another Agent or another human. Type
`task`, lifetime — until its takeaways are harvested.

## When to create

- The task will take more than one session or needs research and a specification.
- Decisions will be made along the way that must be remembered until the task is finished.

## When not to create

- A small thing that will be finished in this session. An idea for the future goes to Plans.

## Statuses

- `active` — in progress; `blocked` — waiting on something external (record the reason under "Progress").
- `done` — finished; takeaways are distributed to Decisions, Gotchas, Entities, Examples (`wrap-up`, `kb-review`),
  then the task file is deleted with the human's consent — it remains in git history.
- When updating progress, set `verified` to today: `active`/`blocked` tasks without updates for 14 days
  show up in `Toolbox/tb kb stale`.

Affected resources go into the `resources` field, branches into "Specification".

## Name and creation

The name states the gist of the task: `auth-token-refresh.md`. Need artifacts — make it a folder task `Tasks/<slug>/index.md` (`--folder`).

`Toolbox/tb kb new task auth-token-refresh --title "Auth token refresh"`

## Example (excerpt)

```markdown
title: "Auth token refresh"
description: "Refresh tokens in api and web: rotation and revocation"
resources: [api, web]
## Progress
- 2026-10-08: rotation in api is done (branch feat/refresh); web is next.
```
