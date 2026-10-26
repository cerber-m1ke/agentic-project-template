# Agentic Project

[Русская версия](README.md)

**Agentic Project** is a workspace where an Agent works comfortably across all of a project's Resources.
This repository is the `agentic-project-template`: projects are deployed from it and updated through
it.

## What a Project is

A **Project** is not a single repository but a connected whole: instructions and tools for the work, the
**Resources** we work on, and the **Knowledge** about them. The project root is its own git repository.

- **Resources** (`Resources/`) — what we ultimately create: source code of applications and services,
  technical documentation, scripts, data. Most often these are separate git repositories with their own
  history and rules. The template does not dictate their contents. Different people may have different
  sets of resources cloned — that is fine: the full list is kept in the catalog `Resources/resources.toml`.
- **Knowledge** (`Knowledge/`) — the project's persistent memory: everything the Agent and the Human need
  for project tasks that cannot be recovered from the Resources and git history. Knowledge goes stale
  quickly and accumulates noise, so regular review is routine, not an exception.
- **Agent** — an AI agent for working with code and text: Claude Code, Codex and others. It reads
  `AGENTS.md`, searches Knowledge, uses the project's tools and works with Resources.

**The main point:** everything related to the project lives inside the project under git, not in agents'
system directories such as `~/.claude`. So the project does not depend on a particular Agent and moves
freely between machines and people.

## Key ideas

- **`.agents/` is the single source of truth** for system configuration: skills, subagents, hooks, MCP.
  Agent-specific directories (`.claude/`, `.codex/`, …) are generated on each machine and are not
  committed to git.
- **Graceful degradation.** An agent that reads `AGENTS.md` and runs commands is enough. Native skills,
  subagents and hooks are an enhancement, not a requirement.
- **Knowledge holds only what cannot be derived** from the Resources and git history.
- **Scripts do the mechanics, the Agent does the meaning.** Structure, links, configs and migrations
  belong in Toolbox. Interviews, analysis and writing belong in skills.
- **Cheap start.** At the start of a session the Agent reads only `AGENTS.md` and the skill descriptions;
  Knowledge is pulled in on demand through search.
- **No empty directories.** Each one holds a README with its rules — which doubles as instructions for
  the Agent.
- **A human confirms anything irreversible:** initialization, updates, commits outside Knowledge. The Agent
  commits Knowledge edits right away and reports them, marked with the session that made them.

## Requirements

- Agent: Claude Code, Codex or any other agent that reads `AGENTS.md` and runs commands.
- git with `user.name` and `user.email` configured.
- Internet access on the first run.

Nothing else is needed. uv and Python are downloaded into the project, into `Runtime/`: nothing is
installed globally and no administrator rights are required. macOS, Linux and Windows are supported.

## Quick start

```sh
git clone --branch v<version> <template-url> my-project   # latest release; without --branch: development
cd my-project
```

Then take one of two paths.

**With the Agent (recommended).** Open the Agent in the `my-project` folder and ask it to initialize the
project. It follows `setup/INIT.md`: asks a few questions (name, language, profile, modules, agents,
resources), shows a summary and runs init once you confirm. It then writes the project-specific part of
`AGENTS.md`, fills in the resource catalog and creates the first Knowledge notes. Existing repositories
are wrapped the same way — just tell the Agent that they already exist.

**Manually:**

```sh
./init.sh --name my-project --language ru --profile software --agents claude,codex --yes
```

On Windows, use `init.cmd` with the same flags. Without `--yes` init changes nothing; `--dry-run` shows
the plan. Optional modules are switched on and off with the `--with` / `--without` flags, for example
`--with devcontainer` or `--without obsidian`.

Init assembles the project from modules, removes the installer and **replaces the template history with a
new git repository** whose first commit is `agentic: init from template vX.Y.Z`, then sets up the machine.
The template URL is saved in `.agents/agentic.lock` — the project is updated from it later.

### Profiles and modules

| Profile | Purpose |
|---|---|
| `software` | Code projects: resources are git repositories |
| `generic` | Projects without code (documentation, research, data): resources are usually plain folders |

| Module | Contents |
|---|---|
| `core` | Always: `AGENTS.md`, `.agents/`, `Toolbox/`, `Runtime/` rules, git settings |
| `knowledge` | Always: `Knowledge/`, `tb kb`, the librarian, skills for working with Knowledge |
| `resources` | Always: `Resources/`, the resource catalog, `tb resources` |
| `obsidian` | On by default: Obsidian vault setup on the machine |
| `devcontainer` | Optional: `.devcontainer/` for running the Agent in a sandbox container |
| `adopt` | For the time of moving a large project in: skill `adopt`, `tb adopt`, worker and auditor subagents; removed after the old places are cleaned up |

## Project structure

```
<project>/
├── AGENTS.md                 # entry point for all agents
├── README.md                 # about the project, for humans
├── .gitignore  .gitattributes  .ignore
├── .agents/                  # system files, the source of truth
│   ├── agentic.lock          # template origin, profile, modules, hashes of managed files
│   ├── skills/               # procedures (Agent Skills standard)
│   ├── agents/               # subagents in the canonical format
│   ├── hooks/                # hooks.toml with abstract events
│   ├── git-hooks/            # git hooks (pre-commit: kb lint, secret scan)
│   ├── adapters/<agent>/     # adapter manifests
│   ├── mcp.toml              # canonical MCP server definitions
│   ├── permissions.toml      # permission rules (deny/ask/allow) for all agents
│   └── docs/                 # concept and reference, read on demand
├── Knowledge/                # Obsidian vault
│   ├── README.md             # general Knowledge rules
│   ├── _templates/           # note templates (tb kb new + Obsidian)
│   └── Decisions/ Entities/ Examples/ Gotchas/ Plans/ Tasks/ Reminders/   # each has a README.md with rules
├── Resources/
│   ├── README.md             # rules for working with resources
│   ├── resources.toml        # the project's resource catalog
│   └── <name>/               # cloned resources (not in the root git)
├── Toolbox/
│   ├── README.md             # tool index
│   ├── tb  tb.cmd            # single entry point
│   ├── agentic/              # template tools (managed)
│   └── …                     # project tools
├── Runtime/                  # not in git
└── .claude/  .codex/  CLAUDE.md  …   # generated adapters, not in git
```

**Toolbox** is the project's toolbox and, at the same time, a layer of independence from the host system.
`Toolbox/tb` (on Windows `Toolbox\tb.cmd`) is the single entry point: it finds or downloads uv and Python
on its own. `Toolbox/agentic/` holds the template's tools. Everything else is project tools: scripts that
automate routine work or rare but laborious tasks. They run via `tb run <script>` and are listed in
`Toolbox/README.md`.

**Runtime** is the place for temporary, non-critical things: logs, sketches, one-off scripts, intermediate
data. Everything produced along the way sits in one place and is deleted deliberately. It also holds the
environment (`tools/`, `cache/`) and the template copy during an update (`update/`) — these subdirectories
are reserved; the rest of the layout is up to whoever does the work. `Runtime/` is not committed to git;
after it is deleted, the next `tb` call restores the environment.

## Knowledge

| Type | What it stores | Lifetime |
|---|---|---|
| Decisions | Architecture decisions (ADR): context, decision, rejected alternatives, consequences | While the decision is in force |
| Entities | Entity cards: purpose, where it lives in Resources, relations, non-obvious invariants, owners. Not a retelling of the code | While the entity exists |
| Examples | Reusable examples and templates that are quick to find and apply | While relevant |
| Gotchas | Pitfalls: symptom, cause, workaround, how to check it still applies (`applies_to: [node@22]`) | While the cause exists |
| Plans | Ideas, postponed items and things discovered along the way | Until they become a task or are dropped |
| Tasks | Specification of the current task: goal, details, decisions along the way, progress, takeaways | Until the takeaways are harvested |

Knowledge holds only what is alive: outdated notes are fixed in place, dead ones (a replaced decision,
a fixed pitfall, a rejected plan) are deleted — git history keeps earlier versions.

Decisions made within a task live in the task and go away with it. Only decisions that outlive the task
go into Decisions.

```
Plans (idea) ──► Tasks (active) ──► done ──► harvest ──► delete task
                                                 │
                             Decisions / Gotchas / Entities / Examples
```

Notes are Markdown with YAML frontmatter and relative links: agents, IDEs, GitHub and Obsidian all read
them the same way. Tools: `tb kb search` (BM25 with stemming for Russian and English), `tb kb new`,
`tb kb lint`, `tb kb stale`. Procedures are the skills `kb-lookup` (the librarian: find and verify an
answer), `wrap-up` (session wrap-up), `kb-commit` (commit Knowledge), `kb-review` (review Knowledge: a verdict with
evidence for every note, checked in batches by the `kb-auditor` subagent) and `plan-review` (review the Plans backlog).

## Lifecycle

**Initialization** — see [Quick start](#quick-start). When existing projects are wrapped (adopt),
their repositories are cloned into `Resources/` afresh rather than moved: moving breaks everything tied to
the absolute path (agent history and memory, IDE settings). Personal knowledge — agents' built-in memory,
notes — is sorted into Knowledge types by the Agent and confirmed by the human. A large project (dozens of
repositories, a notes vault, working documents, agent memory) is moved in with the `adopt` module: in stages,
in batches with ledgers and an audit, and the old places are deleted only by a manifest after a final audit.

**New machine:**

```sh
git clone <project-repository>
cd <project>
Toolbox/tb setup --agents claude,codex   # Windows: Toolbox\tb.cmd setup --agents claude,codex
```

`tb setup` downloads uv and Python into `Runtime/`, creates adapters for the listed agents (the list is
remembered in `.agents/local.toml` on this machine), applies git and Obsidian settings and shows which
catalog resources are missing (`--clone-missing` clones them). The same command restores the
environment after `Runtime/` has been deleted and connects a new agent (`--agents`).

**Work.** At the start of a session the Agent reads `AGENTS.md`, searches Knowledge before making
decisions (`kb-lookup`), wraps up at the end (`wrap-up`) and offers to take up nearby reminders, plans
and tasks, periodically runs reviews (`kb-review`, `plan-review`). It commits Knowledge right away, everything
else only when you ask.

**Update.** Ask the Agent to update the project — the `agentic-update` skill kicks in. `tb update fetch`
downloads the latest template release into `Runtime/update/<version>/`, and the Agent follows
`setup/UPDATE.md` from that fresh copy — so the update mechanism updates itself as well. The Agent shows
the plan, the changes from `CHANGELOG.md`, conflicts and migrations; after you confirm, it applies them on
the `agentic/update-<version>` branch, checks the project and commits. Merging happens after your OK;
rolling back is done with git.

The same mechanism changes the project composition: add or remove a module, switch the language or the
profile (`--add-module`, `--remove-module`, `--language`, `--profile`; without a new release — from a copy
of the installed version, `tb update fetch --ref v<version>`).

### File ownership

| Class | Owner | What an update does |
|---|---|---|
| `managed` | template | Replaces the file if it has not changed locally; otherwise it is a conflict for the human to resolve |
| `seeded` | project (created from the template once) | Leaves it alone; may suggest changes |
| `block` | mixed | Updates only the block between the `agentic:begin` and `agentic:end` markers (`AGENTS.md`, `.gitignore`, `.gitattributes`, `.ignore`) |
| everything else | project | Leaves it alone |

Classes and hashes are recorded in `.agents/agentic.lock` — the basis for the three-way comparison during
an update. The note templates in `Knowledge/_templates/` are `seeded`: adapt them to the project.

## Agents

The system is designed for agents with different capabilities:

| Level | The agent can | How the system works |
|---|---|---|
| 0 | Read `AGENTS.md` and run commands | The protocol is written as text in `AGENTS.md`, procedures live in `.agents/skills/`, tools — `tb` |
| 1 | Use native skills | Skills are picked up automatically |
| 2 | Use subagents | The librarian and others work in an isolated context |
| 3 | Use hooks | Automatic hints from Knowledge based on the prompt text |

Level 0 must work in full — this is the guarantee for new and weaker agents.

The starter adapters are **Claude Code** and **Codex**; both support all levels. `tb agents link`
connects skills to them, generates subagents, hooks and MCP from `.agents/`, and disables the agent's
built-in memory: the project's memory is `Knowledge/` only. `tb agents doctor` checks that everything is
in place and up to date.

A new agent means a new `.agents/adapters/<agent>/` directory and, if needed, a generator in
`Toolbox/agentic/adapters/`. The core does not change; new adapters reach projects through a regular
update. An open-source or Chinese model running inside an already supported agent needs no adapter.

## Languages

The template ships in Russian (the default) and English. The language is chosen at init, and the project
gets only that language: translation duplicates stay in the template and do not bloat the Agent's context.
`tb` messages are always in English. The language can be switched later by an update with `--language`:
the template's files are translated, the project's own files are not.

## Versions

A template release is a git tag `vX.Y.Z` (semver) with a section in [CHANGELOG.md](CHANGELOG.md), which
must describe any migrations. An update takes the latest release, not the current state of the branch.
A project deployed from a fork is updated from that fork.

Between releases — from the first change after a release — `setup/VERSION` holds the next version with the
`-dev` suffix (e.g. `0.2.0-dev`). Init
warns when a project is deployed from such a state, and an update offers release `0.2.0` as soon as it is
out. Use a release tag for real projects.

## Documentation

- [setup/DESIGN.md](setup/DESIGN.md) — architecture and decisions made (in Russian).
- [CHANGELOG.md](CHANGELOG.md) — versions and migrations (in Russian).
- [AGENTS.md](AGENTS.md) — instructions for the Agent that initializes a project or develops the
  template (in Russian).
