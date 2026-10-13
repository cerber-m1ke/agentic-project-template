# Decisions

Architecture decisions (ADR): why things are done this way and not another. The code shows what was
done; a decision keeps the context, the rejected alternatives and the consequences. Type `decision`,
lifetime — while the decision is in force.

## When to create

- The decision affects several resources, tasks or people and will outlive the current task.
- There were real alternatives, and someone will surely come back asking "why this way?".

## When not to create

- The decision applies only within a task — record it under the task's "Decisions along the way".
- The choice is obvious from the code or described in the resource's documentation.
- It is still an idea — put it in Plans.

## Statuses

- `proposed` — proposed, awaiting a human's decision. The Agent creates decisions only with this status.
- `accepted` — accepted; set by a human, or by the Agent with the human's explicit consent.
- Delete a rejected proposal; if the reason for rejecting it matters, record it under "Alternatives" of the accepted decision.

## When to delete

- The decision is replaced by another: delete the old one and explain in the new one's "Context" or
  "Alternatives" what was abandoned and why. The old text remains in git history.
- The decision is revoked, or its gist is already obvious from the code and the resources' documentation,
  or nobody will ask "why this way?" about it any more.

## Name and creation

The file name states the gist of the decision: `use-uv-for-tools.md`, `single-root-repo.md`.

`Toolbox/tb kb new decision use-uv-for-tools --title "Run tools via uv"`

## Example (excerpt)

```markdown
title: "Run tools via uv"
description: "Toolbox does not require Python on the machine: uv installs it into Runtime/"
## Decision
Toolbox scripts are Python with PEP 723, run via `Toolbox/tb run`.
## Alternatives
System Python — different versions on different machines; Docker — heavy and slow for hooks.
```
