# Resources

Resources are what the project works on: git repositories (code, documentation, scripts) or plain
folders (documents, data). The template does not prescribe the content or the structure inside resources.

## Catalog and personal set

- `resources.toml` — the catalog of all known project resources. It is stored in the root git repository; its fields
  are described in the comments at the top of the file.
- `Resources/<name>/` — local resources. They are not committed to the root git repository (`.gitignore`).
- Each person may have any subset of the catalog cloned — that is fine.

## Resource kinds

- `kind = "git"` — a separate repository with its own history. Cloned with `Toolbox/tb resources clone`;
  commits are made inside it: `git -C Resources/<name> …`.
- `kind = "folder"` — a plain folder without git: documents, exports, large and binary data. Its
  content is not versioned by the root git repository; where to get it is stated in `url` or in the resource card.

## Commands

| Command | Purpose |
|---|---|
| `Toolbox/tb resources status` | What exists locally, the current branch, whether there are changes |
| `Toolbox/tb resources clone <name>…` | Clone resources from the catalog; `--all` — all of them; `<name> --from <path>` — from a local copy while the upstream is unreachable (`origin` — the catalog url) |
| `Toolbox/tb resources add <url> [--name N] [--branch B] [--kind git\|folder] [--description "…"] [--entity <path>] [--clone]` | Add a resource to the catalog (with `--clone`, clone it right away). A path to a local working copy records its `origin` and warns about work that exists only in that copy; if the upstream is unreachable, `--clone` clones the copy itself |
| `Toolbox/tb resources set <name> <field>=<value>…` | Change or add a field of a catalog entry, leaving the rest of the text and the comments alone; `<field>=` removes the field. Fields: `kind`, `url`, `branch`, `description`, `entity`, `agent_settings_reviewed` (comma-separated) |
| `Toolbox/tb setup --clone-missing` | Clone all missing resources |

On Windows (PowerShell): `Toolbox\tb.cmd resources …`.

## Rules for the Agent

- If a task needs a resource that is not available locally, suggest `Toolbox/tb resources clone <name>` to the human.
- If a resource has its own `AGENTS.md` or `CLAUDE.md` (at its root or in the working subdirectory), read them
  before working: the resource's own rules apply inside it, and different agents pick up nested instructions
  differently. These files belong to the resource — do not change them unless asked.
- A resource's agent settings (`.claude/settings.json`, `.mcp.json`, `.codex/`, `.claude/skills`, …) are not
  loaded by an agent started in the project root: its hooks, permissions and MCP servers do not apply.
  `tb resources status` and `tb agents doctor` list them. What the project needs goes into `.agents/`
  (`permissions.toml`, `mcp.toml`, `skills/`, `hooks/hooks.toml`). The human marks reviewed paths in the
  `agent_settings_reviewed` field (`Toolbox/tb resources set <name> agent_settings_reviewed=…`): they are no
  longer reported, new ones still are.
- Commits to a resource repository are made only inside it and only when the human asks. Resource content
  never goes into the root repository.
- A task lists the affected resources in its `resources` field (names from the catalog).
- Knowledge about a resource goes into its card `Knowledge/Entities/<name>.md`; the path to the card is the `entity` field in the catalog.
  Do not retell the resource's content in Knowledge.

## Search

`Resources/*` is excluded from the root git repository, so search that respects `.gitignore` does not see resources.

- ripgrep (`rg`) reads `.ignore` at the project root: the `!/Resources/*` rule brings resources back to it.
- A nested git repository inside a resource that is listed in its `.gitignore` is invisible to ripgrep from
  the root: `!/Resources/*` works on the first level only. Bring it back with a specific rule in the project part
  of the root `.ignore` (below the template block): `!/Resources/<resource>/<path>/`. Otherwise search inside it:
  `git -C <path> grep …`, `rg` from its folder — or `rg --no-ignore`.
- Search that honours only `.gitignore` (e.g. `grep` in the Claude Code shell, a wrapper around ugrep) does not
  see `Resources/` from the root at all. Search from the resource folder or with `rg`.
- An empty result of such a search does not prove absence. Before claiming "used nowhere", repeat the search
  without ignore files: `rg --no-ignore …`, `git -C <repository> grep …` or `command grep -r …` over the folder
  in question.
