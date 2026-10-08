# {{agentic.project_name}}

<!-- Describe the project in 2–3 lines: what we build, for whom, which Resources matter most. -->

<!-- agentic:begin -->
## Map

- `Resources/` — project Resources; catalog — `Resources/resources.toml`, rules — `Resources/README.md`.
- `Knowledge/` — Knowledge: the project's persistent memory (Obsidian vault).
- `Toolbox/` — tools; entry point — `Toolbox/tb` (Windows PowerShell: `Toolbox\tb.cmd`).
- `.agents/` — source of truth for agents: skills, subagents, hooks, adapters, docs.
- `Runtime/` — temporary files, cache, environment; not in git.

## Rules

- Persistent memory is `Knowledge/` only. Do not use the agent's built-in memory.
- Write to Knowledge only what cannot be derived from Resources and git history. One note — one topic: find and update an existing note first. Rules — `Knowledge/README.md`.
- Temporary files and one-off scripts go only in `Runtime/`. Permanent tools go in `Toolbox/`, with an entry in `Toolbox/README.md`.
- Commit only when the human asks, with explicit paths only (no `git add -A`/`.`). Message: `<scope>: <summary>` + bullet points; scope — `knowledge|agents|toolbox|resources|agentic`.
- Do not edit `.agents/agentic.lock` or the generated `.claude/`, `.codex/`, `CLAUDE.md`: change `.agents/`, then run `Toolbox/tb agents link`.
- A needed resource is missing from `Resources/` — suggest `Toolbox/tb resources clone <name>`.
- Never write secrets to `Knowledge/`, `Toolbox/`, `.agents/`.
- Deleting data, updating the template, committing — only after the human confirms.
- Procedures — `.agents/skills/<name>/SKILL.md`. If your agent does not load skills itself, find the matching skill and read its `SKILL.md`.
- Details — `.agents/docs/concept.md` (when needed).

{{agentic.profile_rules}}

## Session protocol

1. Start: do not read all of Knowledge; active tasks — `Toolbox/tb kb search --type task --status active --brief`.
2. Before planning and decisions, on first contact with an entity, on a familiar error — skill `kb-lookup`.
3. End of a session or stage — skill `wrap-up`.
4. Periodically — skill `kb-review`.

Template skills: `kb-lookup` — search Knowledge; `wrap-up` — session wrap-up; `kb-commit` — commit Knowledge; `kb-review` — review Knowledge; `agentic-update` — update from the template.

## `Toolbox/tb` commands

- `kb search <query>`, `kb show <path|slug>`, `kb related <path|slug>` — search and read Knowledge.
- `kb new <type> <slug> --title "…"` — new note; `kb lint` — validate; `kb stale` — what to re-verify.
- `resources status`, `resources clone <name>` — Resources.
- `agents link`, `agents doctor` — agent adapters.
- `secrets scan` — secret scan; `run <script>` — project script; `setup` — machine setup.
<!-- agentic:end -->

## Project specifics

<!-- Rules and conventions of this project. The block above is updated by the template — do not edit it; this section is yours. -->
