# Toolbox

Project tools and a layer of independence from the host system. The machine only needs git and internet
access on the first run: `tb` downloads uv and Python into `Runtime/tools/` by itself and installs
nothing globally. Deleted `Runtime/`? The next `tb` call restores the environment.

## Running

- macOS, Linux, Git Bash: `Toolbox/tb <command>`
- Windows (PowerShell, cmd): `Toolbox\tb.cmd <command>`

Help: `Toolbox/tb --help`, `Toolbox/tb <command> --help`. `tb` messages are always in English; paths
in the output are relative to the project root.

## Template commands

| Command | Purpose |
|---|---|
| `tb version` | Template version, project name, language and profile |
| `tb setup [--agents a,b] [--clone-missing]` | Machine setup: uv, adapters, git, Obsidian, Resources |
| `tb kb search <query> [--type T] [--status S] [--resource R]` | Search Knowledge |
| `tb kb show <path\|slug>`, `tb kb related <path\|slug>` | Full note; links and backlinks |
| `tb kb new <type> <slug> [--title T] [--description D] [--folder]` | New note from `Knowledge/_templates/` |
| `tb kb index [--base DIR]`, `tb kb lint [--staged]`, `tb kb stale` | Index; validation of Knowledge and `AGENTS.md` (`--staged` — what goes into the commit); candidates for re-verification |
| `tb secrets scan [--staged] [paths…]` | Secret scan |
| `tb agents list\|link\|unlink\|doctor` | Agent adapters on this machine |
| `tb resources status\|clone\|add` | Resources: status, cloning, adding to the catalog |
| `tb obsidian setup` | Obsidian vault configuration |
| `tb update fetch [--ref vX.Y.Z]` | Download a fresh (or the given) template release into `Runtime/update/` (next — skill `agentic-update`) |
| `tb hook <name> [--agent A]` | Hook handlers; called by agents, not by hand. Never block the agent and never download anything |
| `tb run <script> [args…]` | Run a script via uv |

## Adding a project tool

Preferably a Python script in `Toolbox/` with its dependencies declared in the file itself (PEP 723).
uv installs the required Python and packages into an isolated environment on its own:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"   # pins package versions as of this date
# ///
"""What the tool does and how to call it."""
```

Run: `Toolbox/tb run Toolbox/<name>.py [args…]`.

Any other script works too, but then you take care of macOS, Linux and Windows yourself (for example,
a `<name>.sh` and `<name>.cmd` pair). Rules:

- file names: Latin letters, kebab-case;
- paths relative to the project root, temporary files in `Runtime/`;
- no secrets in code: read them from environment variables or `.env` (it is in `.gitignore`);
- each tool gets a line in the list below.

## Project tools

<!-- One line per tool: `Toolbox/<name>` — what it does; how to run it. -->

None yet.

## Toolbox/agentic/

Template tools. This directory is managed by the template: it is updated via the `agentic-update` skill,
and local edits will cause a conflict on update. Do not edit it — put your own tools next to it, in
`Toolbox/`.
