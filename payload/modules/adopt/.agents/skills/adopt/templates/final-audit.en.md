# Final audit

Read-only; one `adopt-auditor` subagent per block (`prompts/final-check.md`), sections —
`Runtime/adopt/final-audit/<block>.md`, here — the summary and the sections in full. The orchestrator rechecks the blockers.

## Summary

| Block | Result | pass / warn / fail | Key points |
|---|---|---|---|
| A. Knowledge | | | |
| B. Code | | | |
| C. Secrets | | | |
| D. Agent data | | | |
| E. Environment | | | |
| F. New environment | | | |

Verdict: <GO | NO-GO>. On NO-GO — blocker → fix session → recheck.

## Blocks

- **A. Knowledge** — completeness of manifests by a reverse walk of sources; re-audit of 10% of
  `obsolete`/`derivable`/`duplicate`/`junk` rows (at least 15); `tb adopt gate`, `tb kb lint`.
- **B. Code** — `tb adopt inventory --compare <S1 snapshot>`; work outside the new clones; the
  `resources.md` decisions are carried out.
- **C. Secrets** — every ledger pointer is resolved; secret files are copied with a checksum check;
  the project's `tb secrets scan` is clean.
- **D. Agent data** — memory, transcripts, settings of the old copies: migrated or archived.
- **E. Environment** — `tb adopt refs`: references to old paths in git, agents, shell, Obsidian, IDE, cron, Docker.
- **F. New environment** — `tb setup`, `tb agents doctor`, `tb resources status`, Knowledge opens.

## What to take into account during cleanup

<!-- Warnings from the blocks. -->
