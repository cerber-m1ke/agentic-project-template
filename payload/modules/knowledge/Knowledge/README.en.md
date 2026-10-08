# Knowledge

The project's persistent memory: what the Agent and humans need for the work and what cannot be found
in Resources or git history. Agents' built-in memory is not used — everything is stored here, under git,
independent of any particular Agent. Knowledge goes stale and gathers noise quickly, so it is reviewed
regularly (skill `kb-review`).

## Rules

- Store only what cannot be recovered from Resources and git history.
- One note — one topic. First search for an existing note (`Toolbox/tb kb search`) and update it instead of creating duplicates.
- Turn relative dates ("yesterday", "next month") into absolute ones: `2026-10-08`.
- File names: ASCII, lowercase kebab-case: `uv-proxy-ssl.md`. Title and text are in the project language.
- Links: relative Markdown links: `[Choosing uv](../Decisions/use-uv-for-tools.md)`. Not `[[wikilinks]]`.
- No secrets: no tokens, passwords, keys or personal data.
- Do not maintain an index by hand: `Toolbox/tb kb index` builds it from frontmatter.
- The main Agent writes to Knowledge (the librarian only reads); commit only when a human asks (skill `kb-commit`).

## Note types

| Type | Folder | What it stores | Statuses | Lifetime |
|---|---|---|---|---|
| `decision` | [Decisions](Decisions/README.md) | Architecture decisions (ADR): context, decision, alternatives, consequences | `proposed`, `accepted`, `superseded` | Permanent |
| `entity` | [Entities](Entities/README.md) | Entity card: purpose, where it lives, relationships, non-obvious details, owners | `active`, `deprecated` | While the entity exists |
| `example` | [Examples](Examples/README.md) | Reusable examples and samples — a reference | `active`, `outdated` | While they are current |
| `gotcha` | [Gotchas](Gotchas/README.md) | Pitfalls: symptom, cause, workaround, how to check it still applies | `active`, `resolved` | While the cause exists |
| `plan` | [Plans](Plans/README.md) | Ideas, postponed work, things discovered along the way | `idea`, `ready`, `dropped` | Until it becomes a task or is dropped |
| `task` | [Tasks](Tasks/README.md) | The current task: goal, specification, decisions along the way, progress, takeaways | `active`, `blocked`, `done` | Until its takeaways are harvested |

Decisions made within a task live in the task and go away with it. Only decisions that outlive the
task go to Decisions.

## Frontmatter

```yaml
---
type: gotcha               # decision | entity | example | gotcha | plan | task
title: "uv cannot download Python behind a proxy"
description: "SSL error in tb setup behind a corporate proxy"   # one line: used to search and to decide whether to open the note
status: active             # allowed values depend on the type
created: 2026-10-08
verified: 2026-10-08       # when it was last checked against reality
tags: [uv, network]
aliases: [proxy, https-proxy]   # synonyms, also in other languages — for search
resources: [api]           # names from Resources/resources.toml
applies_to: [uv@0.12]      # gotcha and example only: which versions it applies to
---
```

- `type`, `title`, `description`, `status`, `created` are required.
- A decision with status `superseded` must have `superseded_by` — the path to the new decision.
- Keys and enum values are always in English; dates are `YYYY-MM-DD`. `Toolbox/tb kb lint` validates the schema.

## Lifecycle

```
Plans (idea) ──► Tasks (active) ──► done ──► harvest ──► task deleted
                                                │
                            Decisions / Gotchas / Entities / Examples
```

Takeaways are harvested by the skill `wrap-up`; a deleted task remains in git history. `Toolbox/tb kb stale`
suggests re-checking a note when `verified` (or `created`) is older than a threshold: gotcha — 90 days,
entity and example — 180, plan (`idea`, `ready`) — 60, task (`active`, `blocked`) — 30, decision (`proposed`) — 30.
A task with status `done` is always listed: its takeaways have not been harvested yet.

## Commands

| Command | Purpose |
|---|---|
| `Toolbox/tb kb search <query> [--type T] [--status S] [--resource R]` | Search titles, descriptions, aliases, tags and text |
| `Toolbox/tb kb show <path\|slug>` | The whole note |
| `Toolbox/tb kb related <path\|slug>` | Links and backlinks |
| `Toolbox/tb kb new <type> <slug> --title "…"` | New note from a template; `--folder` — a task as a folder |
| `Toolbox/tb kb index` | Index grouped by type |
| `Toolbox/tb kb lint` | Frontmatter, links, file names, `AGENTS.md` budget |
| `Toolbox/tb kb stale` | Candidates for re-checking |

On Windows (PowerShell): `Toolbox\tb.cmd kb …`.

## Templates

`_templates/` holds note templates shared by `Toolbox/tb kb new` and Obsidian. The placeholders `{{title}}` and `{{date}}`
are filled in when a note is created. Templates are not counted as notes.

## Obsidian

The vault root is `Knowledge/`: open this folder in Obsidian as a vault. `Toolbox/tb obsidian setup`
writes the configuration: Markdown links instead of `[[wikilinks]]`, relative paths, templates folder `_templates`.
The `.obsidian/` folder is not committed to git. When creating a note in Obsidian, give the file a kebab-case name,
insert the template of the right type and replace `title` with a human-readable title.
