# {{agentic.project_name}}

<!-- Describe the project in 2–3 lines: what we build, for whom, which Resources matter most. -->

<!-- agentic:begin -->
## Map

- `Resources/` — project Resources; catalog — `Resources/resources.toml`, rules — `Resources/README.md`.
- `Knowledge/` — Knowledge, the project's persistent memory (Obsidian vault).
- `Toolbox/` — tools; entry point — `Toolbox/tb` (Windows PowerShell: `Toolbox\tb.cmd`).
- `.agents/` — source of truth for agents: skills, subagents, hooks, adapters; how the project works — `.agents/docs/concept.md`.
- `Runtime/` — temporary data, cache, environment; not in git.

## Rules

- Persistent memory is `Knowledge/` only. Do not use the agent's built-in memory.
- Write to Knowledge only what cannot be derived from Resources and git history. One note — one topic: find and update an existing note first. Rules — `Knowledge/README.md`.
- Temporary files and one-off scripts go only in `Runtime/`, permanent tools in `Toolbox/` with an entry in `Toolbox/README.md`.
- Commit Knowledge right after each edit (skill `kb-commit`) and tell the human. Everything else — only when the human asks, with explicit paths (no `git add -A`/`.`): `<scope>: <summary>` + bullet points, scope — `knowledge|agents|toolbox|resources|agentic`. Never bypass or disable the pre-commit hook (`--no-verify`, `commit-tree`): it catches secrets.
- Do not edit `.agents/agentic.lock` or the generated `.claude/`, `.codex/`, `CLAUDE.md`: change `.agents/`, then run `Toolbox/tb agents link`.
- A needed resource is missing from `Resources/` — suggest `Toolbox/tb resources clone <name>`.
- Never write secrets to `Knowledge/`, `Toolbox/`, `.agents/`.
- Deleting data and updating the template — only after the human confirms.
- Procedures — `.agents/skills/<name>/SKILL.md`. If the agent does not load skills itself, read the matching `SKILL.md`.

{{agentic.profile_rules}}

## Session protocol

1. Start: do not read all of Knowledge; tasks — `Toolbox/tb kb search --type task --status active --brief`.
2. Before planning and decisions, on first contact with an entity, on a familiar error — skill `kb-lookup`.
3. End of a session or stage — skill `wrap-up`.
4. Periodically — skills `kb-review` (Knowledge) and `plan-review` (plans).

## `Toolbox/tb` commands

- `kb search <query>`, `kb show|related <path|slug>` — search and read Knowledge.
- `kb new <type> <slug> --title "…"` — new note; `kb lint` — validate; `kb stale` — what to re-verify.
- `resources status|clone <name>` — Resources; `agents link|doctor` — agent adapters.
- `secrets scan` — secret scan; `run <script>` — project script; `setup` — machine setup.
<!-- agentic:end -->

## Project specifics

<!-- Rules and conventions of this project. The block above is updated by the template — do not edit it; this section is yours. -->
