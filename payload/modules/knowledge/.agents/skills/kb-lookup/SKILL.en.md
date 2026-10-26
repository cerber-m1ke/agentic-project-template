---
name: kb-lookup
description: Librarian — find the answer in the project's Knowledge and verify it against Resources. Use before planning a task, before making a decision, the first time an entity (service, module, resource) comes up in a session, and when an error looks familiar.
---

# Knowledge lookup

Read-only: do not edit files, create notes or commit. Any resulting edits are made by the main
Agent — right away or during `wrap-up`.

## Who runs it

If your agent can launch subagents and the `librarian` subagent is available, delegate the question to it:
pass the question and the context (task, resource, error text). It answers in the format below; if a
detail matters, open the files from "Sources" yourself. Otherwise run the procedure in the main session.

## Procedure

1. **Search.** `Toolbox/tb kb search <keywords>` (Windows PowerShell: `Toolbox\tb.cmd kb search …`).
   - Search with keywords, not the whole question. Try 2–3 phrasings: synonyms, terms in English
     and in the team's other languages, the resource or library name, a fragment of the error text.
   - Filters as the situation requires: `--type gotcha` for an error, `--type decision` before a decision,
     `--resource <name>` for a resource, `--brief` — result headers only.
   - Reminders: `Toolbox/tb kb search --type reminder <the same words>` — which overlapping items are due
     for consideration; their paths go to the "Reminders" line.
2. **Read.** Open the 1–3 best matches in full: `Toolbox/tb kb show <path>`; related notes —
   `Toolbox/tb kb related <path>`. Take `status` and `verified` into account.
3. **Verify against Resources** — the key claims, not everything:
   - versions: lock files and manifests in `Resources/<name>/` (`package-lock.json`, `uv.lock`, `go.mod`,
     `Cargo.lock`, etc.) against `applies_to`;
   - the mentioned files, functions, commands and config keys exist (search in `Resources/<name>/`);
   - the state of the resources: `Toolbox/tb resources status`.
   Read-only: do not run builds, installs, `git checkout`/`pull`.
4. **Answer** strictly in the format below.

## Answer format

```
Answer: <the gist of the answer: facts, commands, names — briefly>
Sources: Knowledge/Gotchas/<slug>.md, Knowledge/Entities/<slug>.md
Verification: confirmed | stale? | unverifiable (why)
Knowledge suggestions: <what to update, mark, create> | none
Reminders: <paths of reminders that overlap the question> | none
```

- `confirmed` — the key claims are confirmed by Resources.
- `stale?` — a mismatch or signs of staleness: the version does not match `applies_to`, a file or
  function was not found, the status is `deprecated` or a retired one (`resolved`, `outdated`, `superseded`,
  `dropped`). Say what exactly.
- `unverifiable (why)` — cannot be checked: the resource is not cloned, the claim is not about Resources.
- Sources with different results — mark each one: `confirmed (uv-proxy-ssl), stale? (api: no function X)`.
- Paths in "Sources" are mandatory: the main Agent uses them to open the originals.

If nothing was found, say so explicitly — do not make things up:

```
Answer: nothing found (queries: "…", "…", "…")
Sources: —
Verification: —
Knowledge suggestions: <create a note once the answer is found> | none
Reminders: <paths> | none
```
