# Base knowledge migration rules

For workers, auditors and the orchestrator of the `adopt` skill. The basis is `Knowledge/README.md` and the folder READMEs; here —
only what concerns the migration. Project rules (resources and tags, the human's decisions, exceptions) —
in the task's `rules.md`: they extend these and take precedence on conflict.

## Verdicts

Every manifest file gets exactly one ledger row with one verdict:

| Verdict | Meaning | Target | Reason |
|---|---|---|---|
| `migrated` | Moved into new notes | notes, comma-separated | if it deviates from slugmap — why |
| `merged` | Merged into an existing note | note | — |
| `task` | Active work | `Knowledge/Tasks/<slug>.md` or `…/<slug>/index.md` | — |
| `secret` | Entirely a secret (key, profile, passwords) | a file in the secrets folder (`secrets_dir`) | — |
| `foreign` | Not related to the project | — | where to hand it over; the human decides (question) |
| `obsolete` | No longer relevant: done, cancelled, outdated | — | evidence: commit, path, command |
| `derivable` | Derivable from code, configs, git, README | — | where exactly |
| `duplicate` | A duplicate | — | of what exactly |
| `duplicate-candidate` | A possible duplicate of a note from another batch | that note | resolved by the orchestrator; never final |
| `junk` | Junk: fragments, experiments, service files | — | what it is, briefly |

- Partially migrated — the verdict by the main part (`migrated`/`merged`), what was dropped — in "Reason" in one phrase.
- Several sources into one note: the first is `migrated`, the rest are `merged` into it.
- A `migrated` target may be outside Knowledge: a skill (`.agents/skills/<name>/SKILL.md`), a tool
  (`Toolbox/<name>` with an entry in `Toolbox/README.md`), the project part of `AGENTS.md`.
- Could not check — do not invent a verdict: migrate it marked `unverified` or ask a question.

## Ledger

`ledger/<source>/<batch>.md`, a batch is `NN-<topic>` (`01-auth`), `pilot` or `hNN` (reworking handoffs).

```markdown
# <source> / <batch>

| Source | Verdict | Target | Reason | Audit |
|---|---|---|---|---|
| ~/Vaults/App/decisions/2026-03-01-auth-tokens.md | migrated | Knowledge/Decisions/auth-tokens.md | | ok |
| ~/Vaults/App/decisions/old-cache.md | obsolete | | `rg --no-ignore -n CacheV1 Resources/api` → empty; deleted in `a1b2c3d` | ok |

## Handoff

- #1 → <receiving-source>: <a row of its manifest> — <fact with evidence>

## Questions

- #1 <question> — <context>

## Secrets

- #1 <path>:<line> — <what it is>
```

- Columns are positional: source, verdict, target, reason, audit. Headers — in the project language.
- "Source" — the manifest row verbatim; "Target" — paths from the project root, comma-separated.
- "Reason" — up to ~400 characters: the main evidence (command → result), what was dropped,
  `unverified: …`. Details — in the note.
- `|` inside a cell is escaped: `\|`.
- Only the auditor writes "Audit": `ok` or `fix: <remark>`. The worker leaves it empty and clears it after
  rework.
- The id of a section item is `<source>/<batch>#<n>`; numbers within a batch are never reused.
- Check: `tb adopt check <source> [<batch>] [--pre-audit]`.

## Type and folder

| Source kind | Where | Rule |
|---|---|---|
| `vault` | by type folder (`folder`) | Collapse "Refined <date>", "Revised" layers into the current state; a rejected option — into "Alternatives". Glossary: a term — `aliases` of an entity, a concept with a life of its own — entity, conflicting meanings — gotcha, a name from the code — `derivable`; the file's verdict — `merged` with all targets. The vault index — `derivable` (`tb kb index`) |
| `docs` | by content | The unit is the live remainder of a folder: first the status by git and code. Done — `obsolete`/`derivable`, extract only the "why" (decision) and non-obvious pitfalls (gotcha). Live — a task or plan per folder + extracted decisions/gotchas. A procedure — a skill. Attachments, experiments, exploratory scripts — `junk`; research — by the human's decision (archive or a folder resource) |
| `claude-memory` | by content | Cut by topic. Check statuses ("not committed", "in progress") against the resource's git before writing. `MEMORY.md` — `derivable` (index) |
| `codex-memory` | by content | The memory is global: what relates to the project — as `claude-memory`, the rest — `foreign` |
| `agent-files` | — / `.agents/` | `settings.local.json` — `junk` after `tb secrets scan`. Commands, agents, skills — a question: into `.agents/` or drop. `.git/info/exclude` — `obsolete` (ignores in new clones — stage 2). Root `CLAUDE.md`/`AGENTS.md` — rules for working with the human go to the project part of `AGENTS.md` with consent, the rest `obsolete`/`derivable` |
| `loose-docs` | — | `diff` against the committed copy: identical — `derivable` with the path and commit; different — a question with a short diff |
| `transcripts` | by digest | A row is a session. A note candidate only from a list approved by the human; the rest — `junk` ("ordinary work, the result is in git") or `derivable` |
| `instructions` | `AGENTS.md` | Rules for working with the human that relate to the project — to the project part of `AGENTS.md` with consent; general ones — `foreign` |

Gotchas:

- "How to check it still applies" — a check without side effects (`rg -n`, `git log -S`, a version in a
  lock file) and the expected result while the cause is alive. If it can be checked only in production or in an external
  system — say so.
- `applies_to`: a third-party component — `<package>@<major.minor>` from a lock file or manifest; behavior of
  your own code — `<module>@<YYYY-MM-DD of the check>`.
- A fixable defect in your own code is a "fix" plan, not a gotcha. Third-party behavior and your own defect in
  one source are split: a gotcha + a plan linking to it.
- "Fixed", "no longer relevant" in the text — a reason to check them first, but not evidence.

Plans and entities:

- Plan `ready` — if it is clear where to start; otherwise `idea`. A multi-topic plan is split; history
  ("Revised", "What is closed") is not migrated. Check the status on the branch the plan names.
- Entity: "Purpose" in 1–3 sentences + a link to the resource's README/`AGENTS.md`; stack, build, tests,
  current state — `derivable` or Tasks; constraints — in "Non-obvious details". Remove absolute paths.
  A thin card with nothing non-obvious — `derivable`.
- Entities and decisions do not link to plans: the relation is a link from the plan.
- Task decisions — in the task's "Decisions along the way", not in Decisions.
- A script a live note relies on or that is needed regularly — into `Toolbox/` or a resource
  (a question to the human); one-off experiments — `junk`. An attachment that is the only copy of code: the note says where it is
  (archive) and asks where to keep it.

## Note name

- slug — per `slugmap.md`: the file name without the `YYYY-MM-DD-` date prefix (the date goes to `created`), transliterated,
  kebab-case. A deviation (another folder, a split, a merge) — in "Reason".
- New notes from a split — Latin letters, kebab-case, the gist of the topic.
- An entity — by the resource name in the catalog or the module directory name.
- Create only with `tb kb new <type> <slug> --title "…" --description "…"`.

## Frontmatter

| Was | Becomes |
|---|---|
| `title`, H1 | `title` in the project language |
| `date`, date in the name, the file's first commit | `created` |
| — | `verified` — today, if the key claims were checked against `Resources/`; otherwise — the source date and the `unverified` tag |
| — | `description` — one line, the gist, not a repeat of the title |
| — | `status`: decision — `accepted` if the code matches (evidence in the ledger), otherwise `proposed` + a question; plan — `idea`/`ready`; entity — `active`/`deprecated`; task — `active`/`blocked` |
| service fields (`project`, `tags: [decision]`, `metadata`) | drop |
| `area` and the like | `resources` (names from the catalog, `<resource>/<subpath>` for modules) + `tags` — per the task's `rules.md` |
| synonyms, glossary terms | `aliases` |
| versions in a gotcha's text | `applies_to` |

## Body

- Follow the sections of the type's template. The current state, not a chronology.
- Do not migrate: retellings of code, `file:line`, "where things are" tables, hashes and ticket numbers without
  a "why", measurements and experiments, progress of finished work.
- Language — the project language; notes in another language are translated.

## Links

- Instead of `[[wikilinks]]` — relative Markdown links: `tb adopt links <notes> --write` (by the ledger,
  then by `slugmap.md`). An `UNKNOWN` report — fix by hand (a link or text).
- The target is not migrated yet — a deferred link `[Text](../Entities/api.md "pending")`: lint
  warns, the commit is not blocked. Once the target appears, `links --write` removes `"pending"`. At the end of a
  source and at stage 6 — `links --write` over all Knowledge.
- A target with an `obsolete`/`derivable`/`junk` verdict — the link becomes text.
- Links to code — relative, to `Resources/<name>/<path>`; absolute paths of old copies — replace or
  remove. External URLs — only permanent ones.

## Dates

- Only absolute `YYYY-MM-DD`; `dd.mm` without a year — the year from the source's context.
- "Today", "now" — rephrase without a date or as "as of <source date>". Mechanical replacement is forbidden.

## Relevance and derivability

- **`derivable`**: the same can be read from code, configs, CI, the DB schema, README, git history — name the place.
  If a "why" or something non-obvious remains — only that is migrated.
- **Relevant**: 1–3 key claims (paths, symbols, keys, versions, branches, "done") checked against
  `Resources/` by the `kb-review` rules ("Evidence"). The main thing: decision — does the code match;
  gotcha — is the cause alive; plan — is it not done yet; entity — does it exist and where.
- **Unverified** (no resource, needs the network, production or a run):
  - the main thing is not checked — the `unverified` tag, `verified` = the source date;
  - the main thing is checked, but not the secondary — `verified` = today, the text says "(per the source, not
    checked)";
  - in "Reason" — `unverified: <what exactly>`.
- An evidence command is exactly the one that was run, with its result; a search — by the exact string.
- A pattern from one module is searched for in neighboring ones too: the note's scope follows the facts.
- Every path and symbol mentioned is checked for existence: the note gets the symbol, not `path:line`.
- Refuted by the code — correct it to the fact; unclear what is right — a question, decision — `proposed`.

## Secrets and sensitive data

- Values of passwords, tokens, keys (both dev and "public" ones) are never copied anywhere. The note holds a pointer:
  where it lives (the secrets folder, a secrets store, a file in the code).
- A finding — an item of the batch's "Secrets" section: `- #N <path>:<line> — <what it is>`. A file that is entirely
  secret — the `secret` verdict (no copy in the secrets folder — a question).
- Do not migrate personal data, customer data, IPs and host names of the infrastructure — generalize.
- Before handing in a batch — `tb adopt check … --pre-audit` (includes `tb kb lint` with a secrets search).

## Duplicates

- Before creating — `tb kb search "<topic>"` (and by aliases). A note of your own batch — `merged`.
- A note of another batch or session — do not edit it: `duplicate-candidate` with its path in "Target"; the
  orchestrator resolves it at the end of the source.

## Handing facts between sources

- A fact is needed by a note another batch or session makes — do not put it in "Reason", add an
  item to your batch's "Handoff" section: `- #N → <source>: <a row of the receiver's manifest> — <fact with
  evidence>`.
- The receiver's worker migrates the fact and writes in its own batch (the "Handoff" section or below the table)
  `accepted: <id> → <note>` or `accepted: <id> → — <why it is not needed>`.
- `tb adopt check` shows unaccepted handoffs for a source: in a batch — as a warning, at the end of the
  source — as an error; `gate` — as an error. Unaccepted ones for a source already finished — a rework batch `hNN`.

## Questions

- An item of the batch's "Questions" section: `- #N <question> — <context>`; questions outside batches — in the task's `questions.md`
  in the same format. The answer goes on the same line: `(answer: …)`.
- The orchestrator asks the human the open questions in one batch (`tb adopt status`) and puts the answers into notes and the
  ledger through the same pipeline. `foreign` passes the audit with `ok` before the answer.
