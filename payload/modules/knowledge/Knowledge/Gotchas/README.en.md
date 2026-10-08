# Gotchas

Things we have already tripped over and do not want to repeat: symptom, cause, workaround and a way
to check that the problem still exists. Type `gotcha`, lifetime — while the cause exists.

## When to create

- A non-obvious problem took noticeable time, and it may happen again to another human or Agent.
- There is a workaround that cannot be found in the tool's documentation within a minute.

## When not to create

- The bug can be fixed in the code right away — fix it; if not now — create a plan in Plans.
- It is common knowledge from the documentation, or it was a one-off failure.

## Statuses

- `active` — the cause exists, the workaround is needed.
- `resolved` — the cause is gone (version upgraded, code fixed); record when and how. During review
  such notes are deleted if they will no longer help anyone.

Always fill in "How to check it still applies" and `applies_to` in the `<name>@<version>` format:
`[node@22, uv@0.12]`. `Toolbox/tb kb stale` and `kb-review` use them to tell that a note may be outdated.

## Name and creation

The file name states the gist of the problem: `uv-proxy-ssl.md`, `windows-long-paths.md`.

`Toolbox/tb kb new gotcha uv-proxy-ssl --title "uv cannot download Python behind a proxy"`

## Example (excerpt)

```markdown
title: "uv cannot download Python behind a proxy"
description: "SSL error in tb setup behind a corporate proxy — needs the root certificate"
applies_to: [uv@0.12]
## Fix or workaround
Set `SSL_CERT_FILE` to the corporate certificate before `Toolbox/tb setup`.
```
