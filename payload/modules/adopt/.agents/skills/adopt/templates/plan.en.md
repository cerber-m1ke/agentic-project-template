# Migration plan

The start prompt of any session: "Run session <ID> per `Knowledge/Tasks/{{slug}}/plan.md`; read the shared
rules and your section". A session edits only its own status row, rereading the file before the edit. The procedure
and stage criteria — the `adopt` skill.

## Status

| ID | Stage | Depends on | Status | Date | Outcome |
|---|---|---|---|---|---|
| S0 | Preparation: start, archive of what cannot be recovered | — | todo | | |
| S1 | Inventory, resource decisions | S0 | todo | | |
| S2 | Resources, secrets, agent settings | S1 | todo | | |
| S3 | Rules and pilot | S1 | todo | | |
| S4a | Migration: <source group> | S2, S3 | todo | | |
| S5 | Questions | S4* | todo | | |
| S6 | Consolidation | S4*, S5 | todo | | |
| S7 | Final audit | S6 | todo | | |
| S8 | Cleanup | S7 = GO | todo | | |

Statuses: `todo`, `doing`, `done`, `blocked: <by what>`. S4 sessions are split by source group and run in parallel.

## Shared rules

- Old locations are only read until S8; irreversible and external actions — after the human's "yes".
- Subagents do the bulk reading; a subagent's answer ≤ 10 lines; a batch ≤ 12 files or ~60 KB; ≤ 5 subagents.
- Commits — by explicit paths: your own notes and batches — after a green `check`, shared files — after a green `gate`.
- End of a session: the status row, "Progress" in `index.md`, a commit offer, an answer ≤ 10 lines.

## Project decisions and facts

<!-- Old copies and which of them takes precedence, environment traps, the human's decisions with dates. -->

## S0. Preparation

Done when: the task is created, archives of what cannot be recovered are verified.

## S1. Inventory

Done when: every row in `resources.md` has a decision, all local work is accounted for.

## S2. Resources

Done when: `tb resources status` and `tb agents doctor` report nothing.

## S3. Rules and pilot

Done when: `adopt.toml` has the sources, manifests and slugmap are built, the project rules are approved
by the human after the pilot.

## S4a. Migration: <source group>

Sources: <names from adopt.toml>. Done when: `tb adopt check <source>` is green for each.

## S5. Questions

Done when: there are no open questions or the human explicitly postponed them.

## S6. Consolidation

Done when: `tb adopt gate` is green, `tb kb lint` 0/0, `tb secrets scan` is clean, "In progress" is filled in.

## S7. Final audit

Done when: `final-audit.md` has GO and `deletion-manifest.md` is drawn up.

## S8. Cleanup

Done when: the old is removed by the manifest, the task is closed with `wrap-up`, the `adopt` module is removed.
