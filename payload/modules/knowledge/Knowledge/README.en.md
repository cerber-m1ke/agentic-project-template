# Knowledge

The project's persistent memory: what the Agent and humans need for the work and what cannot be found
in Resources or git history. Agents' built-in memory is not used — everything is stored here, under git,
independent of any particular Agent. Knowledge goes stale and gathers noise quickly, so it is reviewed
regularly (skills `kb-review` and `plan-review`).

## Rules

- Store only what cannot be recovered from Resources and git history.
- Only what is alive: fix outdated notes in place, delete dead ones. Earlier versions remain in git history,
  so there are no statuses like "outdated" or "superseded".
- One note — one topic. First search for an existing note (`Toolbox/tb kb search`) and update it instead of creating duplicates.
- Turn relative dates ("yesterday", "next month") into absolute ones: `2026-10-08`.
- File names: ASCII, lowercase kebab-case: `uv-proxy-ssl.md`. Title and text are in the project language.
- Links: relative Markdown links: `[Choosing uv](../Decisions/use-uv-for-tools.md)`. Not `[[wikilinks]]`.
- A link to a note yet to be written gets the link title `"pending"` (the link tooltip):
  `[Cache](../Gotchas/cache.md "pending")`. `Toolbox/tb kb lint` warns about it without blocking the commit,
  and `Toolbox/tb kb stale` lists the note as a candidate for completion. Once the target exists, remove the `"pending"` title.
- No secrets (tokens, passwords, keys) and no real customer or user data: no exports, no personal data.
- Do not maintain an index by hand: `Toolbox/tb kb index` builds it from frontmatter.
- The main Agent writes to Knowledge (the librarian only reads). It commits each edit right away and tells
  the human (skill `kb-commit`): `Toolbox/tb kb commit` takes only the given paths and signs the commit with
  the `Agent-Session` trailer. With parallel sessions this shows which one wrote what. A correction to its
  own recent commit (a plan, pitfall or decision was cancelled) goes into that same commit (`--amend`),
  not a new one.

## Note types

| Type | Folder | What it stores | Statuses | Lifetime |
|---|---|---|---|---|
| `decision` | [Decisions](Decisions/README.md) | Architecture decisions (ADR): context, decision, alternatives, consequences | `proposed`, `accepted` | While in force |
| `entity` | [Entities](Entities/README.md) | Entity card: purpose, where it lives, relationships, non-obvious details, owners | `active`, `deprecated` | While the entity exists |
| `example` | [Examples](Examples/README.md) | Reusable examples and samples — a reference | — | While they are current |
| `gotcha` | [Gotchas](Gotchas/README.md) | Pitfalls: symptom, cause, workaround, how to check it still applies | — | While the cause exists |
| `plan` | [Plans](Plans/README.md) | Ideas, postponed work, things discovered along the way | `idea`, `ready` | Until it becomes a task or is dropped |
| `task` | [Tasks](Tasks/README.md) | The current task: goal, specification, decisions along the way, progress, takeaways | `active`, `blocked`, `done` | Until its takeaways are harvested |
| `reminder` | [Reminders](Reminders/README.md) | What to consider soon: links to notes, plans, tasks; why and when | — | Until considered |

The end of a note's life is its deletion: a superseded decision, a fixed pitfall, an outdated example,
a rejected plan, the card of a retired entity, a considered reminder. Anything important from the deleted note moves to a live one
(for example, why the previous decision was abandoned goes to "Alternatives" of the new one).

Decisions made within a task live in the task and go away with it. Only decisions that outlive the
task go to Decisions.

## Frontmatter

```yaml
---
type: gotcha               # decision | entity | example | gotcha | plan | task | reminder
title: "uv cannot download Python behind a proxy"
description: "SSL error in tb setup behind a corporate proxy"   # one line: used to search and to decide whether to open the note
# status: active           # gotcha and example have none; for other types values depend on the type
created: 2026-10-08
verified: 2026-10-08       # when it was last checked against reality
tags: [uv, network]
aliases: [proxy, https-proxy]   # synonyms, also in other languages — for search
resources: [api, api/src/billing]   # names from Resources/resources.toml, optionally with a subpath
applies_to: [uv@0.12]      # gotcha and example only: which versions it applies to
due: 2026-11-01            # reminder only: when to consider it
---
```

- `type`, `title`, `description`, `created` are required; `status` — for all types except gotcha and example.
- Keys and enum values are always in English; dates are `YYYY-MM-DD`. `Toolbox/tb kb lint` validates the schema.
- `resources`: a catalog name, optionally with a subpath inside the resource (`api/src/billing`) and a branch
  (`api@main`). When the resource is cloned, lint checks that the subpath exists. In search, `--resource api`
  also finds `api/…`, `--resource api/src` only that subpath. Put the resource's card from `Entities/` into the
  catalog's `entity` field: lint checks that the file exists and hints when the field is empty.
- Checked a note against reality — `Toolbox/tb kb verify <path|slug>`: sets `verified` to today, leaves the rest
  of the text untouched, and lints the note. `--date` sets another date, `--dry-run` only shows.

## Lifecycle

```
Plans (idea) ──► Tasks (active) ──► done ──► harvest ──► task deleted
                                                │
                            Decisions / Gotchas / Entities / Examples
```

Takeaways are harvested by the skill `wrap-up`; a deleted note remains in git history. `Toolbox/tb kb stale`
suggests re-checking a note when `verified` (or `created`) is older than a threshold: gotcha — 90 days,
entity and example — 180, plan (`idea`, `ready`) — 60, task (`active`, `blocked`) — 14, decision (`proposed`) — 30,
reminder — 14, and a reminder with `due` — on the `due` date.
A task with status `done` is always listed: its takeaways have not been harvested yet. So is a note with
a retired status (`superseded`, `resolved`, `outdated`, `dropped`): it is dead and due for deletion.
So is a note with pending links (`"pending"`): it is due for completion.

## Commands

| Command | Purpose |
|---|---|
| `Toolbox/tb kb search <query> [--type T] [--status S] [--resource R]` | Search titles, descriptions, aliases, tags and text |
| `Toolbox/tb kb show <path\|slug>` | The whole note |
| `Toolbox/tb kb related <path\|slug>` | Links and backlinks |
| `Toolbox/tb kb new <type> <slug> --title "…" --description "…"` | New note from a template; `--folder` — a task as a folder |
| `Toolbox/tb kb index` | Index grouped by type |
| `Toolbox/tb kb lint` | Frontmatter, links, file names, the Resources catalog, `AGENTS.md` budget |
| `Toolbox/tb kb verify <path\|slug>…` | Record a check: `verified` set to today, notes linted |
| `Toolbox/tb kb stale` | Candidates for re-checking and completion |
| `Toolbox/tb kb nearby [<path\|slug>…] [--query TEXT] [--resource R]` | Reminders, open plans and tasks close to the context |
| `Toolbox/tb kb commit <paths>… -m "…" [--amend]` | Commit Knowledge right after an edit, with the authoring session |
| `Toolbox/tb kb squash [--dry-run]` | Fold `fixup!` corrections into their commits (clean tree, not pushed) |

On Windows (PowerShell): `Toolbox\tb.cmd kb …`.

## Templates

`_templates/` holds note templates shared by `Toolbox/tb kb new` and Obsidian. The placeholders `{{title}}` and `{{date}}`
are filled in when a note is created. Templates are not counted as notes. The templates belong to the
project: adapt them — a template update only suggests its changes.

## Obsidian

The vault root is `Knowledge/`: open this folder in Obsidian as a vault. `Toolbox/tb obsidian setup`
writes the configuration: Markdown links instead of `[[wikilinks]]`, relative paths, templates folder `_templates`.
The `.obsidian/` folder is not committed to git. When creating a note in Obsidian, give the file a kebab-case name,
insert the template of the right type and replace `title` with a human-readable title.
