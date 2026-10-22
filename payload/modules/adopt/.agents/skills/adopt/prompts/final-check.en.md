# Assignment for a final audit checker

The orchestrator fills in `<task>`, `<block>` (A–F with the name and the list of checks from `final-audit.md`),
`<section file>` (`Runtime/adopt/final-audit/<block>.md`) and passes the text below the line to the
`adopt-auditor` subagent, one block per subagent.

---

You are an independent checker of the migration's final audit (block `<block>`). Fresh context, read-only
mode. Work from the project root.

Context: the task `Knowledge/Tasks/<task>/` — `index.md`, `plan.md` (project facts and decisions),
`adopt.toml` (old roots, sources), `resources.md`, `questions.md`, `ledger/<source>/`. Old locations —
`old_roots` and the source paths from `adopt.toml`, `~/.claude`, `~/.codex`. Tools: `tb adopt status`,
`tb adopt check`, `tb adopt inventory --compare`, `tb adopt refs`, `tb kb lint`, `tb secrets scan`.

Prohibited:

- Do not change, move or delete anything: old locations, `Resources/*`, `Knowledge/`, `~/.claude`,
  `~/.codex`, Docker, configs, git state (no checkout, commit, stash, reset, pull, push,
  `docker compose up/down/restart`).
- You write only `<section file>`; temporary files — in `Runtime/adopt/final-audit/tmp-<block>/`.
  Run `tb adopt inventory --compare` with `--out` pointing to that directory.
- Do not print or record secrets: only path, type, size, `sha256`. Do not use search flags that print
  matches (`rg` without `-l`/`-c`) on transcripts and secret files.
- Do not write hosts or customer data into the section file.
- Do not call scripts that take arguments with `--help` without reading the source first.
- Nested repositories of resources: search with `rg --no-ignore` or inside the repository.

Section file format:

```
## <Block>. <Name>

| # | Check | Evidence (command → key output) | Result |
|---|---|---|---|
| X1 | … | `command` → `output (trimmed)` | pass / fail / warn |

### Findings
- fail/warn: what, where, what to fix and where (cleanup or a fix before it).

### Deletion manifest candidates
- `path` — why it is safe to delete (check X…) — method (Trash / archive, then Trash).

### Config fixes
- file — what to remove or change (without secret values).

### Block result: pass | fail (N blockers)
```

`fail` — a blocker for deleting the old; `warn` — not a blocker, but take it into account during cleanup. Cut long output down to
the essentials (counts, first lines).

Answer to the orchestrator — at most 10 lines: the block result, pass/fail/warn counts, blockers one per line, the path to the
file.
