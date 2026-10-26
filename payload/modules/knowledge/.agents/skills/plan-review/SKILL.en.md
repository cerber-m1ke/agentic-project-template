---
name: plan-review
description: Review of the Plans backlog — what is already done or no longer relevant, duplicates and overlaps with tasks, readiness for work, priorities; a verdict with reasoning for each plan (ready, refine, to-task, merge, delete, ask). Use when the human asks, when planning work, when plans have piled up, or on a tb kb stale reminder about plans.
---

# Plan review

## Goal and result

Plans is a short, live backlog. Every plan is relevant and does not duplicate other plans or tasks. For
each it is clear whether it is ready for work, and the human has a proposed order. The review is
finished when:

- every plan has a verdict with reasoning, `delete` — with evidence;
- the confirmed actions are applied, `Toolbox/tb kb lint` shows no errors;
- the human has the report with priorities and questions.

## Boundaries

- Scope — `Knowledge/Plans/`. The rest of Knowledge is checked by the `kb-review` skill.
- You read tasks to find overlaps but do not change them — except when moving a plan into a task.
- You do not start working on a plan. Create a task, delete, merge or change a status only after
  the human confirms.
- Checking against Resources is read-only, as in `kb-review`.
- Commit what you applied right away (skill `kb-commit`) and name the commits to the human.
- Reminders (`Knowledge/Reminders/`) about a plan are part of its verdict: the plan is deleted or taken
  into a task — delete the reminder or move its link to the task.

## Verdicts

| Verdict | When | Action |
|---|---|---|
| `ready` | Meets the readiness criteria | `status: ready`, `Toolbox/tb kb verify <path>` |
| `refine` | The idea is alive but does not meet the readiness criteria | Add what is known, questions — to the human; `idea`, `tb kb verify` |
| `to-task` | Ready, and the human takes it up now | `Toolbox/tb kb new task <slug>`, move the content, delete the plan |
| `merge` | Overlaps with another plan or is covered by an active task | Merge into one plan or add to the task; delete the rest |
| `delete` | Already done; no longer relevant (approach changed, entity gone); the human rejected it | Delete; an important reason for rejection — as a decision in Decisions |
| `ask` | The human must choose, or it cannot be checked | A specific question |

## Readiness criteria

- Goal and benefit — in 1–3 sentences; it is clear how to check the result.
- The size is estimated: a small item for one session or a task for several.
- Affected resources are listed in `resources` and exist in the catalog.
- The first steps are known. There are no open questions, or they are written down; blockers are named.

## Evidence

- "Already done" — a commit or a place in the code: `git -C Resources/<name> log --oneline --grep '<word>'`
  or `-S '<string>'`, `Resources/<name>/<path>:<line>`, `git log --oneline -- <path>`.
- "No longer relevant" — what changed: a decision, a removed entity, a new approach; a path or a commit.
- "Covered by a task" — the task path and the item of its specification.
- "Not done", "not in the code" — a negative claim: only a search that ignores ignore files, across all
  affected repositories, including those nested in a resource (`rg --no-ignore`, `git -C <repository> grep`),
  as in `kb-review`. An empty result of an ordinary search is not evidence.
- No evidence — `ask`.

## Steps

1. **Collect.** `Toolbox/tb kb search --type plan --brief`, `Toolbox/tb kb stale` (plans),
   `Toolbox/tb kb search --type task --status active,blocked --brief` — for overlaps
   (Windows PowerShell: `Toolbox\tb.cmd …`).
2. **Read.** Read every plan: `Toolbox/tb kb show <path>`.
3. **Check.** Check against Resources whether it is done and whether it is still relevant. If there are
   more than eight plans and your agent can launch subagents, hand the check to `kb-auditor` in batches
   per resource (per module for `<resource>/<subpath>` in `resources`), in parallel, marked
   "skill plan-review". More than ~30 plans — also pass each one a report path
   `Runtime/plan-review/<YYYY-MM-DD>/<batch>.md`: the full report goes there, the reply is a summary of at
   most 10 lines. Consolidate from the report files.
4. **Verdicts.** Give the verdicts and find overlaps: plan with plan, plan with task.
5. **Priorities.** For `ready` and `refine`, propose an order by these criteria: benefit, urgency (what
   it blocks), cost, dependencies. The order goes only into the report; plan files are not changed for it.
6. **Report.** Show the report in the format below and wait for confirmation. Ask which plans to take up.
7. **Apply** only what was confirmed. Kept plans — `Toolbox/tb kb verify <paths>` (do not edit `verified`
   by hand). Then `Toolbox/tb kb lint` with no errors.
8. **Wrap up.** Counts per verdict, tasks created, commits, open questions.

## Acceptance criteria

- No two plans about the same thing and no plans covered by an active task.
- Only plans that meet the readiness criteria have `ready`.
- Kept plans have `verified` = today, so `tb kb stale` no longer lists them.
- Dead plans are deleted, and important reasons for rejection are recorded.

## Report format

```
Plan review <YYYY-MM-DD> — plans: N
ready: N · refine: N · to-task: N · merge: N · delete: N · ask: N

| Plan | Verdict | Reasoning / evidence | Action |
|---|---|---|---|

Proposed order: 1. <plan> — <why first>; 2. …
Questions for the human:
1. …
```
