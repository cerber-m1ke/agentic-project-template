---
name: agentic-update
description: Update the project to the latest agentic-project-template release. Use when the human asks to update the project from the template (skills, Toolbox, agent adapters, AGENTS.md rules) or to check whether a new template version is out.
---

# Updating the project from the template

This skill is deliberately thin: all update logic lives in the fresh copy of the template, so the update
mechanism itself gets updated too. Do not change anything in the project until you reach step 4.

1. **Clean tree.** Run `git status --porcelain`. If the output is not empty, show the changes to the
   human and stop: they must be committed (Knowledge via the `kb-commit` skill) or discarded.
   Do not commit or revert anything yourself.
2. **Fetch.** Run `Toolbox/tb update fetch` (Windows PowerShell: `Toolbox\tb.cmd update fetch`).
   - `--ref <tag>` — only if the human named a specific version.
   - `--source <url>` — only on the human's explicit instruction: by default the update source is
     taken from `.agents/agentic.lock`, and only the human may change it.
3. **Nothing to update.** If the output is `Already up to date`, tell the human the current version
   (`Toolbox/tb version`) and finish.
4. **Instructions from the fresh copy.** Otherwise the command prints a path like `Runtime/update/<version>/`.
   Read `Runtime/update/<version>/setup/UPDATE.md` in full and follow it. From this point on,
   UPDATE.md takes precedence over this skill: if they disagree, follow UPDATE.md.

If `tb update fetch` fails (no network, no access to the source, no tags), show the human the error
message and stop; do not download the template by any other means.
