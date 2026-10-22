---
name: kb-review
description: Knowledge review — check Decisions, Entities, Gotchas, Examples and Tasks notes against Resources and git history; a verdict with evidence for each (keep, fix, shrink, merge, delete, ask), checked in batches by kb-auditor subagents. Use when the human asks, on a reminder (tb kb stale, hook), after a major milestone or every few weeks. The Plans backlog — skill plan-review.
---

# Knowledge review

## Goal and result

Knowledge keeps only what is alive, correct and non-obvious. The review is finished when:

- every note in scope has a verdict with evidence;
- the actions the human confirmed are applied, `Toolbox/tb kb lint` shows no errors;
- the human has the report and the questions.

## Boundaries

- Default scope: Decisions, Entities, Gotchas, Examples, Tasks. The human may narrow it: a type,
  a resource, a list of paths, only `tb kb stale`. Plans — skill `plan-review`.
- You change only `Knowledge/`. Do not fix errors in Resources, code or `.agents/` — put them in the report.
- Checking is read-only. You may read files, search, look at `git log`/`show`/`branch` and versions.
  You may not run builds, installs, tests, `checkout`/`pull`/`fetch`. If a check needs side effects,
  the verdict is `ask`.
- Delete, merge, change a status or edit an accepted decision only after the human confirms. They may
  confirm the whole list at once or item by item.
- Do not commit: at the end offer the `kb-commit` skill.

## Verdicts

Exactly one verdict per note:

| Verdict | When | Action |
|---|---|---|
| `keep` | Key claims are confirmed | `Toolbox/tb kb verify <path>` (`verified` = today) |
| `fix` | The topic is alive, but facts are wrong (paths, versions, commands, relations) | Fix in place, then `tb kb verify` |
| `shrink` | Retells the code, a resource README, git history | Keep a link to the source and the non-obvious parts |
| `merge` | Overlaps with another note | Merge into one, redirect links |
| `delete` | Dead (see the criteria), a retired status, a `done` task after harvesting | Move what matters to a live note, delete, remove links |
| `ask` | Cannot be checked, or the human must choose | A specific question in the report |

## Evidence

A verdict without evidence is not allowed. Evidence is something the human can check themselves:

- a file, function or key found: `Resources/<name>/<path>:<line>`;
- not found — a search command with an empty result, by the rule below;
- a version from a lock file or manifest against `applies_to`;
- a commit: `git -C Resources/<name> log --oneline -S '<string>'`, `git log --oneline -- <path>` —
  when it was fixed, deleted, a branch merged;
- the result of the "How to check it still applies" check (without side effects);
- the path of another note — for `merge`, and for `delete` when replaced.

A negative claim ("not in the code", "unused", "removed") is proven only by a search that ignores
ignore files, across all affected repositories, including those nested in a resource:
`rg --no-ignore '<string>' Resources/<name>` or `git -C Resources/<name>/<nested> grep '<string>'`
in each repository. An empty result of an ordinary search (the agent's Grep, `rg` or `grep` from the root) is not
evidence: it may not see `Resources/` and nested repositories (`Resources/README.md`).

"Looks like", "probably", "not updated for a long time" do not count as evidence: in such cases the verdict
is `ask`. If the resource is not cloned, it is also `ask`, not `delete`.

## Criteria by type

- **Gotcha.** Is the cause alive. Compare `applies_to` versions with lock files, run "How to check it
  still applies", look for a fix or workaround in the code. The cause is gone in all versions in use —
  `delete`; only in some — `fix` with a narrower `applies_to`.
- **Example.** Does it match the accepted approach. Find 1–2 recent places with the same pattern in
  Resources. Diverges — `fix` or `delete`. A canonical sample appeared in the code — `shrink` to a link or `delete`.
- **Decision.** Is it in force: code and configs match the "Decision" section. They do not — `ask`
  (is the decision violated or revoked?). Replaced by another — `delete`, moving the reason to the new one.
  If the gist is visible from the code and documentation and nobody will ask "why this way?" any more —
  `delete`; for an `accepted` one, `ask` when in doubt. `proposed` older than 30 days — `ask`: accept or delete.
- **Entity.** Does the entity exist. Check paths, entry points, relations and owners. A retelling of
  the code — `shrink`. A `deprecated` entity that no longer exists — `delete`.
- **Task.** `done` — distribute "Takeaways for Knowledge" by the rules of the `wrap-up` skill, then
  `delete`. `active`/`blocked` without updates for 30 days — `ask`. Compare progress with commits and check
  branches: `git -C Resources/<name> branch -a --list '<branch>'`, `git -C Resources/<name> branch --merged`.
- **All types.** `description` reflects the gist, links are not broken and do not lead to notes being
  deleted, no duplicates, no secrets.

## Steps

1. **Collect.** `Toolbox/tb kb lint`, `Toolbox/tb kb stale`, `Toolbox/tb kb index --json`,
   `Toolbox/tb resources status` (Windows PowerShell: `Toolbox\tb.cmd …`). List the notes in scope.
2. **Batches.** Split the notes into batches of 5–8, one resource per batch where possible, so a subagent
   reads one resource. Group notes with `<resource>/<subpath>` in `resources` by module: one batch per module.
   Notes without a resource go into a separate batch.
3. **Check.** If your agent can launch subagents and `kb-auditor` is available, run it on every batch
   in parallel, all calls in one message. Pass the note paths, today's date and the scope. If there are no
   subagents or fewer than six notes, check them yourself by the same criteria and in the `kb-auditor` format.
   Large scope (more than ~30 notes): also pass every `kb-auditor` a report path
   `Runtime/kb-review/<YYYY-MM-DD>/<batch>.md`. It writes the full report there and replies with a summary
   of at most 10 lines.
4. **Consolidate.** Collect the verdicts (for a large scope — from the report files, not the replies) and
   check yourself what a batch cannot see: overlaps between batches, links to notes with `delete` and `merge`.
   Recheck a verdict with weak evidence or turn it into `ask`.
5. **Report.** Show the human the report in the format below. For `delete` and `merge`, say what
   moves where. Wait for confirmation.
6. **Apply** only what was confirmed, in this order: move what matters → `merge` → `fix`/`shrink` →
   `delete` → fix links → `Toolbox/tb kb verify <paths>` for `keep` and `fix` (do not edit `verified`
   by hand).
7. **Verify.** `Toolbox/tb kb lint` — no errors and no warnings about retired statuses.
   `Toolbox/tb kb stale` — only notes with the `ask` verdict remain in scope.
8. **Wrap up.** Counts per verdict, what was applied, open questions. Offer the `kb-commit` skill.

## Report format

```
Knowledge review <YYYY-MM-DD> — scope: <…>; checked: N
keep: N · fix: N · shrink: N · merge: N · delete: N · ask: N

| Note | Verdict | Evidence | Action |
|---|---|---|---|
| Knowledge/Gotchas/uv-proxy-ssl.md | delete | Resources/api/uv.lock: uv 0.14 (applies_to uv@0.12); fixed in 0.13 — Resources/api/CHANGELOG.md:12 | delete; link from Entities/api.md |

Questions for the human:
1. Knowledge/Decisions/<slug>.md — <question>
```

`keep` rows may be collapsed into one: `keep: <paths>`.
