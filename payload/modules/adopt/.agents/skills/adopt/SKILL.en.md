---
name: adopt
description: Migrating a large existing project into an Agentic Project — inventory of old copies, resources, knowledge migration in batches (worker → auditor) with ledgers and a gate, a final audit and cleanup of the old by a manifest. Use when the human asks to move, wrap or migrate a project with many repositories, a notes vault, working documents or agent memory, or to continue a migration already started (a task with adopt.toml).
---

# Project migration (adopt)

## Goal and result

Everything valuable from the old locations is in Resources and Knowledge, nothing is lost silently, the old is deleted after the GO
of the final audit. The migration is finished when:

- every file of every source has a ledger row with a verdict and the auditor's `ok`, `tb adopt gate`
  is green;
- the final audit gave GO, the human checked the new environment and confirmed the cleanup;
- the old is removed by the deletion manifest, the task is closed with `wrap-up`, the `adopt` module is removed.

A small project (a few repositories, only agent memory) does not need this skill: INIT §6 is enough.

## Boundaries and safety

- Old locations (old copies, vaults, `~/.claude`, `~/.codex`) — read-only until stage 8, after that —
  only by the deletion manifest. Deletion goes to the Trash, which the human empties themselves.
- Checks — read-only: no docker, builds, tests, `fetch`/`pull`/`checkout`, network. Cannot check —
  `unverified` per `rules.md`.
- Secret values are never copied anywhere: not into notes, the ledger or answers. The ledger holds a pointer
  `path:line — what it is`. Checkers do not print the content they find: only path, type, size, checksum.
- Irreversible and external actions (renaming, `mv` of a resource, push, deletion) — only after the human's "yes".
- Do not bypass the pre-commit hook: no `--no-verify` and `commit-tree`. It failed — fix the cause.
- "Not in the code" is proven only by a search that ignores ignore files: `rg --no-ignore`,
  `git -C <repository> grep` in every nested repository.

## Where things are

- The task `Knowledge/Tasks/<task>/` (created by `tb adopt start`), all in git:
  - `index.md` — the task note: goal, progress, decisions, "In progress", template feedback;
  - `plan.md` — status of stages and sessions, dependency graph, project facts and decisions, a section per stage;
  - `adopt.toml` — old roots, archive directory, secrets folder, sources `[[source]]`;
  - `rules.md` — project rules on top of the base `.agents/skills/adopt/rules.md`;
  - `resources.md` — the inventory and a decision for each row;
  - `questions.md` — questions outside batches; `ledger/<source>/` — manifest and batches;
  - `final-audit.md`, `deletion-manifest.md` — stage 7.
- `Runtime/adopt/` — raw material outside git: inventory, digests, checker reports.
- The archive directory (`archive_dir`) — outside the project, mode 700, archives 600.
- Subagent prompts — `.agents/skills/adopt/prompts/`, templates — `.agents/skills/adopt/templates/`.

## Roles and context

- **Orchestrator** — the main session of a stage: cuts batches, runs subagents, consolidates, maintains `index.md` and
  its row in `plan.md`, asks questions, commits. Does not read in bulk: subagents read note bodies and sources,
  the orchestrator reads `check`/`gate` reports and verdicts.
- **Worker** — the `adopt-worker` subagent, one batch per `prompts/worker.md`.
- **Auditor** — the `adopt-auditor` subagent, fresh context, per `prompts/auditor.md`; writes only the
  "Audit" column. The orchestrator does not fill in audit verdicts for the auditor.
- A batch — up to 12 files or ~60 KB of text on one topic or folder. At most 5 subagents at a time.
  A subagent's answer — at most 10 lines, details — in the ledger.
- No subagents — play the roles yourself by the same prompts, the audit — a separate pass after a pause to
  reread `rules.md`.

## Sessions and resuming

- A session = a row in `plan.md` (ID, dependencies, status, date, outcome). The session start prompt is the same for all:
  "Run session <ID> per `plan.md` of task <task>; read the shared rules and your section".
- A session edits only its own status row, rereading `plan.md` before the edit.
- The resume point is the ledger and `plan.md`, not the session's memory: `tb adopt status`. Near the context limit
  stop at a batch boundary, record progress in `index.md` and finish; the next session with the same
  prompt continues from the first uncovered row.
- End of a session: the status row, "Progress" in `index.md`, a commit offer, an answer to the human ≤ 10 lines.

## Batch pipeline

1. `tb adopt next <source>` — uncovered files with sizes; cut a batch by topic.
2. Worker (`prompts/worker.md`) → `tb adopt check <source> <batch> --pre-audit` is green.
3. Auditor (`prompts/auditor.md`) → `ok` or `fix: …` for each row.
4. `fix` — the worker reworks and clears "Audit", the auditor again. At most 2 rounds, then — a question to
   the human.
5. Finishing a source: `tb adopt check <source>` is green, `duplicate-candidate` resolved by the orchestrator
   (merged → `merged`/`duplicate`), unaccepted handoffs passed on in the recipient's `hNN` batch.

The first batch of each kind of source is a pilot: the human looks at "source → result" pairs and approves
the rules before the remaining batches.

## Parallel sessions and commits

- In parallel — one group of sources per session, in the shared project tree (a worktree of the root does not contain the resources).
- A session commits only its own notes and its own ledger files, by explicit paths, after a green
  `check <source>`. Links to notes not yet created are deferred (`"pending"`), they are resolved by
  `tb adopt links --write`.
- Shared task files and closing a stage are committed by the orchestrator after a green `tb adopt gate`. If
  `index.lock` is taken — retry later.

## Stages

0. **Preparation (before init — INIT §6.2).** A fresh machine backup; agent and IDE sessions in the old path closed;
   the old folder renamed, whatever is bound to the path moved; init `--with adopt`, resources and adopt skipped
   in init. From here, this skill: `tb adopt start <task> --old-root <path>… --archive-dir <path>`,
   `plan.md` from the template, an archive of what cannot be recovered (a vault without a remote, working documents, local
   repositories without a remote) — `tb adopt archive <name> <paths…>`.
   Done when: the task and `plan.md` are created, archives are verified (`archive` checked the checksums).
1. **Inventory.** `tb adopt inventory` (over `old_roots`), the draft — in the task's `resources.md`.
   The human decides on every row in one batch: `clone` (+ branch), `mv` (state bound to the
   path), `folder`, `secret`, `toolbox`, `knowledge` (goes to the migration), `push-first` (the human pushes,
   then `clone`), `archive` (git bundle or tar), `discard` (with a reason).
   Done when: every row has a decision, all local work (branches, stash, dirty, stale
   `origin/*`) is accounted for.
2. **Resources.** `tb resources add <old copy> --clone --entity …`; check warnings about local work
   against `resources.md`, anything unaccounted — stop and ask. Secrets — by copying into the secrets folder
   (`secrets_dir`, mode 700/600, hidden in `.ignore`) with a sha256 check. `mv` — by the procedure: a snapshot of
   the state, a search for absolute paths, the human's "yes", a stop without data loss, the move, path fixes,
   a check against the snapshot, a described rollback. Leftovers that need the network — the first step of the next
   session. Agent settings of resources (`.claude/`, `.mcp.json`, `.codex/`) are sorted out by a subagent with a summary:
   MCP → `.agents/mcp.toml`, denials → `.agents/permissions.toml`, procedures → `.agents/skills/`, hooks →
   rules in `AGENTS.md`; once sorted — `tb resources set <name> agent_settings_reviewed=…`. Agent instructions
   inside resources stay in place, but check them for secrets.
   Done when: `tb resources status` and `tb agents doctor` report nothing.
3. **Rules and pilot.** `tb adopt sources` → `[[source]]` blocks in `adopt.toml` (transcripts — only at
   the human's request). Subagents study ~5 samples of each source folder. `tb adopt manifest`,
   `tb adopt slugmap`, the project's `rules.md` (table of resources and tags, the human's decisions, exceptions).
   Pilot — 8–10 diverse files through the whole pipeline.
   Done when: the human approved the rules by "source → result" pairs, the pilot's `check` is green.
4. **Migration.** By source, in parallel sessions, through the batch pipeline. Transcripts — last and only
   via digests: `tb adopt digest <source>`, subagents take ~8 digests each and produce candidates, the human
   approves the list, then workers create notes (other rows — `junk`/`derivable` with a reason).
   Done when: the `check` of every source is green.
5. **Questions.** A round of questions in one batch (`tb adopt status` collects the open ones), answers go into notes through the same
   pipeline, the question row gets `(answer: …)`. Repeated after stages 4, 6 and 7.
6. **Consolidation.** Duplicates and overlaps between sources; `tb adopt links --write` over all Knowledge;
   skills `kb-review` and `plan-review` over everything (reports to files); `tb kb verify` for what was checked;
   the project part of `AGENTS.md` (rules from instructions and memory — with consent); `entity` in the catalog.
   "In progress" in `index.md`: active tasks with resources, branches, push/MR and the next step.
   Template feedback consolidated by topic in `index.md`.
   Done when: `tb adopt gate` is green, `tb kb lint` 0/0, `tb secrets scan` is clean.
7. **Final audit.** Read-only, blocks — by separate subagents per `prompts/final-check.md`:
   A — Knowledge (completeness of manifests by a reverse walk of sources, re-audit of 10% of
   `obsolete`/`derivable`/`duplicate`/`junk` rows, at least 15); B — code (`tb adopt inventory --compare
   <stage 1 snapshot>`, work outside the new clones); C — secrets; D — agent data; E — environment
   (`tb adopt refs`); F — the new environment (`tb setup`, `doctor`, resources, Knowledge). The result — `final-audit.md`
   with GO/NO-GO (on NO-GO every blocker gets a fix session) and `deletion-manifest.md`.
   Done when: the verdict is GO, the deletion manifest is drawn up.
8. **Cleanup** — only after GO and the human's "yes". First the human checks themselves: Knowledge in Obsidian by
   type; two or three questions to a new agent session ("what is in progress now?") — the answers must come from Knowledge;
   resources and the environment work. Then close sessions and IDEs in the old paths. Order: archive the root
   repository of the old copy and the transcripts (`tb adopt archive`); deletion by the manifest — each group
   after a "yes" (the human moves it to the Trash or the agent does `mv` to the OS Trash); config fixes from the audit;
   agent app records — through their interface; the orchestrator session's transcript — last.
   Then the task's `wrap-up` skill, removing the module (`agentic-update`, "remove the adopt module": the task data
   stays), template feedback — to the human for an issue.
   Done when: the old locations are removed by the manifest, the new environment is the only workplace.

## Commands

| Command | What it does |
|---|---|
| `tb adopt start <task>` | task folder from templates, `adopt.toml` with the old roots |
| `tb adopt archive <name> <paths…>` | tar.gz into the archive directory, mode 600, sha256 check of every file |
| `tb adopt inventory [roots…]` | repositories (with nested ones), local work against the server, stash, dirty, valuable untracked, non-git; `--fetch`, `--offline`, `--compare` |
| `tb adopt sources` | `[[source]]` candidates from the old roots and agent data |
| `tb adopt manifest [--source S]` | `ledger/<source>/manifest.txt` |
| `tb adopt slugmap` | a planned note for each file of sources with `folder` |
| `tb adopt next <source>` | uncovered files with sizes |
| `tb adopt links [notes…] [--write]` | `[[wikilinks]]` and old links → relative; not yet migrated — `"pending"` |
| `tb adopt check <source> [batch] [--pre-audit]` | ledger: coverage exactly once, verdicts, targets, audit; then `tb kb lint` |
| `tb adopt gate` | all sources, handoffs accepted, questions listed; before a shared commit |
| `tb adopt status` | where the migration is: `plan.md` status, coverage, handoffs, questions, secrets |
| `tb adopt refs [paths…]` | old paths in the environment (git, agents, shell, Obsidian, IDE, cron, Docker) |
| `tb adopt digest <source>` | transcript digests with secrets masked → `Runtime/adopt/digests/` |

Migration rules — `rules.md` next to this file.
