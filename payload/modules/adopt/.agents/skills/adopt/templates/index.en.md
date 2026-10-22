---
type: task
title: "{{title}}"
description: "Project migration by the adopt skill: inventory, resources, knowledge migration with ledgers, final audit, cleanup of the old"
status: active
created: {{date}}
verified: {{date}}
tags: [adopt]
aliases: []
resources: []
---

# {{title}}

## Goal

Everything valuable from the old locations is in Resources and Knowledge, nothing is lost silently; the old is deleted by the manifest
after the GO of the final audit. Procedure — the `adopt` skill.

## Specification

- Stages, sessions and status — [plan.md](plan.md); project rules — [rules.md](rules.md) (on top of
  `.agents/skills/adopt/rules.md`); `tb adopt` settings — `adopt.toml`.
- Inventory and resource decisions — [resources.md](resources.md); questions outside batches —
  [questions.md](questions.md); ledgers — `ledger/<source>/`.
- Final audit — [final-audit.md](final-audit.md), deletion manifest —
  [deletion-manifest.md](deletion-manifest.md).
- Where the migration is now: `Toolbox/tb adopt status --task {{slug}}`.

## Decisions along the way

<!-- Date — decision — why. -->

## Progress

<!-- Session, date, outcome in 1–3 lines. Details — in the ledgers and plan.md. -->

## In progress

<!-- Stage 6: active tasks with resources, branches, push/MR and the next step. -->

## Template feedback

<!-- What got in the way in the template and the adopt skill: stage — problem — proposal. -->

## Takeaways for Knowledge

<!-- What to move to Decisions, Gotchas, Entities when the task is closed. -->
