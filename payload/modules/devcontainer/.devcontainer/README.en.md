# Devcontainer

A sandbox for agents. Run Claude Code and Codex CLI in autonomous mode here, along with agents and
models you trust less: they see only the container and the project, not your machine. The main way
to work is on the host; the container is for these cases.

## Contents

- Debian, git, curl, ripgrep, uv (the same version pinned in `Toolbox/tb`).
- Claude Code and Codex CLI, installed with the official installers.
- A `dev` user without sudo.
- After the container is created, `Toolbox/tb setup --agents claude,codex` runs.

## Usage

1. Open the project in VS Code and choose "Dev Containers: Reopen in Container"
   (or run `devcontainer up --workspace-folder .` from the Dev Containers CLI).
2. In the container terminal, run `claude` or `codex` and sign in once.
3. Enable autonomous mode only here, for example `claude --dangerously-skip-permissions`
   or `codex --yolo`.

To update the agents, rebuild the container ("Dev Containers: Rebuild Container").

## Caveats

- **Windows.** Don't open a folder from the host drive in the container; clone the repository into a
  container volume instead ("Dev Containers: Clone Repository in Container Volume"). The adapter
  links the container creates in a mounted folder don't work for native Windows agents, so the
  container needs its own copy of the project.
- **Agent sign-in** is stored in named volumes for `~/.claude` and `~/.codex` and survives rebuilds.
  Each container has its own volumes. To sign out of the accounts completely, delete the volumes
  (`docker volume ls`, `docker volume rm …`).
- **Python and uv caches** live in the container's home directory, not in the project's `Runtime/`,
  so they don't mix with host files. After a rebuild, Python is downloaded again.
- **The network is unrestricted.** If an agent only needs API access, add a firewall modeled on the
  reference Claude Code devcontainer: https://code.claude.com/docs/en/devcontainer
- The container isolates the host, but not the project: an agent can modify or delete project files.
  Commit before an autonomous run.
