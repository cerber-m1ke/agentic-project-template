# Examples

Reusable examples and samples: how we usually do common things in this project. A passive
reference — it is read and copied. Type `example`, lifetime — while the examples are current.

## When to create

- The same snippet (code, config, query, text) is needed for the second time.
- There is an accepted project pattern that does not live in one obvious place in Resources.

## When not to create

- It is a procedure the Agent performs step by step — make it a skill in `.agents/skills/`.
- A good example already exists in the code — link to the file (for example, from an entity card).
- The snippet is needed only once.

## Statuses

- `active` — the example matches the accepted approach.
- `outdated` — no longer matches; name the replacement, or fix the example and set it back to `active`.

The versions the example applies to go into `applies_to`: `[python@3.12, pytest@8]`.

## Name and creation

The file name says what the example demonstrates: `pytest-db-fixture.md`, `release-notes.md`.

`Toolbox/tb kb new example pytest-db-fixture --title "Test DB fixture in pytest"`

## Example (excerpt)

```markdown
title: "Test DB fixture in pytest"
description: "One transaction per test, rolled back — no schema re-creation"
applies_to: [pytest@8, sqlalchemy@2]
## When to use
Integration tests for services that write to Postgres.
```
