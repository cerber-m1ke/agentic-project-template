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
| `Toolbox/tb resources clone <name>…` | Clone resources from the catalog; `--all` — all of them |
| `Toolbox/tb resources add <url> [--name N] [--branch B] [--kind git\|folder] [--description "…"] [--clone]` | Add a resource to the catalog (with `--clone`, clone it right away) |
| `Toolbox/tb setup --clone-missing` | Clone all missing resources |

On Windows (PowerShell): `Toolbox\tb.cmd resources …`.

## Rules for the Agent

- If a task needs a resource that is not available locally, suggest `Toolbox/tb resources clone <name>` to the human.
- If a resource has its own `AGENTS.md` or `CLAUDE.md` (at its root or in the working subdirectory), read them
  before working: the resource's own rules apply inside it, and different agents pick up nested instructions
  differently. These files belong to the resource — do not change them unless asked.
- Commits to a resource repository are made only inside it and only when the human asks. Resource content
  never goes into the root repository.
- A task lists the affected resources in its `resources` field (names from the catalog).
- Knowledge about a resource goes into its card `Knowledge/Entities/<name>.md`; the path to the card is the `entity` field in the catalog.
  Do not retell the resource's content in Knowledge.

## Search

`Resources/*` is excluded from the root git repository, and agents' search (ripgrep) respects `.gitignore`. The `.ignore` file
at the project root brings resources back into search.
